"""
Storage backend for muLLM scoring log.
Configure via DATABASE_URL in mullm.toml or env:

  SQLite (default):   sqlite:///$MULLM_STATE_DIR/cache/data/mullm.db
  PostgreSQL:         postgresql://user:pass@host/dbname
  MongoDB:            mongodb://user:pass@host:27017/mullm
  Snowflake:          snowflake://user:pass@account/db/schema?warehouse=WH
  JSONL (legacy):     jsonl:///./cache/data/scoring_log.jsonl
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse


class StorageBackend:
    def log(self, record: dict) -> None: ...
    def recent(self, n: int = 50) -> list[dict]: ...
    def stats(self) -> dict: ...
    def recent_by_session(self, session_id: str, n: int = 100_000) -> list[dict]: ...
    def delete_by_session(self, session_id: str) -> int: ...
    def close(self) -> None: ...


class JSONLBackend(StorageBackend):
    """Legacy append-only JSONL (original muLLM format)."""
    def __init__(self, path: str):
        self._path = Path(path.replace("jsonl:///", "").replace("jsonl://", ""))
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, record: dict) -> None:
        with open(self._path, "a") as f:
            f.write(json.dumps(record) + "\n")

    def recent(self, n: int = 50) -> list[dict]:
        if not self._path.exists():
            return []
        lines = self._path.read_text().strip().split("\n")
        return [json.loads(l) for l in lines[-n:] if l]

    def recent_by_session(self, session_id: str, n: int = 100_000) -> list[dict]:
        return [row for row in self.recent(n) if str(row.get("session_id", "")) == session_id]

    def delete_by_session(self, session_id: str) -> int:
        if not self._path.exists():
            return 0
        kept: list[str] = []
        removed = 0
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    kept.append(line)
                    continue
                if str(row.get("session_id", "")) == session_id:
                    removed += 1
                else:
                    kept.append(line)
        self._path.write_text("".join(kept), encoding="utf-8")
        return removed

    def stats(self) -> dict:
        if not self._path.exists():
            return {"total": 0, "backend": "jsonl"}
        with open(self._path) as f:
            count = sum(1 for _ in f)
        return {"total": count, "backend": "jsonl", "path": str(self._path)}

    def close(self) -> None:
        pass


class SQLiteBackend(StorageBackend):
    """SQLite — zero-config, single-user default."""
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS queries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        tier TEXT,
        model TEXT,
        category TEXT,
        complexity INTEGER,
        cost_usd REAL DEFAULT 0.0,
        latency_ms REAL,
        tokens_in INTEGER,
        tokens_out INTEGER,
        quality_escalated INTEGER DEFAULT 0,
        session_id TEXT,
        query_hash TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_ts ON queries(ts);
    CREATE INDEX IF NOT EXISTS idx_session ON queries(session_id);
    """

    def __init__(self, url: str):
        import sqlite3
        path = url.replace("sqlite:///", "")
        path = os.path.expanduser(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()

    def log(self, record: dict) -> None:
        self._conn.execute(
            "INSERT INTO queries (ts,tier,model,category,complexity,cost_usd,latency_ms,"
            "tokens_in,tokens_out,quality_escalated,session_id,query_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (record.get("ts", time.time()), record.get("tier"), record.get("model"),
             record.get("category"), record.get("complexity"), record.get("cost_usd", record.get("cost", 0)),
             record.get("latency_ms"), record.get("tokens_in"), record.get("tokens_out"),
             int(record.get("quality_escalated", False)), record.get("session_id"),
             record.get("query_hash"))
        )
        self._conn.commit()

    def recent(self, n: int = 50) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM queries ORDER BY ts DESC LIMIT ?", (n,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def recent_by_session(self, session_id: str, n: int = 100_000) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM queries WHERE session_id = ? ORDER BY ts DESC LIMIT ?", (session_id, n))
        cols = [d[0] for d in cur.description]
        return list(reversed([dict(zip(cols, row)) for row in cur.fetchall()]))

    def delete_by_session(self, session_id: str) -> int:
        cur = self._conn.execute("DELETE FROM queries WHERE session_id = ?", (session_id,))
        self._conn.commit()
        return int(cur.rowcount if cur.rowcount is not None else 0)

    def stats(self) -> dict:
        row = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(cost_usd),0), COALESCE(SUM(CASE WHEN cost_usd=0 THEN 1 ELSE 0 END),0) "
            "FROM queries").fetchone()
        return {"total": row[0], "total_cost_usd": round(row[1], 4),
                "free_queries": row[2], "backend": "sqlite"}

    def close(self) -> None:
        self._conn.close()


