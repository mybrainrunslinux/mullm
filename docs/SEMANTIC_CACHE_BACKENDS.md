# Semantic Cache Backends

muLLM defaults to a dependency-free SQLite semantic cache. It stores embeddings in
`MULLM_STATE_DIR/cache/data/semantic_cache.sqlite3` and performs cosine similarity scans in-process.
This is intentionally conservative: it keeps `pip install mullm` free of the current ChromaDB 1.x
security advisory while preserving Tier 1 semantic cache behavior for small and home-user installs.

## Current Backends

| Backend | Setting | Install | Status | Use When |
|---|---|---|---|---|
| SQLite cosine scan | `MULLM_SEMANTIC_CACHE_BACKEND=sqlite` | default | default | Safe local installs, small/medium personal caches |
| ChromaDB | `MULLM_SEMANTIC_CACHE_BACKEND=chroma` | `pip install mullm[vector-cache]` | opt-in | Existing Chroma cache users who accept the local-only risk or need Chroma compatibility |
| Off | `MULLM_SEMANTIC_CACHE_BACKEND=off` | default | supported | High-privacy sessions or debugging |

## Evaluated Next Backends

| Backend | Fit |
|---|---|
| SQLite `vec1` / `sqlite-vec` | Best likely next default once packaging/API stability is acceptable. Keeps the single-file SQLite state model while adding native vector search. |
| Qdrant local mode | Strong local optional backend; can run embedded on disk and later move to a server. Good candidate for power users. |
| LanceDB | Good Studio/media-memory candidate, especially for multimodal asset metadata and larger local datasets. |
| pgvector | Best for team/enterprise mode when Postgres is already required for shared state, backup, and access control. |
| Redis vector search | Good when Redis Stack/Search is already running, but too operationally heavy as the only home-user default. |
| DuckDB VSS | Interesting for analytics and research exports; keep experimental until persistence and extension packaging are boring. |

## Security Notes

- Query/response text is not stored unless `MULLM_LOG_QUERY_CONTENT=true`.
- Obvious PII patterns skip cache storage even when query-content logging is enabled.
- ChromaDB is not a default dependency because `pip-audit` currently reports PYSEC-2026-311 for
  ChromaDB 1.x with no fixed version.
- The default SQLite backend uses no network listener and no third-party vector database package.
