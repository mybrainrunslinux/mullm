"""
muLLM Tier 1 — Semantic vector cache wrapper.

Design decisions:
  - Default backend: dependency-free SQLite cosine scan for safer fresh installs.
  - Lazy initialisation: ChromaDB import happens inside _get_client() so the
    module can be imported even when chromadb is not installed.
  - Graceful degrade: any cache / embedding error → log warning, return None.
  - ELO-style update: only overwrite a cached entry when the new response is
    longer (proxy for quality) than the existing one.
  - Embeddings: prefer Ollama nomic-embed-text (768-dim); fall back to
    sentence-transformers if Ollama is unreachable.
  - Per-category cosine thresholds (see config.CACHE_THRESHOLDS_BY_CATEGORY).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import time
from typing import Any

import httpx

from router.config import CACHE_THRESHOLDS_BY_CATEGORY, settings

logger = logging.getLogger("mullm.cache")

# ---------------------------------------------------------------------------
# PII detection
# ---------------------------------------------------------------------------

_PII_PATTERNS = [
    re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),          # SSN
    re.compile(r'\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b'),  # credit card
    re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),  # email
]


def _contains_pii(text: str) -> bool:
    return any(p.search(text) for p in _PII_PATTERNS)


# Module-level lazy references (populated on first use)
_chroma_client: Any = None
_chroma_collection: Any = None
_sqlite_conn: sqlite3.Connection | None = None
_sqlite_path: str | None = None
_redis_client: Any = None
_redis_unavailable: bool = False
_st_model: Any = None          # sentence-transformers fallback

_COLLECTION_NAME = "mullm_v1"
_REDIS_PREFIX = "mullm:exact:"
_REDIS_TTL_SECONDS = 60 * 60 * 24


# ---------------------------------------------------------------------------
# Backend helpers
# ---------------------------------------------------------------------------

def _backend() -> str:
    return str(getattr(settings, "semantic_cache_backend", "sqlite") or "sqlite").strip().lower()


def backend_name() -> str:
    """Return the configured semantic cache backend name for health/UI surfaces."""
    return _backend()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _sqlite_db_path() -> str:
    return str(settings.cache_dir / "semantic_cache.sqlite3")


def _get_sqlite_conn() -> sqlite3.Connection | None:
    """Return the default dependency-free SQLite semantic cache connection."""
    global _sqlite_conn, _sqlite_path
    path = _sqlite_db_path()
    if _sqlite_conn is not None and _sqlite_path == path:
        return _sqlite_conn
    try:
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS semantic_cache (
                id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                response TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                query_length INTEGER NOT NULL,
                response_length INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_semantic_cache_timestamp ON semantic_cache(timestamp)")
        conn.commit()
        _sqlite_conn = conn
        _sqlite_path = path
        return conn
    except Exception as exc:
        logger.warning("SQLite semantic cache unavailable: %s", exc)
        return None


# ---------------------------------------------------------------------------
# ChromaDB client initialisation
# ---------------------------------------------------------------------------

def _get_client() -> Any | None:
    """Return a (lazy-initialised) ChromaDB PersistentClient, or None on failure."""
    global _chroma_client, _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection
    try:
        import chromadb  # deferred import — graceful degrade if not installed
        chroma_path = str(settings.cache_dir / "chromadb")
        _chroma_client = chromadb.PersistentClient(path=chroma_path)
        _chroma_collection = _chroma_client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("ChromaDB initialised at %s (collection=%s)", chroma_path, _COLLECTION_NAME)
        return _chroma_collection
    except Exception as exc:
        logger.warning("ChromaDB unavailable — cache disabled: %s", exc)
        return None


def _sqlite_lookup(query: str, embedding: list[float], threshold: float) -> tuple[str, dict] | None:
    conn = _get_sqlite_conn()
    if conn is None:
        return None
    try:
        best: tuple[float, sqlite3.Row] | None = None
        for row in conn.execute(
            "SELECT id, query, response, embedding_json, metadata_json FROM semantic_cache"
        ):
            try:
                candidate = [float(v) for v in json.loads(row["embedding_json"])]
            except Exception:
                continue
            similarity = _cosine_similarity(embedding, candidate)
            if best is None or similarity > best[0]:
                best = (similarity, row)
        if best is None or best[0] < threshold:
            return None
        similarity, row = best
        try:
            meta = json.loads(row["metadata_json"])
            if not isinstance(meta, dict):
                meta = {}
        except Exception:
            meta = {}
        meta["cache_similarity"] = round(similarity, 4)
        meta["cache_backend"] = "sqlite"
        return str(row["response"]), meta
    except Exception as exc:
        logger.warning("SQLite cache lookup error: %s", exc)
        return None


def _sqlite_store(query: str, response: str, embedding: list[float], metadata: dict) -> bool:
    conn = _get_sqlite_conn()
    if conn is None:
        return False
    doc_id = _cache_id(query)
    now = int(time.time())
    meta = dict(metadata)
    meta.setdefault("cache_backend", "sqlite")
    try:
        existing = conn.execute(
            "SELECT response_length FROM semantic_cache WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if existing is not None and int(existing["response_length"]) >= len(response):
            logger.debug(
                "SQLite cache ELO-gate: skipping update (existing=%d >= new=%d chars)",
                int(existing["response_length"]),
                len(response),
            )
            return False
        conn.execute(
            """
            INSERT INTO semantic_cache (
                id, query, response, embedding_json, metadata_json,
                timestamp, query_length, response_length
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                query = excluded.query,
                response = excluded.response,
                embedding_json = excluded.embedding_json,
                metadata_json = excluded.metadata_json,
                timestamp = excluded.timestamp,
                query_length = excluded.query_length,
                response_length = excluded.response_length
            """,
            (
                doc_id,
                query,
                response,
                json.dumps([float(v) for v in embedding]),
                json.dumps(meta),
                now,
                len(query),
                len(response),
            ),
        )
        conn.commit()
        return True
    except Exception as exc:
        logger.warning("SQLite cache store error: %s", exc)
        return False


def _get_redis_client() -> Any | None:
    """Return optional Redis exact-match cache client, or None when absent."""
    global _redis_client, _redis_unavailable
    if _redis_client is not None:
        return _redis_client
    if _redis_unavailable:
        return None

    url = (
        settings.redis_url
        or os.getenv("MULLM_REDIS_URL")
        or os.getenv("REDIS_URL")
        or os.getenv("MULLM_CACHE_REDIS_URL")
        or ""
    )
    if not url:
        return None
    try:
        import redis  # optional dependency
        _redis_client = redis.Redis.from_url(
            url,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
            decode_responses=True,
        )
        _redis_client.ping()
        return _redis_client
    except Exception as exc:
        _redis_unavailable = True
        logger.info("Redis exact cache unavailable; falling back to ChromaDB only: %s", exc)
        return None


def _redis_key(text: str) -> str:
    return _REDIS_PREFIX + _cache_id(text)


def _lookup_redis_exact(query: str) -> tuple[str, dict] | None:
    client = _get_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(_redis_key(_normalize_query(query)))
        if not raw:
            return None
        payload = json.loads(raw)
        response = str(payload.get("response") or "")
        if not response:
            return None
        meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        meta["cache_similarity"] = 1.0
        meta["cache_backend"] = "redis_exact"
        return response, meta
    except Exception as exc:
        logger.debug("Redis exact cache lookup failed: %s", exc)
        return None


def _store_redis_exact(query: str, response: str, metadata: dict) -> bool:
    client = _get_redis_client()
    if client is None:
        return False
    try:
        payload = {
            "response": response,
            "metadata": metadata,
            "timestamp": int(time.time()),
        }
        client.setex(_redis_key(query), _REDIS_TTL_SECONDS, json.dumps(payload))
        return True
    except Exception as exc:
        logger.debug("Redis exact cache store failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Query normalization — reduces word-order variance before embedding
# ---------------------------------------------------------------------------

import re as _re

_QUESTION_PREFIX_RE = _re.compile(
    r"^(?:what(?:'s| is)(?: the)?|can you|could you|please|tell me|explain|describe|show me|how do(?:es)?|why is|when is|where is)\s+",
    _re.IGNORECASE,
)
_FILLER_RE = _re.compile(r"\b(?:please|just|quickly|briefly|simply|really|actually|basically)\b", _re.IGNORECASE)


def _normalize_query(text: str) -> str:
    """Light normalization so near-duplicate phrasings share closer embeddings."""
    t = text.strip().lower()
    t = _QUESTION_PREFIX_RE.sub("", t)
    t = _FILLER_RE.sub("", t)
    t = _re.sub(r"\s{2,}", " ", t).strip().rstrip("?.!")
    return t or text.strip().lower()


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

async def _embed_ollama(text: str) -> list[float] | None:
    """Call Ollama /api/embeddings for nomic-embed-text."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/embeddings",
                json={"model": settings.ollama_embed_model, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json()["embedding"]
    except Exception as exc:
        logger.debug("Ollama embedding failed: %s", exc)
        return None


def _embed_sentence_transformers(text: str) -> list[float] | None:
    """Fallback: sentence-transformers local embed."""
    global _st_model
    try:
        if _st_model is None:
            from sentence_transformers import SentenceTransformer  # deferred
            _st_model = SentenceTransformer("all-MiniLM-L6-v2")
        vec = _st_model.encode(text, normalize_embeddings=True)
        return vec.tolist()
    except Exception as exc:
        logger.debug("sentence-transformers fallback failed: %s", exc)
        return None


async def _embed(text: str) -> list[float] | None:
    """Get embedding, trying Ollama first then sentence-transformers."""
    vec = await _embed_ollama(text)
    if vec is not None:
        return vec
    # Run sync fallback in executor to avoid blocking event loop
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _embed_sentence_transformers, text)


# ---------------------------------------------------------------------------
# Cache ID (stable key for dedup)
# ---------------------------------------------------------------------------

def _cache_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def lookup(
    query: str,
    category: str = "default",
) -> tuple[str, dict] | None:
    """
    Semantic similarity lookup.

    Returns (cached_response, metadata) if a hit is found above the
    category-specific cosine threshold, else None.
    """
    exact = _lookup_redis_exact(query)
    query = _normalize_query(query)
    if exact is not None:
        return exact

    backend = _backend()
    if backend == "off":
        return None

    embedding = await _embed(query)
    if embedding is None:
        return None

    threshold = CACHE_THRESHOLDS_BY_CATEGORY.get(category, settings.cache_cosine_threshold)

    if backend != "chroma":
        return _sqlite_lookup(query, embedding, threshold)

    col = _get_client()
    if col is None:
        return None

    try:
        results = col.query(
            query_embeddings=[embedding],
            n_results=1,
            include=["documents", "metadatas", "distances"],
        )
        if not results["ids"][0]:
            return None

        distance = results["distances"][0][0]
        # ChromaDB cosine distance: 0 = identical, 2 = opposite
        # similarity = 1 - (distance / 2) for normalised cosine space
        similarity = 1.0 - (distance / 2.0)

        if similarity < threshold:
            return None

        response_text = results["documents"][0][0]
        meta = results["metadatas"][0][0] or {}
        meta["cache_similarity"] = round(similarity, 4)
        logger.debug("Cache hit (sim=%.4f, threshold=%.2f)", similarity, threshold)
        return (response_text, meta)

    except Exception as exc:
        logger.warning("Cache lookup error: %s", exc)
        return None


async def store(
    query: str,
    response: str,
    metadata: dict | None = None,
) -> bool:
    """
    Store a (query, response) pair in the vector cache.

    ELO-update semantics: if an entry with the same ID already exists and the
    existing response is longer than the new one, skip the update (assume
    longer = higher quality proxy).
    """
    if not settings.log_query_content:
        return False  # privacy mode — do not persist query/response text

    # PII guard — skip cache storage if query or response contains PII
    if _contains_pii(query) or _contains_pii(response):
        logger.warning("Cache store skipped — PII detected in query or response")
        return False

    query = _normalize_query(query)
    meta = metadata or {}
    meta["timestamp"] = int(time.time())
    meta["query_length"] = len(query)
    meta["response_length"] = len(response)
    _store_redis_exact(query, response, meta)

    backend = _backend()
    if backend == "off":
        return False

    embedding = await _embed(query)
    if embedding is None:
        return False

    if backend != "chroma":
        return _sqlite_store(query, response, embedding, meta)

    col = _get_client()
    if col is None:
        return False

    doc_id = _cache_id(query)

    try:
        # Check if entry exists (ELO gate)
        existing = col.get(ids=[doc_id], include=["documents", "metadatas"])
        if existing["ids"]:
            existing_len = len(existing["documents"][0])
            if existing_len >= len(response):
                logger.debug("Cache ELO-gate: skipping update (existing=%d >= new=%d chars)", existing_len, len(response))
                return False
            # Overwrite with better response
            col.update(ids=[doc_id], documents=[response], embeddings=[embedding], metadatas=[meta])
            logger.debug("Cache updated (ELO improvement)")
        else:
            col.add(ids=[doc_id], documents=[response], embeddings=[embedding], metadatas=[meta])
            logger.debug("Cache stored (id=%s)", doc_id)
        return True
    except Exception as exc:
        logger.warning("Cache store error: %s", exc)
        return False


def is_available() -> bool:
    """Return True if the configured semantic cache backend is reachable."""
    backend = _backend()
    if backend == "off":
        return False
    if backend != "chroma":
        return _get_sqlite_conn() is not None
    return _get_client() is not None


def count_entries() -> int:
    """Return semantic cache entry count for health/privacy status."""
    backend = _backend()
    if backend == "off":
        return 0
    if backend != "chroma":
        conn = _get_sqlite_conn()
        if conn is None:
            return 0
        try:
            row = conn.execute("SELECT COUNT(*) AS n FROM semantic_cache").fetchone()
            return int(row["n"]) if row is not None else 0
        except Exception:
            return 0
    col = _get_client()
    if col is None:
        return 0
    try:
        return int(col.count())
    except Exception:
        return 0


def clear_entries() -> tuple[bool, int, int]:
    """Clear configured semantic cache. Returns (cleared, before, remaining)."""
    backend = _backend()
    if backend == "off":
        return False, 0, 0
    if backend != "chroma":
        conn = _get_sqlite_conn()
        cleared_any = False
        before = count_entries() if conn is not None else 0
        if conn is not None:
            try:
                conn.execute("DELETE FROM semantic_cache")
                conn.commit()
                cleared_any = True
            except Exception as exc:
                logger.warning("SQLite cache clear error: %s", exc)
        chroma_remaining = 0
        if _chroma_collection is not None:
            try:
                chroma_before = int(_chroma_collection.count())
                if chroma_before:
                    items = _chroma_collection.get(include=[])
                    ids = items.get("ids", [])
                    if ids:
                        _chroma_collection.delete(ids=ids)
                    cleared_any = True
                chroma_remaining = int(_chroma_collection.count())
            except Exception as exc:
                logger.warning("Chroma side-cache clear error: %s", exc)
        remaining = max(count_entries() if conn is not None else 0, chroma_remaining)
        return cleared_any, before, remaining
    col = _get_client()
    if col is None:
        return False, 0, 0
    try:
        before = int(col.count())
        if before:
            items = col.get(include=[])
            ids = items.get("ids", [])
            if ids:
                col.delete(ids=ids)
        return True, before, int(col.count())
    except Exception as exc:
        logger.warning("Chroma cache clear error: %s", exc)
        return False, 0, 0


def scan_entries(limit: int = 1000, offset: int = 0) -> list[dict[str, Any]]:
    """Return cache entries for privacy export/review without exposing backend internals."""
    backend = _backend()
    if backend == "off":
        return []
    if backend != "chroma":
        conn = _get_sqlite_conn()
        if conn is None:
            return []
        try:
            rows = conn.execute(
                """
                SELECT id, response, metadata_json
                FROM semantic_cache
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                (max(1, int(limit)), max(0, int(offset))),
            ).fetchall()
        except Exception as exc:
            logger.warning("SQLite cache scan error: %s", exc)
            return []
        entries: list[dict[str, Any]] = []
        for row in rows:
            try:
                meta = json.loads(row["metadata_json"])
                if not isinstance(meta, dict):
                    meta = {}
            except Exception:
                meta = {}
            entries.append({"id": row["id"], "document": row["response"], "metadata": meta})
        return entries

    col = _get_client()
    if col is None:
        return []
    try:
        results = col.get(limit=limit, offset=offset, include=["documents", "metadatas"])
    except Exception as exc:
        logger.warning("Cache scan error: %s", exc)
        return []
    ids = results.get("ids") or []
    docs = results.get("documents") or []
    metas = results.get("metadatas") or []
    entries: list[dict[str, Any]] = []
    for idx, doc_id in enumerate(ids):
        entries.append(
            {
                "id": doc_id,
                "document": docs[idx] if idx < len(docs) else "",
                "metadata": metas[idx] if idx < len(metas) and isinstance(metas[idx], dict) else {},
            }
        )
    return entries


def export_entries_by_session(session_id: str, limit: int = 100_000) -> list[dict[str, Any]]:
    """Return cache entries tagged with a session id."""
    if not session_id:
        return []
    entries: list[dict[str, Any]] = []
    for entry in scan_entries(limit=limit):
        if str(entry.get("metadata", {}).get("session_id", "")) == session_id:
            entries.append(entry)
    return entries


def delete_entries_by_session(session_id: str, limit: int = 100_000) -> int:
    """Delete cache entries tagged with a session id."""
    backend = _backend()
    if backend != "chroma":
        conn = _get_sqlite_conn()
        if conn is None or not session_id:
            return 0
        ids = [entry["id"] for entry in export_entries_by_session(session_id, limit=limit) if entry.get("id")]
        if not ids:
            return 0
        try:
            conn.executemany("DELETE FROM semantic_cache WHERE id = ?", [(doc_id,) for doc_id in ids])
            conn.commit()
            return len(ids)
        except Exception as exc:
            logger.warning("SQLite cache session delete error: %s", exc)
            return 0

    col = _get_client()
    if col is None or not session_id:
        return 0
    ids = [entry["id"] for entry in export_entries_by_session(session_id, limit=limit) if entry.get("id")]
    if not ids:
        return 0
    try:
        col.delete(ids=ids)
        return len(ids)
    except Exception as exc:
        logger.warning("Cache session delete error: %s", exc)
        return 0


def delete_entry(entry_id: str | None = None, query: str | None = None) -> int:
    """Delete one cache entry by id or exact query hash."""
    backend = _backend()
    doc_id = entry_id or (_cache_id(_normalize_query(query)) if query else "")
    if not doc_id:
        return 0
    if backend != "chroma":
        conn = _get_sqlite_conn()
        if conn is None:
            return 0
        try:
            cur = conn.execute("DELETE FROM semantic_cache WHERE id = ?", (doc_id,))
            conn.commit()
            return int(cur.rowcount or 0)
        except Exception as exc:
            logger.warning("SQLite cache entry delete error: %s", exc)
            return 0

    col = _get_client()
    if col is None:
        return 0
    try:
        existing = col.get(ids=[doc_id], include=[])
        if not existing.get("ids"):
            return 0
        col.delete(ids=[doc_id])
        return 1
    except Exception as exc:
        logger.warning("Cache entry delete error: %s", exc)
        return 0
