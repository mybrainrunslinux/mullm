# muLLM — Enterprise & Hardware Compatibility Plan

## Hardware Compatibility Matrix

### Currently Supported
| Hardware | VRAM | Works? | Models | Notes |
|----------|------|--------|--------|-------|
| RTX 5090 | 32GB | Yes (current) | Qwen 3.5 9B+27B | Can swap models sequentially |
| RTX 4090 | 24GB | Yes | 9B comfortable, 27B tight | Use `keep_alive:0` aggressively |
| RTX 3090/4080 | 16-24GB | Yes | 9B easily, 27B with quantization | Q4_K_M fits in 16GB |

### What Needs Work
| Hardware | VRAM | Status | What's Needed |
|----------|------|--------|---------------|
| **8GB VRAM (RTX 4060, etc.)** | 8GB | Doable | Use 1-3B models (Qwen 2.5 3B, Phi-3 mini). Config change only — set `GENERAL_MODEL=qwen2.5:3b` |
| **AMD GPUs (RX 7900 XT, etc.)** | 16-24GB | Doable | Ollama supports ROCm. Just install `ollama` with ROCm. No code changes needed |
| **CPU-only / RAM-only** | 0 GPU | Doable | Ollama runs on CPU (slower). Works for 1-7B models. Set `num_gpu: 0` in Ollama |
| **Mac Mini M4** | Unified 16-24GB | Doable | Ollama has native Apple Silicon. Metal acceleration. Very fast for 7-9B models |
| **Mac Pro M2 Ultra** | 192GB unified | Excellent | Can run 70B+ models locally |
| **NVIDIA DGX / A100 / H100** | 40-80GB | Excellent | Run multiple models simultaneously, no swapping needed |
| **Intel Arc GPUs** | 16GB | Experimental | Ollama has early SYCL/oneAPI support |

### Key Point
muLLM's architecture is **model-agnostic**. The `config/settings.py` models are just env vars:
```bash
GENERAL_MODEL=phi3:mini     # 3B, fits in 4GB VRAM
GENERAL_MODEL=qwen2.5:3b    # 3B, fits in 4GB VRAM
GENERAL_MODEL=llama3.2:3b   # 3B, fits in 4GB VRAM
GENERAL_MODEL=qwen3.5:9b    # 9B, needs 8GB+ VRAM (current)
GENERAL_MODEL=qwen3:32b     # 32B, needs 24GB+ VRAM
```

No code changes needed for any of these. Just change the model name.

---

## Enterprise Cloud/Proxy Compatibility

### Currently Supported Providers
- **Anthropic** (direct API) — claude-haiku, claude-sonnet, claude-opus
- **OpenAI** (direct API) — gpt-4o-mini, gpt-4o, gpt-4-turbo, o1, o3-mini
- **Google** (direct API) — gemini-flash, gemini-pro, gemini-flash-lite

### What Enterprises Need (Next Session)

#### 1. OpenAI-Compatible Proxies
Many enterprises run LLMs behind an OpenAI-compatible proxy (vLLM, TGI, Azure OpenAI, etc.)
```python
# In cloud.py, just change the base_url:
OPENAI_BASE_URL=https://my-company-proxy.internal/v1
OPENAI_API_KEY=internal-key-here
```
**Effort:** ~1 hour. The OpenAI SDK already supports `base_url` override.

#### 2. Azure OpenAI
```python
AZURE_OPENAI_ENDPOINT=https://mycompany.openai.azure.com/
AZURE_OPENAI_KEY=xxx
AZURE_OPENAI_DEPLOYMENT=gpt-4o-deployment-name
```
**Effort:** ~2 hours. Need `openai.AzureOpenAI` client variant in cloud.py.

#### 3. AWS Bedrock
```python
AWS_REGION=us-east-1
# Uses IAM role / credentials chain
```
**Effort:** ~4 hours. Need `boto3` + bedrock-runtime client. Different API shape.

#### 4. Custom Self-Hosted (vLLM, TGI, llama.cpp server)
Any server with an OpenAI-compatible API just works via the proxy approach above.
```python
OPENAI_BASE_URL=http://my-vllm-server:8000/v1
```

#### 5. Go / Rust / Java Inference Servers
If they expose an OpenAI-compatible REST API (most do), same proxy approach.
If custom API, need a thin adapter in `cloud.py` — one function per provider.

---

## Auth / SSO for Enterprise

### Current: None (localhost only)

### Planned Levels

#### Level 1: API Key / Bearer Token (Next Session)
```python
# .env
MULLM_API_KEY=sk-mullm-xxxxx
```
- Middleware checks `Authorization: Bearer sk-mullm-xxxxx`
- Simple, stateless, works immediately
- **Effort:** 1 hour

#### Level 2: OIDC / OAuth2 (Google, GitHub, Microsoft Entra)
```python
OIDC_ISSUER=https://accounts.google.com
OIDC_CLIENT_ID=xxxxx
OIDC_CLIENT_SECRET=xxxxx
```
- Use `authlib` or `python-jose` for JWT validation
- Login page redirects to IdP, callback sets session cookie
- **Effort:** 4-6 hours

#### Level 3: SAML2 (Enterprise SSO — Okta, Azure AD, OneLogin)
```python
SAML_METADATA_URL=https://mycompany.okta.com/app/xxx/sso/saml/metadata
```
- Use `python3-saml` library
- SP-initiated flow with assertion consumer service
- **Effort:** 8-12 hours (SAML is complex)

#### Level 4: Per-User Quotas + RBAC
- Each authenticated user gets daily/monthly API budget
- Admin role can see all users' spend
- Dev role sees only own queries
- **Effort:** 1-2 days

---

## Summary: What's Quick vs. What's Work

| Feature | Effort | Priority |
|---------|--------|----------|
| 8GB VRAM support | Config only | Free |
| AMD GPU support | Ollama install | Free |
| Mac M4 support | Ollama install | Free |
| CPU-only mode | Config only | Free |
| OpenAI proxy | 1 hour | High |
| Azure OpenAI | 2 hours | High |
| Bearer token auth | 1 hour | P0 |
| OIDC (Google/GitHub/Entra) | 4-6 hours | P1 |
| AWS Bedrock | 4 hours | P2 |
| SAML2 | 8-12 hours | P3 |
| Per-user quotas | 1-2 days | P3 |
