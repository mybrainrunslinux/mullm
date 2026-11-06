# Models and classifier configuration

Catalog rechecked against first-party documentation on **2026-11-05**.
Release verification made two small paid calls: GPT-6 Astra and Claude Fable 5.1
both returned visible READY responses under their requested model IDs. Reported
combined cost was $0.00078. Other newly added providers remain documentation-
and transport-test verified rather than live-certified in this pass.
Existing explicit
model overrides remain valid; new defaults apply when no override is supplied.

| Provider | Cheap | Full | Power |
| --- | --- | --- | --- |
| OpenAI | `gpt-6-luna` | `gpt-6.1-sol` | `gpt-6-astra` |
| Anthropic | `claude-haiku-5-5` | `claude-sonnet-5-5` | `claude-opus-5-5` |
| Google | `gemini-3.5-flash-lite` | `gemini-3.8-flash` | `gemini-4-argon` |
| DeepSeek | `deepseek-flash` | `deepseek-v4-pro` | `deepseek-v4-pro` |
| Z.AI | `glm-5.3-flash` | `glm-5.3` | `glm-5.3` |
| Cerebras | `gpt-oss-120b` | `gpt-oss-120b` | `gpt-oss-120b` |

The existing Fable setup toggle selects `claude-fable-5-1` for Anthropic power.
`gpt-6.1-terra` is also registered and can replace the full model with
`MULLM_CLOUD_FULL_MODEL_OPENAI=gpt-6.1-terra`. All tier settings use the
`MULLM_CLOUD_{CHEAP,FULL,POWER}_MODEL_{PROVIDER}` environment-variable pattern.

