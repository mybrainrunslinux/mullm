# Release runtime guards

`DISABLE_CLOUD=1` (or `MULLM_DISABLE_CLOUD=1`) forces local-only inference even
when a request explicitly selects a cloud tier. SDK, raw HTTP, streaming,
compatible backends, cloud image/audio and 3D transports check the same policy.
Remote classifier and inference endpoints are blocked; loopback inference remains
available. This switch controls inference, not all network activity on the host.

`MULLM_REQUEST_TIMEOUT_SECONDS` defaults to 29 and accepts values above zero and
at most 29. Remove old 600-second overrides before upgrading. The `/query` deadline
includes the powerup branch. Cancellation propagates to pending provider work.
`MULLM_MAX_CONCURRENT_QUERIES` defaults to 32; excess requests receive 503 with
Retry-After instead of creating an unbounded inference queue. Deadlines return 504.

New cloud defaults are Luna / Sol / Astra for OpenAI and Haiku 5.5 / Sonnet 5.5 /
Opus 5.5 for Anthropic. The existing Fable toggle selects Fable 5.1. Terra 6.1 is
also registered. Explicit configured model overrides remain available.

All eight model IDs passed paid text smoke calls on 2026-11-05. The test discovered
that Haiku 5.5 rejects temperature; all current Claude 5.5 calls now omit it.
This validates text API access on the tested account, not application task quality.
Run `python -m pytest tests/test_frontier_live.py --grep=@spend -s` explicitly;
ordinary test runs skip paid cases. Each model uses one short fixed prompt, no
retries and a 1024-token output ceiling. The combined standard-price upper bound
is under $0.25, excluding any provider pricing changes or account premiums.

Sources: [OpenAI models](https://developers.openai.com/api/docs/models) and
[Anthropic models](https://platform.claude.com/docs/en/models/overview).

Cloud text adapters now reserve spend atomically in `spend_reservations.sqlite3`
under the state cache directory before every provider attempt. Reservations obey
session, rolling-day and rolling-week limits across processes sharing that file.
Successful completions retain twice the reported standard cost as a conservative
allowance; failed/cancelled calls and streams retain their full ceiling because
usage may be unavailable or estimated. The ledger is a conservative admission
budget, not an invoice. It starts when this version is installed; provider-side
account caps remain appropriate for existing spend and non-text integrations.
