"""
Storage backend smoke tests.

Coverage:
  - JSONLBackend: log / recent / stats / close (in-process, no deps)
  - SQLiteBackend: log / recent / stats / roundtrip / schema idempotency (in-process, no deps)
  - PostgreSQLBackend: import-only guard + skip if psycopg2 absent
  - MongoBackend: import-only guard + skip if pymongo absent
  - SnowflakeBackend: import-only guard + skip if snowflake-connector-python absent
  - get_storage factory: URL dispatch, unknown scheme raises
  - No cloud API calls, no real money spent.
"""
from __future__ import annotations

import importlib
import time

import pytest

from router.storage import (
    JSONLBackend,
    SQLiteBackend,
    get_storage,
)

# ---------------------------------------------------------------------------
# Shared fixture: a minimal valid query record
# ---------------------------------------------------------------------------

SAMPLE = {
    "ts": time.time(),
    "tier": "tier1",
    "model": "qwen3.5:9b",
    "category": "code",
    "complexity": 3,
    "cost_usd": 0.0,
    "latency_ms": 14.2,
    "tokens_in": 42,
    "tokens_out": 18,
    "quality_escalated": False,
    "session_id": "test-session-abc",
    "query_hash": "deadbeef",
}


# ---------------------------------------------------------------------------
# JSONL backend
# ---------------------------------------------------------------------------

class TestJSONLBackend:
    def test_log_creates_file(self, tmp_path):
        path = tmp_path / "sub" / "log.jsonl"
        b = JSONLBackend(f"jsonl:///{path}")
        b.log(dict(SAMPLE))
        assert path.exists()
        b.close()

    def test_log_and_recent_roundtrip(self, tmp_path):
        b = JSONLBackend(f"jsonl:///{tmp_path}/q.jsonl")
        for i in range(5):
            r = dict(SAMPLE)
            r["tokens_out"] = i
            b.log(r)
        recent = b.recent(3)
        assert len(recent) == 3
        # most recent has highest tokens_out
        assert recent[-1]["tokens_out"] == 4
        b.close()

    def test_stats_counts(self, tmp_path):
        b = JSONLBackend(f"jsonl:///{tmp_path}/q.jsonl")
        for _ in range(7):
            b.log(dict(SAMPLE))
        s = b.stats()
        assert s["total"] == 7
        assert s["backend"] == "jsonl"
        b.close()

    def test_recent_on_missing_file_returns_empty(self, tmp_path):
        b = JSONLBackend(f"jsonl:///{tmp_path}/nonexistent.jsonl")
        assert b.recent() == []

    def test_stats_on_missing_file(self, tmp_path):
        b = JSONLBackend(f"jsonl:///{tmp_path}/nonexistent.jsonl")
        assert b.stats()["total"] == 0


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------