Official sources: [OpenAI Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra),
[Astra](https://developers.openai.com/api/docs/models/gpt-6-astra),
[Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), and
[Claude models](https://platform.claude.com/docs/en/models/overview).
The verified Fable ID is **5.1**, not 6.1.
Its explicit Opus 4.8 refusal fallback is intentional: Anthropic's
[Fable 5.1 migration guide](https://platform.claude.com/docs/en/models/fable-5-1/migration-guide)
permits Opus 4.8 and Opus 5 as fallback targets. It is not the normal power-tier default.

GPT-6 completion requests use Responses with `max_output_tokens`, omitting
sampling parameters. Standard price accounting includes the GPT-6 surcharge
above 272,000 input tokens and Haiku 5.5 pricing above 100,000 input tokens.
Pricing assumes standard service; cache write/read accounting, fast modes,
regional premiums, and tool fees still need dedicated accounting before use.
See [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing).

### Other provider changes

- Google: the `google` extra now installs `google-genai`, matching the code's
  imports. [Current models](https://ai.google.dev/gemini-api/docs/models) include
  Argon; the previous 3.1 Pro preview is no longer the power default.
  [Pricing](https://ai.google.dev/gemini-api/docs/pricing) changes automatically
  in cost accounting: Argon $2/$10 per million input/output tokens until
  December 1, then $4/$20; Flash 3.8 $0.75/$3.75 until January 1, then $1.50/$7.50.
  Reasoning tokens count toward output charges. The 29-second query deadline
  remains in force; long reasoning jobs may time out.
- DeepSeek: use `deepseek-flash`, currently V4.1 Flash 1017. The old V4 Flash ID
  is a redirected compatibility alias. muLLM budgets at peak uncached rates
  ($0.30/$1.20 Flash, $1.32/$3.96 Pro) and does not claim exact off-peak invoices.
  [Official pricing and aliases](https://api-docs.deepseek.com/quick_start/pricing/).
- GLM: [5.3](https://docs.z.ai/guides/llm/glm-5.3) and
  [Flash/FlashX](https://docs.z.ai/guides/vlm/glm-5.3-flash) require reasoning.
  Requests enable it with low effort to fit synchronous routing. The default
  endpoint is Z.AI's international API. Set `MULLM_GLM_BASE_URL` for a different
  regional or account endpoint; keys are not interchangeable.
  [Rates](https://docs.z.ai/guides/overview/pricing): $1.40/$4.40,
  $0.15/$0.50, and $0.37/$1.25 respectively.
- Cerebras retains its supported GPT OSS default and additionally registers
  [`qwen-3.8-27b`](https://inference-docs.cerebras.ai/models/qwen-3.8-27b)
  at $0.99/$1.49 per million tokens.
- Backend registry defaults also use [Grok 4.7](https://docs.x.ai/developers/models),
  [Command A+](https://docs.cohere.com/docs/command-a-plus), and the
  [Perplexity Agent API](https://docs.perplexity.ai/docs/agent-api/openai-compatibility).
  Mistral's current Small alias remains `mistral-small-latest`; Large 4 is available
  through its [model catalog](https://docs.mistral.ai/models).
  OpenRouter defaults to its [free-model router](https://openrouter.ai/openrouter/free).
  Set `VENICE_MODEL` from the [account model list](https://docs.venice.ai/api-reference/endpoint/models/list),
  or `IBM_BAM_MODEL` for your IBM deployment; these integrations no longer guess
  an old model. Backend transport availability does not establish full tier-router
  support, tool-fee accounting, or live account access.

Historical IDs remain readable for logs and explicit overrides. An explicit
override is preserved, even if it names an older model; check saved `.env` and
TOML configuration when upgrading.

## Kev.js in the browser

The browser project is [ai-ecoverse/kev.js](https://github.com/ai-ecoverse/kev.js),
separate from the Python Kev server. `/classifier` provides an opt-in local
preview using a Web Worker, WebGPU or WASM, and the same System One questions.
It validates confidence and labels. Browser predictions never authorize spending,
change server routing, or answer required factory decisions.

Build the pinned optional runtime from this source checkout:

```bash
cd examples/browser-classifier
npm ci --ignore-scripts
npm run build
```

Download/export a `q8f32` model bundle using the upstream Kev.js instructions
into a dedicated local directory, preserving `manifest.json` and its referenced
paths. The 0.8B bundle is approximately 838 MB. Then start muLLM with absolute paths:

```bash
export MULLM_KEV_ASSET_DIR=/absolute/path/to/examples/browser-classifier/dist
export MULLM_KEV_MODEL_DIR=/absolute/path/to/kev-0.8b
mullm-server
```

Open `/classifier` on localhost or HTTPS and click **Load classifier**. The page
loads only same-origin assets, and classification text stays in the worker.
**Unload** terminates the worker. Missing files, unsupported WebGPU, invalid
answers, and timeouts leave server classification unchanged. In an authenticated
deployment, use an authenticated reverse proxy session for this optional asset
surface. The runtime bundle build is checked; real model quality/performance
requires the actual weights and target browser/GPU and is not claimed here.

## Local Kev / System One classifier

Jev and Kev are decision models rather than chat completion models. The
`systemone` backend asks for intent and complexity together, validates the
answers, and falls back to existing classification on errors or low confidence.
It connects only to literal loopback addresses and does not follow redirects.
Hosted Jev is not yet enabled: charging classifier calls before session budget
reservation would bypass muLLM's spend controls. The adapter supports its wire
format for local gateways, but this is not a claim of live Jev validation.

Run Kev in its own environment following its [upstream installation and serving
guide](https://github.com/jaredpalmer/kev), then configure muLLM:

```bash
export MULLM_CLASSIFIER_BACKEND=systemone
export MULLM_CLASSIFIER_HTTP_URL=http://127.0.0.1:8009/v1/systemone
export MULLM_CLASSIFIER_HTTP_MODEL=kev-latest
export MULLM_CLASSIFIER_HTTP_TIMEOUT_SECONDS=2
export MULLM_CLASSIFIER_CONFIDENCE_THRESHOLD=0.8
mullm-server
```

For an authenticated local gateway, set `MULLM_CLASSIFIER_HTTP_API_KEY`.
The credential is excluded from settings serialization. Tune the confidence
threshold on held-out routing examples; System One confidence is not necessarily
the winning class probability. [System One API reference](https://docs.typesafe.ai/api/system-one).

Other custom classifiers can use `MULLM_CLASSIFIER_BACKEND=http`. The configured
URL receives `content` and `text`, and optionally `model`. Return
`{"category":"code","complexity":3,"confidence":0.95}`. This existing generic
HTTP path is operator-configured; do not point it at an unmetered paid service.

## Training a custom classifier

The installed package includes a local training command. Prepare a CSV with
`query,category` columns. Intent labels are muLLM intent names; binary labels
are `local` and `cloud`. Duplicate queries are removed, conflicting labels are
rejected, and each represented class needs at least two unique queries to make
a reproducible held-out split. Real training needs substantially more examples.

```bash
python -m router.train_classifier --data routing.csv --output candidate --dry-run
python -m router.train_classifier --data routing.csv --output candidate \
  --base-model /absolute/path/to/local/sequence-classifier --mode intent
```

Install the `classifier` extra for training. The base model must already exist
locally in Transformers format with safetensors weights. No model download or
remote Python execution is enabled. The command writes a label map and validation
report; it never automatically promotes a candidate. Review accuracy per class,
cloud escalation rate, latency, and task outcomes before setting
`MULLM_CLASSIFIER_MODEL_PATH` to the candidate directory. Scheduled training uses
the same installed module and defaults to dry-run.

Kev's pointer head and calibration need its own training pipeline, rather than
the sequence-classification trainer. Use the [Kev fine-tuning guide](https://github.com/jaredpalmer/kev#fine-tune-on-your-own-data)
with routing labels, reserve a separate evaluation set, and benchmark the trained
checkpoint before serving it on port 8009. Keep Kev's GPU dependencies in a
separate environment from muLLM.

## Local runners and provider expansion

TabbyAPI / ExLlamaV3, vLLM, SGLang, llama.cpp, and Ollama already have integration
paths. Configure TabbyAPI with `TABBYAPI_BASE_URL`, `TABBYAPI_MODEL`, and optional
`TABBYAPI_API_KEY`; verify the actual model with the backend smoke endpoint.
Do not install GPU runner dependency trees into the core router environment.

Cerebras is already integrated. New compatible providers should be evaluated
through the existing LiteLLM/OpenRouter gateway paths before adding dedicated
adapters. Provider qualification requires current model IDs, pricing, usage
accounting, streaming/tool compatibility, and measured latency on the target
workload. No new provider's throughput has been measured in this change.