class PostgreSQLBackend(StorageBackend):
    """PostgreSQL — team/multi-user deployments. Requires psycopg2."""
    def __init__(self, url: str):
        import psycopg2
        import psycopg2.extras
        self._conn = psycopg2.connect(url)
        self._conn.autocommit = True
        with self._conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS queries (
                    id SERIAL PRIMARY KEY, ts FLOAT NOT NULL, tier TEXT, model TEXT,
                    category TEXT, complexity INT, cost_usd FLOAT DEFAULT 0,
                    latency_ms FLOAT, tokens_in INT, tokens_out INT,
                    quality_escalated BOOL DEFAULT FALSE, session_id TEXT, query_hash TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_ts ON queries(ts);
            """)

    def log(self, record: dict) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO queries (ts,tier,model,category,complexity,cost_usd,latency_ms,"
                "tokens_in,tokens_out,quality_escalated,session_id,query_hash) VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (record.get("ts", time.time()), record.get("tier"), record.get("model"),
                 record.get("category"), record.get("complexity"), record.get("cost_usd", record.get("cost", 0)),
                 record.get("latency_ms"), record.get("tokens_in"), record.get("tokens_out"),
                 record.get("quality_escalated", False), record.get("session_id"),
                 record.get("query_hash"))
            )

    def recent(self, n: int = 50) -> list[dict]:
        with self._conn.cursor(cursor_factory=__import__("psycopg2").extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM queries ORDER BY ts DESC LIMIT %s", (n,))
            return [dict(r) for r in cur.fetchall()]

    def recent_by_session(self, session_id: str, n: int = 100_000) -> list[dict]:
        with self._conn.cursor(cursor_factory=__import__("psycopg2").extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM queries WHERE session_id = %s ORDER BY ts DESC LIMIT %s", (session_id, n))
            return list(reversed([dict(r) for r in cur.fetchall()]))

    def delete_by_session(self, session_id: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM queries WHERE session_id = %s", (session_id,))
            return int(cur.rowcount or 0)

    def stats(self) -> dict:
        with self._conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), COALESCE(SUM(cost_usd),0) FROM queries")
            row = cur.fetchone()
        return {"total": row[0], "total_cost_usd": round(row[1], 4), "backend": "postgresql"}

    def close(self) -> None:
        self._conn.close()


class MongoBackend(StorageBackend):
    """MongoDB — document storage, great for variable-schema query logs. Requires pymongo."""
    def __init__(self, url: str):
        from pymongo import MongoClient
        self._client = MongoClient(url)
        db_name = urlparse(url).path.lstrip("/") or "mullm"
        self._col = self._client[db_name]["queries"]
        self._col.create_index("ts")

    def log(self, record: dict) -> None:
        if "ts" not in record:
            record["ts"] = time.time()
        self._col.insert_one(record)

    def recent(self, n: int = 50) -> list[dict]:
        docs = list(self._col.find({}, {"_id": 0}).sort("ts", -1).limit(n))
        return docs

    def recent_by_session(self, session_id: str, n: int = 100_000) -> list[dict]:
        docs = list(self._col.find({"session_id": session_id}, {"_id": 0}).sort("ts", -1).limit(n))
        return list(reversed(docs))

    def delete_by_session(self, session_id: str) -> int:
        result = self._col.delete_many({"session_id": session_id})
        return int(result.deleted_count)

    def stats(self) -> dict:
        pipeline = [{"$group": {"_id": None, "total": {"$sum": 1}, "cost": {"$sum": "$cost_usd"}}}]
        res = list(self._col.aggregate(pipeline))
        if not res:
            return {"total": 0, "total_cost_usd": 0, "backend": "mongodb"}
        return {"total": res[0]["total"], "total_cost_usd": round(res[0].get("cost", 0), 4), "backend": "mongodb"}

    def close(self) -> None:
        self._client.close()


class SnowflakeBackend(StorageBackend):
    """Snowflake — enterprise/data warehouse analytics. Requires snowflake-connector-python."""
    def __init__(self, url: str):
        import snowflake.connector
        parsed = urlparse(url)
        parts = parsed.path.lstrip("/").split("/")
        self._conn = snowflake.connector.connect(
            user=parsed.username, password=parsed.password,
            account=parsed.hostname,
            database=parts[0] if len(parts) > 0 else "MULLM",
            schema=parts[1] if len(parts) > 1 else "PUBLIC",
            warehouse=dict(x.split("=") for x in (parsed.query or "").split("&") if "=" in x).get("warehouse", "COMPUTE_WH"),
        )
        with self._conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS queries (
                    id NUMBER AUTOINCREMENT PRIMARY KEY, ts FLOAT, tier VARCHAR,
                    model VARCHAR, category VARCHAR, complexity INT, cost_usd FLOAT,
                    latency_ms FLOAT, tokens_in INT, tokens_out INT,
                    quality_escalated BOOLEAN, session_id VARCHAR, query_hash VARCHAR
                )
            """)

    def log(self, record: dict) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO queries (ts,tier,model,category,complexity,cost_usd,latency_ms,"
                "tokens_in,tokens_out,quality_escalated,session_id,query_hash) VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (record.get("ts", time.time()), record.get("tier"), record.get("model"),
                 record.get("category"), record.get("complexity"), record.get("cost_usd", record.get("cost", 0)),
                 record.get("latency_ms"), record.get("tokens_in"), record.get("tokens_out"),
                 record.get("quality_escalated", False), record.get("session_id"),
                 record.get("query_hash"))
            )

    def recent(self, n: int = 50) -> list[dict]:
        with self._conn.cursor(__import__("snowflake.connector").connector.DictCursor) as cur:
            cur.execute("SELECT * FROM queries ORDER BY ts DESC LIMIT %s", (n,))
            return cur.fetchall()

    def recent_by_session(self, session_id: str, n: int = 100_000) -> list[dict]:
        with self._conn.cursor(__import__("snowflake.connector").connector.DictCursor) as cur:
            cur.execute("SELECT * FROM queries WHERE session_id = %s ORDER BY ts DESC LIMIT %s", (session_id, n))
            return list(reversed(cur.fetchall()))

    def delete_by_session(self, session_id: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM queries WHERE session_id = %s", (session_id,))
            return int(cur.rowcount or 0)

    def stats(self) -> dict:
        with self._conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), COALESCE(SUM(cost_usd),0) FROM queries")
            row = cur.fetchone()
        return {"total": row[0], "total_cost_usd": round(row[1], 4), "backend": "snowflake"}

    def close(self) -> None:
        self._conn.close()


def get_storage(url: str | None = None) -> StorageBackend:
    """Factory: create the right backend from DATABASE_URL or config."""
    if url is None:
        url = os.getenv("DATABASE_URL", "")
    if not url:
        # Default: SQLite under the user-writable muLLM runtime cache.
        from router.config import settings

        url = f"sqlite:///{settings.cache_dir / 'mullm.db'}"

    if url.startswith("jsonl://"):
        return JSONLBackend(url)
    elif url.startswith("sqlite://"):
        return SQLiteBackend(url)
    elif url.startswith("postgresql://") or url.startswith("postgres://"):
        return PostgreSQLBackend(url)
    elif url.startswith("mongodb://") or url.startswith("mongodb+srv://"):
        return MongoBackend(url)
    elif url.startswith("snowflake://"):
        return SnowflakeBackend(url)
    else:
        raise ValueError(f"Unsupported DATABASE_URL scheme: {url[:30]}")