class TestSQLiteBackend:
    def test_schema_created(self, tmp_path):
        import sqlite3
        db_path = tmp_path / "test.db"
        b = SQLiteBackend(f"sqlite:///{db_path}")
        conn = sqlite3.connect(str(db_path))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "queries" in tables
        conn.close()
        b.close()

    def test_log_and_recent(self, tmp_path):
        b = SQLiteBackend(f"sqlite:///{tmp_path}/test.db")
        b.log(dict(SAMPLE))
        rows = b.recent(10)
        assert len(rows) == 1
        assert rows[0]["tier"] == "tier1"
        assert rows[0]["model"] == "qwen3.5:9b"
        assert rows[0]["query_hash"] == "deadbeef"
        b.close()

    def test_multiple_records_order(self, tmp_path):
        b = SQLiteBackend(f"sqlite:///{tmp_path}/test.db")
        for i in range(10):
            r = dict(SAMPLE, ts=time.time() + i, tokens_out=i)
            b.log(r)
        rows = b.recent(5)
        assert len(rows) == 5
        # most recent first
        assert rows[0]["tokens_out"] == 9
        b.close()

    def test_stats_free_query_count(self, tmp_path):
        b = SQLiteBackend(f"sqlite:///{tmp_path}/test.db")
        b.log(dict(SAMPLE, cost_usd=0.0))
        b.log(dict(SAMPLE, cost_usd=0.0))
        b.log(dict(SAMPLE, cost_usd=0.003))
        s = b.stats()
        assert s["total"] == 3
        assert s["free_queries"] == 2
        assert s["backend"] == "sqlite"
        b.close()

    def test_stats_total_cost(self, tmp_path):
        b = SQLiteBackend(f"sqlite:///{tmp_path}/test.db")
        b.log(dict(SAMPLE, cost_usd=0.01))
        b.log(dict(SAMPLE, cost_usd=0.02))
        s = b.stats()
        assert abs(s["total_cost_usd"] - 0.03) < 0.0001
        b.close()

    def test_schema_idempotency(self, tmp_path):
        """Creating the backend twice on the same file must not raise."""
        path = f"sqlite:///{tmp_path}/idem.db"
        b1 = SQLiteBackend(path)
        b1.log(dict(SAMPLE))
        b1.close()
        b2 = SQLiteBackend(path)
        rows = b2.recent()
        assert len(rows) == 1
        b2.close()

    def test_quality_escalated_bool_stored(self, tmp_path):
        b = SQLiteBackend(f"sqlite:///{tmp_path}/test.db")
        b.log(dict(SAMPLE, quality_escalated=True))
        rows = b.recent(1)
        assert rows[0]["quality_escalated"] in (1, True)
        b.close()


# ---------------------------------------------------------------------------
# get_storage factory
# ---------------------------------------------------------------------------

class TestGetStorageFactory:
    def test_default_returns_sqlite(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        b = get_storage("sqlite:///./cache/data/mullm.db")
        assert isinstance(b, SQLiteBackend)
        b.close()

    def test_empty_default_uses_runtime_cache(self, tmp_path, monkeypatch):
        from router.config import settings

        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(settings, "cache_dir", tmp_path / "runtime-cache")

        b = get_storage()

        try:
            assert isinstance(b, SQLiteBackend)
            assert (tmp_path / "runtime-cache" / "mullm.db").exists()
        finally:
            b.close()

    def test_jsonl_url(self, tmp_path):
        b = get_storage(f"jsonl:///{tmp_path}/x.jsonl")
        assert isinstance(b, JSONLBackend)
        b.close()

    def test_unknown_scheme_raises(self):
        with pytest.raises(ValueError, match="Unsupported DATABASE_URL"):
            get_storage("redis://localhost/0")

    def test_postgresql_alias(self, monkeypatch):
        """postgres:// alias must route to PostgreSQLBackend (or skip if psycopg2 absent)."""
        psycopg2 = importlib.util.find_spec("psycopg2")
        if psycopg2 is None:
            pytest.skip("psycopg2 not installed — PostgreSQLBackend import-only check passes")
        # If psycopg2 IS installed, an invalid URL should raise a connection error,
        # not a ValueError about the scheme.
        with pytest.raises(Exception) as exc:
            get_storage("postgres://invalid-host/testdb")
        assert "Unsupported" not in str(exc.value)


# ---------------------------------------------------------------------------
# PostgreSQL — connection-guarded (requires live server; skip if no psycopg2)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    importlib.util.find_spec("psycopg2") is None,
    reason="psycopg2 not installed",
)
class TestPostgreSQLBackendImport:
    def test_class_importable(self):
        from router.storage import PostgreSQLBackend
        assert PostgreSQLBackend is not None


# ---------------------------------------------------------------------------
# MongoDB — import guard
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    importlib.util.find_spec("pymongo") is None,
    reason="pymongo not installed",
)
class TestMongoBackendImport:
    def test_class_importable(self):
        from router.storage import MongoBackend
        assert MongoBackend is not None


# ---------------------------------------------------------------------------
# Snowflake — import guard
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    importlib.util.find_spec("snowflake") is None,
    reason="snowflake-connector-python not installed",
)
class TestSnowflakeBackendImport:
    def test_class_importable(self):
        from router.storage import SnowflakeBackend
        assert SnowflakeBackend is not None
