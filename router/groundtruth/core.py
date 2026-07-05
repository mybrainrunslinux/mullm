"""
Groundtruth core categories — always enabled, zero cost, zero false positives.

Categories registered here:
  arithmetic      — safe AST-based evaluator
  datetime        — current date/time with optional timezone
  http_status     — RFC 9110 status code descriptions
  unit_conversion — metric/imperial conversions + temperature
  git_commands    — common git one-liner lookups
  big_o           — algorithm time complexity LUT
  big_o_ds        — data structure Big-O table
  ports           — well-known TCP/UDP port numbers
"""
from __future__ import annotations

import ast
import math
import operator
import re
import zoneinfo
from datetime import UTC, datetime

from .registry import CategoryPlugin, register_category

# ---------------------------------------------------------------------------
# 1. Safe arithmetic evaluator (whitelist AST approach — no eval/exec)
# ---------------------------------------------------------------------------

_SAFE_OPS = {
    ast.Add:      operator.add,
    ast.Sub:      operator.sub,
    ast.Mult:     operator.mul,
    ast.Div:      operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod:      operator.mod,
    ast.Pow:      operator.pow,
    ast.USub:     operator.neg,
    ast.UAdd:     operator.pos,
}

_SAFE_FUNCS = {
    "sqrt":  math.sqrt,
    "abs":   abs,
    "round": round,
}

_MAX_POW_BASE = 1_000_000   # guard against 999**999 DoS


