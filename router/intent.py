"""
muLLM intent classifier.

Two modes:
  1. DeBERTa binary routing classifier (CPU, ~5ms) — lazy loaded from
     settings.classifier_model_path or ~/.mullm/models/routing-classifier/.
  2. Rule-based fallback — comprehensive regex + keyword heuristics, always available.

The classifier input includes the last 3 conversation turns so that follow-up
questions ("explain it differently") inherit context.

Categories:
  CODE, RESEARCH, CREATIVE, CONVERSATION, DEPLOY, NOTE, LOOKUP, VISION

Complexity 1-5 mapping:
  1 = trivial (single fact, one-liner)
  2 = simple (few steps, standard pattern)
  3 = moderate (multi-step, some domain knowledge)
  4 = complex (architecture-level, debugging, multi-file)
  5 = expert (novel algorithm, research-grade, adversarial)
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from router.config import settings
from router.models import IntentCategory, IntentObject

logger = logging.getLogger("mullm.intent")

try:
    import ollama as ollama_client  # type: ignore
except ImportError:
    ollama_client = None  # type: ignore

# Module-level lazy references (populated on first load call)
_deberta_classifier: object = None
_deberta_tokenizer: object = None
_deberta_warmed: bool = False
_use_deberta: bool = True  # runtime toggle
_onnx_checked: bool = False
_onnx_available: bool = False
_onnx_session: object = None
_onnx_tokenizer: object = None
_onnx_model_key: str = ""


# ---------------------------------------------------------------------------
# Web search need detection
# ---------------------------------------------------------------------------

def _needs_web_search(query: str) -> bool:
    """Return True if the query likely needs up-to-date information."""
    q = query.lower()

    # Pure date arithmetic — never needs search
    date_math = [
        "how many days", "days between", "day of the week", "what day is",
        "calculate", "difference between", "years since", "months since",
        "how long ago", "days until", "countdown",
    ]
    if any(p in q for p in date_math):
        return False

    # Mentions year >= 2024 in a factual context
    if re.findall(r"\b(202[4-9]|20[3-9]\d|2[1-9]\d\d)\b", query):
        return True

    # 2023 only if combined with recency signals
    if re.search(r"\b2023\b", query):
        recency = ["latest", "recent", "current", "now", "today", "this year",
                   "just", "new", "update", "release", "announce"]
        if any(r in q for r in recency):
            return True

    # General recency signals regardless of year
    strong_recency = [
        "today", "yesterday", "this week", "this month", "right now",
        "just announced", "just released", "breaking", "live score",
        "current price", "stock price", "weather", "news today",
    ]
    if any(p in q for p in strong_recency):
        return True

    # Version/release/status lookups without an explicit year are still temporal:
    # "latest Python version" and "current Node LTS" should not hit old cache.
    temporal_lookup = [
        r"\b(?:latest|newest|current|recent)\b.{0,48}\b(?:version|release|lts|stable|status|price|model|api|sdk|package)\b",
        r"\b(?:version|release|lts|stable|status|price|model|api|sdk|package)\b.{0,48}\b(?:latest|newest|current|recent)\b",
    ]
    if any(re.search(pattern, q) for pattern in temporal_lookup):
        return True

    return False


# ---------------------------------------------------------------------------
# Keyword / pattern rules
# ---------------------------------------------------------------------------

# Each entry: (IntentCategory, [patterns...], base_complexity, confidence)
RULES: list[tuple] = [
    # ── NOTE ─────────────────────────────────────────────────
    (
        IntentCategory.NOTE,
        [
            r"\bremember\b", r"\btake note\b", r"\bnote that\b", r"\bsave this\b",
            r"\bjot down\b", r"\bdon'?t forget\b", r"\bkeep track\b",
            r"\bstore this\b", r"\bmemo\b", r"\brecord that\b", r"\blog this\b",
        ],
        1, 0.92,
    ),
    # ── CODE (strong) ────────────────────────────────────────
    (
        IntentCategory.CODE,
        [
            r"\bwrite (?:a |me )?(?:\w+ )*?(?:python|javascript|js|typescript|ts|rust|go|bash|shell|ruby|java|c\+\+|c#|lua|sql)\b",
            r"\b(?:write|create|build|implement|code|make) (?:a |me |an )?(?:\w+ )*?(?:function|class|method|script|module|component|endpoint|api|app|program|cli|tool|server|bot|crawler|scraper|parser|handler|route|view|controller|service|worker|daemon|cron|scheduler|implementation|library|package|algorithm|data ?structure)\b",
            r"\b(?:fix|debug|refactor|optimize) (?:the |my |this )?(?:bug|code|function|error|issue|script|crash|config|configuration)\b",
            r"\bfizzbuzz\b", r"\bpalindrome\b", r"\blru cache\b",
            r"\bsort (?:a |the )?(?:list|array)\b",
            r"\bregex\b.*\b(?:for|to|that)\b",
            r"\b(?:unit |integration )?test(?:s)? for\b",
            r"\bone-?liner\b",
            r"\b(?:leetcode|hackerrank|codewars)\b",
            r"\b(?:create|make|generate|draw|build) (?:a |an |me )?(?:\w+ )?(?:diagram|chart|graph|visualization|svg|mermaid|flowchart|schematic)\b",
        ],
        2, 0.93,
    ),
    # ── CODE (medium) ────────────────────────────────────────
    (
        IntentCategory.CODE,
        [
            r"\b(?:write|create|build|implement|make|generate|add) (?:a |an |me )?(?:\w+ )?(?:dockerfile|makefile|docker.compose|\.?gitignore|config|yaml|json|csv|parser|handler|middleware|decorator|wrapper|hook|plugin|extension|validator|serializer|formatter|linter)\b",
            r"\b(?:how (?:do i|to|can i)) (?:write|create|build|implement|code|make|fix|parse|convert|decode|encode|hash|encrypt|compress|serialize|center|align|style|use|add|remove|install|configure|deploy|setup|set up|import|export|connect|send|fetch|query|run|execute|test|debug|format|render|display|animate|loop|iterate|sort|filter|map|reduce|merge|split|join|validate|sanitize|handle|catch|throw|await|async)\b",
            r"\bdebounce\b", r"\bthrottle\b",
            r"\b(?:how (?:do i|to|can i)) .{3,60}\b(?:in |with |using )?(?:css|html|javascript|js|typescript|python|react|vue|angular|node|express|django|flask|rust|go|java|c\+\+|sql|bash|shell|git|docker|kubernetes)\b",
            r"\b(?:write|create|build) .{0,30}(?:that|which|to) (?:accept|validate|process|handle|parse|convert|return|check|verify|filter|sort|search|find|count|calculate|compute|generate|render|display|format|transform|normalize|sanitize|encrypt|decrypt|compress|decompress)\b",
        ],
        2, 0.88,
    ),
    # ── CREATIVE ─────────────────────────────────────────────
    (
        IntentCategory.CREATIVE,
        [
            r"\b(?:write|draft|compose) (?:a |me )?(?:story|poem|essay|article|blog ?post|email|letter|description|tagline|slogan|pitch|bio|about page|readme)\b",
            r"\bsuggest (?:\d+ )?(?:names?|titles?|ideas?|slogans?|taglines?)\b",
            r"\b(?:brainstorm|ideate|come up with)\b",
            r"\b(?:creative|catchy|clever|fun|witty)\b.*\b(?:name|title|idea|slogan)\b",
            r"\bproduct description\b",
            r"\b(?:write|draft) .{0,20}(?:description|copy|blurb|pitch|proposal|brief)\b",
            r"\bname (?:for|ideas)\b",
        ],
        2, 0.88,
    ),
    # ── DEPLOY ───────────────────────────────────────────────
    (
        IntentCategory.DEPLOY,
        [
            r"\b(?:deploy|deployment) (?:to|on|a|the|my)\b",
            r"\b(?:ansible|terraform|pulumi|cloudformation)\b",
            r"\b(?:nginx|apache|caddy) (?:config|setup|reverse proxy|proxy)\b",
            r"\b(?:docker|kubernetes|k8s|helm|pod|container) (?:deploy|setup|config|orchestrat)\b",
            r"\b(?:ci/?cd|github actions|gitlab ci)\b",
            r"\b(?:ssl|tls|https|certificate|let'?s ?encrypt)\b.*\b(?:setup|config|install)\b",
            r"\bsystemd (?:service|unit)\b",
            r"\bset up (?:a )?server\b",
            r"\b(?:deploy|provision|spin up|launch) .{0,20}(?:server|instance|cluster|node|pod|container|vm|droplet)\b",
        ],
        3, 0.90,
    ),
    # ── RESEARCH ─────────────────────────────────────────────
    (
        IntentCategory.RESEARCH,
        [
            r"\b(?:what are|which are) the (?:best|top|most popular|recommended)\b",
            r"\bcompare\b.*\bvs\.?\b",
            r"\b(?:compare|comparison|versus|vs\.?) (?:between )?\b",
            r"\b(?:pros and cons|advantages|disadvantages|tradeoffs?|trade-offs?)\b",
            r"\b(?:best practices|state of the art|sota|latest|trends?) (?:for|in|of)\b",
            r"\b(?:survey|overview|landscape|ecosystem) of\b",
            r"\bhow does .{5,} work\b",
            r"\bexplain (?:how|what|why|the|a|an)\b",
            r"\bsummarize\b",
            r"\b(?:what are|what is) the (?:difference|similarities)\b",
            r"\b(?:describe|outline|break down|walk.?through)\b",
            r"\b(?:benefits|drawbacks|implications) of\b",
        ],
        2, 0.90,
    ),
    # ── LOOKUP ───────────────────────────────────────────────
    (
        IntentCategory.LOOKUP,
        [
            r"^what (?:is|are|was|were|does) .{2,40}\??\s*$",
            r"\b(?:what|which) port\b",
            r"\b(?:what|which) version\b",
            r"\bdefault (?:port|value|setting|config)\b",
            r"^(?:how many|how much|when did|where is|who is)\b",
            r"\b\d+\s*(?:times|plus|minus|divided|multiplied|\+|\-|\*|\/|x)\s*\d+",
            r"\b(?:what is|what's|calculate|compute)\s+\d+",
            r"^(?:what|who|where|when|why|how)\b.{2,60}\?\s*$",
            r"\b(?:define|definition of|meaning of)\b",
            r"\b(?:translate|convert)\s+\w+\s+(?:to|into)\b",
            r"\b(?:what|which) (?:color|colour|language|capital|country|currency)\b",
        ],
        1, 0.90,
    ),
    # ── VISION ───────────────────────────────────────────────
    (
        IntentCategory.VISION,
        [
            r"\b(?:image|photo|picture|screenshot|diagram|chart|visual|look at|what(?:'s| is) in this)\b",
        ],
        2, 0.85,
    ),
    # ── CONVERSATION ─────────────────────────────────────────
    (
        IntentCategory.CONVERSATION,
        [
            r"^(?:hey|hi|hello|yo|sup|what'?s up|howdy|good (?:morning|afternoon|evening))",
            r"^(?:thanks|thank you|thx|ty|cheers|great|awesome|perfect|nice|cool|ok|okay|got it|understood)\b",
            r"^(?:bye|goodbye|see you|later|ttyl|gotta go)\b",
            r"^(?:yes|no|yeah|nah|sure|nope|yep|yup)\s*[.!?]*$",
        ],
        1, 0.95,
    ),
    # ── Catch-all patterns (lower confidence) ────────────────
    (IntentCategory.LOOKUP,   [r"^.{3,50}\?\s*$"], 1, 0.70),
    (IntentCategory.CODE,     [r"\b(?:draw|create|make|build|generate|show|render|display)\b"], 2, 0.70),
    (IntentCategory.RESEARCH, [r"^(?:steps?|how)\s+to\b", r"\bsteps?\s+(?:to|for)\b", r"\bhow\s+(?:do\s+I|to)\s+\w+.*\b(?:and|with|for|in|on)\b"], 2, 0.80),
    (IntentCategory.RESEARCH, [r"^.{50,}$"], 2, 0.65),
    (IntentCategory.CONVERSATION, [r"^.{2,}$"], 1, 0.60),
]

# ---------------------------------------------------------------------------
# Complexity boosters
# ---------------------------------------------------------------------------

COMPLEXITY_BOOST_PATTERNS: list[tuple[str, int]] = [
    (r"\b(?:with|include|including|plus|and also) (?:\w+ )*?(?:auth|tests?|ci/?cd|docker|monitoring|logging|error handling|unit tests?|integration tests?|benchmarks?)\b", 1),
    (r"\b(?:multi-?(?:file|step|stage|tenant|player))\b", 1),
    (r"\b(?:production|enterprise|scalable|distributed|microservice)\b", 1),
    (r"\b(?:full|complete|comprehensive|end-to-end|e2e)\b", 1),
    (r"\b(?:from scratch|entire|whole system|full stack|architecture)\b", 2),
    (r"\b(?:serializ|deserializ|marshalling|big-?o|complexity analysis|performance analysis)\b", 1),
    (r"\bwhile (?:also|maintaining|keeping|ensuring|preserving)\b", 1),
    (r"\b(?:as well as|in addition to|on top of) (?:that\b|which\b|\w+ing\b)", 1),
    (r"\b(?:and|but) (?:also|additionally|furthermore|moreover)\b", 1),
    (r"\b(?:must|should|need to|has to) (?:also|both|either)\b", 1),
]

# Estimated output tokens per category (used for cost prediction)
TOKEN_ESTIMATES: dict[IntentCategory, int] = {
    IntentCategory.NOTE:         50,
    IntentCategory.LOOKUP:      100,
    IntentCategory.CONVERSATION: 100,
    IntentCategory.CODE:        500,
    IntentCategory.CREATIVE:    400,
    IntentCategory.RESEARCH:    800,
    IntentCategory.DEPLOY:     1000,
    IntentCategory.VISION:      200,
}


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

_STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "for", "and", "but", "or",
    "nor", "not", "so", "yet", "to", "of", "in", "on", "at", "by", "with",
    "from", "up", "about", "into", "through", "during", "before", "after",
    "above", "below", "between", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "only", "own", "same", "than", "too", "very", "just",
    "because", "as", "until", "while", "that", "this", "these", "those",
    "what", "which", "who", "whom", "whose", "me", "my", "i", "you", "your",
    "it", "its", "we", "our", "they", "their", "write", "create", "build",
    "make", "please", "using", "use",
}


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r"\b[a-z][a-z0-9+#._-]{1,20}\b", text.lower())
    seen: set[str] = set()
    unique: list[str] = []
    for w in words:
        if w not in _STOP_WORDS and w not in seen:
            seen.add(w)
            unique.append(w)
    return unique[:6]


# ---------------------------------------------------------------------------
# Fast rule-based classifier (Layer 1)
# ---------------------------------------------------------------------------

def _fast_classify(text: str) -> dict | None:
    """Match text against RULES. Returns a result dict or None."""
    lower = text.lower().strip()

    for category, patterns, base_complexity, confidence in RULES:
        for pattern in patterns:
            if re.search(pattern, lower):
                complexity = base_complexity

                # Apply complexity boosters
                for boost_pattern, boost in COMPLEXITY_BOOST_PATTERNS:
                    if re.search(boost_pattern, lower):
                        complexity = min(5, complexity + boost)

                # Adjust complexity by query length (proxy for scope)
                if len(text) > 2400:      # ~600 tokens: force cloud-worthy complexity
                    complexity = min(5, max(complexity, 4))
                elif len(text) > 300:
                    complexity = min(5, complexity + 1)
                elif len(text) > 150:
                    complexity = min(5, max(complexity, 3))

                keywords = _extract_keywords(text)
                est_tokens = TOKEN_ESTIMATES.get(category, 500)
                if complexity >= 4:
                    est_tokens *= 2

                return {
                    "category":         category,
                    "complexity":       complexity,
                    "confidence":       confidence,
                    "keywords":         keywords,
                    "needs_vision":     category == IntentCategory.VISION,
                    "needs_web":        _needs_web_search(text),
                    "estimated_tokens": est_tokens,
                    "method":           "rules",
                }

    return None


# ---------------------------------------------------------------------------
# DeBERTa binary routing classifier (lazy load)
# ---------------------------------------------------------------------------

def _load_deberta() -> bool:
    """Load DeBERTa binary local/cloud classifier. Returns True on success."""
    global _deberta_classifier, _deberta_tokenizer, _deberta_warmed

    if _deberta_classifier is not None:
        return True

    from router.config import settings

    # Check configured path first, then the conventional fallback location
    model_path: Path | None = None
    if settings.classifier_model_path:
        p = Path(settings.classifier_model_path)
        if p.exists():
            model_path = p
    if model_path is None:
        fallback = Path.home() / ".mullm" / "models" / "routing-classifier"
        if (fallback / "model.safetensors").exists():
            model_path = fallback

    if model_path is None:
        _deberta_warmed = True   # no model = fallback is correct, don't block /api/ready
        return False

    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer  # type: ignore

        # local_files_only=True prevents remote code execution when loading from local path
        _deberta_tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)  # nosec B615
        _deberta_classifier = AutoModelForSequenceClassification.from_pretrained(str(model_path), local_files_only=True)  # nosec B615
        _deberta_classifier.eval()  # type: ignore[union-attr]
        _deberta_warmed = True
        logger.info("DeBERTa classifier loaded from %s", model_path)
        return True
    except Exception as exc:
        logger.warning("Could not load DeBERTa from %s: %s — using rule-based fallback", model_path, exc)
        _deberta_warmed = True   # failed = fallback expected
        return False


def _deberta_predict(text: str) -> tuple[str, float]:
    """Returns (tier, confidence) where tier is 'local' or 'cloud'."""
    if not _load_deberta():
        return ("local", 0.5)
    try:
        import torch  # type: ignore

        inputs = _deberta_tokenizer(  # type: ignore[call-arg]
            text[:256], return_tensors="pt", truncation=True, max_length=128
        )
        with torch.no_grad():
            logits = _deberta_classifier(**inputs).logits  # type: ignore[misc]
        probs = torch.softmax(logits, dim=-1)[0]
        tier = "local" if probs[0] > probs[1] else "cloud"
        confidence = float(probs[0] if tier == "local" else probs[1])
        return (tier, confidence)
    except Exception as exc:
        logger.debug("DeBERTa inference error: %s", exc)
        return ("local", 0.5)


# ---------------------------------------------------------------------------
# Legacy multi-class DeBERTa path (kept for backwards compat)
# ---------------------------------------------------------------------------

def _deberta_classify(text: str) -> IntentObject | None:
    """
    Multi-class DeBERTa classification (maps class labels to IntentCategory).
    Used only when the loaded model has more than 2 output classes.
    """
    if not _load_deberta():
        return None
    try:
        import math

        import torch  # type: ignore

        inputs = _deberta_tokenizer(  # type: ignore[call-arg]
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True,
        )
        with torch.no_grad():
            logits = _deberta_classifier(**inputs).logits  # type: ignore[misc]
            probs  = torch.softmax(logits, dim=-1)[0].tolist()

        id2label = _deberta_classifier.config.id2label  # type: ignore[union-attr]
        scores = {id2label[i]: p for i, p in enumerate(probs)}
        best_label = max(scores, key=scores.__getitem__)
        confidence = scores[best_label]

        try:
            category = IntentCategory(best_label.lower())
        except ValueError:
            category = IntentCategory.CONVERSATION

        entropy = -sum(p * math.log(p + 1e-9) for p in probs)
        max_entropy = math.log(len(probs))
        normed = entropy / max_entropy if max_entropy > 0 else 0.5
        complexity = max(1, min(5, round(1 + normed * 4)))

        return IntentObject(
            category=category,
            complexity=complexity,
            keywords=[],
            confidence=confidence,
            raw_scores=scores,
        )
    except Exception as exc:
        logger.debug("DeBERTa multi-class inference error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# BYO/external classifier adapters
# ---------------------------------------------------------------------------

def _coerce_external_intent(payload: dict[str, Any], method: str) -> IntentObject | None:
    """Validate an external classifier response before it can affect routing."""
    try:
        category = IntentCategory(str(payload.get("category", "")).strip().lower())
    except ValueError:
        return None

    try:
        complexity = int(payload.get("complexity", 2))
    except (TypeError, ValueError):
        complexity = 2
    complexity = max(1, min(5, complexity))

    try:
        confidence = float(payload.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    raw_keywords = payload.get("keywords", [])
    keywords = [str(k)[:64] for k in raw_keywords[:12]] if isinstance(raw_keywords, list) else []

    return IntentObject(
        category=category,
        complexity=complexity,
        keywords=keywords,
        confidence=confidence,
        needs_vision=bool(payload.get("needs_vision", False)),
        needs_web=bool(payload.get("needs_web", False)),
        raw_scores={method: confidence},
    )


def _http_classify(text: str) -> IntentObject | None:
    from router.config import settings

    if not settings.classifier_http_url:
        return None
    try:
        import httpx

        with httpx.Client(timeout=settings.classifier_http_timeout_seconds) as client:
            resp = client.post(
                settings.classifier_http_url,
                json={"content": text[:4000], "text": text[:4000]},
                headers={"User-Agent": "mullm-classifier/1.0"},
            )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and isinstance(data.get("intent"), dict):
            data = data["intent"]
        if not isinstance(data, dict):
            return None
        result = _coerce_external_intent(data, "http")
        if result:
            logger.debug(
                "intent classified: method=http category=%s complexity=%d confidence=%.2f",
                result.category.value,
                result.complexity,
                result.confidence,
            )
        return result
    except Exception as exc:
        logger.debug("HTTP classifier unavailable; using local fallback: %s", exc)
        return None


def _onnx_runtime_available() -> bool:
    global _onnx_checked, _onnx_available
    if _onnx_checked:
        return _onnx_available
    _onnx_checked = True
    try:
        import onnxruntime  # noqa: F401

        _onnx_available = True
    except Exception:
        _onnx_available = False
    return _onnx_available


def _softmax(values: list[float]) -> list[float]:
    import math

    if not values:
        return []
    peak = max(values)
    exps = [math.exp(v - peak) for v in values]
    total = sum(exps) or 1.0
    return [v / total for v in exps]


def _load_onnx_classifier() -> tuple[object, object, list[str]] | None:
    global _onnx_model_key, _onnx_session, _onnx_tokenizer

    from router.config import settings

    model_path = Path(settings.classifier_onnx_model_path).expanduser()
    tokenizer_path = Path(settings.classifier_onnx_tokenizer_path or model_path.parent).expanduser()
    key = f"{model_path}|{tokenizer_path}"
    if _onnx_session is not None and _onnx_tokenizer is not None and _onnx_model_key == key:
        labels = _load_onnx_labels(model_path)
        return _onnx_session, _onnx_tokenizer, labels

    if not model_path.exists():
        logger.debug("ONNX classifier path does not exist: %s", model_path)
        return None
    if not tokenizer_path.exists():
        logger.debug("ONNX classifier tokenizer path does not exist: %s", tokenizer_path)
        return None
    if not _onnx_runtime_available():
        logger.debug("ONNX classifier configured but onnxruntime is not installed")
        return None

    try:
        import onnxruntime as ort
        from transformers import AutoTokenizer  # type: ignore

        _onnx_session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        _onnx_tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_path), local_files_only=True)  # nosec B615
        _onnx_model_key = key
        return _onnx_session, _onnx_tokenizer, _load_onnx_labels(model_path)
    except Exception as exc:
        logger.debug("ONNX classifier load failed: %s", exc)
        return None


def _load_onnx_labels(model_path: Path) -> list[str]:
    label_map = model_path.parent / "mullm_label_map.json"
    if label_map.exists():
        try:
            data = json.loads(label_map.read_text(encoding="utf-8"))
            id2label = data.get("id2label", {})
            labels = [str(id2label[str(i)] if str(i) in id2label else id2label[i]) for i in range(len(id2label))]
            if labels:
                return labels
        except Exception as exc:
            logger.debug("Could not read ONNX label map %s: %s", label_map, exc)
    return ["note", "lookup", "code", "research", "creative", "deploy", "conversation"]


def _onnx_classify(text: str) -> IntentObject | None:
    """Classify through an exported ONNX sequence classifier."""
    from router.config import settings

    if not settings.classifier_onnx_model_path:
        return None
    loaded = _load_onnx_classifier()
    if loaded is None:
        return None
    session, tokenizer, labels = loaded

    try:
        encoded = tokenizer(  # type: ignore[operator]
            text[:4000],
            return_tensors="np",
            truncation=True,
            max_length=512,
            padding=True,
        )
        input_names = {item.name for item in session.get_inputs()}  # type: ignore[attr-defined]
        feeds = {k: v for k, v in encoded.items() if k in input_names}
        outputs = session.run(None, feeds)  # type: ignore[attr-defined]
        logits = outputs[0][0].tolist()
        probs = _softmax([float(v) for v in logits])
        if not probs:
            return None
        best = max(range(len(probs)), key=probs.__getitem__)
        label = labels[best] if best < len(labels) else "conversation"
        result = _coerce_external_intent(
            {
                "category": label,
                "complexity": max(1, min(5, round(1 + (1 - probs[best]) * 4))),
                "confidence": probs[best],
                "keywords": [],
            },
            "onnx",
        )
        if result:
            logger.debug(
                "intent classified: method=onnx category=%s complexity=%d confidence=%.2f",
                result.category.value,
                result.complexity,
                result.confidence,
            )
        return result
    except Exception as exc:
        logger.debug("ONNX classifier inference failed: %s", exc)
        return None


def classifier_status() -> dict[str, Any]:
    from router.config import settings

    model_path = Path(settings.classifier_model_path).expanduser() if settings.classifier_model_path else None
    onnx_path = Path(settings.classifier_onnx_model_path).expanduser() if settings.classifier_onnx_model_path else None
    data_path = Path(settings.classifier_retrain_data_path).expanduser() if settings.classifier_retrain_data_path else None
    return {
        "backend": settings.classifier_backend,
        "use_deberta": _use_deberta,
        "deberta_loaded": is_model_loaded(),
        "deberta_warmed": is_classifier_warmed(),
        "local_path": str(model_path) if model_path else "",
        "local_path_exists": bool(model_path and model_path.exists()),
        "http_enabled": bool(settings.classifier_http_url),
        "http_url": settings.classifier_http_url,
        "http_timeout_seconds": settings.classifier_http_timeout_seconds,
        "onnx_enabled": bool(settings.classifier_onnx_model_path),
        "onnx_model_path": str(onnx_path) if onnx_path else "",
        "onnx_model_exists": bool(onnx_path and onnx_path.exists()),
        "onnxruntime_available": _onnx_runtime_available() if settings.classifier_onnx_model_path else False,
        "retrain_enabled": settings.classifier_retrain_enabled,
        "retrain_schedule": settings.classifier_retrain_schedule,
        "retrain_data_path": str(data_path) if data_path else "",
        "retrain_data_exists": bool(data_path and data_path.exists()),
        "retrain_output_path": settings.classifier_retrain_output_path,
        "retrain_min_samples": settings.classifier_retrain_min_samples,
        "retrain_dry_run": settings.classifier_retrain_dry_run,
        "retrain_mode": settings.classifier_retrain_mode,
    }


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_model_loaded() -> bool:
    """Return True if the DeBERTa model is currently loaded in memory."""
    return _deberta_classifier is not None


def is_classifier_warmed() -> bool:
    """Return True once model load has been attempted (whether successful or not)."""
    return _deberta_warmed


def set_use_deberta(enabled: bool) -> None:
    """Toggle DeBERTa routing classifier on/off without restart."""
    global _use_deberta
    _use_deberta = enabled
    logger.info("DeBERTa toggle: enabled=%s", enabled)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(
    query: str,
    history: list[dict] | None = None,
) -> IntentObject:
    """
    Classify *query* intent, returning an IntentObject.

    Classification pipeline:
      Layer 1: Fast RULES regex matching.
      Layer 1.5: DeBERTa binary routing classifier (if available and confidence < 0.75).
      Layer 2: Multi-class DeBERTa (if loaded model supports it).
      Fallback: Simple heuristic classification.

    *history* is the conversation history list; the last 3 turns are prepended
    to the classification context to handle follow-up questions correctly.
    """
    start = time.perf_counter()

    # Build context-enriched text (multi-turn)
    context_parts: list[str] = []
    if history:
        for turn in history[-3:]:
            role    = turn.get("role", "")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                context_parts.append(f"{role}: {content[:200]}")
    context_parts.append(f"user: {query}")
    enriched_text = "\n".join(context_parts)

    from router.config import settings

    backend = settings.classifier_backend
    if backend in ("http", "auto"):
        external = _http_classify(enriched_text)
        if external is not None and external.confidence >= settings.classifier_confidence_threshold:
            return external
        if backend == "http" and external is not None:
            return external

    if backend in ("onnx", "auto"):
        onnx_result = _onnx_classify(enriched_text)
        if onnx_result is not None and onnx_result.confidence >= settings.classifier_confidence_threshold:
            return onnx_result
        if backend == "onnx" and onnx_result is not None:
            return onnx_result

    # ── Layer 1: Fast rules ──────────────────────────────────
    fast_result = _fast_classify(enriched_text)

    if fast_result:
        confidence = fast_result["confidence"]

        # ── Layer 1.5: DeBERTa confidence check ─────────────
        # If rules matched but confidence is low (<0.75), consult DeBERTa
        # binary classifier before committing. Local-first: only escalate
        # complexity when DeBERTa is confident about cloud.
        if backend != "rules" and confidence < 0.75 and _use_deberta:
            deberta_tier, deberta_conf = _deberta_predict(query)
            logger.debug(
                "DeBERTa predict: tier=%s confidence=%.3f (rules conf=%.2f)",
                deberta_tier, deberta_conf, confidence,
            )
            if deberta_tier == "cloud" and deberta_conf > 0.75:
                # DeBERTa is confident this should go to cloud — bump complexity
                fast_result["complexity"] = min(5, max(fast_result["complexity"], 4))
                fast_result["method"] = "rules+deberta_cloud"
            else:
                fast_result["method"] = "rules+deberta_local"

        latency_ms = (time.perf_counter() - start) * 1000
        category   = fast_result["category"]
        needs_vision = fast_result.get("needs_vision", False)

        logger.debug(
            "intent classified: method=%s category=%s complexity=%d confidence=%.2f latency_ms=%.1f",
            fast_result["method"],
            category.value,
            fast_result["complexity"],
            fast_result["confidence"],
            latency_ms,
        )

        return IntentObject(
            category=category,
            complexity=fast_result["complexity"],
            keywords=fast_result["keywords"],
            confidence=fast_result["confidence"],
            needs_vision=needs_vision,
            needs_web=fast_result.get("needs_web", False),
        )

    # ── Layer 2: Try multi-class DeBERTa ────────────────────
    num_classes = 0
    if _deberta_classifier is not None:
        try:
            num_classes = len(_deberta_classifier.config.id2label)  # type: ignore[union-attr]
        except Exception:
            pass

    if backend != "rules" and num_classes > 2:
        result = _deberta_classify(enriched_text)
        if result is not None:
            logger.debug(
                "intent classified: method=deberta_multiclass category=%s complexity=%d",
                result.category.value, result.complexity,
            )
            return result

    # ── Fallback: heuristic classification ───────────────────
    logger.debug("intent fallback classifier: no rule matched, using heuristics")
    return _rule_heuristic_classify(query, enriched_text)


def _rule_heuristic_classify(original_query: str, enriched_text: str) -> IntentObject:
    """Final fallback when no RULES pattern matches. Always returns a valid IntentObject."""
    text_len = len(original_query)

    # Length-based complexity estimate
    if text_len < 50:
        complexity = 1
        category = IntentCategory.LOOKUP
    elif text_len < 150:
        complexity = 2
        category = IntentCategory.CONVERSATION
    elif text_len < 500:
        complexity = 3
        category = IntentCategory.RESEARCH
    else:
        complexity = 4
        category = IntentCategory.RESEARCH

    # Apply boosters even in fallback
    lower = enriched_text.lower()
    for boost_pattern, boost in COMPLEXITY_BOOST_PATTERNS:
        if re.search(boost_pattern, lower):
            complexity = min(5, complexity + boost)

    keywords = _extract_keywords(original_query)
    needs_vision = bool(re.search(r"\b(image|photo|picture|screenshot)\b", original_query, re.I))

    return IntentObject(
        category=category,
        complexity=complexity,
        keywords=keywords,
        confidence=0.50,
        needs_vision=needs_vision,
        needs_web=_needs_web_search(original_query),
    )


def _default_classification() -> dict:
    return {
        "category": "conversation",
        "complexity": 2,
        "confidence": 0.3,
        "keywords": [],
    }


def _parse_classifier_output(raw: str) -> dict:
    if not raw or not raw.strip():
        return _default_classification()

    cleaned = raw.strip()
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()

    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    m = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    return _default_classification()


# ---------------------------------------------------------------------------
# classify_intent — compatibility wrapper matching original pipeline API
# ---------------------------------------------------------------------------

_CATEGORY_TIER_MAP = {
    "note":     "cache",
    "lookup":   "cache",
    "code":     "local",
    "research": "cloud_cheap",
    "creative": "cloud_cheap",
    "deploy":   "local",
    "vision":   "cloud_cheap",
    "conversation": "local",
}


_CLASSIFIER_SYSTEM_PROMPT = (
    'Classify the user query. Respond with JSON only: '
    '{"category":"<one of: code,research,creative,conversation,deploy,note,lookup,vision>","complexity":<1-5>,"confidence":<0.0-1.0>,"keywords":[]}'
)


async def classify_intent(intent, rules_only: bool = False):
    """
    Async intent classifier.
    1. Try _fast_classify (rules/regex).
    2. If rules_only=False and no rules match, try ollama_client LLM.
    3. Fall back to default (conversation) if LLM unavailable.
    """
    import time as _time

    from router.models import ClassificationResult, IntentCategory, Tier

    content = getattr(intent, "content", "") or str(intent)
    t0 = _time.monotonic()

    # Fast path: rule-based
    fast = _fast_classify(content)
    if fast is not None:
        cat_str = fast.get("category", "conversation")
        try:
            cat = IntentCategory(cat_str)
        except ValueError:
            cat = IntentCategory.CONVERSATION
        tier_str = _CATEGORY_TIER_MAP.get(cat.value, "local")
        if fast.get("complexity", 1) >= 4 and tier_str == "local":
            tier_str = "cloud_cheap"
        try:
            suggested_tier = Tier(tier_str)
        except ValueError:
            suggested_tier = Tier.LOCAL
        return ClassificationResult(
            category=cat,
            complexity=fast.get("complexity", 2),
            confidence=fast.get("confidence", 0.85),
            keywords=fast.get("keywords", []),
            needs_vision=fast.get("needs_vision", False),
            needs_web=fast.get("needs_web", False),
            suggested_tier=suggested_tier,
            classifier_latency_ms=round((_time.monotonic() - t0) * 1000, 2),
            classifier_method="rules",
        )

    if rules_only:
        result = classify(content)
        tier_str = _CATEGORY_TIER_MAP.get(result.category.value, "local")
        try:
            suggested_tier = Tier(tier_str)
        except ValueError:
            suggested_tier = Tier.LOCAL
        return ClassificationResult(
            category=result.category,
            complexity=result.complexity,
            confidence=result.confidence,
            keywords=result.keywords,
            needs_vision=result.needs_vision,
            needs_web=result.needs_web,
            suggested_tier=suggested_tier,
            classifier_latency_ms=round((_time.monotonic() - t0) * 1000, 2),
            classifier_method="rules_only_fast",
        )

    # LLM fallback when rules return None
    if ollama_client is not None:
        try:
            model = settings.ollama_model
            resp = ollama_client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": _CLASSIFIER_SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                options={"temperature": 0},
            )
            raw = resp.get("message", {}).get("content", "")
            parsed = _parse_classifier_output(raw)
            cat_str = parsed.get("category", "conversation")
            try:
                cat = IntentCategory(cat_str)
            except ValueError:
                cat = IntentCategory.CONVERSATION
            tier_str = _CATEGORY_TIER_MAP.get(cat.value, "local")
            try:
                suggested_tier = Tier(tier_str)
            except ValueError:
                suggested_tier = Tier.LOCAL
            return ClassificationResult(
                category=cat,
                complexity=parsed.get("complexity", 2),
                confidence=parsed.get("confidence", 0.7),
                keywords=parsed.get("keywords", []),
                suggested_tier=suggested_tier,
                classifier_latency_ms=round((_time.monotonic() - t0) * 1000, 2),
                classifier_method="llm",
            )
        except Exception:
            pass

    # Ultimate fallback
    return ClassificationResult(
        category=IntentCategory.CONVERSATION,
        complexity=2,
        confidence=0.3,
        keywords=[],
        suggested_tier=Tier.LOCAL,
        classifier_latency_ms=round((_time.monotonic() - t0) * 1000, 2),
        classifier_method="fallback",
    )
