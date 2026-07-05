"""
Semantic vector cache using ChromaDB + Ollama embeddings.
Redis RAM exact-match layer for sub-ms hits on repeated queries.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

try:
    import chromadb as _chromadb
    _CHROMADB_AVAILABLE = True
except Exception:  # nosec -- graceful degrade when chromadb/otel versions mismatch
    _chromadb = None  # type: ignore[assignment]
    _CHROMADB_AVAILABLE = False
try:
    import ollama as ollama_client
    _OLLAMA_AVAILABLE = True
except ImportError:
    ollama_client = None  # type: ignore[assignment]
    _OLLAMA_AVAILABLE = False
import structlog

from router.config import CACHE_THRESHOLDS_BY_CATEGORY, settings
from router.models import CacheResult

CACHE_HIT_THRESHOLD = settings.cache_cosine_threshold
CACHE_PARTIAL_THRESHOLD = max(0.0, CACHE_HIT_THRESHOLD - 0.06)
CACHE_THRESHOLDS = {
    **CACHE_THRESHOLDS_BY_CATEGORY,
    "default": CACHE_HIT_THRESHOLD,
}
CACHE_TTL_SECONDS = settings.cache_ttl_days * 86400
CHROMA_DIR = str(settings.cache_dir / "chromadb")
EMBED_MODEL = settings.ollama_embed_model
REDIS_RAM_URL = settings.redis_url

# ── Redis RAM exact-match cache ──────────────────────────────
_redis_client = None
try:
    import redis

    if REDIS_RAM_URL:
        _redis_client = redis.from_url(REDIS_RAM_URL, decode_responses=True, socket_timeout=0.1)
        _redis_client.ping()
except Exception:
    _redis_client = None

# ── Displacement Log — implicit model quality signal ────────
_DISPLACEMENT_LOG = Path(CHROMA_DIR).parent / "displacement_log.jsonl"

log = structlog.get_logger()

# [Suggestion #1] Semaphore prevents embed calls from starving the GPU
_embed_sem = asyncio.Semaphore(settings.embed_concurrency)


# ── Ollama Embedding Function for ChromaDB (with LRU cache) ──
_EmbedBase = _chromadb.EmbeddingFunction if _CHROMADB_AVAILABLE else object


class OllamaEmbedder(_EmbedBase):
    def __init__(self, model: str = EMBED_MODEL, cache_size: int = 4000):
        self.model = model
        # OrderedDict gives O(1) move_to_end + O(1) popitem
        from collections import OrderedDict

        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = cache_size
        self._hits = 0
        self._misses = 0

    def _cache_get(self, text: str) -> list[float] | None:
        if text in self._cache:
            self._hits += 1
            self._cache.move_to_end(text)  # O(1) vs O(n) list.remove
            return self._cache[text]
        return None

    def _cache_put(self, text: str, embedding: list[float]) -> None:
        if text in self._cache:
            return
        self._misses += 1
        self._cache[text] = embedding
        # Evict oldest if over capacity — O(1) popitem
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    @property
    def cache_stats(self) -> dict:
        return {
            "size": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / max(self._hits + self._misses, 1), 3),
        }

    def __call__(self, input: list[str]) -> list[Any]:  # type: ignore[override]
        embeddings = []
        for text in input:
            cached = self._cache_get(text)
            if cached is not None:
                embeddings.append(cached)
            else:
                if ollama_client is None:
                    raise RuntimeError("ollama package not installed")
                response = ollama_client.embed(model=self.model, input=text, keep_alive=-1)
                emb = response["embeddings"][0]
                self._cache_put(text, emb)
                embeddings.append(emb)
        return embeddings


class VectorCache:
    """Semantic cache backed by ChromaDB."""

    def __init__(self, collection_name: str = "intent_cache", chroma_dir: str | None = None):
        if not _CHROMADB_AVAILABLE:
            raise RuntimeError(
                "chromadb is not importable (opentelemetry version mismatch). "
                "Run: pip install 'chromadb>=1.0,<2.0' 'opentelemetry-sdk>=1.30,<1.38'"
            )
        _path = chroma_dir or CHROMA_DIR
        self.client = _chromadb.PersistentClient(path=_path)
        self.embedder = OllamaEmbedder()
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedder,
            metadata={"hnsw:space": "cosine"},
        )
        log.info(
            "vector_cache_ready",
            path=CHROMA_DIR,
            docs=self.collection.count(),
        )

    async def lookup_async(self, query: str, n_results: int = 1, category: str = "") -> CacheResult:
        """Async wrapper — respects embed semaphore."""
        async with _embed_sem:
            return await asyncio.to_thread(self.lookup, query, n_results, category)

    def lookup(self, query: str, n_results: int = 1, category: str = "") -> CacheResult:
        """Search the cache for semantically similar past queries.
        Checks Redis exact-match first (sub-ms), then ChromaDB semantic."""
        start = time.perf_counter()

        # Redis exact-match layer — sub-ms for repeated queries
        if _redis_client and not getattr(self, "_skip_redis", False):
            try:
                key = f"mullm:exact:{hashlib.md5(query.strip().lower().encode()).hexdigest()}"
                cached = _redis_client.get(key)
                if cached:
                    data = json.loads(cached)  # type: ignore[arg-type]
                    if isinstance(data, dict):
                        latency = (time.perf_counter() - start) * 1000
                        log.info("redis_exact_hit", query=query[:40], latency_ms=round(latency, 3))
                        return CacheResult(
                            hit=True,
                            similarity=1.0,
                            cached_response=data.get("response", ""),
                            cached_metadata={
                                "original_query": data.get("query", query),
                                "model": data.get("model", "redis-exact"),
                                "tier": data.get("tier", "cache"),
                            },
                            lookup_latency_ms=round(latency, 3),
                        )
                    # else: corrupt Redis entry — fall through to ChromaDB
            except Exception:
                pass  # Redis down — fall through to ChromaDB

        if self.collection.count() == 0:
            latency = (time.perf_counter() - start) * 1000
            return CacheResult(
                hit=False,
                similarity=0.0,
                lookup_latency_ms=round(latency, 1),
            )

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            log.warning("cache_query_error", error=str(e)[:100])
            return CacheResult(
                hit=False,
                similarity=0.0,
                lookup_latency_ms=round(latency, 1),
            )

        latency = (time.perf_counter() - start) * 1000

        if not results["documents"] or not results["documents"][0]:
            return CacheResult(
                hit=False,
                similarity=0.0,
                lookup_latency_ms=round(latency, 1),
            )

        distance = results["distances"][0][0]
        similarity = 1.0 - (distance / 2.0)

        metadata = results["metadatas"][0][0] if results["metadatas"][0] else {}
        cached_response = metadata.get("response", "")
        matched_query = results["documents"][0][0]

        # [Suggestion #7] Cache TTL — old entries become partial hits
        age_seconds = 0.0
        cached_at = float(str(metadata.get("cached_at", 0)) or "0")
        if cached_at > 0:
            age_seconds = time.time() - cached_at

        # vCache-inspired: use per-category threshold if category is known,
        # otherwise fall back to the global CACHE_HIT_THRESHOLD.
        # CACHE_THRESHOLDS is mutable so update_threshold() can nudge it at runtime.
        hit_threshold = CACHE_THRESHOLDS.get(category, CACHE_THRESHOLDS.get("default", CACHE_HIT_THRESHOLD))
        # Creative queries containing code/HTML/function keywords need code-level strictness —
        # similar-sounding prompts produce completely different implementations.
        _CODE_SIGNALS = ("html", "javascript", "function", "class ", "def ", "css", "canvas", "```")
        if category == "creative" and any(s in query.lower() for s in _CODE_SIGNALS):
            hit_threshold = max(hit_threshold, CACHE_THRESHOLDS.get("code", 0.97))

        is_expired = age_seconds > CACHE_TTL_SECONDS and cached_at > 0
        is_hit = similarity >= hit_threshold and not is_expired
        is_partial = (CACHE_PARTIAL_THRESHOLD <= similarity < hit_threshold) or (
            similarity >= hit_threshold and is_expired
        )

        log.info(
            "cache_lookup",
            similarity=round(similarity, 3),
            threshold=round(hit_threshold, 3),
            category=category or "default",
            hit=is_hit,
            partial=is_partial,
            expired=is_expired,
            age_days=round(age_seconds / 86400, 1) if cached_at else 0,
            matched=matched_query[:60],
            latency_ms=round(latency, 1),
        )

        return CacheResult(
            hit=is_hit,
            similarity=round(similarity, 4),
            cached_response=str(cached_response) if (is_hit and cached_response) else None,
            cached_metadata={
                "matched_query": matched_query,
                "tier": metadata.get("tier", ""),
                "model": metadata.get("model", ""),
                "cost": float(str(metadata.get("cost", 0)) or "0"),
                "is_partial": is_partial,
            },
            lookup_latency_ms=round(latency, 1),
            source="vector",
            age_seconds=round(age_seconds, 1),
        )

    async def store_async(self, **kwargs) -> None:
        """Async wrapper for store."""
        async with _embed_sem:
            await asyncio.to_thread(self.store, **kwargs)

    def store(
        self,
        query: str,
        response: str,
        intent_id: str,
        tier: str = "",
        model: str = "",
        cost: float = 0.0,
        category: str = "",
        complexity: int = 0,
        success: bool = True,
    ) -> None:
        """Store a query + response pair for future cache hits."""
        self.collection.add(
            documents=[query],
            ids=[intent_id],
            metadatas=[
                {
                    "response": response[:10000],
                    "tier": tier,
                    "model": model,
                    "cost": str(cost),
                    "category": category,
                    "complexity": str(complexity),
                    "success": str(success),
                    "cached_at": str(time.time()),  # [Suggestion #7]
                }
            ],
        )
        log.info("cache_stored", intent_id=intent_id, tier=tier, query=query[:60])

        # Also store in Redis RAM for exact-match sub-ms hits
        if _redis_client:
            try:
                key = f"mullm:exact:{hashlib.md5(query.strip().lower().encode()).hexdigest()}"
                _redis_client.setex(
                    key,
                    CACHE_TTL_SECONDS,
                    json.dumps(
                        {
                            "response": response[:10000],
                            "query": query,
                            "model": model,
                            "tier": tier,
                        }
                    ),
                )
            except Exception:
                pass  # Redis down — ChromaDB is the source of truth

    async def update_if_better_async(self, **kwargs) -> bool:
        """Async wrapper for update_if_better."""
        async with _embed_sem:
            return await asyncio.to_thread(self.update_if_better, **kwargs)

    def update_if_better(
        self,
        query: str,
        new_response: str,
        new_tier: str = "",
        new_model: str = "",
        new_cost: float = 0.0,
        category: str = "",
        complexity: int = 0,
        quality_threshold: float = 0.10,
    ) -> bool:
        """
        Check if there's a cached response for this query. If the new response
        is significantly better (longer, from a higher tier), replace the cache entry.
        Returns True if cache was updated.
        """
        if self.collection.count() == 0:
            return False

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=1,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return False

        if not results["documents"] or not results["documents"][0]:
            return False

        distance = results["distances"][0][0]
        similarity = 1.0 - (distance / 2.0)

        # Only consider updating if it's a close match
        if similarity < CACHE_HIT_THRESHOLD:
            return False

        metadata = results["metadatas"][0][0] if results["metadatas"][0] else {}
        old_response = metadata.get("response", "")
        old_id = results["ids"][0][0] if results["ids"] and results["ids"][0] else None

        if not old_id or not old_response:
            return False

        # Quality heuristic: compare response length as a proxy for thoroughness
        # A cloud-escalated answer that is 10%+ longer/more detailed is "better"
        tier_rank = {"cache": 0, "local": 1, "local_multi": 2, "cloud_cheap": 3, "cloud_full": 4}
        old_tier_rank = tier_rank.get(str(metadata.get("tier", "local")), 1)
        new_tier_rank = tier_rank.get(new_tier, 1)

        # New response must be from a higher tier
        if new_tier_rank <= old_tier_rank:
            return False

        old_len = len(old_response)  # type: ignore[arg-type,operator]
        new_len = len(new_response)

        # New response should be meaningfully different (at least 10% longer or similar length from better tier)
        length_ratio = new_len / max(old_len, 1)
        if length_ratio < (1.0 + quality_threshold) and new_tier_rank - old_tier_rank < 2:
            return False

        # Replace: update the existing cache entry
        try:
            self.collection.update(
                ids=[old_id],
                documents=[query],
                metadatas=[
                    {
                        "response": new_response[:10000],
                        "tier": new_tier,
                        "model": new_model,
                        "cost": str(new_cost),
                        "category": category,
                        "complexity": str(complexity),
                        "success": "True",
                        "cached_at": str(time.time()),
                        "upgraded_from": metadata.get("tier", "unknown"),
                    }
                ],
            )
            log.info(
                "cache_upgraded",
                old_tier=metadata.get("tier", "?"),
                new_tier=new_tier,
                old_len=old_len,
                new_len=new_len,
                similarity=round(similarity, 3),
                query=query[:60],
            )
            # Log displacement event for model leaderboard
            _log_displacement(
                query_preview=query[:80],
                old_model=str(metadata.get("model", "unknown")),
                new_model=new_model,
                old_tier=str(metadata.get("tier", "unknown")),
                new_tier=new_tier,
                category=category,
                complexity=complexity,
                similarity=round(similarity, 4),
                old_len=old_len,
                new_len=new_len,
            )
            return True
        except Exception as e:
            log.warning("cache_upgrade_failed", error=str(e)[:100])
            return False

    def neighborhood_scores(self, query: str, n_neighbors: int = 20) -> list[dict]:
        """
        Find semantically similar cached queries and return their model/score data.
        This is the "which model does best around here?" signal for complex queries
        that rarely repeat exactly.
        """
        if self.collection.count() < 5:
            return []
        try:
            n = min(n_neighbors, self.collection.count())
            results = self.collection.query(
                query_texts=[query],
                n_results=n,
                include=["metadatas", "distances"],
            )
        except Exception:
            return []

        neighbors = []
        for i, meta_list in enumerate(results["metadatas"]):
            for j, meta in enumerate(meta_list):
                dist = results["distances"][i][j]
                sim = 1.0 - (dist / 2.0)
                if sim < 0.5:  # too dissimilar to be meaningful
                    continue
                resp = str(meta.get("response", ""))
                neighbors.append(
                    {
                        "model": meta.get("model", "unknown"),
                        "tier": meta.get("tier", "unknown"),
                        "category": meta.get("category", ""),
                        "complexity": int(str(meta.get("complexity", 0)) or "0"),
                        "response_len": len(resp),
                        "similarity": round(sim, 3),
                        "success": meta.get("success", "True") == "True",
                    }
                )
        return neighbors

    def count(self) -> int:
        return self.collection.count()

    def clear(self) -> None:
        """Delete and recreate the collection. Recreates the client
        to flush ChromaDB's in-memory HNSW index references."""
        name = self.collection.name
        old_count = self.collection.count()
        self.client.delete_collection(name)
        self.client = _chromadb.PersistentClient(path=CHROMA_DIR)
        self.collection = self.client.get_or_create_collection(
            name=name,
            embedding_function=self.embedder,
            metadata={"hnsw:space": "cosine"},
        )
        new_count = self.collection.count()
        if new_count > 0:
            log.error("cache_clear_incomplete", deleted=old_count, remaining=new_count)
        else:
            log.warning("cache_cleared", deleted=old_count)

    def purge_all(self) -> int:
        """GDPR/CCPA compliance: purge all cached query data.
        Returns the number of entries deleted. Alias for clear() with count return."""
        deleted = self.collection.count()
        self.clear()
        return deleted

    def delete_by_query(self, query: str) -> bool:
        """Find and delete the closest cache entry to a query."""
        try:
            results = self.collection.query(
                query_embeddings=None,
                query_texts=[query],
                n_results=1,
                include=["documents", "distances"],
            )
            if results["ids"] and results["ids"][0]:
                doc_id = results["ids"][0][0]
                distance = results["distances"][0][0] if results["distances"] else 999
                similarity = 1.0 - (distance / 2.0)
                if similarity >= 0.85:  # only delete if it's actually a close match
                    self.collection.delete(ids=[doc_id])
                    log.info(
                        "cache_entry_deleted", doc_id=doc_id, similarity=round(similarity, 3), query_preview=query[:60]
                    )
                    return True
                log.warning("cache_delete_skip", similarity=round(similarity, 3), reason="no close match found")
            return False
        except Exception as e:
            log.warning("cache_delete_error", error=str(e)[:200])
            return False

    def delete_by_id(self, doc_id: str) -> bool:
        """Delete a cache entry by its ChromaDB document ID."""
        try:
            self.collection.delete(ids=[doc_id])
            log.info("cache_entry_deleted_by_id", doc_id=doc_id)
            return True
        except Exception as e:
            log.warning("cache_delete_error", error=str(e)[:200])
            return False

    def scan_entries(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Return cache entries for inspection/sweeping."""
        try:
            results = self.collection.get(
                limit=limit,
                offset=offset,
                include=["documents", "metadatas"],
            )
            entries = []
            for i, doc_id in enumerate(results["ids"]):
                meta = results["metadatas"][i] if results["metadatas"] else {}
                doc = results["documents"][i] if results["documents"] else ""
                entries.append(
                    {
                        "id": doc_id,
                        "query": meta.get("query", doc[:80] if doc else ""),
                        "response_preview": str(meta.get("response", "") or "")[:200],
                        "model": meta.get("model", ""),
                        "tier": meta.get("tier", ""),
                        "category": meta.get("category", ""),
                        "created_at": meta.get("created_at", ""),
                    }
                )
            return entries
        except Exception as e:
            log.warning("cache_scan_error", error=str(e)[:200])
            return []


# ── vCache-Inspired Adaptive Threshold Learning ───────────────


def get_threshold(category: str) -> float:
    """Return the current hit threshold for a category (runtime-mutable)."""
    return CACHE_THRESHOLDS.get(category, CACHE_THRESHOLDS.get("default", CACHE_HIT_THRESHOLD))


def update_threshold(category: str, was_good: bool) -> None:
    """Nudge the per-category cache threshold based on hit quality feedback.

    Called after a cache hit: if the user accepted the cached answer without
    correction (was_good=True), we can afford to be slightly more permissive
    (lower threshold) for future hits in this category. If it was a bad hit,
    raise the threshold faster than we lower it to avoid repeated mistakes.

    Learning rate is intentionally small (0.001) so drift is gradual and
    bounded between 0.80 and 0.99.
    """
    lr = 0.001
    current = CACHE_THRESHOLDS.get(category, CACHE_THRESHOLDS.get("default", CACHE_HIT_THRESHOLD))
    if was_good:
        CACHE_THRESHOLDS[category] = max(0.80, current - lr)
    else:
        CACHE_THRESHOLDS[category] = min(0.99, current + lr * 3)  # raise faster than lower
    log.info(
        "threshold_updated",
        category=category,
        was_good=was_good,
        old=round(current, 4),
        new=round(CACHE_THRESHOLDS[category], 4),
    )


# ── Displacement-Based Model Leaderboard ─────────────────────


def _log_displacement(
    query_preview: str,
    old_model: str,
    new_model: str,
    old_tier: str,
    new_tier: str,
    category: str,
    complexity: int,
    similarity: float,
    old_len: int,
    new_len: int,
) -> None:
    """Log a cache displacement event — implicit model head-to-head."""
    try:
        _DISPLACEMENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.time(),
            "query": query_preview,
            "winner": new_model,
            "loser": old_model,
            "winner_tier": new_tier,
            "loser_tier": old_tier,
            "category": category,
            "complexity": complexity,
            "similarity": similarity,
            "len_delta": new_len - old_len,
        }
        with open(_DISPLACEMENT_LOG, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass  # best-effort, never block pipeline


def compute_leaderboard(scoring_log_path: str | None = None) -> dict:
    """
    Build model leaderboard from two signals:

    1. Displacement wins (from displacement_log.jsonl):
       Model X replaced Model Y in cache → X wins that matchup.

    2. Neighborhood scoring (from scoring_log.jsonl):
       Group by category + complexity band, compare average success/latency
       per model. This captures high-complexity queries that rarely displace.

    Returns {models: [{name, wins, losses, elo, avg_latency, categories}]}
    """
    from collections import defaultdict

    # ── Signal 1: Displacement wins ──
    wins: dict[str, int] = defaultdict(int)  # model → win count
    losses: dict[str, int] = defaultdict(int)  # model → loss count
    matchups: dict[str, Any] = defaultdict(lambda: defaultdict(int))  # winner → {loser → count}

    if _DISPLACEMENT_LOG.exists():
        for line in _DISPLACEMENT_LOG.read_text().splitlines():
            try:
                r = json.loads(line.strip())
                w, loser = r["winner"], r["loser"]
                if w == loser:
                    continue  # same model, not meaningful
                wins[w] += 1
                losses[loser] += 1
                matchups[w][loser] += 1
            except (json.JSONDecodeError, KeyError):
                continue

    # ── Signal 2: Scoring log — per-model stats by complexity band ──
    model_stats: dict[str, Any] = defaultdict(
        lambda: {
            "count": 0,
            "success": 0,
            "total_latency": 0.0,
            "total_cost": 0.0,
            "categories": defaultdict(int),
            "by_complexity": defaultdict(lambda: {"count": 0, "success": 0}),
        }
    )

    log_path = Path(scoring_log_path) if scoring_log_path else Path(CHROMA_DIR).parent / "scoring_log.jsonl"
    if log_path.exists():
        for line in log_path.read_text().splitlines():
            try:
                r = json.loads(line.strip())
                m = r.get("model_used", "")
                if not m:
                    continue
                s = model_stats[m]
                s["count"] += 1
                if r.get("success"):
                    s["success"] += 1
                s["total_latency"] += r.get("latency_ms", 0)
                s["total_cost"] += r.get("cost", 0)
                cat = r.get("category", "unknown")
                s["categories"][cat] += 1
                cx = r.get("complexity", 0)
                band = "simple" if cx <= 2 else "medium" if cx <= 3 else "complex"
                s["by_complexity"][band]["count"] += 1
                if r.get("success"):
                    s["by_complexity"][band]["success"] += 1
            except (json.JSONDecodeError, KeyError):
                continue

    # ── Simple Elo from displacement matchups ──
    elo: dict[str, float] = defaultdict(lambda: 1200.0)
    all_models = set(wins.keys()) | set(losses.keys()) | set(model_stats.keys())
    # Process each matchup pair
    for winner, losers in matchups.items():
        for loser, count in losers.items():
            for _ in range(count):
                ea = 1.0 / (1.0 + 10 ** ((elo[loser] - elo[winner]) / 400))
                k = 32
                elo[winner] += k * (1.0 - ea)
                elo[loser] += k * (0.0 - (1.0 - ea))

    # ── Build leaderboard ──
    board = []
    for m in sorted(all_models):
        s = model_stats.get(m, {})
        count = s.get("count", 0) if isinstance(s, dict) else 0
        success = s.get("success", 0) if isinstance(s, dict) else 0
        total_lat = s.get("total_latency", 0) if isinstance(s, dict) else 0
        total_cost = s.get("total_cost", 0) if isinstance(s, dict) else 0
        cats = dict(s.get("categories", {})) if isinstance(s, dict) else {}
        by_cx = {}
        if isinstance(s, dict):
            for band, bd in s.get("by_complexity", {}).items():
                by_cx[band] = {
                    "count": bd["count"],
                    "success_rate": round(bd["success"] / bd["count"], 3) if bd["count"] else 0,
                }

        board.append(
            {
                "model": m,
                "displacement_wins": wins.get(m, 0),
                "displacement_losses": losses.get(m, 0),
                "elo": round(elo.get(m, 1200.0)),
                "queries": count,
                "success_rate": round(success / count, 3) if count else 0,
                "avg_latency_ms": round(total_lat / count, 1) if count else 0,
                "total_cost": round(total_cost, 6),
                "top_categories": sorted(cats.items(), key=lambda x: -x[1])[:3],
                "by_complexity": by_cx,
            }
        )

    # Sort by Elo descending
    board.sort(key=lambda x: -x["elo"])  # type: ignore[arg-type,operator]
    return {
        "models": board,
        "total_displacements": sum(wins.values()),
        "signal_strength": "strong"
        if sum(wins.values()) > 50
        else "moderate"
        if sum(wins.values()) > 10
        else "warming_up",
    }