def _safe_eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.BinOp):
        op_fn = _SAFE_OPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        left  = _safe_eval_node(node.left)
        right = _safe_eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(left) > _MAX_POW_BASE:
            raise ValueError("Base too large for exponentiation")
        return op_fn(left, right)
    if isinstance(node, ast.UnaryOp):
        op_fn = _SAFE_OPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")
        return op_fn(_safe_eval_node(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls allowed")
        fn = _SAFE_FUNCS.get(node.func.id)
        if fn is None:
            raise ValueError(f"Unsupported function: {node.func.id!r}")
        args = [_safe_eval_node(a) for a in node.args]
        return fn(*args)
    raise ValueError(f"Unsupported AST node: {type(node).__name__}")


def _safe_eval(expr: str) -> float | None:
    try:
        tree = ast.parse(expr.strip(), mode="eval")
        result = _safe_eval_node(tree)
        if not math.isfinite(result):
            return None
        return result
    except Exception:
        return None


def _normalise_expr(s: str) -> str:
    return s.replace("^", "**")


_ARITH_PREFIX_RE = re.compile(
    r"^(?:what(?:'s| is)(?: the)? |calculate |compute |evaluate )",
    re.IGNORECASE,
)
_ARITH_CHARS_RE = re.compile(
    r"""^[\s\d\+\-\*\/\(\)\.\%\^\_]+$""",
    re.VERBOSE,
)


def _resolve_arithmetic(q: str) -> str | None:
    arith_q = _ARITH_PREFIX_RE.sub("", q).rstrip("?").strip()
    arith_q = _normalise_expr(arith_q)
    if _ARITH_CHARS_RE.match(arith_q) or re.search(r"[\+\-\*\/]", arith_q):
        result = _safe_eval(arith_q)
        if result is not None:
            if result == int(result) and abs(result) < 1e15:
                return str(int(result))
            return f"{result:.6g}"
    return None


# ---------------------------------------------------------------------------
# 2. Date / time
# ---------------------------------------------------------------------------

_DT_RE = re.compile(
    r"\b(what(?:'s| is)(?: the)? (?:current )?(?:date|time(?!\s+(?:complex|limit|out|stamp|zone|frame|series|ly|line|ly\b))|day)"
    r"|what time is it|what day is it|today(?:'s date)?|current time)\b",
    re.IGNORECASE,
)
_TZ_RE = re.compile(
    r"\b(?:in|for)\s+([A-Za-z_/]+(?:\s+[A-Za-z]+)?)\s*(?:time|timezone|tz)?\b",
    re.IGNORECASE,
)


_WEATHER_RE = re.compile(
    r"\b(?:weather|forecast|temperature|temp\b|humid|rain|snow|wind|climate|storm|sunny|cloudy"
    r"|warm(?:er|est|th)?|cold(?:er|est)?|hot(?:ter|test)?|cool(?:er|est)?|chilly|freez)",
    re.IGNORECASE,
)


def _resolve_datetime(q: str) -> str | None:
    if _WEATHER_RE.search(q):
        return None
    if not _DT_RE.search(q):
        return None
    now_utc = datetime.now(UTC)
    tz_match = _TZ_RE.search(q)
    if tz_match:
        tz_name = tz_match.group(1).strip().replace(" ", "_")
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
            now_local = now_utc.astimezone(tz)
            return now_local.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            pass
    return now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------------------
# 3. HTTP status codes (RFC 9110 + common de-facto codes)
# ---------------------------------------------------------------------------

_HTTP_CODES: dict[int, str] = {
    100: "Continue",
    101: "Switching Protocols",
    200: "OK",
    201: "Created",
    202: "Accepted",
    204: "No Content",
    206: "Partial Content",
    301: "Moved Permanently",
    302: "Found",
    304: "Not Modified",
    307: "Temporary Redirect",
    308: "Permanent Redirect",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    409: "Conflict",
    410: "Gone",
    413: "Content Too Large",
    415: "Unsupported Media Type",
    422: "Unprocessable Content",
    429: "Too Many Requests",
    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}

_HTTP_RE = re.compile(
    r"\b(what(?:'s| is)(?: an?)? |meaning of |http (?:status )?(?:code )?)(\d{3})\b",
    re.IGNORECASE,
)


def _http_handler(m: re.Match) -> str | None:
    code = int(m.group(2))
    meaning = _HTTP_CODES.get(code)
    if meaning:
        return f"HTTP {code}: {meaning}"
    return None


# ---------------------------------------------------------------------------
# 3b. Tiny web/CSS facts used by first-run sample cards
# ---------------------------------------------------------------------------

_CSS_MARGIN_PADDING_RE = re.compile(
    r"\b(?:difference|diff|compare)\b.*\bmargin\b.*\bpadding\b.*\bcss\b|\bcss\b.*\bmargin\b.*\bpadding\b",
    re.IGNORECASE,
)

_MEDIA_SETUP_RE = re.compile(
    r"\b(?:3d|three.?d|image|video|asset|model)\b.{0,50}\b(?:not configured|setup|configure|provider|generator|generation)\b|"
    r"\b(?:comfyui|meshy|tripo|rodin|sana.?wm)\b.{0,40}\b(?:setup|configure|provider|key|url)\b",
    re.IGNORECASE,
)

_RESPONSIVE_GAME_RE = re.compile(
    r"\b(?:vertical|phone|mobile|portrait|fold)\b.{0,80}\b(?:game|canvas|layout|viewport)\b|"
    r"\b(?:game|canvas|layout|viewport)\b.{0,80}\b(?:vertical|phone|mobile|portrait|fold)\b",
    re.IGNORECASE,
)

_ENTERPRISE_SETUP_RE = re.compile(
    r"\b(?:air.?gapped|noninteractive|immutable|mdm|gpo|jamf|entra|oidc|audit)\b.{0,70}\b(?:setup|install|deploy|deployment|enterprise|configure)\b|"
    r"\b(?:enterprise|studio|company)\b.{0,70}\b(?:air.?gapped|noninteractive|immutable|mdm|gpo|jamf|entra|oidc|audit)\b",
    re.IGNORECASE,
)


def _resolve_css_facts(q: str) -> str | None:
    if _CSS_MARGIN_PADDING_RE.search(q):
        return (
            "In CSS, margin is the space outside an element's border; padding is the "
            "space inside the border between the content and the border. Margin moves "
            "the element away from neighbors, while padding gives the element's content "
            "more internal breathing room."
        )
    if _MEDIA_SETUP_RE.search(q):
        return (
            "muLLM media generation is provider-gated. Image/video/3D requests should first check "
            "`/api/setup/status` for ComfyUI, Meshy, Tripo, Rodin, or SANA-WM. If no compatible "
            "local or cloud provider is configured, the UI should route the user to Setup instead "
            "of sending the prompt to an LLM or spending money."
        )
    if _RESPONSIVE_GAME_RE.search(q):
        return (
            "For phone-first games that also work on desktop, keep the gameplay lane or aiming "
            "volume aspect-stable, then use extra desktop width for peripheral scenery, inventory, "
            "spectator UI, or non-competitive information. Do not let wider screens reveal targets "
            "earlier or expand the effective hit area."
        )
    if _ENTERPRISE_SETUP_RE.search(q):
        return (
            "Enterprise muLLM deployment should support noninteractive config, immutable or managed "
            "settings, local-only/air-gapped operation, full audit logging, SSO/OIDC policy hooks, "
            "and explicit provider allowlists. Setup should be repeatable from config files and "
            "environment variables, not only from the browser wizard."
        )
    return None


# ---------------------------------------------------------------------------
# 4. Unit conversion (exact ratios)
# ---------------------------------------------------------------------------

_UNIT_PATTERNS: list[tuple[str, str, float]] = [
    # length
    ("miles?",             "km|kilometers?",      1.609344),
    ("km|kilometers?",     "miles?",              1 / 1.609344),
    ("feet|ft",            "meters?|m",           0.3048),
    ("meters?|m",          "feet|ft",             1 / 0.3048),
    ("inches?|in",         "cm|centimeters?",     2.54),
    ("cm|centimeters?",    "inches?|in",          1 / 2.54),
    # mass
    ("pounds?|lbs?",       "kg|kilograms?",       0.453592),
    ("kg|kilograms?",      "pounds?|lbs?",        1 / 0.453592),
    # data
    ("gb|gigabytes?",      "mb|megabytes?",       1024.0),
    ("mb|megabytes?",      "gb|gigabytes?",       1 / 1024.0),
    ("tb|terabytes?",      "gb|gigabytes?",       1024.0),
    ("gb|gigabytes?",      "tb|terabytes?",       1 / 1024.0),
]

_CONVERT_RE = re.compile(
    r"(?:convert\s+)?([\d,]+(?:\.\d+)?)\s+(\w+)\s+(?:in\s+)?to\s+(\w+)",
    re.IGNORECASE,
)
_TEMP_RE = re.compile(
    r"([\-\d]+(?:\.\d+)?)\s*°?([cf])\s+(?:in\s+)?(?:to\s+)?°?([cf])",
    re.IGNORECASE,
)


def _resolve_unit_conversion(q: str) -> str | None:
    # Temperature
    m = _TEMP_RE.search(q)
    if m:
        val = float(m.group(1))
        from_unit = m.group(2).lower()
        to_unit   = m.group(3).lower()
        if from_unit == "c" and to_unit == "f":
            return f"{val * 9/5 + 32:.2f}°F"
        if from_unit == "f" and to_unit == "c":
            return f"{(val - 32) * 5/9:.2f}°C"

    # General unit conversion
    m = _CONVERT_RE.search(q)
    if m:
        raw_val  = m.group(1).replace(",", "")
        from_raw = m.group(2).lower()
        to_raw   = m.group(3).lower()
        try:
            val = float(raw_val)
        except ValueError:
            return None
        for (from_pat, to_pat, factor) in _UNIT_PATTERNS:
            if re.match(f"^(?:{from_pat})$", from_raw, re.IGNORECASE) and \
               re.match(f"^(?:{to_pat})$",   to_raw,   re.IGNORECASE):
                converted = val * factor
                if converted == int(converted):
                    formatted = str(int(converted))
                else:
                    formatted = f"{converted:.4g}"
                return f"{formatted} {to_raw}"
    return None


# ---------------------------------------------------------------------------
# 5. Git one-liners
# ---------------------------------------------------------------------------

_GIT_LUT: dict[str, str] = {
    "undo last commit":              "git reset --soft HEAD~1",
    "undo last commit keep changes": "git reset --soft HEAD~1",
    "unstage file":                  "git restore --staged <file>",
    "discard changes":               "git restore <file>",
    "rename branch":                 "git branch -m <old> <new>",
    "delete local branch":           "git branch -d <branch>",
    "delete remote branch":          "git push origin --delete <branch>",
    "stash changes":                 "git stash push -m 'description'",
    "list stashes":                  "git stash list",
    "apply stash":                   "git stash pop",
    "show diff staged":              "git diff --cached",
    "show all branches":             "git branch -a",
    "show remote url":               "git remote -v",
    "amend last commit":             "git commit --amend --no-edit",
    "cherry pick":                   "git cherry-pick <commit-hash>",
    "squash commits":                "git rebase -i HEAD~<n>",
    "show log one line":             "git log --oneline",
    "clone specific branch":         "git clone -b <branch> <url>",
    "force pull":                    "git fetch --all && git reset --hard origin/<branch>",
    "show file history":             "git log --follow -p -- <file>",
}

_GIT_RE = re.compile(
    r"(?:what(?:'s| is)(?: the)? )?git(?: command)? (?:to |for )?(.+?)[\?\.]?$",
    re.IGNORECASE,
)


def _git_handler(m: re.Match) -> str | None:
    key = m.group(1).strip().lower().rstrip("?")
    return _GIT_LUT.get(key)


# ---------------------------------------------------------------------------
# 6. Big-O algorithm complexity
# ---------------------------------------------------------------------------

_BIG_O_LUT: dict[str, str] = {
    "binary search":        "O(log n)",
    "linear search":        "O(n)",
    "bubble sort":          "O(n²)",
    "selection sort":       "O(n²)",
    "insertion sort":       "O(n²)",
    "merge sort":           "O(n log n)",
    "quicksort":            "O(n log n) average, O(n²) worst",
    "quick sort":           "O(n log n) average, O(n²) worst",
    "heapsort":             "O(n log n)",
    "heap sort":            "O(n log n)",
    "timsort":              "O(n log n)",
    "counting sort":        "O(n + k)",
    "radix sort":           "O(nk)",
    "hash table lookup":    "O(1) average",
    "hash map lookup":      "O(1) average",
    "bfs":                  "O(V + E)",
    "breadth first search": "O(V + E)",
    "dfs":                  "O(V + E)",
    "depth first search":   "O(V + E)",
    "dijkstra":             "O((V + E) log V)",
    "bellman ford":         "O(VE)",
    "floyd warshall":       "O(V³)",
}

_BIG_O_RE = re.compile(
    r"(?:what(?:'s| is)(?: the)? )?(?:time )?complexity(?: of)? (.+?)[\?\.]?$",
    re.IGNORECASE,
)


def _big_o_handler(m: re.Match) -> str | None:
    key = m.group(1).strip().lower().rstrip("?")
    answer = _BIG_O_LUT.get(key)
    if answer:
        return f"{key.title()}: {answer}"
    return None


# ---------------------------------------------------------------------------
# 7. Data structure Big-O table (from groundtruth_extras.py)
# ---------------------------------------------------------------------------

_DATA_STRUCTURES: dict[str, tuple[str, str, str, str, str, str]] = {
    "hashmap": (
        "O(1)*", "O(1)*", "O(1)*", "O(1)*", "O(n)",
        "* amortized; worst case O(n) on hash collision. Python dict / JS Map.",
    ),
    "dict": (
        "O(1)*", "O(1)*", "O(1)*", "O(1)*", "O(n)",
        "* amortized; worst case O(n) on hash collision. Python dict / JS Map.",
    ),
    "array": (
        "O(1)", "O(n)", "O(n)", "O(n)", "O(n)",
        "Random access O(1) by index. Insert/delete shifts elements. Cache-friendly.",
    ),
    "linkedlist": (
        "O(n)", "O(1)*", "O(n)", "O(1)*", "O(n)",
        "* O(1) if you already have the node pointer. No random access. High pointer overhead.",
    ),
    "stack": (
        "O(1)", "O(1)", "O(n)", "O(1)", "O(n)",
        "LIFO. Push/pop at one end. Implemented via array or linked list.",
    ),
    "queue": (
        "O(1)", "O(1)", "O(n)", "O(1)", "O(n)",
        "FIFO. Enqueue rear, dequeue front. Use collections.deque in Python.",
    ),
    "heap": (
        "O(1)*", "O(log n)", "O(n)", "O(log n)", "O(n)",
        "* peek/get-min is O(1). Insert & delete require heapify. Binary heap standard.",
    ),
    "bst": (
        "O(log n)*", "O(log n)*", "O(log n)*", "O(log n)*", "O(n)",
        "* balanced tree (AVL, Red-Black). Degenerate (sorted input) → O(n).",
    ),
    "trie": (
        "O(k)", "O(k)", "O(k)", "O(k)", "O(n*k)",
        "k = key length. Great for prefix search / autocomplete.",
    ),
    "set": (
        "N/A", "O(1)*", "O(1)*", "O(1)*", "O(n)",
        "Hash-set. Same amortized O(1) as hashmap. TreeSet = O(log n) but sorted.",
    ),
    "deque": (
        "O(1)", "O(1)", "O(n)", "O(1)", "O(n)",
        "Double-ended queue. O(1) push/pop at BOTH ends. Python collections.deque.",
    ),
}

_DS_KEYS: dict[str, str] = {
    "hashmap": "hashmap", "hash map": "hashmap", "hash table": "hashmap", "hashtable": "hashmap",
    "dict": "dict", "dictionary": "dict",
    "array": "array", "list": "array",
    "linked list": "linkedlist", "linkedlist": "linkedlist",
    "stack": "stack", "queue": "queue", "heap": "heap", "priority queue": "heap",
    "bst": "bst", "binary search tree": "bst",
    "trie": "trie", "set": "set", "deque": "deque",
}

_DS_RE = re.compile(
    r"\b(hashmap|hash\s*map|hash\s*table|dict(?:ionary)?|array|list|linked\s*list|"
    r"stack|queue|heap|priority\s*queue|bst|binary\s*search\s*tree|trie|set|deque)\b"
    r".*?\b(?:big.?o|time\s+complex|space\s+complex|complex|o\()",
    re.IGNORECASE,
)
_DS_RE2 = re.compile(
    r"\b(?:big.?o|time\s+complex|space\s+complex|complex|o\()"
    r".*?\b(hashmap|hash\s*map|hash\s*table|dict(?:ionary)?|array|linked\s*list|"
    r"stack|queue|heap|priority\s*queue|bst|binary\s*search\s*tree|trie|set|deque)\b",
    re.IGNORECASE,
)


def _resolve_ds(q: str) -> str | None:
    m = _DS_RE.search(q) or _DS_RE2.search(q)
    if not m:
        return None
    raw = re.sub(r"\s+", " ", m.group(1).lower().strip())
    key = _DS_KEYS.get(raw)
    if not key:
        return None
    g, s, srch, d, sp, note = _DATA_STRUCTURES[key]
    return (
        f"**{key.title()} Big-O Complexity**\n\n"
        f"| Operation  | Time   |\n"
        f"|------------|--------|\n"
        f"| Get/Access | {g}    |\n"
        f"| Set/Insert | {s}    |\n"
        f"| Search     | {srch} |\n"
        f"| Delete     | {d}    |\n"
        f"| Space      | {sp}   |\n\n"
        f"{note}"
    )


# ---------------------------------------------------------------------------
# 8. Well-known port numbers
# ---------------------------------------------------------------------------

_PORTS: dict[int, str] = {
    21:   "FTP (File Transfer Protocol, control)",
    22:   "SSH (Secure Shell)",
    23:   "Telnet",
    25:   "SMTP (email sending)",
    53:   "DNS (Domain Name System)",
    80:   "HTTP",
    110:  "POP3 (email retrieval)",
    143:  "IMAP (email retrieval)",
    443:  "HTTPS",
    465:  "SMTPS (SMTP over TLS)",
    587:  "SMTP submission (email clients)",
    993:  "IMAPS (IMAP over TLS)",
    995:  "POP3S (POP3 over TLS)",
    3306: "MySQL",
    5432: "PostgreSQL",
    5672: "AMQP (RabbitMQ)",
    6379: "Redis",
    8080: "HTTP alternative / dev server",
    8443: "HTTPS alternative",
    9200: "Elasticsearch HTTP API",
    27017:"MongoDB",
}

_PORT_RE = re.compile(
    r"\bwhat(?:'s| is)(?: the)? (?:port|default port)(?: (?:number|for))? (?:for )?(.+?)[\?\.]?$"
    r"|\bport\s+(\d{2,5})\b",
    re.IGNORECASE,
)


def _port_handler(m: re.Match) -> str | None:
    # Match by number
    if m.group(2):
        port_num = int(m.group(2))
        desc = _PORTS.get(port_num)
        if desc:
            return f"Port {port_num}: {desc}"
        return None
    # Match by name — reverse lookup
    name = m.group(1).strip().lower()
    for port_num, desc in _PORTS.items():
        if name in desc.lower():
            return f"Port {port_num}: {desc}"
    return None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_all_core() -> None:
    """Register all core (always-on) groundtruth categories."""

    register_category(CategoryPlugin(
        name="arithmetic",
        patterns=[],
        resolver=_resolve_arithmetic,
    ))

    register_category(CategoryPlugin(
        name="datetime",
        patterns=[],
        resolver=_resolve_datetime,
    ))

    register_category(CategoryPlugin(
        name="http_status",
        patterns=[(
            _HTTP_RE,
            _http_handler,
        )],
    ))

    register_category(CategoryPlugin(
        name="css_facts",
        patterns=[],
        resolver=_resolve_css_facts,
    ))

    register_category(CategoryPlugin(
        name="unit_conversion",
        patterns=[],
        resolver=_resolve_unit_conversion,
    ))

    register_category(CategoryPlugin(
        name="git_commands",
        patterns=[(
            _GIT_RE,
            _git_handler,
        )],
    ))

    register_category(CategoryPlugin(
        name="big_o",
        patterns=[(
            _BIG_O_RE,
            _big_o_handler,
        )],
    ))

    register_category(CategoryPlugin(
        name="big_o_ds",
        patterns=[],
        resolver=_resolve_ds,
    ))

    register_category(CategoryPlugin(
        name="ports",
        patterns=[(
            _PORT_RE,
            _port_handler,
        )],
    ))
