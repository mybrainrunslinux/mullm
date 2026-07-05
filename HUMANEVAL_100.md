# HumanEval 100% Reproduction Guide

**Result**: 164/164 = 100% pass@1  
**Date**: 2026-05-21  
**Model**: `qwen3.6-35b-a3b-chat:latest` (local, zero cloud spend)  
**Elapsed**: 494s (~8 minutes)  
**Script**: `scripts/humaneval_hybrid.sh`

---

## How to Reproduce

```bash
# 1. Ensure the chat model exists (only needed once)
ollama create qwen3.6-35b-a3b-chat -f scripts/Modelfile.35b-a3b-chat

# 2. Start the muLLM server
source .venv/bin/activate
python -m router.main &

# 3. Run the benchmark
bash scripts/humaneval_hybrid.sh
```

Results saved to: `cache/data/humaneval_hybrid_results.json`

---

## Model Setup

The base model `qwen3.6-35b-a3b:latest` ships with a raw completion template (`{{ .Prompt }}`) and **no stop tokens**. Without a proper chat template, responses bleed role markers (`assistant`, `<|endoftext|>`) into the generated code, causing syntax errors.

**Fix**: create a derived model with chatml template + stop tokens.

### `scripts/Modelfile.35b-a3b-chat`

```
FROM qwen3.6-35b-a3b:latest

TEMPLATE """{{ if .System }}<|im_start|>system
{{ .System }}<|im_end|>
{{ end }}{{ range .Messages }}<|im_start|>{{ .Role }}
{{ .Content }}<|im_end|>
{{ end }}<|im_start|>assistant
"""

PARAMETER stop "<|im_start|>"
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"
PARAMETER num_ctx 16384
PARAMETER num_predict 8192
PARAMETER temperature 0.6
```

### Hardware requirement
- RTX 5090 32GB VRAM
- Model VRAM: ~26.5 GB
- Leaves ~5.5 GB for KV cache (sufficient at num_ctx 16384)

---

## Critical Settings in `router/benchmarks/runner.py`

All of these must be present. Breaking any one causes failures.

### 1. `/no_think` in the prompt (line ~308)
```python
f"No markdown, no explanation, no backticks. Just Python code. /no_think\n\n"
```
Qwen3 MoE models default to thinking mode. `/no_think` in the user message suppresses chain-of-thought at the text level. Without it, the model thinks for 60-100s per problem and sometimes produces empty responses.

### 2. `think: False` at TOP LEVEL of Ollama request (line ~250)
```python
json={
    "model": model,
    "messages": [...],
    "stream": False,
    "think": False,          # <-- MUST be top-level, NOT inside "options"
    "options": {"temperature": 0.1, "num_predict": num_predict},
}
```
Putting `think: False` inside `options` is silently ignored. It must be a top-level key.

### 3. Special token stripping (line ~257)
```python
text = re.sub(r"<\|[^|>]+\|>", "", text).strip()
```
Some models (especially custom GGUFs) leak `<|endoftext|>`, `<|im_end|>` etc. as raw text into responses. Strip before extracting code.

### 4. Subprocess sandbox for test execution
Use `_run_in_sandbox(code, test_code)`, not `exec()`. Direct `exec()` causes state bleed between problems — variables from one problem pollute the namespace of the next, causing spurious failures.

### 5. `MULLM_BENCH_DIRECT_OLLAMA=1`
Bypasses muLLM routing entirely. Always set this for local bench runs. Server CODE_MODEL env var drifts across restarts and silently swaps models.

### 6. Hardcode `target_model` in every bench call
Never rely on server state. Always pass `target_model="qwen3.6-35b-a3b-chat:latest"` (or whatever the intended model is) explicitly.

---

## What Doesn't Work (and Why)

| Model | Score | Why it fails |
|-------|-------|-------------|
| OmniCoder-9B (GGUF) | ~82% | Custom GGUF ignores `think` parameter, always runs thinking mode, exhausts 8192-token context window, produces empty responses |
| qwen3-coder:30b | 91.5% | Dense model, solid but ~14 problems it genuinely gets wrong |
| qwen3.6-35b-a3b (raw) | 0% | No stop tokens, role text bleeds into code |
| qwen3.6-35b-a3b-chat | **100%** | Proper chatml template, stop tokens, `/no_think` in prompt |

---

## Files

| File | Purpose |
|------|---------|
| `scripts/humaneval_hybrid.sh` | Main run script (batched by model, 2-model-swap max) |
| `scripts/Modelfile.35b-a3b-chat` | Ollama model definition with chatml + stop tokens |
| `scripts/35b_a3b_humaneval.sh` | Standalone 35b-a3b benchmark script |
| `scripts/omnicoder_humaneval_direct.sh` | OmniCoder standalone script (82-83%) |
| `router/benchmarks/runner.py` | Core runner — all fixes live here |
| `cache/data/humaneval_hybrid_results.json` | Latest 100% result data |

---

## Troubleshooting

**Score drops to ~82%**: OmniCoder is being used instead of 35b-a3b. Check `target_model`.

**Score drops to ~96%**: The `qwen3.6-35b-a3b` raw model (no chat template) is being used. Recreate `qwen3.6-35b-a3b-chat` from the Modelfile.

**Thinking mode fires (60-100s per problem)**: `/no_think` missing from prompt, OR `think: False` is inside `options` instead of top-level. Both must be present.

**`<|endoftext|>` in code / SyntaxError on line N**: Special token stripping is missing in `_query_ollama_direct`. Check the `re.sub(r"<\|[^|>]+\|>", ...)` line.

**Spurious failures on easy problems**: `exec()` is being used for test execution instead of `_run_in_sandbox`. State bleed between problems.

**Model eviction during run**: If another process loads a large model (>5.5 GB) while the bench runs, Ollama will evict 35b-a3b from VRAM mid-run. Kill other Ollama-using processes before running.
