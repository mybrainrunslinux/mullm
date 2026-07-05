# muLLM Architecture

## System Overview

muLLM is a local-first LLM router that classifies user intent, routes to the cheapest capable model, and caches results. Local models handle simple tasks free; cloud APIs (Anthropic, OpenAI, Google) only for genuinely complex work.

```mermaid
graph TB
    subgraph Client["Browser Client"]
        Chat["chat.html<br/>Dexie IndexedDB"]
        Dash["dashboard.html<br/>Chart.js + D3"]
        SW["Service Worker<br/>PWA Offline"]
    end

    subgraph FastAPI["FastAPI :8100"]
        Query["/query<br/>Main Pipeline"]
        Split["/query/split<br/>Decompose + Parallel"]
        Stream["/query/stream<br/>SSE Streaming"]
        Health["/health"]
        DashAPI["/api/dashboard"]
        SysAPI["/api/system"]
        Events["/events<br/>SSE Push"]
    end

    subgraph Pipeline["Pipeline Stages"]
        Dedup["Dedup<br/>MD5 Content Hash"]
        Cache["Cache Lookup<br/>ChromaDB Vector"]
        Classify["Intent Classifier<br/>qwen3.5:9b"]
        Route["Model Selector<br/>scorer.py"]
        Exec["Tier Executor<br/>tiers.py"]
        Log["Score Logger<br/>JSONL"]
    end

    subgraph Models["Model Tiers"]
        Local["LOCAL<br/>qwen3.5:9b via Ollama<br/>RTX 5090 32GB"]
        LocalMulti["LOCAL_MULTI<br/>Multi-step local"]
        Cloud["CLOUD<br/>Anthropic / OpenAI / Google"]
        Vision["VISION<br/>llava:13b"]
    end

    subgraph Storage["Storage Layer"]
        Chroma["ChromaDB<br/>Vector Cache"]
        JSONL["scoring_log.jsonl<br/>Metrics + Costs"]
        IDB["IndexedDB<br/>Chat History (client)"]
    end

    Chat --> Query
    Chat --> Split
    Chat --> Stream
    Dash --> DashAPI
    Dash --> SysAPI

    Query --> Dedup --> Cache --> Classify --> Route --> Exec
    Exec --> Local
    Exec --> LocalMulti
    Exec --> Cloud
    Exec --> Vision
    Exec --> Log

    Cache --> Chroma
    Log --> JSONL
    Chat --> IDB
```

## Request Flow (Single Query)

```mermaid
sequenceDiagram
    participant U as User
    participant F as FastAPI
    participant D as Dedup
    participant C as ChromaDB
    participant I as Classifier
    participant S as Scorer
    participant T as Tier Engine
    participant M as Model

    U->>F: POST /query {content, session_id}
    F->>D: Check rapid-fire + content hash
    D-->>F: OK / 429
    F->>C: Vector similarity lookup
    alt Cache Hit (>0.88)
        C-->>F: Cached response
        F-->>U: {tier: cache, cost: $0}
    else Cache Miss
        F->>I: classify_intent(content)
        I-->>F: {category, complexity, keywords}
        F->>S: select_model(classification)
        S-->>F: {model, tier, provider}
        F->>T: execute_tier(intent, classification)
        T->>M: Generate response
        M-->>T: Response + token counts
        T-->>F: TierResult
        F->>C: Store in cache
        F->>F: Log to JSONL
        F-->>U: {response, tier, cost, tokens}
    end
```

## Split Routing (Multi-Task Decomposition)

```mermaid
graph LR
    subgraph Decompose
        Input["Multi-part<br/>Prompt"] --> Heuristic["Fast Heuristic<br/>(regex split)"]
        Input --> LLM["LLM Decompose<br/>(qwen3.5:9b)"]
        Heuristic --> Tasks["Sub-tasks<br/>with deps"]
        LLM --> Tasks
    end

    subgraph Execute
        Tasks --> Topo["Topological<br/>Sort"]
        Topo --> P1["Parallel Batch 1"]
        Topo --> P2["Parallel Batch 2<br/>(depends on B1)"]
        P1 --> Merge["Merge Results"]
        P2 --> Merge
    end

    subgraph Route["Per-Task Routing"]
        P1 --> Local["local"]
        P1 --> Cloud["cloud_cheap"]
        P2 --> Local2["local"]
    end
```

## Cost Tiers

| Tier | Models | Cost Range | Use Case |
|------|--------|-----------|----------|
| `cache` | ChromaDB vector match | $0.00 | Repeat/similar queries |
| `local` | qwen3.5:9b (Ollama) | $0.00 | Simple tasks, lookups, notes |
| `local_multi` | qwen3.5:9b multi-step | $0.00 | Multi-step local reasoning |
| `cloud_cheap` | Haiku, GPT-4o-mini, Flash | $0.001-0.01 | Medium complexity |
| `cloud_full` | Opus, GPT-4o, Pro | $0.01-0.50 | Complex analysis, large code |

## Safety & Guards

- **Rapid-fire detection**: 20 req/min per session -> 429
- **Content dedup**: MD5 hash, 2s window
- **Hard timeout**: 10 min absolute max per request
- **Budget caps**: Auto-approve ceiling, ask-approval ceiling (configurable)
- **Session cost tracking**: Cumulative per-session spend visible in UI

## File Map

```
mullm/
  router/
    main.py          # FastAPI app, endpoints, pipeline orchestration
    intent.py         # Intent classifier (local LLM)
    tiers.py          # Tier execution engine (local, cloud, vision)
    cloud.py          # Cloud API clients (Anthropic, OpenAI, Google)
    scorer.py         # Model selection, cost logging, session tracking
    decomposer.py     # Split routing decomposer
    models.py         # Pydantic models (IntentObject, PipelineResult, etc.)
    chat.html         # Single-file chat UI (HTML + JS + CSS)
    dashboard.html    # Dashboard UI (Chart.js, D3, isometric views)
    manifest.json     # PWA manifest
    sw.js             # Service worker
  config/
    settings.py       # All configuration, model pricing, thresholds
  cache/
    vector.py         # ChromaDB vector cache wrapper
    data/             # ChromaDB storage + scoring_log.jsonl
  tests/
    test_router.py    # Pipeline integration tests
    test_classifier.py # Classifier accuracy tests
  *.spec.js           # Playwright E2E tests (59 tests)
```
