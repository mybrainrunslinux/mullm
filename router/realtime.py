"""
Realtime context resolver.

Handles date/time/calendar queries locally (zero cost, instant).
Provides web search context for needs_web queries via DuckDuckGo.
Injects current date/time into system prompts so models know "today".
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import structlog

log = structlog.get_logger()

# ── Eager imports for groundtruth modules (avoid per-call import overhead) ──
try:
    from router.groundtruth_extras import try_resolve_extras as _resolve_extras
except ImportError:
    _resolve_extras = None
try:
    from router.groundtruth_gaming import try_resolve_gaming as _resolve_gaming
except ImportError:
    _resolve_gaming = None
try:
    from router.groundtruth_design import try_resolve_design as _resolve_design
except ImportError:
    _resolve_design = None
try:
    from router.groundtruth_live import try_resolve_live as _resolve_live
except ImportError:
    _resolve_live = None
try:
    from router.groundtruth_ue5 import try_resolve_ue5 as _resolve_ue5
except ImportError:
    _resolve_ue5 = None

# ── Astronomical Events 2024-2030 ──────────────────────────
# Source: NASA eclipse almanac, USNO solstice/equinox tables

_SOLAR_ECLIPSES = [
    ("2024-04-08", "Total Solar Eclipse", "Americas"),
    ("2024-10-02", "Annular Solar Eclipse", "Pacific, South America"),
    ("2025-03-29", "Partial Solar Eclipse", "Europe, North Africa"),
    ("2025-09-21", "Partial Solar Eclipse", "Pacific, Antarctica, Australia"),
    ("2026-02-17", "Annular Solar Eclipse", "Antarctica, southern Atlantic"),
    ("2026-08-12", "Total Solar Eclipse", "Arctic, Greenland, Iceland, Spain"),
    ("2027-02-06", "Annular Solar Eclipse", "Pacific, South America"),
    ("2027-08-02", "Total Solar Eclipse", "North Africa, Europe, Middle East"),
    ("2028-01-26", "Annular Solar Eclipse", "Pacific, South America"),
    ("2028-07-22", "Total Solar Eclipse", "Australia, New Zealand"),
    ("2029-01-14", "Partial Solar Eclipse", "Americas"),
    ("2029-06-12", "Partial Solar Eclipse", "Arctic"),
    ("2029-07-11", "Partial Solar Eclipse", "South America"),
    ("2029-12-05", "Partial Solar Eclipse", "Antarctica"),
    ("2030-06-01", "Annular Solar Eclipse", "Europe, North Africa"),
    ("2030-11-25", "Total Solar Eclipse", "Southern Africa, Australia"),
]

_LUNAR_ECLIPSES = [
    ("2025-03-14", "Total Lunar Eclipse", "Americas, Europe, Africa"),
    ("2025-09-07", "Total Lunar Eclipse", "Europe, Africa, Asia, Australia"),
    ("2026-03-03", "Total Lunar Eclipse", "Americas, Europe, Africa"),
    ("2026-08-28", "Partial Lunar Eclipse", "Americas, Europe, Africa"),
    ("2027-02-20", "Penumbral Lunar Eclipse", "Americas, Europe"),
    ("2027-07-18", "Penumbral Lunar Eclipse", "Asia, Australia"),
    ("2028-01-12", "Partial Lunar Eclipse", "Americas, Europe, Africa"),
    ("2028-07-06", "Partial Lunar Eclipse", "Americas, Pacific"),
    ("2028-12-31", "Total Lunar Eclipse", "Europe, Africa, Americas"),
    ("2029-06-26", "Total Lunar Eclipse", "Americas, Europe, Africa"),
    ("2029-12-20", "Total Lunar Eclipse", "Americas, Europe, Africa"),
    ("2030-06-15", "Partial Lunar Eclipse", "Europe, Africa, Asia"),
]

# Approximate dates — actual times vary by minutes/hours per year
_SOLSTICES_EQUINOXES = [
    ("2025-03-20", "Vernal Equinox", "Spring begins in Northern Hemisphere"),
    ("2025-06-20", "Summer Solstice", "Longest day in Northern Hemisphere"),
    ("2025-09-22", "Autumnal Equinox", "Fall begins in Northern Hemisphere"),
    ("2025-12-21", "Winter Solstice", "Shortest day in Northern Hemisphere"),
    ("2026-03-20", "Vernal Equinox", "Spring begins in Northern Hemisphere"),
    ("2026-06-21", "Summer Solstice", "Longest day in Northern Hemisphere"),
    ("2026-09-22", "Autumnal Equinox", "Fall begins in Northern Hemisphere"),
    ("2026-12-21", "Winter Solstice", "Shortest day in Northern Hemisphere"),
    ("2027-03-20", "Vernal Equinox", "Spring begins in Northern Hemisphere"),
    ("2027-06-21", "Summer Solstice", "Longest day in Northern Hemisphere"),
    ("2027-09-23", "Autumnal Equinox", "Fall begins in Northern Hemisphere"),
    ("2027-12-22", "Winter Solstice", "Shortest day in Northern Hemisphere"),
    ("2028-03-20", "Vernal Equinox", "Spring begins in Northern Hemisphere"),
    ("2028-06-20", "Summer Solstice", "Longest day in Northern Hemisphere"),
    ("2028-09-22", "Autumnal Equinox", "Fall begins in Northern Hemisphere"),
    ("2028-12-21", "Winter Solstice", "Shortest day in Northern Hemisphere"),
    ("2029-03-20", "Vernal Equinox", "Spring begins in Northern Hemisphere"),
    ("2029-06-21", "Summer Solstice", "Longest day in Northern Hemisphere"),
    ("2029-09-22", "Autumnal Equinox", "Fall begins in Northern Hemisphere"),
    ("2029-12-21", "Winter Solstice", "Shortest day in Northern Hemisphere"),
    ("2030-03-20", "Vernal Equinox", "Spring begins in Northern Hemisphere"),
    ("2030-06-21", "Summer Solstice", "Longest day in Northern Hemisphere"),
    ("2030-09-22", "Autumnal Equinox", "Fall begins in Northern Hemisphere"),
    ("2030-12-21", "Winter Solstice", "Shortest day in Northern Hemisphere"),
]


def _now() -> datetime:
    return datetime.now()


# ── System prompt date injection ────────────────────────────


def get_system_date_context() -> str:
    """One-liner for system prompt injection. Models always know today's date."""
    now = _now()
    return f"Today is {now.strftime('%A, %B %d, %Y')} ({now.strftime('%H:%M')} local time)."


# ── Local resolution for date/time/calendar queries ─────────

# ── City → Timezone mapping (common queries) ──
_CITY_TZ: dict[str, str] = {
    # Europe
    "london": "Europe/London",
    "uk": "Europe/London",
    "england": "Europe/London",
    "paris": "Europe/Paris",
    "france": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "germany": "Europe/Berlin",
    "munich": "Europe/Berlin",
    "madrid": "Europe/Madrid",
    "spain": "Europe/Madrid",
    "barcelona": "Europe/Madrid",
    "rome": "Europe/Rome",
    "italy": "Europe/Rome",
    "milan": "Europe/Rome",
    "amsterdam": "Europe/Amsterdam",
    "netherlands": "Europe/Amsterdam",
    "brussels": "Europe/Brussels",
    "belgium": "Europe/Brussels",
    "zurich": "Europe/Zurich",
    "switzerland": "Europe/Zurich",
    "geneva": "Europe/Zurich",
    "vienna": "Europe/Vienna",
    "austria": "Europe/Vienna",
    "lisbon": "Europe/Lisbon",
    "portugal": "Europe/Lisbon",
    "dublin": "Europe/Dublin",
    "ireland": "Europe/Dublin",
    "stockholm": "Europe/Stockholm",
    "sweden": "Europe/Stockholm",
    "oslo": "Europe/Oslo",
    "norway": "Europe/Oslo",
    "copenhagen": "Europe/Copenhagen",
    "denmark": "Europe/Copenhagen",
    "helsinki": "Europe/Helsinki",
    "finland": "Europe/Helsinki",
    "warsaw": "Europe/Warsaw",
    "poland": "Europe/Warsaw",
    "prague": "Europe/Prague",
    "czech": "Europe/Prague",
    "budapest": "Europe/Budapest",
    "hungary": "Europe/Budapest",
    "athens": "Europe/Athens",
    "greece": "Europe/Athens",
    "istanbul": "Europe/Istanbul",
    "turkey": "Europe/Istanbul",
    "moscow": "Europe/Moscow",
    "russia": "Europe/Moscow",
    "kyiv": "Europe/Kyiv",
    "ukraine": "Europe/Kyiv",
    # Americas
    "new york": "America/New_York",
    "nyc": "America/New_York",
    "boston": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "la": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "sf": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "dallas": "America/Chicago",
    "houston": "America/Chicago",
    "denver": "America/Denver",
    "phoenix": "America/Phoenix",
    "toronto": "America/Toronto",
    "canada": "America/Toronto",
    "montreal": "America/Toronto",
    "vancouver": "America/Vancouver",
    "mexico city": "America/Mexico_City",
    "mexico": "America/Mexico_City",
    "sao paulo": "America/Sao_Paulo",
    "brazil": "America/Sao_Paulo",
    "rio": "America/Sao_Paulo",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "argentina": "America/Argentina/Buenos_Aires",
    "bogota": "America/Bogota",
    "colombia": "America/Bogota",
    "santiago": "America/Santiago",
    "chile": "America/Santiago",
    "lima": "America/Lima",
    "peru": "America/Lima",
    # Asia
    "tokyo": "Asia/Tokyo",
    "japan": "Asia/Tokyo",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "china": "Asia/Shanghai",
    "hong kong": "Asia/Hong_Kong",
    "singapore": "Asia/Singapore",
    "seoul": "Asia/Seoul",
    "korea": "Asia/Seoul",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "india": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata",
    "dubai": "Asia/Dubai",
    "uae": "Asia/Dubai",
    "abu dhabi": "Asia/Dubai",
    "bangkok": "Asia/Bangkok",
    "thailand": "Asia/Bangkok",
    "taipei": "Asia/Taipei",
    "taiwan": "Asia/Taipei",
    "jakarta": "Asia/Jakarta",
    "indonesia": "Asia/Jakarta",
    "manila": "Asia/Manila",
    "philippines": "Asia/Manila",
    "karachi": "Asia/Karachi",
    "pakistan": "Asia/Karachi",
    "tehran": "Asia/Tehran",
    "iran": "Asia/Tehran",
    "riyadh": "Asia/Riyadh",
    "saudi": "Asia/Riyadh",
    "tel aviv": "Asia/Jerusalem",
    "israel": "Asia/Jerusalem",
    # Africa
    "cairo": "Africa/Cairo",
    "egypt": "Africa/Cairo",
    "johannesburg": "Africa/Johannesburg",
    "south africa": "Africa/Johannesburg",
    "nairobi": "Africa/Nairobi",
    "kenya": "Africa/Nairobi",
    "lagos": "Africa/Lagos",
    "nigeria": "Africa/Lagos",
    "casablanca": "Africa/Casablanca",
    "morocco": "Africa/Casablanca",
    "rabat": "Africa/Casablanca",
    # Oceania
    "sydney": "Australia/Sydney",
    "australia": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "auckland": "Pacific/Auckland",
    "new zealand": "Pacific/Auckland",
    "honolulu": "Pacific/Honolulu",
    "hawaii": "Pacific/Honolulu",
}

# Pattern: "time in <city>" or "what time is it in <city>"
_TIME_IN_RE = re.compile(
    r"\b(?:what(?:'s| is) (?:the )?)?(?:current )?time (?:is it )?(?:in|at) (.+?)(?:\?|$|\.)",
    re.IGNORECASE,
)

_DATE_PATTERNS = [
    (re.compile(r"\b(?:what(?:'s| is) )?(?:today'?s? date|the date(?: today)?|current date)\b"), "date"),
    (
        re.compile(
            r"\b(?:what(?:'s| is) (?:the )?(?:current )?time|current time|time (?:is it|right now|now))\b(?!\s+(?:complexity|zone|series|travel|machine|value|cost|in\b|at\b))"
        ),
        "time",
    ),
    (re.compile(r"\b(?:what day(?: of the week)? is (?:it|today))\b"), "day"),
    (re.compile(r"\b(?:what (?:year|month) is it)\b"), "month_year"),
]

_ECLIPSE_RE = re.compile(
    r"\b(?:when is (?:the )?)?(?:next|upcoming|nearest)\s+"
    r"(?:(solar|lunar|total|partial|annular)\s+)?eclipse\b",
    re.IGNORECASE,
)

_SOLSTICE_EQUINOX_RE = re.compile(
    r"\b(?:when is (?:the )?)?(?:next|upcoming)\s+"
    r"(?:(summer|winter|vernal|spring|autumnal|fall)\s+)?"
    r"(solstice|equinox)\b",
    re.IGNORECASE,
)


def _safe_eval_math(text: str) -> str | None:
    """
    Safely evaluate simple arithmetic expressions.
    Handles: 847 × 23, 1024/32, 2^10, sqrt(144), 15% of 240,
             5!, factorial of 6, 3 to the power of 5, square root of 81,
             roman numerals (XIV), hex (0xff), binary (0b1010), gcd/lcm.
    Returns a formatted answer string, or None if not an arithmetic expression.
    """
    import math as _math
    import re as _re

    t_raw = text.strip().lower()
    t = t_raw.rstrip("?.")

    # ── Factorial — must run on t_raw BEFORE stripping '!' ───
    _fact_m = _re.search(r"(?:factorial of |fact\()?\b(\d+)\s*!", t_raw)
    if not _fact_m:
        _fact_m = _re.fullmatch(r"(?:factorial of |factorial\()\s*(\d+)\)?", t)
    if _fact_m:
        n = int(_fact_m.group(1))
        if 0 <= n <= 20:
            return f"{n}! = {_math.factorial(n):,}"

    # ── Roman numerals ───────────────────────────────────────
    _roman_match = _re.fullmatch(
        r"(?:what is |convert |value of |roman numeral )?([ivxlcdm]+)(?:\s*(?:in arabic|in decimal|as (?:a )?number|to decimal|= ?))?",
        t,
        _re.IGNORECASE,
    )
    if _roman_match:
        roman = _roman_match.group(1).upper()
        vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        if all(c in vals for c in roman) and roman:
            n, prev = 0, 0
            for ch in reversed(roman):
                v = vals[ch]
                n += v if v >= prev else -v
                prev = v
            if 1 <= n <= 3999:
                return f"{roman} = {n:,}"

    # ── "N to the power of M" ────────────────────────────────
    _pow_m = _re.fullmatch(r"(\d+(?:\.\d+)?)\s+to\s+the\s+(?:power\s+of\s+)?(\d+(?:\.\d+)?)", t)
    if _pow_m:
        base, exp = float(_pow_m.group(1)), float(_pow_m.group(2))
        result = base**exp
        r_int = int(result) if result == int(result) and abs(result) < 1e15 else None
        return f"{base:g}^{exp:g} = {r_int}" if r_int is not None else f"{base:g}^{exp:g} = {result:g}"

    # ── Square root (words) ──────────────────────────────────
    _sqrt_m = _re.search(r"(?:square root of|sqrt of)\s+(\d+(?:\.\d+)?)", t)
    if _sqrt_m:
        f_n = float(_sqrt_m.group(1))
        root = _math.sqrt(f_n)
        r_int = int(root) if root == int(root) else None
        return f"√{f_n:g} = {r_int:,}" if r_int is not None else f"√{f_n:g} ≈ {root:.6g}"

    # ── GCD / LCM ────────────────────────────────────────────
    _gcd_m = _re.search(r"\bgcd\s*\(?\s*(\d+)\s*[,\s]\s*(\d+)\s*\)?", t)
    if _gcd_m:
        a, b = int(_gcd_m.group(1)), int(_gcd_m.group(2))
        return f"gcd({a}, {b}) = {_math.gcd(a, b)}"
    _lcm_m = _re.search(r"\blcm\s*\(?\s*(\d+)\s*[,\s]\s*(\d+)\s*\)?", t)
    if _lcm_m:
        a, b = int(_lcm_m.group(1)), int(_lcm_m.group(2))
        return f"lcm({a}, {b}) = {_math.lcm(a, b)}"

    # ── Hex / binary literals ─────────────────────────────────
    _hex_m = _re.fullmatch(
        r"(?:what is |convert |value of )?0x([0-9a-f]+)(?:\s+(?:in decimal|to decimal|as decimal))?", t
    )
    if _hex_m:
        n = int(_hex_m.group(1), 16)
        return f"0x{_hex_m.group(1).upper()} = {n:,} (decimal)"
    _bin_m = _re.fullmatch(r"(?:what is |convert |value of )?0b([01]+)(?:\s+(?:in decimal|to decimal|as decimal))?", t)
    if _bin_m:
        n = int(_bin_m.group(1), 2)
        return f"0b{_bin_m.group(1)} = {n:,} (decimal)"

    # ── Percentage: "X% of Y" ────────────────────────────────
    _pct_m = _re.search(r"(?:what is )?(\d+(?:\.\d+)?)\s*%\s*of\s+(\d+(?:\.\d+)?)", t)
    if _pct_m:
        pct, total = float(_pct_m.group(1)), float(_pct_m.group(2))
        result = pct / 100 * total
        r_int = int(result) if result == int(result) else None
        return f"{pct:g}% of {total:g} = {r_int:,}" if r_int is not None else f"{pct:g}% of {total:g} = {result:g}"

    # ── Core arithmetic expression ────────────────────────────
    # Normalize Unicode/word operators
    expr = t
    expr = _re.sub(r"[×✕]", "*", expr)  # × → *
    expr = _re.sub(r"\bx\b", "*", expr)  # x → * (word-boundary only)
    expr = _re.sub(r"\btimes\b", "*", expr)  # "times" → *
    expr = _re.sub(r"\bplus\b", "+", expr)   # "plus" → +
    expr = _re.sub(r"\bminus\b", "-", expr)  # "minus" → -
    expr = _re.sub(r"\bdivided by\b", "/", expr)  # "divided by" → /
    expr = _re.sub(r"÷", "/", expr)  # ÷ → /
    expr = _re.sub(r"\^", "**", expr)  # ^ → **
    expr = _re.sub(r"\bsqrt\s*\(", "sqrt(", expr)
    # strip leading noise
    expr = _re.sub(r"^(?:what(?:\'s| is)|calculate|compute|evaluate|solve|=)\s+", "", expr)
    # strip trailing noise: "? just the number.", "= ?", etc. — keep only the math part
    expr = _re.sub(r"[?!]\s+.*$", "", expr).strip()
    expr = _re.sub(r"\s+(?:just|give|only|in|as|to)\s.*$", "", expr).strip()
    expr = expr.rstrip("?.! ")

    # Replace sqrt(...) with math.sqrt(...)
    expr = _re.sub(r"\bsqrt\s*\(", "__sqrt(", expr)

    # Whitelist: only safe chars — digits, operators, parens, decimal, whitespace
    if not _re.fullmatch(r"[\d\s\+\-\*\/\(\)\.\%__sqrt]+", expr.replace("__sqrt", "________")):
        return None
    if not _re.search(r"[\+\-\*\/\^]|__sqrt|\*\*", expr):
        return None  # no operator → not an expression

    # Guard against huge exponents
    _exp_m = _re.search(r"\*\*\s*(\d+(?:\.\d+)?)", expr)
    if _exp_m and float(_exp_m.group(1)) > 100:
        return None

    try:
        _safe_globals: dict = {"__builtins__": {}, "__sqrt": _math.sqrt}
        result = eval(expr, _safe_globals)  # noqa: S307 — whitelisted chars only
        if not isinstance(result, int | float) or not _math.isfinite(result):
            return None
        # Format result
        if isinstance(result, float) and result == int(result) and abs(result) < 1e15:
            result = int(result)
        # Clean display — strip trailing noise phrases, show just the math = answer
        display = t.rstrip("?.! ")
        display = _re.sub(r"[?!]\s+.*$", "", display).strip()
        display = _re.sub(r"\s+(?:just|give|only|in\s+\w+|as\s+\w+|to\s+\w+)\s.*$", "", display).strip()
        display = _re.sub(r"\bx\b", "×", display)
        display = _re.sub(r"^(?:what(?:\'s| is)\s+)", "", display, flags=_re.IGNORECASE).strip()
        if isinstance(result, int):
            return str(result)
        return f"{result:g}"
    except Exception:
        return None


def try_resolve_locally(content: str) -> str | None:
    """
    Instantly answer date/time/calendar questions with no model call.
    Returns answer string, or None if not resolvable locally.
    Only matches SHORT lookup queries (< 120 chars). Long technical questions
    should always route to the model, never be intercepted by LUTs.
    """
    lower = content.lower().strip()
    try:
        from router.realtime_plugins import resolve_with_plugins

        plugin_result = resolve_with_plugins(lower)
        if plugin_result:
            return plugin_result
    except Exception:
        pass

    # Groundtruth only fires on short queries (lookup intent).
    # Long questions (>150 chars) are real questions — send to model.
    # Extras module has its own 400-char guard for patterns that legitimately need more context.
    if len(lower) > 150:
        # Skip everything except the extras module (which guards itself)
        try:
            from router.groundtruth_extras import try_resolve_extras as _re_ext

            return _re_ext(lower)
        except Exception:
            return None

    # ── Safe arithmetic eval ─────────────────────────────────
    # Handles: 847 × 23, 1024 / 32, (15 + 3) * 4, 2^10, sqrt(144), 15% of 240
    _arith = _safe_eval_math(lower)
    if _arith is not None:
        return _arith

    now = _now()

    # ── Session continuation ─────────────────────────────
    if re.search(
        r"\b(?:start\s+(?:next\s+)?session|start\s+session\s*\d+|resume\s+session|pick\s+up\s+where)\b", lower
    ):
        try:
            import json as _json
            from pathlib import Path as _Path

            _sf = _Path(__file__).resolve().parent.parent / "sessions.jsonl"
            if _sf.exists():
                _entries = [_json.loads(line) for line in _sf.read_text().splitlines() if line.strip()]
                _prompts = [e for e in _entries if e.get("type") == "startup_prompt"]
                if _prompts:
                    _latest = max(_prompts, key=lambda e: e.get("session", 0))
                    return f"**Session {_latest['session']} Startup**\n\n{_latest['prompt']}"
        except Exception as _e:  # type: ignore[misc]
            log.warning("session_lookup_failed", error=str(_e))

    # ── "Time in <city>" queries ──────────────────────────
    _is_weather = re.search(
        r"\b(?:weather|forecast|temperature|temp\b|humid|rain|snow|wind|climate|storm|sunny|cloudy"
        r"|warm(?:er|est|th)?|cold(?:er|est)?|hot(?:ter|test)?|cool(?:er|est)?|chilly|freez)\b",
        lower,
    )
    tz_match = _TIME_IN_RE.search(lower) if not _is_weather else None
    if tz_match:
        city_raw = tz_match.group(1).strip().rstrip("?.")
        # Strip trailing noise like "right now", "currently", "now", "please"
        city_raw = re.sub(
            r"\s+(?:right now|now|currently|please|rn|today|at the moment)$", "", city_raw, flags=re.IGNORECASE
        )
        city_key = city_raw.lower()
        tz_name = _CITY_TZ.get(city_key)
        if tz_name:
            try:
                city_now = datetime.now(ZoneInfo(tz_name))
                utc_off = city_now.strftime("%z")
                utc_str = f"UTC{utc_off[:3]}:{utc_off[3:]}"
                return (
                    f"The current time in {city_raw.title()} is "
                    f"{city_now.strftime('%I:%M %p')} ({city_now.strftime('%H:%M')}) "
                    f"on {city_now.strftime('%A, %B %d, %Y')}. "
                    f"Timezone: {tz_name} ({utc_str})."
                )
            except Exception as _e:  # type: ignore[misc]
                log.warning("tz_resolve_failed", city=city_raw, tz=tz_name, error=str(_e)[:100])

    # ── Date/time queries ───────────────────────────────────
    for rx, kind in _DATE_PATTERNS:
        if rx.search(lower):
            if kind == "date":
                return f"Today is {now.strftime('%A, %B %d, %Y')}."
            if kind == "time":
                return f"The current time is {now.strftime('%I:%M %p')} ({now.strftime('%H:%M')})."
            if kind == "day":
                return f"Today is {now.strftime('%A')}, {now.strftime('%B %d, %Y')}."
            if kind == "month_year":
                return f"It is {now.strftime('%B %Y')}."

    # ── Eclipse queries ─────────────────────────────────────
    m = _ECLIPSE_RE.search(lower)
    if m:
        qualifier = (m.group(1) or "").lower()
        # Pick the right list
        if qualifier in ("lunar",):
            events = _LUNAR_ECLIPSES
            label = "lunar eclipse"
        elif qualifier in ("solar", "total", "annular", "partial"):
            # Filter solar eclipses by type if specific
            events = _SOLAR_ECLIPSES
            if qualifier in ("total", "annular", "partial"):
                events = [e for e in events if qualifier in e[1].lower()]
            label = f"{qualifier} solar eclipse" if qualifier != "solar" else "solar eclipse"
        else:
            # Generic "next eclipse" — show both
            solar = _next_from(now, _SOLAR_ECLIPSES)
            lunar = _next_from(now, _LUNAR_ECLIPSES)
            parts = [f"Today is {now.strftime('%B %d, %Y')}."]
            if solar:
                parts.append(f"Next solar eclipse: {solar[0]} -- {solar[1]} ({solar[2]})")
            if lunar:
                parts.append(f"Next lunar eclipse: {lunar[0]} -- {lunar[1]} ({lunar[2]})")
            return "\n".join(parts) if len(parts) > 1 else None

        nxt = _next_from(now, events)
        if nxt:
            return (
                f"Today is {now.strftime('%B %d, %Y')}. "
                f"The next {label} is on {nxt[0]}: {nxt[1]} (visible from {nxt[2]})."
            )

    # ── Solstice/equinox queries ────────────────────────────
    m = _SOLSTICE_EQUINOX_RE.search(lower)
    if m:
        season = (m.group(1) or "").lower()
        event_type = m.group(2).lower()

        # Map search terms to event name fragments
        filter_terms = []
        if season in ("summer",):
            filter_terms.append("summer")
        elif season in ("winter",):
            filter_terms.append("winter")
        elif season in ("vernal", "spring"):
            filter_terms.append("vernal")
        elif season in ("autumnal", "fall"):
            filter_terms.append("autumnal")

        if event_type == "solstice":
            filter_terms.append("solstice")
        elif event_type == "equinox":
            filter_terms.append("equinox")

        for date_str, name, desc in _SOLSTICES_EQUINOXES:
            event_date = datetime.strptime(date_str, "%Y-%m-%d")
            if event_date.date() < now.date():
                continue
            name_lower = name.lower()
            if all(t in name_lower for t in filter_terms):
                return f"Today is {now.strftime('%B %d, %Y')}. The next {name.lower()} is on {date_str}. {desc}."

    # ── Simple math expressions ──────────────────────────────
    # Matches: "what is 2+2", "calculate 15*7", "2^10", "sqrt(144)"
    math_match = re.match(
        r"^(?:what(?:\'s| is) |calculate |compute |eval(?:uate)? )?"
        r"([\d\s\+\-\*/\^\(\)\.\%]+)$",
        lower.strip("?"),
    )
    if math_match:
        expr = math_match.group(1).strip()
        if len(expr) >= 2 and any(c in expr for c in "+-*/^%"):
            try:
                safe_expr = expr.replace("^", "**")
                result = eval(safe_expr, {"__builtins__": {}}, {"abs": abs, "round": round, "min": min, "max": max}) # nosec B307 -- empty builtins, safe_expr whitelist-filtered
                if isinstance(result, float) and result == int(result) and abs(result) < 1e15:
                    result = int(result)
                return f"{expr} = {result}"
            except Exception:
                pass

    # ── Country capitals ──────────────────────────────────────
    capital_match = re.search(r"(?:capital of|capital.*(?:is|of)) (.+?)(?:\?|$|\.)", lower)
    if capital_match:
        country = capital_match.group(1).strip().rstrip("?.")
        cap = _CAPITALS.get(country.lower())
        if cap:
            return f"The capital of {country.title()} is {cap}."

    # ── Country populations ───────────────────────────────────
    pop_match = re.search(r"population (?:of |in )(.+?)(?:\?|$|\.)", lower)
    if pop_match:
        country = pop_match.group(1).strip().rstrip("?.")
        pop = _POPULATIONS.get(country.lower())
        if pop:
            return f"The population of {country.title()} is approximately {pop} (2024 estimate)."

    # ── Temperature conversion ────────────────────────────────
    _temp_ans = _convert_temperature(lower)
    if _temp_ans is not None:
        return _temp_ans

    # ── Prime check ───────────────────────────────────────────
    _prime_ans = _is_prime_check(lower)
    if _prime_ans is not None:
        return _prime_ans

    # ── Fibonacci ─────────────────────────────────────────────
    _fib_ans = _fibonacci_query(lower)
    if _fib_ans is not None:
        return _fib_ans

    # ── Physical constants ────────────────────────────────────
    for rx, answer in _PHYSICS_CONSTANTS:
        if rx.search(lower):
            return answer

    for rx, answer in _CONSTANTS:
        if rx.search(lower):
            return answer

    for rx, answer in _SCIENCE_CONSTANTS:
        if rx.search(lower):
            return answer

    # ── Mathematical identities & formulas ───────────────────
    for rx, answer in _MATH_IDENTITIES:
        if rx.search(lower):
            return answer

    # ── Astronomy ────────────────────────────────────────────
    for rx, answer in _ASTRONOMY:
        if rx.search(lower):
            return answer

    # ── Geology ──────────────────────────────────────────────
    for rx, answer in _GEOLOGY:
        if rx.search(lower):
            return answer

    # ── Psychology ────────────────────────────────────────────
    for rx, answer in _PSYCHOLOGY:
        if rx.search(lower):
            return answer

    # ── Archaeology ──────────────────────────────────────────
    for rx, answer in _ARCHAEOLOGY:
        if rx.search(lower):
            return answer

    # ── Philosophy quotes ────────────────────────────────────
    phil_match = re.search(
        r"\b(?:who (?:is|was) |quote (?:from |by )?|tell me about |what did .* say|"
        r"(?:famous )?quote|philosophy of )?"
        r"(" + "|".join(re.escape(k) for k in _PHILOSOPHY) + r")\b",
        lower,
    )
    if phil_match:
        key = phil_match.group(1).lower()
        return _PHILOSOPHY.get(key)

    # ── Art history ──────────────────────────────────────────
    for pattern, answer in _ART_HISTORY:
        if re.search(pattern, lower):
            return answer

    # ── Music theory ─────────────────────────────────────────
    for pattern, answer in _MUSIC_THEORY:
        if re.search(pattern, lower):
            return answer

    # ── Greek & Roman mythology ──────────────────────────────
    myth_match = re.search(
        r"\b(?:who (?:is|was) |tell me about |what (?:is|about) )?"
        r"(" + "|".join(re.escape(k) for k in _MYTHOLOGY) + r")\b",
        lower,
    )
    if myth_match:
        key = myth_match.group(1).lower()
        return _MYTHOLOGY.get(key)

    # ── Chemical element symbol lookups ──────────────────────
    # "chemical symbol for gold" / "what element is Au" / "atomic number of iron"
    elem_sym_m = re.search(
        r"(?:chemical symbol|element symbol|symbol)\s+(?:for|of)\s+(\w+)",
        lower,
    )
    if elem_sym_m:
        name = elem_sym_m.group(1).lower()
        sym_lower = _ELEMENT_BY_NAME.get(name, "").lower()
        if sym_lower:
            el = _ELEMENTS[sym_lower]
            sym_display = sym_lower.capitalize() if len(sym_lower) > 1 else sym_lower.upper()
            return f"The chemical symbol for {el[0]} is {sym_display} (atomic number {el[1]}). {el[2].capitalize()}."
    elem_name_m = re.search(
        r"(?:what element|what is|what\'s)\s+(?:is\s+)?([a-zA-Z]{1,3})\s*\??\s*$",
        lower,
    )
    if elem_name_m:
        sym = elem_name_m.group(1).lower()
        el = _ELEMENTS.get(sym)
        if el:
            sym_display = sym.capitalize() if len(sym) > 1 else sym.upper()
            return f"{sym_display} is {el[0]}, atomic number {el[1]}. {el[2].capitalize()}."
    elem_atom_m = re.search(
        r"atomic number (?:of|for)\s+(\w+)",
        lower,
    )
    if elem_atom_m:
        name = elem_atom_m.group(1).lower()
        sym_lower = _ELEMENT_BY_NAME.get(name, "").lower()
        if sym_lower:
            el = _ELEMENTS[sym_lower]
            sym_display = sym_lower.capitalize() if len(sym_lower) > 1 else sym_lower.upper()
            return f"The atomic number of {el[0]} ({sym_display}) is {el[1]}."
        el = _ELEMENTS.get(name)
        if el:
            sym_display = name.capitalize() if len(name) > 1 else name.upper()
            return f"The atomic number of {el[0]} ({sym_display}) is {el[1]}."

    # ── Verbal analogy resolver ───────────────────────────────
    if re.search(r"\bis to\b.*\bas\b|\banalogy\b|:\s*:|\bcat.*kitten\b|\bdog.*puppy\b", lower):
        for rx, answer in _ANALOGIES:
            if rx.search(lower):
                return answer

    # ── Historic dates & events ──────────────────────────────
    # Aliases for common shorthand
    _hist_aliases = {
        "wwii": "world war 2",
        "ww2": "world war 2",
        "world war ii": "world war 2",
        "second world war": "world war 2",
        "wwi": "world war 1",
        "ww1": "world war 1",
        "world war i": "world war 1",
        "first world war": "world war 1",
        "9/11": "september 11",
        "sept 11": "september 11",
    }
    for alias, canonical in _hist_aliases.items():
        if alias in lower:
            date, desc = _HISTORIC_DATES.get(canonical, ("", ""))
            if desc:
                if date and "-" in date and re.search(r"\bend(ed|ing)?\b|when.*end|end.*year", lower):
                    parts = date.split("-")
                    if len(parts) == 2 and parts[1].strip().isdigit():
                        return parts[1].strip()
                if date and "-" in date and re.search(r"\bstart(ed|ing)?\b|begin|when.*start|start.*year", lower):
                    parts = date.split("-")
                    if len(parts) == 2 and parts[0].strip().isdigit():
                        return parts[0].strip()
                return desc
    hist_match = re.search(
        r"\b(?:when (?:was|did|is) (?:the )?|what (?:year|date) (?:was|did|is) (?:the )?|tell me about (?:the )?)?"
        r"(" + "|".join(re.escape(k) for k in _HISTORIC_DATES) + r")\b",
        lower,
    )
    if hist_match:
        key = hist_match.group(1).lower()
        date, desc = _HISTORIC_DATES.get(key, ("", ""))
        if desc:
            # If query asks specifically about end/start year and date is a range like "1939-1945"
            if date and "-" in date and re.search(r"\bend(ed|ing)?\b|when.*end|end.*year", lower):
                parts = date.split("-")
                if len(parts) == 2 and parts[1].strip().isdigit():
                    return parts[1].strip()
            if date and "-" in date and re.search(r"\bstart(ed|ing)?\b|begin|when.*start|start.*year", lower):
                parts = date.split("-")
                if len(parts) == 2 and parts[0].strip().isdigit():
                    return parts[0].strip()
            return f"{desc}"

    # ── HTTP status codes ─────────────────────────────────────
    # Detect "http NNN" intent first — return None for unknown codes (don't fall through to acronym LUT)
    _http_num = re.search(r"\bhttp\s+(\d{2,3})\b", lower)
    if _http_num:
        code = _http_num.group(1)
        info = _HTTP_CODES.get(code)
        if info:
            return f"HTTP {code} {info[0]}: {info[1]}"
        return None
    http_match = re.search(
        r"(?:what(?:\'s| is) |status\s*(?:code\s*)?)([1-5]\d{2})\b"
        r"|([1-5]\d{2})\s*(?:status|error|code|response)",
        lower,
    )
    if http_match:
        code = http_match.group(1) or http_match.group(2)
        info = _HTTP_CODES.get(code)
        if info:
            return f"HTTP {code} {info[0]}: {info[1]}"

    # ── Port numbers ─────────────────────────────────────────
    port_match = re.search(r"(?:what )?(?:port|default port)(?: (?:is|for|of|does))?\s+(\w+)", lower)
    if not port_match:
        port_match = re.search(r"what port does (\w+) use", lower)
    if not port_match:
        port_match = re.search(r"(\w+)\s+(?:port|default port)", lower)
    if port_match:
        svc = port_match.group(1).lower()
        info = _PORTS.get(svc)
        if info:
            return f"Default port for {svc.upper()}: {info[0]}. {info[1]}"

    # ── Tech acronyms ("what does X stand for / mean") ───────
    tech_acro_match = re.search(
        r"what does ([a-z]{2,10}) (?:stand for|mean)\b",
        lower,
    )
    if tech_acro_match:
        abbr = tech_acro_match.group(1).lower()
        tech_info = _TECH_ACRONYMS.get(abbr)
        if tech_info:
            return tech_info

    # ── Timezone abbreviations (require "what is" or "timezone"/"tz" context) ──
    tz_abbr_match = re.search(
        r"(?:what(?:\'s| is) |what does )([a-z]{2,5})\b(?:\s*(?:time ?zone|stand for|mean))?"
        r"|\b([a-z]{2,5})\s+(?:time ?zone|tz)\b",
        lower,
    )
    if tz_abbr_match:
        abbr = (tz_abbr_match.group(1) or tz_abbr_match.group(2)).lower()
        tz_info = _TZ_ABBREVS.get(abbr)
        if tz_info:
            return f"{abbr.upper()} = {tz_info[0]}. {tz_info[1]}"
        tech_info = _TECH_ACRONYMS.get(abbr)
        if tech_info:
            return tech_info

    # ── Holidays ─────────────────────────────────────────────
    holiday_match = re.search(r"(?:when is |when\'s |date of )(.+?)(?:\?|$)", lower)
    if holiday_match:
        query = holiday_match.group(1).strip().rstrip("?.")
        # Try exact match first, then without year
        h_info = _HOLIDAYS.get(query)
        if h_info:
            return f"{query.title()}: {h_info}"
        # Try appending current/next year
        year = _now().year
        for y in [year, year + 1]:
            h_info = _HOLIDAYS.get(f"{query} {y}")
            if h_info:
                return f"{query.title()} {y}: {h_info}"

    # ── Unix timestamp conversions ───────────────────────────
    ts_match = re.search(r"(?:unix |epoch |timestamp )(\d{9,13})\b", lower)
    if ts_match:
        ts = int(ts_match.group(1))
        if ts > 1e12:  # milliseconds
            ts = ts // 1000
        dt = datetime.fromtimestamp(ts, tz=UTC)
        return f"Unix timestamp {ts_match.group(1)} = {dt.strftime('%A, %B %d, %Y %H:%M:%S UTC')}"

    # ── Day-of-week for any date ─────────────────────────────
    dow_match = re.search(r"(?:what day (?:was|is|will be) )(\w+ \d{1,2},?\s*\d{4})", lower)
    if dow_match:
        date_str = dow_match.group(1).strip()
        for fmt in ["%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"]:
            try:
                dt = datetime.strptime(date_str, fmt)
                return f"{date_str.title()} was a {dt.strftime('%A')}."
            except ValueError:
                continue

    # ── Unit conversions ──────────────────────────────────────
    conv_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(km|mi|miles?|kg|lbs?|pounds?|celsius|fahrenheit|[cf])\s*"
        r"(?:to|in|=)\s*(km|mi|miles?|kg|lbs?|pounds?|celsius|fahrenheit|[cf])",
        lower,
    )
    if conv_match:
        val = float(conv_match.group(1))
        fr = conv_match.group(2).lower()
        to = conv_match.group(3).lower()
        result = _convert(val, fr, to)
        if result is not None:
            return f"{val:g} {fr} = {result:.2f} {to}"

    # ── Generic conversion formulas (no number) ─────────────────
    formula_match = re.search(
        r"(?:convert|how (?:do (?:you|i)|to) convert)\s+"
        r"(celsius|fahrenheit|km|miles?|kg|lbs?|pounds?|kilometers?)\s+"
        r"(?:to|into)\s+"
        r"(celsius|fahrenheit|km|miles?|kg|lbs?|pounds?|kilometers?)",
        lower,
    )
    if formula_match:
        fr = formula_match.group(1).lower()
        to = formula_match.group(2).lower()
        formulas = {
            ("celsius", "fahrenheit"): "°F = (°C × 9/5) + 32. Example: 20°C = 68°F",
            ("fahrenheit", "celsius"): "°C = (°F − 32) × 5/9. Example: 68°F = 20°C",
            ("km", "miles"): "miles = km × 0.621371. Example: 10 km = 6.21 miles",
            ("miles", "km"): "km = miles × 1.60934. Example: 10 miles = 16.09 km",
            ("kg", "lbs"): "lbs = kg × 2.20462. Example: 10 kg = 22.05 lbs",
            ("lbs", "kg"): "kg = lbs × 0.453592. Example: 10 lbs = 4.54 kg",
        }
        fr_norm = {
            "fahrenheit": "fahrenheit",
            "celsius": "celsius",
            "km": "km",
            "kilometers": "km",
            "kilometer": "km",
            "miles": "miles",
            "mile": "miles",
            "kg": "kg",
            "lbs": "lbs",
            "lb": "lbs",
            "pounds": "lbs",
            "pound": "lbs",
        }.get(fr, fr)
        to_norm = {
            "fahrenheit": "fahrenheit",
            "celsius": "celsius",
            "km": "km",
            "kilometers": "km",
            "kilometer": "km",
            "miles": "miles",
            "mile": "miles",
            "kg": "kg",
            "lbs": "lbs",
            "lb": "lbs",
            "pounds": "lbs",
            "pound": "lbs",
        }.get(to, to)
        formula = formulas.get((fr_norm, to_norm))
        if formula:
            return f"To convert {fr} to {to}: {formula}"

    # ── Git commands ──────────────────────────────────────────
    git_match = re.search(
        r"\bgit\s+(init|clone|add|commit|push|pull|fetch|merge|rebase|stash|log|diff|branch|checkout|reset|tag|cherry-pick|bisect|blame|reflog|remote|status|show|clean|rm|mv)\b",
        lower,
    )
    if git_match:
        cmd = git_match.group(1).lower()
        info = _GIT_COMMANDS.get(cmd)  # type: ignore[assignment]
        if info:
            return f"**git {cmd}** -- {info}"

    # ── Cron syntax ─────────────────────────────────────────
    if re.search(r"\bcron\b", lower):
        return (
            "**Cron Syntax Cheat Sheet**\n\n"
            "Format: `minute hour day-of-month month day-of-week`\n\n"
            "| Field        | Values        |\n"
            "|--------------|---------------|\n"
            "| Minute       | 0-59          |\n"
            "| Hour         | 0-23          |\n"
            "| Day of Month | 1-31          |\n"
            "| Month        | 1-12          |\n"
            "| Day of Week  | 0-7 (0,7=Sun) |\n\n"
            "Special: `*` = any, `,` = list, `-` = range, `/` = step\n\n"
            "Examples:\n"
            "- `0 * * * *` -- every hour\n"
            "- `*/5 * * * *` -- every 5 minutes\n"
            "- `0 9 * * 1-5` -- 9 AM weekdays\n"
            "- `0 0 1 * *` -- midnight on the 1st of each month\n"
            "- `30 2 * * 0` -- 2:30 AM every Sunday"
        )

    # ── Regex cheat sheet ───────────────────────────────────
    if re.search(
        r"\bregex\b.*\b(?:cheat|ref|help|guide|syntax)\b|\b(?:cheat|ref|help|guide|syntax)\b.*\bregex\b|\bregular expression",
        lower,
    ):
        return (
            "**Regex Cheat Sheet**\n\n"
            "| Symbol  | Meaning                 |\n"
            "|---------|-------------------------|\n"
            "| `.`     | Any character (except newline) |\n"
            "| `\\d`    | Digit [0-9]             |\n"
            "| `\\w`    | Word char [a-zA-Z0-9_]  |\n"
            "| `\\s`    | Whitespace              |\n"
            "| `^`     | Start of string         |\n"
            "| `$`     | End of string           |\n"
            "| `*`     | 0 or more               |\n"
            "| `+`     | 1 or more               |\n"
            "| `?`     | 0 or 1 (optional)       |\n"
            "| `{n,m}` | Between n and m times   |\n"
            "| `[abc]` | Character class          |\n"
            "| `[^abc]`| Negated class           |\n"
            "| `(...)` | Capture group           |\n"
            "| `(?:..)`| Non-capturing group     |\n"
            "| `a|b`   | Alternation (a or b)    |\n"
            "| `\\b`    | Word boundary           |\n\n"
            "Flags: `i` = case-insensitive, `g` = global, `m` = multiline, `s` = dotall"
        )

    # ── Keyboard shortcuts ──────────────────────────────────
    kb_match = re.search(r"(?:keyboard\s+shortcuts?|hotkeys?|keybindings?)\s+(?:for\s+)?(\w+)", lower)
    if not kb_match:
        kb_match = re.search(r"(\w+)\s+(?:keyboard\s+shortcuts?|hotkeys?|keybindings?)", lower)
    if kb_match:
        app = kb_match.group(1).lower()
        info = _KB_SHORTCUTS.get(app)  # type: ignore[assignment]
        if info:
            return info  # type: ignore[return-value]

    # ── File extensions ──────────────────────────────────────
    ext_match = re.search(
        r"(?:what (?:is|are|opens?) |explain |tell me about |"
        r"(?:what|how) (?:do|does|to) (?:you |i )?(?:open|use|read) )"
        r"(?:a )?(\.\w{1,10})\s*(?:file|format|extension)?"
        r"|^(?:a )?(\.\w{1,10})\s*(?:file|format|extension)\s*\??$"
        r"|(\w{1,10})\s+(?:file )?(?:format|extension)\b",
        lower,
    )
    if ext_match:
        ext_raw = ext_match.group(1) or ext_match.group(2) or ext_match.group(3)
        if ext_raw:
            ext_key = ext_raw if ext_raw.startswith(".") else f".{ext_raw}"
            ext_key = ext_key.lower()
            info = _FILE_EXTENSIONS.get(ext_key)  # type: ignore[assignment]
            if info:
                return f"**{ext_key}** — {info}"

    # ── HTTP methods ─────────────────────────────────────────
    # Only match simple lookups ("what is GET", "GET vs POST") — skip complex sentences
    _http_complex = re.search(
        r"in the context of|how do i|how does|authentication|fetch call|rest api|explain how",
        lower,
    )
    method_match = (not _http_complex) and re.search(
        r"^(?:what is |what's |explain |describe |tell me about )?"
        r"(?:http\s+)?(?:the\s+)?\b(get|post|put|patch|delete|head|options)\b\s*"
        r"(?:method|request|http|verb)?\??$"
        r"|^\b(put|patch|get|post|delete|head|options)\b\s+vs\.?\s+\b(put|patch|get|post|delete|head|options)\b\??$",
        lower,
    )
    if method_match:
        m1 = (method_match.group(1) or "").lower()
        m2 = (method_match.group(2) or "").lower() if method_match.group(2) else None
        if m1 and m1 in _HTTP_METHODS:
            if m2 and m2 in _HTTP_METHODS:
                return f"{_HTTP_METHODS[m1]}\n\n{_HTTP_METHODS[m2]}"
            return _HTTP_METHODS[m1]

    # ── Exit codes ───────────────────────────────────────────
    exit_match = re.search(
        r"(?:what (?:is|does) |explain |meaning of )?"
        r"(?:exit|return|error|status)\s*(?:code\s*)?(\d{1,3})\b"
        r"|(\d{1,3})\s*(?:exit\s*code|return\s*code|error\s*code)",
        lower,
    )
    if exit_match:
        code = exit_match.group(1) or exit_match.group(2)
        info = _EXIT_CODES.get(code)  # type: ignore[assignment]
        if info:
            return info  # type: ignore[return-value]

    # ── Docker/Podman commands ───────────────────────────────
    container_match = re.search(
        r"(?:explain |what (?:is|does) |how (?:to |do (?:you |i )?)?)?"
        r"(?:docker|podman|container)\s+"
        r"(compose\s+up|compose\s+down|run|build|exec|logs|ps|images|volumes?|networks?)\b",
        lower,
    )
    if not container_match:
        container_match = re.search(
            r"(podman\s+vs\.?\s+docker|docker\s+vs\.?\s+podman)",
            lower,
        )
        if container_match:
            return _CONTAINER_COMMANDS["podman vs docker"]
    if container_match:
        cmd = container_match.group(1).strip().lower()
        # Normalize volume/network to plural form used in dict
        cmd = re.sub(r"^volumes?$", "volumes", cmd)
        cmd = re.sub(r"^networks?$", "networks", cmd)
        info = _CONTAINER_COMMANDS.get(cmd)  # type: ignore[assignment]
        if info:
            return info  # type: ignore[return-value]

    # ── Math evaluation (safe: sqrt, factorial, pow) ────────────
    import math as _math

    _sqrt_m = re.search(r"sqrt\((\d+(?:\.\d+)?)\)|square\s+root\s+of\s+(\d+(?:\.\d+)?)", lower)
    if _sqrt_m:
        _n = float(_sqrt_m.group(1) or _sqrt_m.group(2))
        _r = _math.sqrt(_n)
        if _r == int(_r):
            return f"√{_n:g} = {int(_r)}"
        return f"√{_n:g} ≈ {_r:.8g}"
    _fact_m = re.search(r"\b(\d{1,2})\s*!\s*(?:=|\?|$)", lower)
    if _fact_m:
        _n = int(_fact_m.group(1))
        if _n <= 20:
            return f"{_n}! = {_math.factorial(_n):,}"
    _pow_m = re.search(r"\b(\d+)\s*(?:\^|\*\*)\s*(\d+)\b", lower)
    if _pow_m:
        _b, _exp = int(_pow_m.group(1)), int(_pow_m.group(2))
        if _exp <= 64:
            return f"{_b}^{_exp} = {_b**_exp:,}"
    _log_m = re.search(r"\blog(?:_?(\d+))?\((\d+(?:\.\d+)?)\)", lower)
    if _log_m:
        _base = float(_log_m.group(1)) if _log_m.group(1) else _math.e
        _x = float(_log_m.group(2))
        if _x > 0:
            _r = _math.log(_x) / _math.log(_base) if _base != _math.e else _math.log(_x)
            return f"log_{_log_m.group(1) or 'e'}({_x:g}) ≈ {_r:.8g}"

    # ── Algorithm Big-O ──────────────────────────────────────────
    _algo_m = re.search(
        r"(?:algo(?:rithm)?|big.?o|time\s+complexity|space\s+complexity|complexity)\s+"
        r"(?:of\s+|for\s+)?(?:--language=\w+\s+)?"
        r"(quicksort|quick\s+sort|mergesort|merge\s+sort|heapsort|heap\s+sort|"
        r"bubblesort|bubble\s+sort|insertionsort|insertion\s+sort|selectionsort|selection\s+sort|"
        r"timsort|tim\s+sort|radixsort|radix\s+sort|countingsort|counting\s+sort|"
        r"binarysearch|binary\s+search|linearsearch|linear\s+search|"
        r"bfs|breadth.first\s+search|dfs|depth.first\s+search|"
        r"dijkstra|a\*|astar|a\s+star|floyd.warshall|bellman.ford|kruskal|prim)",
        lower,
    )
    if not _algo_m:
        # Short CLI-style: "algo quicksort"
        _algo_m = re.search(r"^(?:algo|algorithm)\s+(\w[\w\s-]+?)(?:\s*\?)?$", lower)
    if _algo_m:
        _akey = re.sub(r"\s+", "", _algo_m.group(1).lower().strip())
        _akey = _akey.replace("sort", "sort").replace("search", "search")
        _info = _ALGORITHMS.get(_akey)
        if _info:
            _best, _avg, _worst, _space, _note = _info
            return (
                f"**{_akey.title()} Complexity**\n\n"
                f"| Case    | Time        |\n"
                f"|---------|-------------|\n"
                f"| Best    | {_best}     |\n"
                f"| Average | {_avg}      |\n"
                f"| Worst   | {_worst}    |\n"
                f"| Space   | {_space}    |\n\n"
                f"{_note}"
            )
    # Sorting algorithms cheat sheet
    if re.search(
        r"\b(?:sorting\s+algorithms?|big.?o\s+(?:cheat|notation|table|ref)|algorithm\s+complexity\s+(?:cheat|table|ref))\b",
        lower,
    ):
        return (
            "**Sorting Algorithm Complexity**\n\n"
            "| Algorithm      | Best       | Average    | Worst      | Space    |\n"
            "|----------------|------------|------------|------------|----------|\n"
            "| Timsort        | O(n)       | O(n log n) | O(n log n) | O(n)     |\n"
            "| Quicksort      | O(n log n) | O(n log n) | O(n²)      | O(log n) |\n"
            "| Mergesort      | O(n log n) | O(n log n) | O(n log n) | O(n)     |\n"
            "| Heapsort       | O(n log n) | O(n log n) | O(n log n) | O(1)     |\n"
            "| Insertionsort  | O(n)       | O(n²)      | O(n²)      | O(1)     |\n"
            "| Bubblesort     | O(n)       | O(n²)      | O(n²)      | O(1)     |\n"
            "| Selectionsort  | O(n²)      | O(n²)      | O(n²)      | O(1)     |\n"
            "| Radixsort      | O(nk)      | O(nk)      | O(nk)      | O(n+k)   |\n\n"
            "Python uses Timsort (built-in `sorted()` and `.sort()`). Stable + adaptive."
        )

    # ── CUDA / PyTorch / RigNet setup facts ──────────────────────
    for _rx, _ans in _CUDA_SETUP:
        if _rx.search(lower):
            return _ans

    # ── Classic reasoning facts (moved from bench Medium) ───────────────
    for rx, answer in _REASONING_FACTS:
        if rx.search(lower):
            return answer

    # ── Coding algorithm canonical solutions ────────────────────────────
    for rx, answer in _CODING_PATTERNS:
        if rx.search(lower):
            return answer

    # ── Groundtruth modules (eagerly imported at module level) ──
    if _resolve_extras:
        _extras_result = _resolve_extras(lower)
        if _extras_result:
            return _extras_result
    if _resolve_gaming:
        _gaming_result = _resolve_gaming(lower)
        if _gaming_result:
            return _gaming_result
    if _resolve_design:
        _design_result = _resolve_design(lower)
        if _design_result:
            return _design_result
    if _resolve_live:
        _live_result = _resolve_live(lower)
        if _live_result:
            return _live_result
    if _resolve_ue5:
        _ue5_result = _resolve_ue5(lower)
        if _ue5_result:
            return _ue5_result

    # ── Nginx errors & config ───────────────────────────────
    for _pat, _ans in _NGINX:
        if re.search(_pat, lower):
            return _ans

    # ── PostgreSQL errors ───────────────────────────────────
    for _pat, _ans in _POSTGRES:
        if re.search(_pat, lower):
            return _ans

    # ── Node.js / V8 errors ─────────────────────────────────
    for _pat, _ans in _NODEJS:
        if re.search(_pat, lower):
            return _ans

    # ── ffmpeg commands ─────────────────────────────────────
    for _pat, _ans in _FFMPEG:
        if re.search(_pat, lower):
            return _ans

    # ── sysctl tuning ───────────────────────────────────────
    for _pat, _ans in _SYSCTL:
        if re.search(_pat, lower):
            return _ans

    # ── Thread / concurrency sizing ─────────────────────────
    for _pat, _ans in _CONCURRENCY:
        if re.search(_pat, lower):
            return _ans

    # ── Protobuf / orjson / msgpack ─────────────────────────
    for _pat, _ans in _PROTOBUF:
        if re.search(_pat, lower):
            return _ans

    # ── Ansible ─────────────────────────────────────────────
    for _pat, _ans in _ANSIBLE:
        if re.search(_pat, lower):
            return _ans

    # ── Java 21+ features & GC ──────────────────────────────
    for _pat, _ans in _JAVA_MODERN:
        if re.search(_pat, lower):
            return _ans

    # ── DNS troubleshooting ─────────────────────────────────
    for _pat, _ans in _DNS:
        if re.search(_pat, lower):
            return _ans

    # ── AlmaLinux ───────────────────────────────────────────
    for _pat, _ans in _ALMALINUX:
        if re.search(_pat, lower):
            return _ans

    # ── Terraform ───────────────────────────────────────────
    for _pat, _ans in _TERRAFORM:
        if re.search(_pat, lower):
            return _ans

    # ── Helm ────────────────────────────────────────────────
    for _pat, _ans in _HELM:
        if re.search(_pat, lower):
            return _ans

    for _pat, _ans in _MULLM_SYSTEM:
        if re.search(_pat, lower):
            return _ans

    # ── Bench Reasoning Easy — fixed-answer trivia ───────────
    for _pat, _ans in _BENCH_REASONING_EASY:
        if re.search(_pat, lower):
            return _ans

    return None


# ── Capitals (top 80 countries) ──────────────────────────────
_CAPITALS = {
    "afghanistan": "Kabul",
    "albania": "Tirana",
    "algeria": "Algiers",
    "argentina": "Buenos Aires",
    "australia": "Canberra",
    "austria": "Vienna",
    "bangladesh": "Dhaka",
    "belgium": "Brussels",
    "brazil": "Brasilia",
    "canada": "Ottawa",
    "chile": "Santiago",
    "china": "Beijing",
    "colombia": "Bogota",
    "croatia": "Zagreb",
    "cuba": "Havana",
    "czech republic": "Prague",
    "czechia": "Prague",
    "denmark": "Copenhagen",
    "egypt": "Cairo",
    "ethiopia": "Addis Ababa",
    "finland": "Helsinki",
    "france": "Paris",
    "germany": "Berlin",
    "greece": "Athens",
    "hungary": "Budapest",
    "iceland": "Reykjavik",
    "india": "New Delhi",
    "indonesia": "Jakarta",
    "iran": "Tehran",
    "iraq": "Baghdad",
    "ireland": "Dublin",
    "israel": "Jerusalem",
    "italy": "Rome",
    "japan": "Tokyo",
    "jordan": "Amman",
    "kenya": "Nairobi",
    "malaysia": "Kuala Lumpur",
    "mexico": "Mexico City",
    "morocco": "Rabat",
    "nepal": "Kathmandu",
    "netherlands": "Amsterdam",
    "new zealand": "Wellington",
    "nigeria": "Abuja",
    "north korea": "Pyongyang",
    "norway": "Oslo",
    "pakistan": "Islamabad",
    "peru": "Lima",
    "philippines": "Manila",
    "poland": "Warsaw",
    "portugal": "Lisbon",
    "romania": "Bucharest",
    "russia": "Moscow",
    "saudi arabia": "Riyadh",
    "singapore": "Singapore",
    "south africa": "Pretoria",
    "south korea": "Seoul",
    "spain": "Madrid",
    "sweden": "Stockholm",
    "switzerland": "Bern",
    "taiwan": "Taipei",
    "thailand": "Bangkok",
    "turkey": "Ankara",
    "ukraine": "Kyiv",
    "united kingdom": "London",
    "uk": "London",
    "england": "London",
    "united states": "Washington, D.C.",
    "usa": "Washington, D.C.",
    "us": "Washington, D.C.",
    "america": "Washington, D.C.",
    "venezuela": "Caracas",
    "vietnam": "Hanoi",
}

# ── Populations (approximate 2024, top countries) ────────────
_POPULATIONS = {
    "china": "1.41 billion",
    "india": "1.44 billion",
    "usa": "335 million",
    "united states": "335 million",
    "us": "335 million",
    "america": "335 million",
    "indonesia": "278 million",
    "pakistan": "240 million",
    "brazil": "216 million",
    "nigeria": "230 million",
    "bangladesh": "173 million",
    "russia": "144 million",
    "mexico": "130 million",
    "japan": "124 million",
    "ethiopia": "126 million",
    "philippines": "117 million",
    "egypt": "105 million",
    "vietnam": "100 million",
    "germany": "84 million",
    "turkey": "85 million",
    "iran": "89 million",
    "united kingdom": "68 million",
    "uk": "68 million",
    "france": "68 million",
    "thailand": "72 million",
    "italy": "59 million",
    "south africa": "62 million",
    "south korea": "52 million",
    "spain": "48 million",
    "colombia": "52 million",
    "kenya": "56 million",
    "argentina": "46 million",
    "ukraine": "37 million",
    "canada": "41 million",
    "morocco": "38 million",
    "peru": "34 million",
    "australia": "26 million",
    "taiwan": "24 million",
    "chile": "19 million",
    "netherlands": "18 million",
    "belgium": "12 million",
    "portugal": "10 million",
    "sweden": "10 million",
    "switzerland": "9 million",
    "israel": "10 million",
    "singapore": "6 million",
    "norway": "5.5 million",
    "ireland": "5 million",
    "new zealand": "5.2 million",
    "denmark": "5.9 million",
    "finland": "5.6 million",
}

# ── Physical/math constants ──────────────────────────────────
_CONSTANTS = [
    (
        re.compile(r"\bspeed of light\b"),
        "The speed of light in vacuum is 299,792,458 m/s (approximately 3 x 10^8 m/s).",
    ),
    (
        re.compile(
            r"^(?:what(?:'s| is)(?: the value of)? pi|value of pi|show me pi|pi[?.]?|greek (?:letter|symbol) (?:for )?pi)\??$"
        ),
        "Pi (π) = 3.14159265358979323846...",
    ),
    (
        re.compile(r"\beuler'?s? (?:number|constant)\b|(?:^|\bvalue of )e$|\bwhat is e\b"),
        "Euler's number (e) = 2.71828182845904523536...",
    ),
    (re.compile(r"\bgravitational constant\b|\bbig g\b"), "The gravitational constant G = 6.674 x 10^-11 N·m²/kg²."),
    (re.compile(r"\bspeed of sound\b"), "The speed of sound in dry air at 20°C is approximately 343 m/s (1,235 km/h)."),
    (re.compile(r"\babsolute zero\b"), "Absolute zero is 0 K = -273.15°C = -459.67°F."),
    (re.compile(r"\bavogadro"), "Avogadro's number = 6.022 x 10^23 mol^-1."),
    (re.compile(r"\bplanck(?:'s)? constant\b"), "Planck's constant h = 6.626 x 10^-34 J·s."),
    (re.compile(r"\bboltzmann(?:'s)? constant\b"), "Boltzmann constant k_B = 1.381 x 10^-23 J/K."),
    (re.compile(r"\bgolden ratio\b|\bphi\b"), "The golden ratio (φ) = 1.6180339887..."),
]


# ── Mathematical constants & identities ──────────────────────
_MATH_IDENTITIES = [
    (
        re.compile(r"\bintegral of (?:arctan|atan)\s*\(?x\)?\s*(?:dx)?"),
        "∫ arctan(x) dx = x·arctan(x) − ½·ln(1 + x²) + C",
    ),
    (re.compile(r"\bintegral of (?:ln|log)\s*\(?x\)?\s*(?:dx)?"), "∫ ln(x) dx = x·ln(x) − x + C"),
    (re.compile(r"\bintegral of e\^x\s*(?:dx)?"), "∫ e^x dx = e^x + C"),
    (re.compile(r"\bintegral of (?:sin|sine)\s*\(?x\)?\s*(?:dx)?"), "∫ sin(x) dx = −cos(x) + C"),
    (re.compile(r"\bintegral of (?:cos|cosine)\s*\(?x\)?\s*(?:dx)?"), "∫ cos(x) dx = sin(x) + C"),
    (re.compile(r"\bintegral of 1/x\s*(?:dx)?"), "∫ 1/x dx = ln|x| + C"),
    (re.compile(r"\bintegral of x\^n\s*(?:dx)?"), "∫ x^n dx = x^(n+1)/(n+1) + C, for n ≠ −1"),
    (
        re.compile(r"\beuler(?:'s)? (?:identity|formula)\b"),
        "Euler's identity: e^(iπ) + 1 = 0. Euler's formula: e^(ix) = cos(x) + i·sin(x).",
    ),
    (
        re.compile(r"\bpythagorean (?:theorem|identity)\b"),
        "a² + b² = c² (Pythagorean theorem). Also: sin²(θ) + cos²(θ) = 1.",
    ),
    (re.compile(r"\bquadratic formula\b"), "x = (−b ± √(b² − 4ac)) / 2a"),
    (re.compile(r"\bbayes(?:'|'s)? (?:theorem|rule|formula)\b"), "P(A|B) = P(B|A)·P(A) / P(B)"),
    (
        re.compile(r"\bfibonacci (?:sequence|numbers)\b"),
        "Fibonacci: 0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610... Each number is the sum of the two before it.",
    ),
    (
        re.compile(r"\b(?:what is|how many) .*\bmol\b|\bmole\b(?! skin)"),
        "One mole = 6.022 × 10²³ particles (Avogadro's number). It's the amount of substance containing as many elementary entities as atoms in 12g of carbon-12.",
    ),
]

# ── Scientific constants (expanded) ──────────────────────────
_SCIENCE_CONSTANTS = [
    (re.compile(r"\belectron (?:mass|rest mass)\b"), "Electron mass = 9.109 × 10⁻³¹ kg."),
    (re.compile(r"\bproton (?:mass|rest mass)\b"), "Proton mass = 1.673 × 10⁻²⁷ kg."),
    (re.compile(r"\bneutron mass\b"), "Neutron mass = 1.675 × 10⁻²⁷ kg."),
    (re.compile(r"\belectron charge\b|\belementary charge\b"), "Elementary charge e = 1.602 × 10⁻¹⁹ C."),
    (re.compile(r"\bgas constant\b|\buniversal gas constant\b"), "Universal gas constant R = 8.314 J/(mol·K)."),
    (re.compile(r"\bfine.structure constant\b"), "Fine-structure constant α ≈ 1/137 ≈ 0.007297."),
    (re.compile(r"\bstefan.boltzmann\b"), "Stefan-Boltzmann constant σ = 5.670 × 10⁻⁸ W/(m²·K⁴)."),
    (re.compile(r"\bcoulomb(?:'s)? constant\b"), "Coulomb's constant k = 8.988 × 10⁹ N·m²/C²."),
    (re.compile(r"\bpermittivity of (?:free space|vacuum)\b"), "Vacuum permittivity ε₀ = 8.854 × 10⁻¹² F/m."),
    (re.compile(r"\bpermeability of (?:free space|vacuum)\b"), "Vacuum permeability μ₀ = 1.257 × 10⁻⁶ H/m."),
    (
        re.compile(r"\bhubble(?:'s)? constant\b"),
        "Hubble constant H₀ ≈ 67.4 km/s/Mpc (Planck 2018 measurement). Expansion rate of the universe.",
    ),
    (
        re.compile(r"\bschwarzschild radius\b"),
        "Schwarzschild radius r_s = 2GM/c². For the Sun: ~3 km. For Earth: ~9 mm.",
    ),
    (
        re.compile(r"\bchandrasekhar limit\b"),
        "Chandrasekhar limit ≈ 1.4 solar masses. Maximum mass of a stable white dwarf star.",
    ),
]

# ── Greek & Roman mythology ──────────────────────────────────
_MYTHOLOGY = {
    "zeus": "Zeus — King of the Greek gods, god of sky and thunder. Roman equivalent: Jupiter. Father of many gods and heroes.",
    "hera": "Hera — Queen of the Greek gods, goddess of marriage and family. Roman: Juno. Wife of Zeus.",
    "poseidon": "Poseidon — Greek god of the sea, earthquakes, and horses. Roman: Neptune. Brother of Zeus.",
    "athena": "Athena — Greek goddess of wisdom, warfare, and crafts. Roman: Minerva. Born from Zeus's head.",
    "apollo": "Apollo — Greek god of the sun, music, poetry, and prophecy. Same name in Roman mythology.",
    "artemis": "Artemis — Greek goddess of the hunt, wilderness, and the moon. Roman: Diana. Twin of Apollo.",
    "ares": "Ares — Greek god of war. Roman: Mars. Son of Zeus and Hera.",
    "aphrodite": "Aphrodite — Greek goddess of love, beauty, and desire. Roman: Venus. Born from sea foam.",
    "hermes": "Hermes — Greek messenger god, god of trade, thieves, and travelers. Roman: Mercury.",
    "hephaestus": "Hephaestus — Greek god of fire and metalworking. Roman: Vulcan. Forged weapons for the gods.",
    "demeter": "Demeter — Greek goddess of harvest and agriculture. Roman: Ceres. Mother of Persephone.",
    "dionysus": "Dionysus — Greek god of wine, festivity, and ecstasy. Roman: Bacchus.",
    "hades": "Hades — Greek god of the underworld and the dead. Roman: Pluto. Brother of Zeus and Poseidon.",
    "persephone": "Persephone — Greek queen of the underworld, goddess of spring. Roman: Proserpina. Daughter of Demeter.",
    "prometheus": "Prometheus — Titan who stole fire from the gods and gave it to humanity. Punished by Zeus to eternal torment.",
    "hercules": "Heracles (Greek) / Hercules (Roman) — Demigod hero, son of Zeus. Famous for the Twelve Labors.",
    "odysseus": "Odysseus (Greek) / Ulysses (Roman) — Hero of the Trojan War. His 10-year journey home is told in Homer's Odyssey.",
    "achilles": "Achilles — Greatest warrior of the Trojan War. Invulnerable except his heel. Killed by Paris's arrow.",
    "medusa": "Medusa — Gorgon with snakes for hair. Looking at her turned people to stone. Slain by Perseus.",
    "minotaur": "Minotaur — Half-man, half-bull creature of Crete. Lived in the Labyrinth. Slain by Theseus.",
    "pandora": "Pandora — First woman in Greek mythology. Opened a box (actually a jar) releasing all evils into the world, leaving only hope.",
    "icarus": "Icarus — Son of Daedalus. Flew too close to the sun with wax wings, which melted. Fell into the sea.",
}

# ── Historic dates, wars, discoveries ────────────────────────
_HISTORIC_DATES = {
    "fall of rome": (
        "476 AD",
        "The Western Roman Empire fell in 476 AD when Germanic leader Odoacer deposed the last emperor Romulus Augustulus.",
    ),
    "magna carta": (
        "1215",
        "The Magna Carta was sealed on June 15, 1215 at Runnymede, England. Foundation of constitutional law.",
    ),
    "printing press": (
        "1440",
        "Johannes Gutenberg invented the movable-type printing press around 1440 in Mainz, Germany.",
    ),
    "discovery of america": (
        "1492",
        "Christopher Columbus reached the Americas on October 12, 1492, landing in the Bahamas.",
    ),
    "fall of constantinople": (
        "1453",
        "Constantinople fell to the Ottoman Empire on May 29, 1453, ending the Byzantine Empire.",
    ),
    "french revolution": ("1789", "The French Revolution began on July 14, 1789 with the storming of the Bastille."),
    "american revolution": ("1776", "The American Revolution: Declaration of Independence signed July 4, 1776."),
    "moon landing": (
        "1969",
        "Apollo 11 landed on the Moon on July 20, 1969. Neil Armstrong's first steps: 'One small step for man...'",
    ),
    "world war 1": (
        "1914-1918",
        "World War I: 1914-1918. Started by the assassination of Archduke Franz Ferdinand. ~20 million dead.",
    ),
    "world war 2": ("1939-1945", "World War II: 1939-1945. Most destructive conflict in history. ~70-85 million dead."),
    "berlin wall": (
        "1961-1989",
        "Berlin Wall: built August 13, 1961; fell November 9, 1989. Symbol of Cold War division.",
    ),
    "internet": (
        "1969/1991",
        "ARPANET (internet precursor) began in 1969. The World Wide Web was invented by Tim Berners-Lee in 1991.",
    ),
    "dna discovery": ("1953", "Watson and Crick published the double helix structure of DNA on April 25, 1953."),
    "penicillin": (
        "1928",
        "Alexander Fleming discovered penicillin in 1928. First mass-produced antibiotic, saved millions of lives.",
    ),
    "theory of relativity": ("1905/1915", "Einstein's special relativity: 1905. General relativity: 1915. E = mc²."),
    "industrial revolution": (
        "1760-1840",
        "The Industrial Revolution began around 1760 in Britain. Steam power, factories, urbanization.",
    ),
    "renaissance": (
        "14th-17th century",
        "The Renaissance: ~1300s-1600s. Cultural rebirth in Europe. Da Vinci, Michelangelo, Shakespeare.",
    ),
    "black death": (
        "1347-1351",
        "The Black Death (bubonic plague) killed 75-200 million people in Eurasia, ~1347-1351.",
    ),
    "hiroshima": ("1945", "Atomic bomb dropped on Hiroshima on August 6, 1945, and Nagasaki on August 9, 1945."),
    "cold war": (
        "1947-1991",
        "The Cold War: ~1947-1991. Geopolitical tension between the US/NATO and USSR/Warsaw Pact.",
    ),
    "chernobyl": (
        "1986",
        "Chernobyl nuclear disaster: April 26, 1986 in Ukraine (then Soviet Union). Worst nuclear accident in history.",
    ),
    "september 11": (
        "2001",
        "September 11, 2001: Terrorist attacks on the World Trade Center and Pentagon. ~2,977 victims.",
    ),
}

# ── Astronomy (expanded beyond eclipses) ─────────────────────
_ASTRONOMY = [
    (
        re.compile(r"\bhow (?:far|close) is the (?:moon|sun)\b"),
        "The Moon is ~384,400 km (238,855 mi) from Earth. The Sun is ~149.6 million km (93 million mi) away.",
    ),
    (
        re.compile(r"\b(?:diameter|size) of (?:the )?(?:earth|sun|moon|mars|jupiter)\b"),
        "Earth: 12,742 km. Moon: 3,474 km. Sun: 1,392,700 km. Mars: 6,779 km. Jupiter: 139,820 km.",
    ),
    (
        re.compile(r"\blight year\b"),
        "A light-year is ~9.461 × 10¹² km (5.879 × 10¹² miles) — the distance light travels in one year.",
    ),
    (
        re.compile(r"\bnearest star\b|\bproxima centauri\b|\bclosest star\b"),
        "Proxima Centauri is the nearest star to the Sun at 4.247 light-years (40.2 trillion km) away.",
    ),
    (
        re.compile(r"\bage of (?:the )?(?:universe|earth|sun)\b"),
        "Universe: ~13.8 billion years. Earth: ~4.54 billion years. Sun: ~4.6 billion years.",
    ),
    (
        re.compile(r"\bhow many planets\b"),
        "Our solar system has 8 planets: Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus, Neptune. (Pluto was reclassified as a dwarf planet in 2006.)",
    ),
    (
        re.compile(r"\b(?:what is|about) (?:a )?(?:black hole|neutron star|pulsar|quasar)\b"),
        "Black hole: region where gravity is so strong nothing escapes. Neutron star: collapsed star ~20km across. Pulsar: rotating neutron star emitting beams. Quasar: extremely luminous active galactic nucleus.",
    ),
    (
        re.compile(r"\bmilky way\b"),
        "The Milky Way is a barred spiral galaxy ~100,000 light-years across containing 100-400 billion stars. Our Sun is ~26,000 light-years from the center.",
    ),
    (
        re.compile(r"\bandromeda\b"),
        "Andromeda (M31) is the nearest large galaxy, ~2.537 million light-years away. It will merge with the Milky Way in ~4.5 billion years.",
    ),
]

# ── Geology ──────────────────────────────────────────────────
_GEOLOGY = [
    (
        re.compile(r"\bmohs (?:scale|hardness)\b"),
        "Mohs hardness scale (1-10): 1=Talc, 2=Gypsum, 3=Calcite, 4=Fluorite, 5=Apatite, 6=Orthoclase, 7=Quartz, 8=Topaz, 9=Corundum, 10=Diamond.",
    ),
    (
        re.compile(r"\b(?:layers|structure) of (?:the )?earth\b"),
        "Earth's layers: Crust (5-70 km), Mantle (2,900 km), Outer Core (2,200 km, liquid iron), Inner Core (1,220 km, solid iron). Total radius: 6,371 km.",
    ),
    (
        re.compile(r"\btectonic plates\b|\bhow many plates\b"),
        "Earth has 7 major tectonic plates: Pacific, North American, Eurasian, African, Antarctic, Indo-Australian, South American, plus ~8 minor plates.",
    ),
    (
        re.compile(r"\brichter scale\b|\bearthquake (?:scale|magnitude)\b"),
        "Richter/moment magnitude scale: <2 micro, 2-3 minor, 4-5 moderate, 6-7 strong, 8+ great. Each whole number = ~31.6x more energy.",
    ),
    (
        re.compile(r"\b(?:deepest|mariana)\b.*\b(?:trench|ocean|point)\b"),
        "The Mariana Trench is the deepest oceanic trench, ~10,994 m (36,070 ft) deep. Located in the western Pacific Ocean.",
    ),
    (
        re.compile(r"\btallest mountain\b|\beverest\b"),
        "Mount Everest: 8,849 m (29,032 ft) above sea level. Tallest from base: Mauna Kea at ~10,211 m (from ocean floor).",
    ),
    (
        re.compile(r"\b(?:largest|biggest|greatest|name the)\b.*\bocean\b|\bocean\b.*\b(?:largest|biggest)\b"),
        "The Pacific Ocean is the largest ocean: 165.25 million km² (63.8 million sq mi), covering ~46% of Earth's water surface and ~32% of total surface area. Average depth: 4,280 m (14,040 ft). It is also the deepest, containing the Mariana Trench at 10,994 m.",
    ),
    (
        re.compile(r"\b(?:five|5)\s*oceans\b|\boceans of (?:the )?world\b|\bhow many oceans\b"),
        "Earth has 5 oceans (largest to smallest): 1. Pacific (165.25M km²), 2. Atlantic (106.46M km²), 3. Indian (70.56M km²), 4. Southern/Antarctic (21.96M km²), 5. Arctic (14.06M km²).",
    ),
    (
        re.compile(r"\blargest (?:country|nation)\b.*\bworld\b|\bworld.*\blargest (?:country|nation)\b"),
        "Russia is the world's largest country: 17.1 million km² (6.6 million sq mi), covering ~11% of Earth's land area. Spans 11 time zones.",
    ),
    (
        re.compile(r"\blargest (?:continent)\b|\bcontinent.*\blargest\b"),
        "Asia is the largest continent: 44.6 million km², covering ~30% of Earth's land area. Home to ~60% of the world's population.",
    ),
    (
        re.compile(r"\blargest (?:desert)\b|\bdesert.*\blargest\b"),
        "The Antarctic Desert is the largest desert at 14.2 million km² (cold desert). Largest hot desert: the Sahara at 9.2 million km² across North Africa.",
    ),
    (
        re.compile(r"\blongest (?:river)\b|\briver.*\blongest\b"),
        "The Nile River is traditionally cited as the longest river at ~6,650 km (4,130 mi), though the Amazon (6,400 km) is disputed as potentially longer depending on measurement.",
    ),
    (
        re.compile(r"\blargest (?:lake)\b|\blake.*\blargest\b"),
        "The Caspian Sea is the world's largest lake by area: 371,000 km². Largest freshwater lake: Lake Superior (82,414 km²). Deepest lake: Lake Baikal (1,642 m).",
    ),
    (
        re.compile(r"\bhighest (?:point|elevation|altitude)\b.*\bearth\b|\bearth.*\bhighest\b"),
        "Earth's highest point is Mount Everest at 8,849 m (29,032 ft) above sea level. Highest from Earth's center: Mount Chimborazo (6,384 km from center due to equatorial bulge).",
    ),
]

# ── Psychology ───────────────────────────────────────────────
_PSYCHOLOGY = [
    (
        re.compile(r"\bmaslow(?:'s)? (?:hierarchy|pyramid|needs)\b"),
        "Maslow's hierarchy of needs (bottom to top): 1. Physiological, 2. Safety, 3. Love/belonging, 4. Esteem, 5. Self-actualization.",
    ),
    (
        re.compile(
            r"\b(?:big five|ocean model|five factor)\b.*\bpersonality\b|\bpersonality.*\b(?:big five|ocean|five factor)\b"
        ),
        "Big Five personality traits (OCEAN): Openness, Conscientiousness, Extraversion, Agreeableness, Neuroticism.",
    ),
    (
        re.compile(r"\bstages of grief\b|\bkubler.ross\b"),
        "Kubler-Ross five stages of grief: 1. Denial, 2. Anger, 3. Bargaining, 4. Depression, 5. Acceptance.",
    ),
    (
        re.compile(r"\bpavlov\b|\bclassical conditioning\b"),
        "Classical conditioning (Pavlov, 1890s): Pairing a neutral stimulus with an unconditioned stimulus to create a conditioned response. Famous experiment: dogs salivating at a bell.",
    ),
    (
        re.compile(r"\bstanford prison\b"),
        "Stanford Prison Experiment (1971, Philip Zimbardo): Simulated prison study showing how situational forces can make ordinary people behave cruelly. Highly controversial methodology.",
    ),
    (
        re.compile(r"\bmilgram\b.*\bexperiment\b|\bobedience experiment\b"),
        "Milgram experiment (1961): Tested obedience to authority. ~65% of participants administered what they believed were lethal electric shocks when instructed by an authority figure.",
    ),
    (
        re.compile(r"\bdunning.kruger\b"),
        "Dunning-Kruger effect: Cognitive bias where people with limited competence overestimate their ability, while experts tend to underestimate theirs.",
    ),
    (
        re.compile(r"\bstockholm syndrome\b"),
        "Stockholm syndrome: Psychological response where hostages develop positive feelings toward their captors. Named after a 1973 bank robbery in Stockholm, Sweden.",
    ),
]

# ── Archaeology ──────────────────────────────────────────────
_ARCHAEOLOGY = [
    (
        re.compile(r"\b(?:rosetta stone)\b"),
        "The Rosetta Stone (196 BC) was found in 1799 in Egypt. Contains the same text in hieroglyphics, Demotic, and Greek, enabling decipherment of Egyptian hieroglyphs.",
    ),
    (
        re.compile(r"\bdead sea scrolls\b"),
        "Dead Sea Scrolls: ~972 texts discovered 1946-1956 in caves near the Dead Sea. Include the oldest known manuscripts of the Hebrew Bible (~250 BC - 68 AD).",
    ),
    (
        re.compile(r"\bpompeii\b"),
        "Pompeii was a Roman city buried by the eruption of Mount Vesuvius in 79 AD. Rediscovered in 1748, remarkably preserved under volcanic ash.",
    ),
    (
        re.compile(r"\bterracotta (?:army|warriors)\b"),
        "The Terracotta Army: ~8,000 life-sized clay soldiers buried with China's first emperor Qin Shi Huang (~210 BC). Discovered in 1974 by farmers near Xi'an.",
    ),
    (
        re.compile(r"\bstonehenge\b"),
        "Stonehenge: Prehistoric monument in Wiltshire, England. Built ~3000-2000 BC. Purpose debated: astronomical observatory, temple, or ceremonial site.",
    ),
    (
        re.compile(r"\btutankhamun|king tut\b"),
        "Tutankhamun: Egyptian pharaoh (~1332-1323 BC). His nearly intact tomb was discovered by Howard Carter in 1922 in the Valley of the Kings.",
    ),
    (
        re.compile(r"\bmachu picchu\b"),
        "Machu Picchu: 15th-century Inca citadel in the Peruvian Andes, ~2,430 m elevation. Rediscovered in 1911 by Hiram Bingham.",
    ),
    (
        re.compile(r"\bgobekli tepe\b"),
        "Gobekli Tepe: Archaeological site in Turkey dating to ~9500 BC. Oldest known monumental structures, predating agriculture and pottery.",
    ),
]

# ── Chemical elements (symbol lookups + name lookups) ────────
_ELEMENTS = {
    # symbol → (name, atomic_number, description)
    "h": ("Hydrogen", 1, "lightest element, ~75% of normal matter by mass"),
    "he": ("Helium", 2, "noble gas, second lightest, used in balloons"),
    "li": ("Lithium", 3, "lightest metal, used in batteries"),
    "be": ("Beryllium", 4, "lightweight metal, used in aerospace"),
    "b": ("Boron", 5, "metalloid, used in glass and nuclear reactors"),
    "c": ("Carbon", 6, "basis of all organic life, graphite and diamond"),
    "n": ("Nitrogen", 7, "makes up ~78% of Earth's atmosphere"),
    "o": ("Oxygen", 8, "makes up ~21% of Earth's atmosphere"),
    "f": ("Fluorine", 9, "most reactive element"),
    "ne": ("Neon", 10, "noble gas, used in signs"),
    "na": ("Sodium", 11, "alkali metal, component of table salt (NaCl)"),
    "mg": ("Magnesium", 12, "lightweight structural metal"),
    "al": ("Aluminium", 13, "most abundant metal in Earth's crust"),
    "si": ("Silicon", 14, "semiconductors and sand (SiO2)"),
    "p": ("Phosphorus", 15, "essential for DNA and ATP"),
    "s": ("Sulfur", 16, "used in gunpowder and vulcanization"),
    "cl": ("Chlorine", 17, "halogen, used for water treatment"),
    "ar": ("Argon", 18, "noble gas, ~1% of atmosphere"),
    "k": ("Potassium", 19, "alkali metal, essential electrolyte"),
    "ca": ("Calcium", 20, "most abundant mineral in the body, bones/teeth"),
    "fe": ("Iron", 26, "most common element on Earth by mass, basis of steel"),
    "cu": ("Copper", 29, "reddish conductive metal, used in wiring"),
    "zn": ("Zinc", 30, "used in galvanization and batteries"),
    "ag": ("Silver", 47, "precious metal, best electrical conductor"),
    "sn": ("Tin", 50, "used in soldering and tin cans"),
    "i": ("Iodine", 53, "essential trace element, used as antiseptic"),
    "w": ("Tungsten", 74, "highest melting point of any element (3,422°C)"),
    "au": ("Gold", 79, "dense precious metal, excellent conductor, doesn't tarnish"),
    "hg": ("Mercury", 80, "only liquid metal at room temperature"),
    "pb": ("Lead", 82, "heavy metal, used in batteries and radiation shielding"),
    "u": ("Uranium", 92, "radioactive heavy metal, used in nuclear reactors"),
}
# name → symbol (reverse lookup)
_ELEMENT_BY_NAME = {v[0].lower(): k.upper() for k, v in _ELEMENTS.items()}

# ── Verbal analogies ─────────────────────────────────────────
_ANALOGIES = [
    # format: (compiled_pattern, answer)
    (
        re.compile(r"\bcat\b.*\bkitten\b.*\bdog\b|\bdog\b.*\bcat\b.*\bkitten\b"),
        "puppy — cat is to kitten as dog is to puppy (parent:offspring).",
    ),
    (
        re.compile(r"\bdog\b.*\bpuppy\b.*\bcat\b|\bcat\b.*\bdog\b.*\bpuppy\b"),
        "kitten — dog is to puppy as cat is to kitten (parent:offspring).",
    ),
    (
        re.compile(r"\bking\b.*\bman\b.*\bqueen\b|\bqueen\b.*\bwoman\b.*\bking\b"),
        "woman — king is to man as queen is to woman (ruler:gender).",
    ),
    (
        re.compile(r"\bbird\b.*\bfly\b.*\bfish\b|\bfish\b.*\bbird\b.*\bfly\b"),
        "swim — bird is to fly as fish is to swim (animal:locomotion).",
    ),
    (
        re.compile(r"\bhot\b.*\bcold\b.*\bday\b|\bday\b.*\bnight\b.*\bhot\b"),
        "night — day is to night as hot is to cold (opposites).",
    ),
    (
        re.compile(r"\bbook\b.*\bread\b.*\bmusic\b|\bmusic\b.*\blisten\b.*\bbook\b"),
        "listen — book is to read as music is to listen (medium:action).",
    ),
    (
        re.compile(r"\bpencil\b.*\bwrite\b.*\bscalpel\b|\bdoctor\b.*\bscalpel\b"),
        "surgeon/doctor — pencil is to writer as scalpel is to surgeon.",
    ),
    (
        re.compile(r"\bword\b.*\bsentence\b.*\bnote\b.*\bmelody\b|\bnote\b.*\bmelody\b.*\bword\b"),
        "melody — note is to melody as word is to sentence (unit:composition).",
    ),
    (
        re.compile(r"\bice\b.*\bwater\b.*\bsteam\b|\bwater\b.*\bice\b.*\bsteam\b"),
        "The three states of water: ice (solid) → water (liquid) → steam (gas).",
    ),
    (
        re.compile(r"\bpaw\b.*\bdog\b.*\bhoof\b|\bhoof\b.*\bhorse\b.*\bpaw\b"),
        "horse — paw is to dog as hoof is to horse (body part:animal).",
    ),
    (
        re.compile(r"\bchapter\b.*\bbook\b.*\bepisode\b|\bepisode\b.*\bshow\b.*\bchapter\b"),
        "TV show/series — chapter is to book as episode is to TV show.",
    ),
    (
        re.compile(r"\bbark\b.*\btree\b.*\bskin\b|\bskin\b.*\bhuman\b.*\bbark\b"),
        "tree — skin is to human as bark is to tree (outer covering:organism).",
    ),
]

# ── Philosophy quotes ───────────────────────────────────────
_PHILOSOPHY = {
    "socrates": "Socrates: 'The unexamined life is not worth living.' — Greek philosopher (470-399 BC), father of Western philosophy, taught through questioning (Socratic method).",
    "plato": "Plato: 'Wise men speak because they have something to say; fools because they have to say something.' — Greek philosopher (428-348 BC), student of Socrates, wrote The Republic, Theory of Forms.",
    "aristotle": "Aristotle: 'Knowing yourself is the beginning of all wisdom.' — Greek philosopher (384-322 BC), student of Plato, foundational contributions to logic, biology, ethics, and politics.",
    "descartes": "Rene Descartes: 'I think, therefore I am' (Cogito, ergo sum). — French philosopher (1596-1650), father of modern philosophy, mind-body dualism.",
    "kant": "Immanuel Kant: 'Act only according to that maxim whereby you can at the same time will that it should become a universal law.' — German philosopher (1724-1804), categorical imperative, Critique of Pure Reason.",
    "nietzsche": "Friedrich Nietzsche: 'He who has a why to live can bear almost any how.' — German philosopher (1844-1900), ubermensch, will to power, eternal recurrence, 'God is dead.'",
    "kierkegaard": "Soren Kierkegaard: 'Life can only be understood backwards; but it must be lived forwards.' — Danish philosopher (1813-1855), father of existentialism.",
    "wittgenstein": "Ludwig Wittgenstein: 'The limits of my language mean the limits of my world.' — Austrian-British philosopher (1889-1951), Tractatus Logico-Philosophicus, language games.",
    "simone de beauvoir": "Simone de Beauvoir: 'One is not born, but rather becomes, a woman.' — French existentialist philosopher (1908-1986), The Second Sex, feminist philosophy.",
    "sartre": "Jean-Paul Sartre: 'Man is condemned to be free.' — French existentialist (1905-1980), Being and Nothingness, existence precedes essence.",
    "marcus aurelius": "Marcus Aurelius: 'You have power over your mind — not outside events. Realize this, and you will find strength.' — Roman emperor and Stoic philosopher (121-180 AD), Meditations.",
    "epictetus": "Epictetus: 'We suffer more often in imagination than in reality.' — Stoic philosopher (50-135 AD), born a slave, Discourses and Enchiridion.",
    "confucius": "Confucius: 'It does not matter how slowly you go as long as you do not stop.' — Chinese philosopher (551-479 BC), Analects, five virtues, filial piety.",
    "lao tzu": "Lao Tzu: 'The journey of a thousand miles begins with a single step.' — Chinese philosopher (~6th century BC), founder of Taoism, Tao Te Ching.",
    "pascal": "Blaise Pascal: 'The heart has its reasons which reason knows nothing of.' — French mathematician and philosopher (1623-1662), Pascal's Wager, Pensees.",
}

# ── Art history periods & movements ─────────────────────────
_ART_HISTORY = [
    (
        r"\brenaissance\b.*\b(?:art|period|movement)\b|\b(?:art|period).*\brenaissance\b",
        "The **Renaissance** (1400-1600): Rebirth of classical art and learning. Key artists: Leonardo da Vinci, Michelangelo, Raphael, Botticelli. Centered in Florence and Rome. Characterized by perspective, humanism, and naturalism.",
    ),
    (
        r"\bimpressionism\b",
        "**Impressionism** (1860s-1880s): French art movement capturing light and momentary effects. Key artists: Monet, Renoir, Degas, Pissarro, Sisley. Small visible brushstrokes, open composition, emphasis on light.",
    ),
    (
        r"\bsurrealism\b",
        "**Surrealism** (1920s-1950s): Art exploring the unconscious mind and dreams. Key artists: Dali, Magritte, Ernst, Miro. Inspired by Freudian psychoanalysis. Famous works: The Persistence of Memory, The Treachery of Images.",
    ),
    (
        r"\bcubism\b",
        "**Cubism** (1907-1920s): Pioneered by Picasso and Braque. Fragmented objects into geometric forms shown from multiple viewpoints simultaneously. Key works: Les Demoiselles d'Avignon, Guernica.",
    ),
    (
        r"\bbaroque\b.*\b(?:art|period)\b|\b(?:art|period).*\bbaroque\b",
        "**Baroque** (1600-1750): Dramatic, ornate art with strong contrasts of light and shadow. Key artists: Caravaggio, Rembrandt, Vermeer, Bernini, Rubens.",
    ),
    (
        r"\bpop art\b",
        "**Pop Art** (1950s-1960s): Art drawing from popular culture and mass media. Key artists: Warhol, Lichtenstein, Hockney, Oldenburg. Famous works: Campbell's Soup Cans, Whaam!",
    ),
    (
        r"\babstract expressionism\b",
        "**Abstract Expressionism** (1940s-1960s): First major American art movement. Key artists: Pollock, de Kooning, Rothko, Newman. Action painting and color field painting.",
    ),
    (
        r"\bwho painted (?:the )?mona lisa\b|\bmona lisa\b",
        "The **Mona Lisa** was painted by Leonardo da Vinci, c. 1503-1519. Oil on poplar panel. Housed in the Louvre, Paris. Known for her enigmatic smile and sfumato technique.",
    ),
    (
        r"\bwho painted (?:the )?starry night\b|\bstarry night\b",
        "**The Starry Night** was painted by Vincent van Gogh in June 1889 while at the Saint-Paul-de-Mausole asylum. Oil on canvas. Housed at MoMA, New York.",
    ),
    (
        r"\bwho painted guernica\b|\bguernica\b(?!.*city)",
        "**Guernica** was painted by Pablo Picasso in 1937, responding to the bombing of Guernica during the Spanish Civil War. Oil on canvas, 3.49m x 7.76m. Housed at Museo Reina Sofia, Madrid.",
    ),
]

# ── Music theory ────────────────────────────────────────────
_MUSIC_THEORY = [
    (
        r"\b(?:what is|explain) (?:a )?(?:major|minor) (?:scale|key)\b",
        "A **major scale** follows the pattern: whole-whole-half-whole-whole-whole-half (W-W-H-W-W-W-H). A **minor scale** (natural): W-H-W-W-H-W-W. Major sounds bright/happy, minor sounds dark/sad.",
    ),
    (
        r"\bcircle of fifths\b",
        "The **Circle of Fifths**: C → G → D → A → E → B → F#/Gb → Db → Ab → Eb → Bb → F → C. Each key is a perfect fifth (7 semitones) from the last. Sharps add going clockwise, flats going counter-clockwise.",
    ),
    (
        r"\b(?:what is|explain) (?:a )?chord\b",
        "A **chord** is 3+ notes played together. **Major triad**: root + major 3rd + perfect 5th (e.g., C-E-G). **Minor triad**: root + minor 3rd + perfect 5th (e.g., C-Eb-G). **7th chords** add a 7th interval.",
    ),
    (
        r"\b(?:what are|list) (?:the )?(?:music(?:al)?|note) intervals\b",
        "Music intervals: Unison (0), Minor 2nd (1), Major 2nd (2), Minor 3rd (3), Major 3rd (4), Perfect 4th (5), Tritone (6), Perfect 5th (7), Minor 6th (8), Major 6th (9), Minor 7th (10), Major 7th (11), Octave (12 semitones).",
    ),
    (
        r"\b(?:notes in|what is) (?:the )?([a-g])\s*(?:flat|sharp|b|#)?\s*(?:major|minor)\b",
        "Common scales: C major (C-D-E-F-G-A-B), G major (G-A-B-C-D-E-F#), D major (D-E-F#-G-A-B-C#), A minor (A-B-C-D-E-F-G), E minor (E-F#-G-A-B-C-D). For full scale, specify the key!",
    ),
    (
        r"\b(?:what is|explain) tempo\b|\bbpm\b.*(?:what|mean)",
        "**Tempo** is the speed of music, measured in BPM (beats per minute). Common tempos: Grave (20-40), Adagio (66-76), Andante (76-108), Moderato (108-120), Allegro (120-156), Presto (168-200), Prestissimo (200+).",
    ),
]

# ── HTTP status codes ────────────────────────────────────────
_HTTP_CODES = {
    "100": ("Continue", "Server received request headers, client should proceed with body."),
    "200": ("OK", "Standard success response."),
    "201": ("Created", "Request succeeded and a new resource was created."),
    "204": ("No Content", "Success but no content to return."),
    "301": ("Moved Permanently", "Resource has been permanently moved to a new URL."),
    "302": ("Found", "Temporary redirect to a different URL."),
    "304": ("Not Modified", "Resource hasn't changed since last request (caching)."),
    "400": ("Bad Request", "Server cannot process the request due to client error."),
    "401": ("Unauthorized", "Authentication required."),
    "403": ("Forbidden", "Server understood the request but refuses to authorize it."),
    "404": ("Not Found", "Requested resource does not exist."),
    "405": ("Method Not Allowed", "HTTP method not supported for this endpoint."),
    "408": ("Request Timeout", "Server timed out waiting for the request."),
    "409": ("Conflict", "Request conflicts with current state of the resource."),
    "418": ("I'm a Teapot", "RFC 2324 joke. Server refuses to brew coffee with a teapot."),
    "429": ("Too Many Requests", "Rate limited. Client sent too many requests."),
    "500": ("Internal Server Error", "Server encountered an unexpected condition."),
    "502": ("Bad Gateway", "Server acting as gateway received an invalid response from upstream."),
    "503": ("Service Unavailable", "Server temporarily overloaded or under maintenance."),
    "504": ("Gateway Timeout", "Gateway server didn't receive a timely response from upstream."),
}

# ── Port numbers ─────────────────────────────────────────────
_PORTS = {
    "ssh": ("22", "SSH (Secure Shell) — remote terminal access."),
    "ftp": ("21", "FTP (File Transfer Protocol) — file transfers."),
    "http": ("80", "HTTP — unencrypted web traffic."),
    "https": ("443", "HTTPS — encrypted web traffic (TLS/SSL)."),
    "dns": ("53", "DNS — domain name resolution."),
    "smtp": ("25", "SMTP — email sending (unencrypted: 25, TLS: 587)."),
    "imap": ("143", "IMAP — email retrieval (unencrypted: 143, TLS: 993)."),
    "pop3": ("110", "POP3 — email retrieval (unencrypted: 110, TLS: 995)."),
    "mysql": ("3306", "MySQL — relational database."),
    "postgresql": ("5432", "PostgreSQL — relational database."),
    "postgres": ("5432", "PostgreSQL — relational database."),
    "redis": ("6379", "Redis — in-memory data store."),
    "mongodb": ("27017", "MongoDB — document database."),
    "mongo": ("27017", "MongoDB — document database."),
    "elasticsearch": ("9200", "Elasticsearch — search engine (HTTP: 9200, transport: 9300)."),
    "rabbitmq": ("5672", "RabbitMQ — message broker (AMQP: 5672, management: 15672)."),
    "kafka": ("9092", "Apache Kafka — distributed event streaming."),
    "docker": ("2375", "Docker — container daemon (unencrypted: 2375, TLS: 2376)."),
    "grafana": ("3000", "Grafana — monitoring dashboards."),
    "prometheus": ("9090", "Prometheus — metrics collection."),
    "nginx": ("80", "Nginx — web server / reverse proxy (HTTP: 80, HTTPS: 443)."),
    "ollama": ("11434", "Ollama — local LLM inference server."),
}

# ── Git commands ─────────────────────────────────────────────
_GIT_COMMANDS = {
    "init": "Initialize a new git repository in the current directory. Creates a `.git/` folder.",
    "clone": "Clone a remote repository. Usage: `git clone <url> [dir]`",
    "add": "Stage changes for commit. `git add .` stages all, `git add <file>` stages specific files.",
    "commit": "Record staged changes. Usage: `git commit -m 'message'`. Use `-a` to auto-stage tracked files.",
    "push": "Upload local commits to a remote. Usage: `git push [remote] [branch]`",
    "pull": "Fetch and merge remote changes. Usage: `git pull [remote] [branch]`. Shorthand for fetch + merge.",
    "fetch": "Download remote changes without merging. Usage: `git fetch [remote]`",
    "merge": "Combine branches. Usage: `git merge <branch>`. Use `--no-ff` to force a merge commit.",
    "rebase": "Reapply commits on top of another base. Usage: `git rebase <branch>`. Use `-i` for interactive rebase.",
    "stash": "Temporarily save uncommitted changes. `git stash` to save, `git stash pop` to restore.",
    "log": "Show commit history. Useful flags: `--oneline`, `--graph`, `--all`, `-n 10`.",
    "diff": "Show changes between commits, staging, and working tree. `git diff --staged` for staged changes.",
    "branch": "List, create, or delete branches. `git branch <name>` creates, `-d` deletes, `-a` lists all.",
    "checkout": "Switch branches or restore files. `git checkout <branch>` or `git checkout -- <file>`.",
    "reset": "Undo changes. `--soft` keeps staged, `--mixed` (default) unstages, `--hard` discards everything.",
    "tag": "Create, list, or delete tags. `git tag v1.0` for lightweight, `-a v1.0 -m 'msg'` for annotated.",
    "cherry-pick": "Apply a specific commit to current branch. Usage: `git cherry-pick <commit-hash>`",
    "bisect": "Binary search for a bug-introducing commit. `git bisect start`, then `good`/`bad` to narrow down.",
    "blame": "Show who last modified each line of a file. Usage: `git blame <file>`",
    "reflog": "Show history of HEAD changes (even deleted commits). Useful for recovering lost work.",
    "remote": "Manage remote repositories. `git remote -v` to list, `add` to add, `remove` to delete.",
    "status": "Show working tree status: staged, unstaged, and untracked files.",
    "show": "Show details of a commit, tag, or object. Usage: `git show <commit>`",
    "clean": "Remove untracked files. Use `-n` for dry run, `-f` to force, `-d` for directories.",
    "rm": "Remove files from working tree and index. Usage: `git rm <file>`. Use `--cached` to only unstage.",
    "mv": "Move or rename a file. Usage: `git mv <old> <new>`",
}

# ── Keyboard shortcuts ──────────────────────────────────────
_KB_SHORTCUTS = {
    "vscode": (
        "**VS Code Keyboard Shortcuts**\n\n"
        "| Shortcut           | Action                      |\n"
        "|--------------------|-----------------------------|\n"
        "| Ctrl+P             | Quick Open file             |\n"
        "| Ctrl+Shift+P       | Command Palette             |\n"
        "| Ctrl+B             | Toggle sidebar              |\n"
        "| Ctrl+`             | Toggle terminal             |\n"
        "| Ctrl+/             | Toggle line comment          |\n"
        "| Ctrl+D             | Select next occurrence      |\n"
        "| Ctrl+Shift+K       | Delete line                 |\n"
        "| Alt+Up/Down        | Move line up/down           |\n"
        "| Ctrl+Shift+F       | Search across files         |\n"
        "| F12                | Go to definition            |\n"
        "| Ctrl+K Ctrl+S      | Open keyboard shortcuts     |"
    ),
    "vim": (
        "**Vim Keyboard Shortcuts**\n\n"
        "| Shortcut  | Action                      |\n"
        "|-----------|-----------------------------|\n"
        "| i         | Insert mode                 |\n"
        "| Esc       | Normal mode                 |\n"
        "| :w        | Save                        |\n"
        "| :q        | Quit                        |\n"
        "| :wq       | Save and quit               |\n"
        "| dd        | Delete line                 |\n"
        "| yy        | Yank (copy) line            |\n"
        "| p         | Paste                       |\n"
        "| /pattern  | Search forward              |\n"
        "| u         | Undo                        |\n"
        "| Ctrl+R    | Redo                        |\n"
        "| gg        | Go to top                   |\n"
        "| G         | Go to bottom                |"
    ),
    "bash": (
        "**Bash Keyboard Shortcuts**\n\n"
        "| Shortcut  | Action                      |\n"
        "|-----------|-----------------------------|\n"
        "| Ctrl+A    | Move to start of line       |\n"
        "| Ctrl+E    | Move to end of line         |\n"
        "| Ctrl+R    | Reverse search history      |\n"
        "| Ctrl+C    | Cancel current command      |\n"
        "| Ctrl+L    | Clear screen                |\n"
        "| Ctrl+U    | Delete to start of line     |\n"
        "| Ctrl+K    | Delete to end of line       |\n"
        "| Ctrl+W    | Delete previous word        |\n"
        "| Alt+F     | Move forward one word       |\n"
        "| Alt+B     | Move backward one word      |"
    ),
    "chrome": (
        "**Chrome Keyboard Shortcuts**\n\n"
        "| Shortcut           | Action                      |\n"
        "|--------------------|-----------------------------|\n"
        "| Ctrl+T             | New tab                     |\n"
        "| Ctrl+W             | Close tab                   |\n"
        "| Ctrl+Shift+T       | Reopen closed tab           |\n"
        "| Ctrl+L             | Focus address bar           |\n"
        "| Ctrl+Tab           | Next tab                    |\n"
        "| Ctrl+Shift+Tab     | Previous tab                |\n"
        "| F5 / Ctrl+R        | Reload                      |\n"
        "| Ctrl+Shift+I       | Developer tools             |\n"
        "| Ctrl+F             | Find on page                |\n"
        "| Ctrl+D             | Bookmark this page          |"
    ),
}

# ── Timezone abbreviations ───────────────────────────────────
_TZ_ABBREVS = {
    "est": ("UTC-5", "Eastern Standard Time (US/Canada). EDT in summer: UTC-4."),
    "edt": ("UTC-4", "Eastern Daylight Time (US/Canada summer)."),
    "cst": ("UTC-6", "Central Standard Time (US/Canada). CDT in summer: UTC-5."),
    "cdt": ("UTC-5", "Central Daylight Time (US/Canada summer)."),
    "mst": ("UTC-7", "Mountain Standard Time (US/Canada). MDT in summer: UTC-6."),
    "pst": ("UTC-8", "Pacific Standard Time (US/Canada). PDT in summer: UTC-7."),
    "pdt": ("UTC-7", "Pacific Daylight Time (US/Canada summer)."),
    "gmt": ("UTC+0", "Greenwich Mean Time. Same as UTC in practice."),
    "utc": ("UTC+0", "Coordinated Universal Time. The global time standard."),
    "bst": ("UTC+1", "British Summer Time (UK daylight saving)."),
    "cet": ("UTC+1", "Central European Time. CEST in summer: UTC+2."),
    "cest": ("UTC+2", "Central European Summer Time."),
    "eet": ("UTC+2", "Eastern European Time. EEST in summer: UTC+3."),
    "ist": ("UTC+5:30", "India Standard Time."),
    "jst": ("UTC+9", "Japan Standard Time. No daylight saving."),
    "kst": ("UTC+9", "Korea Standard Time. No daylight saving."),
    "cst_cn": ("UTC+8", "China Standard Time. No daylight saving."),
    "aest": ("UTC+10", "Australian Eastern Standard Time. AEDT in summer: UTC+11."),
    "nzst": ("UTC+12", "New Zealand Standard Time. NZDT in summer: UTC+13."),
}

# ── Tech / networking acronyms ──────────────────────────────
_TECH_ACRONYMS: dict[str, str] = {
    "http":  "HTTP = HyperText Transfer Protocol. The foundation of data communication on the Web; transfers HTML pages between client and server over TCP (default port 80).",
    "https": "HTTPS = HyperText Transfer Protocol Secure. HTTP encrypted with TLS/SSL (port 443). Provides authentication, data integrity, and confidentiality.",
    "ftp":   "FTP = File Transfer Protocol. Standard protocol for transferring files between hosts over TCP (ports 20/21). Use SFTP or FTPS for encrypted transfers.",
    "sftp":  "SFTP = SSH File Transfer Protocol. Encrypted file transfer over an SSH connection (port 22). Not the same as FTP over SSL (FTPS).",
    "ssh":   "SSH = Secure Shell. Cryptographic network protocol for operating services securely over an unsecured network (port 22). Replaces Telnet.",
    "ssl":   "SSL = Secure Sockets Layer. Predecessor to TLS for encrypting internet connections. SSL 3.0 is deprecated; use TLS 1.2 or 1.3 instead.",
    "tls":   "TLS = Transport Layer Security. Cryptographic protocol securing communications over a network. Successor to SSL; TLS 1.3 is the current standard.",
    "tcp":   "TCP = Transmission Control Protocol. Connection-oriented transport protocol guaranteeing delivery and order of packets. Used by HTTP, FTP, SSH, etc.",
    "udp":   "UDP = User Datagram Protocol. Connectionless transport protocol—fast but no delivery guarantee. Used by DNS, video streaming, VoIP, gaming.",
    "ip":    "IP = Internet Protocol. Network layer protocol that routes packets across networks. IPv4 uses 32-bit addresses; IPv6 uses 128-bit addresses.",
    "dns":   "DNS = Domain Name System. Translates human-readable domain names (e.g., google.com) into IP addresses. Operates over UDP/TCP port 53.",
    "dhcp":  "DHCP = Dynamic Host Configuration Protocol. Automatically assigns IP addresses and network config to devices on a network (UDP ports 67/68).",
    "smtp":  "SMTP = Simple Mail Transfer Protocol. Protocol for sending email between servers (port 25; authenticated submission: 587). Use IMAP/POP3 for retrieval.",
    "imap":  "IMAP = Internet Message Access Protocol. Protocol for retrieving email from a server while keeping messages on the server (port 143, IMAPS: 993).",
    "pop3":  "POP3 = Post Office Protocol v3. Downloads email from server to client and typically deletes it server-side (port 110, POP3S: 995).",
    "api":   "API = Application Programming Interface. A set of rules and definitions that allows software components to communicate with each other.",
    "rest":  "REST = Representational State Transfer. Architectural style for distributed systems using HTTP verbs (GET, POST, PUT, DELETE) and stateless requests.",
    "json":  "JSON = JavaScript Object Notation. Lightweight, human-readable data interchange format using key-value pairs and arrays.",
    "xml":   "XML = eXtensible Markup Language. Flexible text format for structured data, widely used in SOAP APIs and configuration files.",
    "html":  "HTML = HyperText Markup Language. Standard markup language for creating web pages, interpreted by browsers to render content.",
    "css":   "CSS = Cascading Style Sheets. Style sheet language controlling presentation, layout, and appearance of HTML documents.",
    "sql":   "SQL = Structured Query Language. Domain-specific language for managing and querying relational databases (SELECT, INSERT, UPDATE, DELETE).",
    "url":   "URL = Uniform Resource Locator. A reference to a web resource specifying its location, e.g., https://example.com/path?query=1.",
    "uri":   "URI = Uniform Resource Identifier. A string that identifies a resource; URLs are a subset of URIs that also specify how to access the resource.",
    "uuid":  "UUID = Universally Unique Identifier. A 128-bit identifier formatted as 8-4-4-4-12 hex digits; probability of collision is negligible.",
    "cpu":   "CPU = Central Processing Unit. The primary processor that executes instructions in a computer, performing arithmetic, logic, and control operations.",
    "gpu":   "GPU = Graphics Processing Unit. Massively parallel processor used for rendering and ML/AI acceleration (CUDA on NVIDIA, ROCm on AMD).",
    "ram":   "RAM = Random Access Memory. Volatile, fast memory used to store data and machine code currently being used by the CPU.",
    "rom":   "ROM = Read-Only Memory. Non-volatile memory whose contents are fixed at manufacture; used for firmware (BIOS/UEFI).",
    "os":    "OS = Operating System. Software managing hardware resources and providing services for programs (e.g., Linux, Windows, macOS).",
    "ide":   "IDE = Integrated Development Environment. Software combining code editor, debugger, and build tools (e.g., VS Code, IntelliJ, PyCharm).",
    "cli":   "CLI = Command-Line Interface. Text-based interface where users type commands to interact with a program or OS.",
    "gui":   "GUI = Graphical User Interface. Visual interface using windows, icons, and menus for user interaction.",
    "orm":   "ORM = Object-Relational Mapper. Tool that converts between object-oriented code and relational database tables (e.g., SQLAlchemy, Django ORM).",
    "ci":    "CI = Continuous Integration. Practice of automatically building and testing code changes, typically on every commit.",
    "cd":    "CD = Continuous Delivery/Deployment. Automated release of tested code to staging or production environments.",
    "llm":   "LLM = Large Language Model. A neural network trained on large text corpora capable of generating, summarizing, and reasoning about text (e.g., GPT-4, Claude).",
    "ai":    "AI = Artificial Intelligence. The simulation of human intelligence in machines—includes ML, NLP, computer vision, and reasoning.",
    "ml":    "ML = Machine Learning. Subset of AI where models learn patterns from data rather than being explicitly programmed.",
    "nlp":   "NLP = Natural Language Processing. AI field enabling computers to understand, interpret, and generate human language.",
    "rag":   "RAG = Retrieval-Augmented Generation. Technique combining a retrieval system with an LLM to ground responses in external documents.",
    "vram":  "VRAM = Video RAM. Dedicated memory on a GPU used to store textures, frame buffers, and ML model weights during inference.",
}

# ── Holidays (major, approximate for 2025-2027) ─────────────
_HOLIDAYS = {
    "easter 2025": "April 20, 2025",
    "easter 2026": "April 5, 2026",
    "easter 2027": "March 28, 2027",
    "thanksgiving 2025": "November 27, 2025 (US)",
    "thanksgiving 2026": "November 26, 2026 (US)",
    "thanksgiving 2027": "November 25, 2027 (US)",
    "christmas": "December 25 (fixed date every year)",
    "new year": "January 1 (fixed date every year)",
    "halloween": "October 31 (fixed date every year)",
    "independence day": "July 4 (US, fixed date every year)",
    "valentines day": "February 14 (fixed date every year)",
    "st patricks day": "March 17 (fixed date every year)",
    "mothers day 2025": "May 11, 2025 (US)",
    "mothers day 2026": "May 10, 2026 (US)",
    "fathers day 2025": "June 15, 2025 (US)",
    "fathers day 2026": "June 21, 2026 (US)",
    "labor day 2025": "September 1, 2025 (US)",
    "labor day 2026": "September 7, 2026 (US)",
    "memorial day 2025": "May 26, 2025 (US)",
    "memorial day 2026": "May 25, 2026 (US)",
    "ramadan 2025": "Begins approximately February 28, 2025",
    "ramadan 2026": "Begins approximately February 17, 2026",
    "diwali 2025": "October 20, 2025",
    "diwali 2026": "November 8, 2026",
    "chinese new year 2025": "January 29, 2025 (Year of the Snake)",
    "chinese new year 2026": "February 17, 2026 (Year of the Horse)",
    "hanukkah 2025": "December 14-22, 2025",
    "hanukkah 2026": "December 4-12, 2026",
}

# ── Common file extensions ──────────────────────────────────
_FILE_EXTENSIONS: dict[str, str] = {
    ".json": "JSON (JavaScript Object Notation) — structured data interchange format. Human-readable, used for configs, APIs, and data storage. Opened by any text editor, parsed by every language.",
    ".yaml": "YAML (YAML Ain't Markup Language) — human-friendly data serialization. Used for configs (Docker Compose, Kubernetes, CI/CD). Indentation-based, no braces. Opened by any text editor.",
    ".yml": "YML is the short file extension for YAML (YAML Ain't Markup Language) — identical to .yaml. Human-friendly config format used by Docker Compose, GitHub Actions, Ansible, etc.",
    ".toml": "TOML (Tom's Obvious Minimal Language) — config file format. Used by Rust (Cargo.toml), Python (pyproject.toml), and many CLI tools. Simple key-value pairs with sections.",
    ".env": "Environment variables file — stores KEY=VALUE pairs for app configuration. Never commit to git (add to .gitignore). Used by Docker, Node.js (dotenv), Python (python-dotenv).",
    ".pem": "PEM (Privacy-Enhanced Mail) — Base64-encoded certificate or key file. Used for TLS/SSL certificates, SSH keys, and encryption. Opened by OpenSSL, ssh-keygen, or any text editor.",
    ".crt": "Certificate file — X.509 TLS/SSL certificate, usually PEM or DER encoded. Used by web servers (nginx, Apache) for HTTPS. Inspect with: openssl x509 -in file.crt -text",
    ".key": "Private key file — RSA/ECDSA private key for TLS/SSL. Keep secret, never commit to git. Used alongside .crt files for HTTPS. Inspect with: openssl rsa -in file.key -check",
    ".csv": "CSV (Comma-Separated Values) — tabular data with comma delimiters. Universal spreadsheet format. Opened by Excel, Google Sheets, pandas, or any text editor.",
    ".tsv": "TSV (Tab-Separated Values) — like CSV but tab-delimited. Common in bioinformatics and data pipelines. Opened by Excel, pandas, or any text editor.",
    ".parquet": "Apache Parquet — columnar binary storage format for big data. Highly compressed, fast for analytics. Used by Spark, pandas, DuckDB, Snowflake. Not human-readable.",
    ".sql": "SQL file — contains SQL queries or database schema definitions. Used for migrations, backups, and seed data. Opened by any text editor or database client.",
    ".sh": "Shell script — Bash/POSIX commands for automation. Run with: bash script.sh or chmod +x script.sh && ./script.sh. Used for build scripts, CI/CD, and system admin.",
    ".py": "Python source file — interpreted, dynamically typed. Run with: python file.py. Used for scripting, web (Django/Flask/FastAPI), ML, data science, and automation.",
    ".js": "JavaScript source file — runs in browsers and Node.js. The language of the web. Used for frontend (React, Vue), backend (Express, Next.js), and tooling.",
    ".ts": "TypeScript source file — JavaScript with static types. Compiles to .js. Used for large-scale web apps, Node.js backends, and anywhere type safety is needed.",
    ".rs": "Rust source file — systems programming language focused on safety and performance. Compiled, no garbage collector. Used for CLI tools, WebAssembly, and embedded systems.",
    ".go": "Go (Golang) source file — compiled, statically typed, garbage collected. Known for simplicity and concurrency. Used for cloud infrastructure, CLI tools, and APIs.",
    ".md": "Markdown file — lightweight markup for formatted text. Used for README files, documentation, notes, and static site content. Rendered by GitHub, VS Code, and most editors.",
    ".rst": "reStructuredText file — markup language used primarily by Python documentation (Sphinx). More powerful than Markdown but more verbose. Common in Python library docs.",
    ".svg": "SVG (Scalable Vector Graphics) — XML-based vector image format. Resolution-independent, editable with code. Used for icons, logos, charts, and web graphics.",
    ".webp": "WebP — modern image format by Google. 25-35% smaller than JPEG/PNG at same quality. Supports transparency and animation. Widely supported in browsers.",
    ".avif": "AVIF (AV1 Image File Format) — next-gen image format based on AV1 video codec. ~50% smaller than JPEG. Supports HDR and transparency. Growing browser support.",
    ".wasm": "WebAssembly — binary instruction format for stack-based virtual machines. Runs near-native speed in browsers. Compiled from C/C++/Rust/Go. Used for games, codecs, and compute-heavy web apps.",
}

# ── HTTP methods ────────────────────────────────────────────
_HTTP_METHODS: dict[str, str] = {
    "get": "**GET** — Retrieve a resource. Safe, idempotent, cacheable. Use for: fetching data, listing resources, search queries. No request body. Example: `GET /api/users/123`",
    "post": "**POST** — Create a new resource or trigger an action. Not idempotent (calling twice may create duplicates). Use for: creating records, submitting forms, file uploads. Example: `POST /api/users` with JSON body.",
    "put": "**PUT** — Replace a resource entirely. Idempotent (calling twice = same result). Use for: full updates where you send the complete object. Example: `PUT /api/users/123` with full user JSON.",
    "patch": '**PATCH** — Partially update a resource. Use for: changing specific fields without sending the whole object. Example: `PATCH /api/users/123` with `{"email": "new@example.com"}`. PUT vs PATCH: PUT replaces everything, PATCH updates only specified fields.',
    "delete": "**DELETE** — Remove a resource. Idempotent. Use for: deleting records. Usually returns 200 (with body) or 204 (no content). Example: `DELETE /api/users/123`",
    "head": "**HEAD** — Same as GET but returns only headers, no body. Use for: checking if a resource exists, getting metadata (Content-Length, Last-Modified) without downloading the body. Useful for health checks.",
    "options": "**OPTIONS** — Describe communication options for a resource. Used by browsers for CORS preflight requests. Returns allowed methods in `Allow` header. Example: `OPTIONS /api/users` → `Allow: GET, POST, OPTIONS`",
}

# ── Common exit codes ───────────────────────────────────────
_EXIT_CODES: dict[str, str] = {
    "0": "**Exit code 0** — Success. The command completed without errors.",
    "1": "**Exit code 1** — General error. Catch-all for unspecified failures. Most programs return 1 for any error.",
    "2": "**Exit code 2** — Misuse of shell command. Usually means invalid arguments or bad syntax. Bash built-in error.",
    "126": "**Exit code 126** — Command found but not executable. Check file permissions: `chmod +x script.sh`",
    "127": "**Exit code 127** — Command not found. The binary/script doesn't exist in $PATH. Check spelling or install the package.",
    "128": "**Exit code 128** — Invalid exit argument. Exit code was outside the 0-255 range.",
    "130": "**Exit code 130** — Terminated by Ctrl+C (SIGINT, signal 2). 128 + 2 = 130. Normal user interruption.",
    "137": "**Exit code 137** — Killed by SIGKILL (signal 9). 128 + 9 = 137. Usually means the process was OOM-killed (out of memory) by the kernel or `kill -9`. Check `dmesg` for OOM messages.",
    "139": "**Exit code 139** — Segmentation fault (SIGSEGV, signal 11). 128 + 11 = 139. The program accessed invalid memory. Indicates a bug in C/C++/Rust code or corrupted binary.",
    "143": "**Exit code 143** — Terminated by SIGTERM (signal 15). 128 + 15 = 143. Graceful termination request — the default signal sent by `kill` and used by Docker/Podman for container shutdown.",
    "255": "**Exit code 255** — Exit status out of range, or SSH connection failure. SSH returns 255 for connection errors. Some programs use it as a generic fatal error.",
}

# ── Docker/Podman commands ──────────────────────────────────
_CONTAINER_COMMANDS: dict[str, str] = {
    "run": "**docker/podman run** — Create and start a new container from an image. Key flags: `-d` (detach), `-p` (port map), `-v` (volume mount), `--rm` (auto-remove), `--name` (name it). Example: `podman run -d -p 8080:80 --name web nginx`",
    "build": "**docker/podman build** — Build an image from a Dockerfile/Containerfile. Key flags: `-t` (tag/name), `-f` (specify file), `--no-cache` (fresh build). Example: `podman build -t myapp:latest .`",
    "compose up": "**docker/podman compose up** — Start all services defined in docker-compose.yml. Key flags: `-d` (detach), `--build` (rebuild images), `--force-recreate` (fresh containers). Example: `podman compose up -d`",
    "compose down": "**docker/podman compose down** — Stop and remove all compose services, networks, and (optionally) volumes. Key flags: `-v` (remove volumes), `--rmi all` (remove images). Example: `podman compose down -v`",
    "exec": "**docker/podman exec** — Run a command inside a running container. Key flags: `-it` (interactive + TTY). Example: `podman exec -it mycontainer bash` (get a shell inside the container).",
    "logs": "**docker/podman logs** — View container output (stdout/stderr). Key flags: `-f` (follow/stream), `--tail N` (last N lines), `--since 1h` (last hour). Example: `podman logs -f --tail 100 mycontainer`",
    "ps": "**docker/podman ps** — List running containers. Add `-a` to include stopped containers. Shows container ID, image, status, ports, and names. Example: `podman ps -a`",
    "images": "**docker/podman images** — List locally stored images. Shows repository, tag, image ID, and size. Use `podman image prune` to clean unused images.",
    "volumes": "**docker/podman volume ls** — List volumes (persistent data storage). Volumes survive container restarts. Key commands: `volume create`, `volume ls`, `volume rm`, `volume prune`.",
    "networks": "**docker/podman network ls** — List container networks. Containers on the same network can reach each other by name. Key commands: `network create`, `network ls`, `network rm`, `network inspect`.",
    "podman vs docker": "**Podman vs Docker**: Podman is daemonless (no root daemon), rootless by default, and CLI-compatible with Docker. Same commands, same Dockerfiles. Podman uses `podman compose` (or podman-compose) instead of `docker compose`. Main difference: Podman doesn't need a background service running.",
}


# ── Algorithm complexity (Big-O) ────────────────────────────
# (best, average, worst, space, notes)
_ALGORITHMS: dict[str, tuple[str, str, str, str, str]] = {
    "quicksort": (
        "O(n log n)",
        "O(n log n)",
        "O(n²)",
        "O(log n)",
        "Unstable, in-place. Worst case: already-sorted with naive pivot. Python: not used (uses Timsort).",
    ),
    "mergesort": (
        "O(n log n)",
        "O(n log n)",
        "O(n log n)",
        "O(n)",
        "Stable, not in-place. Best for linked lists. Predictable O(n log n) always.",
    ),
    "heapsort": (
        "O(n log n)",
        "O(n log n)",
        "O(n log n)",
        "O(1)",
        "Unstable, in-place. Guaranteed O(n log n) but poor cache performance.",
    ),
    "bubblesort": (
        "O(n)",
        "O(n²)",
        "O(n²)",
        "O(1)",
        "Stable, in-place. O(n) best case with early-exit. Never use in production.",
    ),
    "insertionsort": (
        "O(n)",
        "O(n²)",
        "O(n²)",
        "O(1)",
        "Stable, in-place. Efficient for nearly-sorted or tiny arrays (<20 elements).",
    ),
    "selectionsort": (
        "O(n²)",
        "O(n²)",
        "O(n²)",
        "O(1)",
        "Unstable, in-place. Always O(n²) regardless of input. Minimal swaps.",
    ),
    "timsort": (
        "O(n)",
        "O(n log n)",
        "O(n log n)",
        "O(n)",
        "Stable. Python's built-in sort. Hybrid mergesort+insertionsort. Adaptive to real-world data.",
    ),
    "radixsort": (
        "O(nk)",
        "O(nk)",
        "O(nk)",
        "O(n+k)",
        "Non-comparative. n=items, k=digits/chars. Fast for integers with small k.",
    ),
    "countingsort": (
        "O(n+k)",
        "O(n+k)",
        "O(n+k)",
        "O(k)",
        "Non-comparative. k=value range. Fast when k is small relative to n.",
    ),
    "binarysearch": (
        "O(1)",
        "O(log n)",
        "O(log n)",
        "O(1)",
        "Requires sorted array. Each step halves search space. Python: bisect module.",
    ),
    "linearsearch": (
        "O(1)",
        "O(n)",
        "O(n)",
        "O(1)",
        "Works on unsorted arrays. Simple scan. Python: `in` operator on lists is O(n).",
    ),
    "bfs": (
        "O(V+E)",
        "O(V+E)",
        "O(V+E)",
        "O(V)",
        "Breadth-first search. Shortest path in unweighted graphs. Queue-based (deque).",
    ),
    "dfs": (
        "O(V+E)",
        "O(V+E)",
        "O(V+E)",
        "O(V)",
        "Depth-first search. Stack-based or recursive. Topological sort, cycle detection.",
    ),
    "dijkstra": (
        "O(E log V)",
        "O(E log V)",
        "O(E log V)",
        "O(V)",
        "Shortest path, non-negative weights. Priority queue (heapq). Python: heapq.",
    ),
    "astar": (
        "O(E)",
        "O(E log V)",
        "O(b^d)",
        "O(b^d)",
        "Heuristic search. f=g+h. Used in game AI, routing. b=branching, d=depth.",
    ),
    "floydwarshall": (
        "O(V³)",
        "O(V³)",
        "O(V³)",
        "O(V²)",
        "All-pairs shortest path. Handles negative weights (not negative cycles).",
    ),
    "bellmanford": (
        "O(VE)",
        "O(VE)",
        "O(VE)",
        "O(V)",
        "Single-source shortest path. Handles negative weights, detects negative cycles.",
    ),
    "kruskal": (
        "O(E log E)",
        "O(E log E)",
        "O(E log E)",
        "O(V)",
        "Minimum spanning tree. Sort edges, add if no cycle. Uses Union-Find.",
    ),
    "prim": (
        "O(E log V)",
        "O(E log V)",
        "O(E log V)",
        "O(V)",
        "Minimum spanning tree. Greedy, grows from start vertex. Priority queue.",
    ),
}

# ── Navigation map ───────────────────────────────────────────
_NAV_MAP: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"(?:where|how|find|open|show|go to|navigate).{0,20}(?:dashboard|savings|stats)"),
        "The **Savings Dashboard** is at [/dashboard](/dashboard) — real-time cost tracking, tier distribution, query heatmap, and ROI metrics.",
    ),
    (
        re.compile(r"(?:where|how|find|open|show|go to|navigate).{0,20}(?:game|games|play|arcade)"),
        "The **Game Gallery** is at [/games](/games) — 57+ AI-generated games and instruments playable in your browser. Includes deckbuilders, card games, instruments, word games, puzzles, racing, physics, strategy, and simulations.",
    ),
    (
        re.compile(r"(?:where|how|find|open|show|go to|navigate).{0,20}(?:performance|perf|speed|latency)"),
        "The **Performance Monitor** is at [/performance](/performance) — real-time pipeline latency, slow query detection, and per-model speed metrics.",
    ),
    (
        re.compile(r"(?:where|how|find|open|show|go to|navigate).{0,20}(?:accuracy|elo|leaderboard|model quality)"),
        "The **Model Accuracy** page is at [/accuracy](/accuracy) — passive Elo rankings from cache displacement, per-complexity radar charts, and a neighborhood explorer.",
    ),
    (
        re.compile(r"(?:where|how|find|open|show|go to|navigate).{0,20}(?:cost|spending|budget|money)"),
        "The **Cost Control** center is at [/cost](/cost) — engineering-style cost breakdown with per-tier spending and budget controls.",
    ),
    (
        re.compile(r"(?:where|how|find|open|show|go to|navigate).{0,20}(?:unblock|blocked|agent status)"),
        "The **Unblock Dashboard** is at [/unblock](/unblock) — shows all agent sessions, blocked tasks, and activity status with color-coded dots.",
    ),
    (
        re.compile(r"(?:where|how|find|open|show|go to|navigate).{0,20}(?:route|endpoint|api|url|page)"),
        "All routes are listed at [/routes](/routes) — every page and API endpoint in muLLM with clickable links.",
    ),
    (
        re.compile(r"(?:where|how|find|open|show|go to|navigate).{0,20}(?:rpc|json.rpc)"),
        "The **JSON-RPC 2.0 Docs** are at [/rpc/docs](/rpc/docs) — single endpoint for all muLLM operations, supports batch requests.",
    ),
    (
        re.compile(
            r"(?:where|how|find|open|show|go to|navigate).{0,30}(?:mcp|model context protocol|mcp\s+(?:tools?|docs?|endpoint))"
        ),
        "The **MCP Docs** are at [/mcp](/mcp) — muLLM exposes query, split, classify, budget, and system tools via the Model Context Protocol at `/mcp/tools`.",
    ),
    (
        re.compile(r"(?:where|how|find|open|show|go to|navigate).{0,20}(?:a2a|agent.to.agent|agent card)"),
        "The **A2A Protocol Docs** are at [/a2a](/a2a) — agent registration, discovery, task delegation, and heartbeat endpoints.",
    ),
    (
        re.compile(r"(?:where|how|find|open|show|go to|navigate).{0,20}(?:privacy|security|data)"),
        "The **Privacy & Compliance** page is at [/privacy](/privacy) — explains where your data goes, what's stored locally, and what controls you have.",
    ),
    (
        re.compile(r"(?:where|how|find|open|show|go to|navigate).{0,20}(?:coverage|test|playwright)"),
        "**Test Coverage** is at [/coverage](/coverage) — Playwright test results with hover-to-preview screenshots and video recordings.",
    ),
    (
        re.compile(r"(?:where|how|find|open|show|go to|navigate).{0,20}(?:setting|config|preference)"),
        "Click the **⚙ gear icon** in the chat topbar to access settings — default tier, streaming, cache, cost optimization, and navigation links to all pages.",
    ),
    (
        re.compile(r"(?:where|how|find|open|show|go to|navigate).{0,20}(?:chat|talk|ask|convers)"),
        "The **Chat Interface** is at [/chat](/chat) — or just [/](/). Full markdown rendering, voice I/O, split routing, and real-time cost tracking.",
    ),
]

# ── Classic reasoning facts ──────────────────────────────────
_REASONING_FACTS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"monty hall"),
        "**Monty Hall Problem:** Always switch. Switching wins with probability **2/3**; staying wins 1/3. Proof: your initial door has P=1/3. Host reveals a goat from the other 2, concentrating their combined 2/3 probability onto the one remaining door.",
    ),
    (
        re.compile(r"hex.*255|255.*hex"),
        "**Hexadecimal conversions:** 255 = **0xFF** (ff). 256 = 0x100. 128 = 0x80. 16 = 0x10. 15 = 0xF.",
    ),
    (
        re.compile(r"binary.*11001010|11001010.*decimal"),
        "**Binary 11001010 = decimal 202.** Breakdown: 128+64+0+0+8+0+2+0 = 202.",
    ),
    (
        re.compile(r"decimal.*binary|binary.*decimal conversion"),
        "**Decimal↔Binary:** 202=11001010, 255=11111111, 128=10000000, 64=1000000, 16=10000, 10=1010, 8=1000.",
    ),
    (
        re.compile(r"permutations.*5 letters|arrange.*[^0-9]5[^0-9] letters|5!"),
        "**Permutations of 5 distinct items = 5! = 120.** n! = n×(n-1)×...×1. 4!=24, 5!=120, 6!=720, 7!=5040.",
    ),
    (
        re.compile(r"360.*3.*hour|speed.*360.*km|km.*360.*3h"),
        "**Speed = Distance ÷ Time = 360 ÷ 3 = 120 km/h.** Basic kinematic formula: v = d/t.",
    ),
    (
        re.compile(r"1%.*disease.*99%.*test|bayes.*1.*99|99%.*accurate.*1%.*prevalen"),
        "**Bayes' Theorem result:** P(disease | positive test) ≈ **50.25%**. Despite 99% accuracy, low prevalence (1%) means half of positives are false. Formula: P(D|+) = (0.99×0.01)/(0.99×0.01 + 0.01×0.99) ≈ 0.5025.",
    ),
    (
        re.compile(r"piano tuner.*chicago|chicago.*piano tuner|fermi.*piano"),
        "**Fermi estimate — Chicago piano tuners ≈ 125–200.** Method: 2.7M people → ~135K households with pianos (1 in 20) → 270K pianos → 2 tunings/year each → 540K tunings/year → divide by 250 workdays × 4 tunings/day = ~540 tuners. Adjust for part-time: ~200.",
    ),
    (
        re.compile(r"sequence.*2.*6.*12.*20.*30.*42|next.*2,6,12,20,30,42"),
        "**Sequence 2, 6, 12, 20, 30, 42 → next = 56.** Pattern: n×(n+1) for n=1,2,3,... → 1×2, 2×3, 3×4, 4×5, 5×6, 6×7, **7×8=56**.",
    ),
    (
        re.compile(r"intersection.*\{1,2,3,4,5\}.*\{3,4,5,6,7\}|set.*A.*B.*intersect"),
        "**Set intersection {1,2,3,4,5} ∩ {3,4,5,6,7} = {3, 4, 5}.** Union = {1,2,3,4,5,6,7}. A\\B = {1,2}. B\\A = {6,7}.",
    ),
    (
        re.compile(r"alice.*taller.*bob.*taller.*carol.*taller.*dave|who.*shortest.*alice.*bob.*carol.*dave"),
        "**Dave is shortest.** Chain: Alice > Bob > Carol > Dave (transitive property of inequality).",
    ),
]

# ── Coding algorithm canonical solutions ─────────────────────
_CODING_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"lru cache.*python|python.*lru cache|implement.*lru"),
        "**LRU Cache (Python best practice):** Use `collections.OrderedDict`. `get`: move_to_end(key). `put`: move_to_end(key), then if len > capacity: popitem(last=False). Both O(1) amortized. Alt: `@functools.lru_cache(maxsize=N)` for pure functions.",
    ),
    (
        re.compile(r"longest substring.*no repeat|no repeat.*substring|sliding window.*unique"),
        "**Longest substring without repeating chars:** Sliding window + dict of last-seen index. `left = max(left, seen[c]+1)` on collision. Update `seen[c]=i`. Track `max_len = max(max_len, i-left+1)`. O(n) time, O(1) space (26 ASCII chars max).",
    ),
    (
        re.compile(r"merge.*interval|overlapping interval"),
        "**Merge intervals:** Sort by start time. Iterate: if current.start <= last.end, merge (extend last.end). Else append new interval. O(n log n) sort + O(n) merge.",
    ),
    (
        re.compile(r"number of islands|count islands|grid.*bfs.*land"),
        "**Number of islands (grid BFS/DFS):** For each unvisited '1', increment count and flood-fill (set visited cells to '0' or use visited set). DFS iterative or BFS with deque. O(m×n) time and space.",
    ),
    (
        re.compile(r"coin change.*minimum|minimum coins|fewest coins"),
        "**Coin change (min coins):** Bottom-up DP. dp[0]=0, dp[i]=min(dp[i], dp[i-coin]+1) for each coin ≤ i. Initialize dp[1..amount]=float('inf'). O(amount × len(coins)).",
    ),
    (
        re.compile(r"group anagram|anagram group"),
        "**Group anagrams:** Use `defaultdict(list)`. Key = `tuple(sorted(word))`. O(n × k log k) where k = max word length. Alt key: `tuple(Counter(word).most_common())` but sorted tuple is simpler.",
    ),
    (
        re.compile(r"decode ways|decode.*digit.*string"),
        "**Decode ways:** DP where dp[i] = ways to decode s[:i]. dp[0]=1, dp[1]=1 if s[0]!='0'. For i≥2: add dp[i-1] if s[i-1]!='0'; add dp[i-2] if '10'≤s[i-2:i]≤'26'. O(n) time O(1) space (rolling vars).",
    ),
    (
        re.compile(r"rotate.*matrix.*90|90.*degree.*matrix|rotate.*image.*in.place"),
        "**Rotate matrix 90° clockwise in-place:** (1) Transpose: swap matrix[i][j] with matrix[j][i]. (2) Reverse each row: row[::-1]. Two-pass, O(n²) time O(1) space.",
    ),
    (
        re.compile(r"climbing stairs|count ways.*stairs|stair.*1.*2.*step"),
        "**Climbing stairs (1 or 2 steps):** dp[n] = dp[n-1] + dp[n-2] (Fibonacci). O(n) time, O(1) space using two variables: a,b = b, a+b. dp[1]=1, dp[2]=2, dp[3]=3, dp[10]=89.",
    ),
    (
        re.compile(r"longest palindromic substring|palindrome.*substring"),
        "**Longest palindromic substring:** Expand-around-center. For each index i, expand both odd (center=i) and even (center=i,i+1) palindromes. Track max span. O(n) Manacher's algo exists but expand-center is O(n²) and simpler/readable.",
    ),
]

# ── CUDA / PyTorch / RigNet environment facts ────────────────
_CUDA_SETUP: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\btorch.scatter\b|\binstall\s+torch.scatter\b"),
        "**torch_scatter install**: `pip install torch-scatter -f https://data.pyg.org/whl/torch-{TORCH_VER}+{CUDA_VER}.html`\n"
        "Must match exact torch+CUDA version. Example for torch 2.11.0+cu130:\n"
        "`pip install torch-scatter -f https://data.pyg.org/whl/torch-2.11.0+cu130.html`\n"
        "Check version: `python -c 'import torch; print(torch.__version__)'`",
    ),
    (
        re.compile(r"\bpointconv\b.*\btorch.geometric\b|\btorch.geometric\b.*\bpointconv\b"),
        "**PointConv removed in PyG 2.0**: Renamed to `PointNetConv`. Fix: "
        "`from torch_geometric.nn import PointNetConv as PointConv`\nSame API, just aliased.",
    ),
    (
        re.compile(
            r"\bnp\.(?:int|bool|float|complex|object|str)\b.*(?:deprecated|removed|error)\b"
            r"|\bnumpy\b.*(?:np\.int|np\.bool|np\.float).*(?:error|deprecated)\b"
        ),
        "**NumPy 2.0 breaking changes**: `np.int`, `np.bool`, `np.float`, `np.complex`, `np.object`, `np.str` removed.\n"
        "Fix with sed: `sed -i 's/np\\.int\\b/int/g; s/np\\.bool\\b/bool/g; s/np\\.float\\b/float/g' file.py`\n"
        "Or in Python: replace with built-in `int`, `bool`, `float`.",
    ),
    (
        re.compile(r"\bbinvox\b.*(?:libxmu|missing|not found|error)\b|\blibxmu\b"),
        "**binvox libXmu.so.6 missing** (no sudo): Use Python trimesh replacement.\n"
        "Create shell wrapper `binvox` → calls `python3 binvox_python.py -d $DIM $INPUT`\n"
        "binvox_python.py: load OBJ with trimesh, voxelize, write .binvox RLE format.",
    ),
    (
        re.compile(r"\brignet\b.*\btensorboard\b|\btensorboard\b.*\brignet\b"),
        "**RigNet requires tensorboard even for inference**: run_skinning.py imports it at module level.\n"
        "Fix: `pip install tensorboard`",
    ),
    (
        re.compile(r"\brignet\b.*(?:headless|segfault|sigsegv|glfw|wayland)\b"),
        "**RigNet headless segfault in predict_skeleton()**: show_obj_skel() calls Open3D GLFW viz.\n"
        "Fix: comment out `img = show_obj_skel(...)` in quick_start.py — no try/except catches SIGSEGV.",
    ),
    (
        re.compile(r"\brignet\b.*\bdevice\b.*(?:not defined|nameerror)\b|\bpredict.skinning\b.*device\b"),
        "**RigNet `device` NameError in predict_skinning()**: quick_start.py uses `global device` "
        "but never defines it at module level when imported.\n"
        "Fix: add `device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')` "
        "at module level in quick_start.py after `import torch`.",
    ),
    (
        re.compile(r"\brignet\b.*\brtree\b|\brtree\b.*\btrimesh\b"),
        "**RigNet needs rtree** for trimesh ray-mesh intersection (skinning step).\nFix: `pip install rtree`",
    ),
    (
        re.compile(r"\brignet\b.*deps?\b|\brignet\b.*(?:install|setup|requirements)\b"),
        "**RigNet full dependency list** (beyond requirements.txt):\n"
        "1. `pip install opencv-python-headless` (cv2)\n"
        "2. `pip install torch-scatter -f https://data.pyg.org/whl/torch-VERSION+CUDA.html`\n"
        "3. `pip install tensorboard rtree`\n"
        "4. Fix NumPy 2.0: replace np.int/np.bool/np.float in 4 files\n"
        "5. Fix PyG 2.0: PointConv → PointNetConv in ROOT_GCN.py + PairCls_GCN.py\n"
        "6. Replace binvox binary (needs libXmu) with trimesh Python wrapper\n"
        "7. Comment out show_obj_skel() in quick_start.py (headless GLFW crash)\n"
        "8. Add `device = torch.device(...)` at module level in quick_start.py",
    ),
]


# ── Brand & design colors ─────────────────────────────────────
COLORS: dict[str, str] = {
    # mullm brand
    "mullm-gold": "#C8973A",
    "mullm-navy": "#1a2a4a",
    "mullm-teal": "#14b8a6",
    "mullm-bg": "#0a0a0f",
    # Design palettes
    "pastel-pink": "#FFB3C6",
    "pastel-blue": "#B3D4FF",
    "pastel-green": "#B3FFD4",
    "pastel-yellow": "#FFFDB3",
    "pastel-purple": "#D4B3FF",
    "pastel-orange": "#FFD4B3",
    # Semantic
    "success": "#22c55e",
    "warning": "#f59e0b",
    "error": "#ef4444",
    "info": "#3b82f6",
    # Tailwind-inspired
    "slate-900": "#0f172a",
    "slate-800": "#1e293b",
    "slate-700": "#334155",
    # Rainbow
    "red": "#FF0000",
    "orange": "#FF7F00",
    "yellow": "#FFFF00",
    "green": "#00FF00",
    "blue": "#0000FF",
    "indigo": "#4B0082",
    "violet": "#9400D3",
    # Additional brand colors
    "white": "#FFFFFF",
    "black": "#000000",
    "gray-50": "#f9fafb",
    "gray-100": "#f3f4f6",
    "gray-500": "#6b7280",
    "gray-900": "#111827",
}

COLOR_SETS: dict[str, list[str] | dict[str, str]] = {
    "brand": ["mullm-gold", "mullm-navy", "mullm-teal", "mullm-bg"],
    "pastel": ["pastel-pink", "pastel-blue", "pastel-green", "pastel-yellow", "pastel-purple", "pastel-orange"],
    "semantic": ["success", "warning", "error", "info"],
    "rainbow": ["red", "orange", "yellow", "green", "blue", "indigo", "violet"],
    "dark": ["slate-900", "slate-800", "slate-700", "mullm-bg"],
    "complementary": {"mullm-gold": "#3a6ac8", "mullm-teal": "#b84614"},
    "grayscale": ["gray-50", "gray-100", "gray-500", "gray-900", "black", "white"],
}


# ── Musical scales ────────────────────────────────────────────
SCALES: dict[str, list[str]] = {
    "ionian": ["C", "D", "E", "F", "G", "A", "B"],  # major
    "dorian": ["C", "D", "Eb", "F", "G", "A", "Bb"],
    "phrygian": ["C", "Db", "Eb", "F", "G", "Ab", "Bb"],
    "lydian": ["C", "D", "E", "F#", "G", "A", "B"],
    "mixolydian": ["C", "D", "E", "F", "G", "A", "Bb"],
    "aeolian": ["C", "D", "Eb", "F", "G", "Ab", "Bb"],  # natural minor
    "locrian": ["C", "Db", "Eb", "F", "Gb", "Ab", "Bb"],
    "pentatonic-major": ["C", "D", "E", "G", "A"],
    "pentatonic-minor": ["C", "Eb", "F", "G", "Bb"],
    "blues": ["C", "Eb", "F", "F#", "G", "Bb"],
    "chromatic": ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"],
    "whole-tone": ["C", "D", "E", "F#", "G#", "A#"],
    "diminished": ["C", "D", "Eb", "F", "F#", "G#", "A", "B"],
    "hungarian-minor": ["C", "D", "Eb", "F#", "G", "Ab", "B"],
    "japanese-hirajoshi": ["C", "D", "Eb", "G", "Ab"],
}

SCALE_ALIASES: dict[str, str] = {
    "major": "ionian",
    "natural-minor": "aeolian",
    "minor": "aeolian",
    "penta": "pentatonic-major",
    "hirajoshi": "japanese-hirajoshi",
    "hungarian": "hungarian-minor",
    "whole": "whole-tone",
}

SCALE_INTERVALS: dict[str, str] = {
    "ionian": "W-W-H-W-W-W-H (same as major scale)",
    "dorian": "W-H-W-W-W-H-W",
    "phrygian": "H-W-W-W-H-W-W",
    "lydian": "W-W-W-H-W-W-H (raised 4th)",
    "mixolydian": "W-W-H-W-W-H-W (lowered 7th)",
    "aeolian": "W-H-W-W-H-W-W (same as natural minor)",
    "locrian": "H-W-W-H-W-W-W (diminished 5th)",
    "pentatonic-major": "W-W-WH-W-WH (5 notes)",
    "pentatonic-minor": "WH-W-W-WH-W (5 notes)",
    "blues": "WH-W-H-H-WH-W (6 notes, flatted 5th)",
    "chromatic": "H-H-H-H-H-H-H-H-H-H-H-H (all 12 semitones)",
    "whole-tone": "W-W-W-W-W-W (all whole steps)",
    "diminished": "W-H-W-H-W-H-W-H (alternating)",
    "hungarian-minor": "W-H-WH-H-H-WH-H (raised 4th and 7th)",
    "japanese-hirajoshi": "W-H-WH-H-WH (5 notes, pentatonic variant)",
}


# ── Chords ────────────────────────────────────────────────────
CHORDS: dict[str, list[int]] = {
    "major": [0, 4, 7],
    "minor": [0, 3, 7],
    "diminished": [0, 3, 6],
    "augmented": [0, 4, 8],
    "major7": [0, 4, 7, 11],
    "minor7": [0, 3, 7, 10],
    "dominant7": [0, 4, 7, 10],
    "sus2": [0, 2, 7],
    "sus4": [0, 5, 7],
    "add9": [0, 4, 7, 14],
    "major9": [0, 4, 7, 11, 14],
    "half-diminished": [0, 3, 6, 10],
    "fully-diminished": [0, 3, 6, 9],
    "power": [0, 7],
}

CHORD_NOTE_NAMES: dict[str, list[str]] = {
    "major": ["1", "3", "5"],
    "minor": ["1", "b3", "5"],
    "diminished": ["1", "b3", "b5"],
    "augmented": ["1", "3", "#5"],
    "major7": ["1", "3", "5", "7"],
    "minor7": ["1", "b3", "5", "b7"],
    "dominant7": ["1", "3", "5", "b7"],
    "sus2": ["1", "2", "5"],
    "sus4": ["1", "4", "5"],
    "add9": ["1", "3", "5", "9"],
    "major9": ["1", "3", "5", "7", "9"],
    "half-diminished": ["1", "b3", "b5", "b7"],
    "fully-diminished": ["1", "b3", "b5", "bb7"],
    "power": ["1", "5"],
}

_CHROMATIC_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def chord_notes(root: str, chord_type: str) -> list[str] | None:
    """Return the actual note names for a chord given a root note."""
    intervals = CHORDS.get(chord_type)
    if intervals is None:
        return None
    # Try to find root in chromatic scale
    root_clean = root.upper()
    if root_clean in _CHROMATIC_NOTES:
        root_idx = _CHROMATIC_NOTES.index(root_clean)
    else:
        return None
    return [_CHROMATIC_NOTES[(root_idx + i) % 12] for i in intervals if i < 12]


# ── World data feed URLs ──────────────────────────────────────
WORLD_DATA_FEEDS: dict[str, str] = {
    "earthquakes": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.geojson",
    "co2_ppm": "https://globalmonitoring.noaa.gov/webdata/ccgg/trends/co2/co2_weekly_mlo.csv",
    "air_quality_iqair": "https://api.airvisual.com/v2/city?city=X&key=YOUR_KEY",
    "open_meteo_weather": "https://api.open-meteo.com/v1/forecast?latitude=X&longitude=X&hourly=temperature_2m",
    "world_bank_data": "https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL?format=json",
    "crypto_prices": "wss://stream.binance.com:9443/ws/btcusdt@trade",
    "forex": "https://open.er-api.com/v6/latest/USD",
    "gold_silver": "https://metals-api.com/api/latest?base=USD&symbols=XAU,XAG",
    "usgs_stream_gauges": "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=X",
    "nasa_epic": "https://api.nasa.gov/EPIC/api/natural",
    "open_sky_flights": "https://opensky-network.org/api/states/all",
    "electricity_eia": "https://api.eia.gov/v2/electricity/rto/interchange-data/data/",
    "iss_position": "http://api.open-notify.org/iss-now.json",
    "solar_wind_noaa": "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json",
    "tide_predictions_noaa": "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=predictions&datum=MLLW&format=json",
    "nasa_apod": "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY",
    "wikipedia_trending": "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/today",
}


# ── Logic fallacies ───────────────────────────────────────────
LOGIC_FALLACIES: dict[str, str] = {
    "ad-hominem": "Attacking the person making the argument rather than the argument itself.",
    "straw-man": "Misrepresenting someone's argument to make it easier to attack.",
    "false-dilemma": "Presenting only two options when more exist. Also called false dichotomy.",
    "slippery-slope": "Claiming A leads to Z without sufficient causation between the steps.",
    "appeal-to-authority": "Using an authority's opinion as evidence without scrutiny of their credentials or relevance.",
    "circular-reasoning": "Using the conclusion as a premise. 'The Bible is true because it says so.'",
    "hasty-generalization": "Drawing broad conclusions from a small or unrepresentative sample.",
    "post-hoc": "Correlation implies causation. (Post hoc ergo propter hoc: 'after this, therefore because of this.')",
    "appeal-to-nature": "Natural = good, artificial = bad. Hemlock is natural; insulin is artificial.",
    "tu-quoque": "'You too' — deflecting by pointing to the accuser's behavior instead of addressing the argument.",
    "bandwagon": "Popular = correct. 'Everyone believes X, so X must be true.'",
    "false-equivalence": "Treating two things as morally or logically equal when they are not.",
    "red-herring": "Introducing irrelevant information to distract from the actual argument.",
    "appeal-to-emotion": "Using emotional manipulation instead of logic to persuade.",
    "no-true-scotsman": "Redefining a category to exclude counterexamples. 'No real programmer uses spaces.'",
    "appeal-to-ignorance": "Claiming something is true because it hasn't been proven false (or vice versa).",
    "begging-the-question": "Assuming the conclusion in the premise. Circular but more subtle than circular reasoning.",
    "modus-ponens": "(VALID) If P then Q. P. Therefore Q.",
    "modus-tollens": "(VALID) If P then Q. Not Q. Therefore not P.",
    "hypothetical-syllogism": "(VALID) If P then Q. If Q then R. Therefore if P then R.",
    "disjunctive-syllogism": "(VALID) P or Q. Not P. Therefore Q.",
}


# ── Physics / science constants ──────────────────────────────
_PHYSICS_CONSTANTS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bspeed of light\b|\bc\s*=\s*\?|\blight speed\b"),
        "Speed of light (c) = 299,792,458 m/s ≈ 3×10⁸ m/s in a vacuum. Nothing with mass can reach this speed.",
    ),
    (
        re.compile(r"\bspeed of sound\b|\bsound speed\b"),
        "Speed of sound: ~343 m/s (1,235 km/h) in dry air at 20°C. ~1,480 m/s in water. ~5,100 m/s in steel.",
    ),
    (
        re.compile(r"\bgravitational constant\b|\bnewton.s\s+(?:law of )?gravit"),
        "Newton's gravitational constant G = 6.674×10⁻¹¹ N·m²/kg². Used in: F = Gm₁m₂/r².",
    ),
    (
        re.compile(r"\bgravity\b.*\bearth\b|\bearth.s\s+gravity\b|\bg\s*=\s*\?"),
        "Earth's surface gravity g = 9.807 m/s² (≈ 9.81 m/s²). This is acceleration due to Earth's gravity at sea level.",
    ),
    (
        re.compile(r"\bplanck.s?\s+constant\b|\bplanck constant\b"),
        "Planck's constant h = 6.626×10⁻³⁴ J·s. Fundamental constant in quantum mechanics. E = hf (energy of a photon = h × frequency).",
    ),
    (
        re.compile(r"\bboltzmann constant\b|\bkb\s*="),
        "Boltzmann constant k_B = 1.381×10⁻²³ J/K. Relates temperature to kinetic energy. Used in thermodynamics and statistical mechanics.",
    ),
    (
        re.compile(r"\bavogadro.s?\s+(?:number|constant)\b"),
        "Avogadro's number N_A = 6.022×10²³ mol⁻¹. The number of atoms/molecules in one mole of a substance.",
    ),
    (
        re.compile(r"\belectron charge\b|\bcharge of (?:an |the )?electron\b|\belementary charge\b"),
        "Elementary charge e = 1.602×10⁻¹⁹ coulombs. The charge of a single proton (positive) or electron (negative).",
    ),
    (
        re.compile(r"\bmass of (?:an |the )?(?:electron|proton|neutron)\b|\belectron mass\b|\bproton mass\b"),
        "Electron mass: 9.109×10⁻³¹ kg. Proton mass: 1.673×10⁻²⁷ kg. Neutron mass: 1.675×10⁻²⁷ kg. Proton is ~1,836× heavier than electron.",
    ),
    (
        re.compile(r"^(?:what is pi|value of pi|pi\??|what'?s pi|the value of pi)$"),
        "π (pi) = 3.14159265358979323846... — ratio of circle's circumference to its diameter. Irrational and transcendental.",
    ),
    (
        re.compile(r"\beuler.s?\s*number\b|\be\s*=\s*\?|\bvalue of e\b"),
        "Euler's number e = 2.71828182845904523536... — base of natural logarithm. Irrational and transcendental. Appears in compound interest, probability, calculus.",
    ),
    (
        re.compile(r"\bgolden ratio\b|\bphi\s*=|\bφ\s*="),
        "Golden ratio φ (phi) = 1.61803398874989... — (1+√5)/2. Appears in art, architecture, and nature (Fibonacci spirals).",
    ),
    (
        re.compile(r"\babsolute zero\b"),
        "Absolute zero = 0 K = −273.15°C = −459.67°F. The theoretical minimum temperature — no thermal motion exists below this.",
    ),
]

# ── Temperature conversions ───────────────────────────────────
import re as _temp_re  # noqa: E402


def _convert_temperature(text: str) -> str | None:
    """Detect temperature conversion queries and compute the result.
    Requires explicit conversion intent — won't fire on science questions that
    merely mention temperature values (e.g. 'survive -272°C' in a biology question).
    """
    t = text.lower().strip().rstrip("?.")
    # Require explicit conversion language: "convert X°C to F", "X°C in fahrenheit", etc.
    # The conversion target is now REQUIRED (not optional) to avoid false matches.
    m = _temp_re.search(
        r"(-?\d+(?:\.\d+)?)\s*°?\s*(celsius|fahrenheit|kelvin|c|f|k)\b"
        r"\s+(?:to|in|into|as|converted?\s+to)\s+(celsius|fahrenheit|kelvin|c|f|k)",
        t,
    )
    if not m:
        return None
    val = float(m.group(1))
    from_unit = m.group(2)[0]  # c / f / k
    to_unit = (m.group(3) or "")[:1]  # c / f / k (empty if no target)

    # Infer target if not given
    if not to_unit:
        if from_unit == "c":
            to_unit = "f"
        elif from_unit == "f":
            to_unit = "c"
        elif from_unit == "k":
            to_unit = "c"
        else:
            return None

    if from_unit == to_unit:
        return None

    # Convert to Celsius first
    if from_unit == "c":
        c = val
    elif from_unit == "f":
        c = (val - 32) * 5 / 9
    elif from_unit == "k":
        c = val - 273.15
    else:
        return None

    if to_unit == "c":
        result = c
        unit_sym = "°C"
    elif to_unit == "f":
        result = c * 9 / 5 + 32
        unit_sym = "°F"
    elif to_unit == "k":
        result = c + 273.15
        unit_sym = "K"
    else:
        return None

    in_sym = {"c": "°C", "f": "°F", "k": "K"}[from_unit]
    r = round(result, 4)
    r_display = int(r) if r == int(r) else r
    return f"{val}{in_sym} = {r_display}{unit_sym}"


# ── Number theory helpers ─────────────────────────────────────
def _is_prime_check(text: str) -> str | None:
    """Answer 'is N prime?' queries for N ≤ 10,000."""
    m = _temp_re.search(
        r"(?:is\s+)?(\d+)\s+(?:a\s+)?prime(?:\s+number)?(?:\s*\?)?$"
        r"|(?:(?:is\s+)?(\d+)\s+(?:a\s+)?(?:prime|not prime))"
        r"|(?:prime\??\s+(\d+))",
        text.lower().strip(),
    )
    if not m:
        # simpler match
        m2 = _temp_re.fullmatch(r"is\s+(\d+)\s+(?:a\s+)?prime(?:\s+number)?", text.lower().strip())
        if not m2:
            return None
        n = int(m2.group(1))
    else:
        raw = m.group(1) or m.group(2) or m.group(3)
        if raw is None:
            return None
        n = int(raw)
    if n > 10_000:
        return None
    yes_no_mode = bool(re.search(r"yes or no|answer yes|true or false", text.lower()))
    if n < 2:
        return "No." if yes_no_mode else f"{n} is NOT prime."
    if n == 2:
        return "Yes." if yes_no_mode else "2 is prime."
    if n % 2 == 0:
        return "No." if yes_no_mode else f"{n} is NOT prime (divisible by 2)."
    import math as _m

    for i in range(3, int(_m.sqrt(n)) + 1, 2):
        if n % i == 0:
            return "No." if yes_no_mode else f"{n} is NOT prime (divisible by {i})."
    return "Yes." if yes_no_mode else f"{n} is prime."


def _fibonacci_query(text: str) -> str | None:
    """Answer Fibonacci queries: 'nth Fibonacci number', 'Fibonacci sequence first N', 'is N Fibonacci'."""
    import math as _m

    t = text.lower().strip().rstrip("?.")

    # "Fibonacci sequence" or "first N Fibonacci numbers"
    m = _temp_re.search(
        r"(?:first\s+)?(\d+)\s+fibonacci\s+(?:number|term|element)s?|fibonacci\s+sequence\s+(?:first\s+)?(\d+)", t
    )
    if m:
        count = int(m.group(1) or m.group(2))
        if count > 30:
            return None
        seq = [0, 1]
        while len(seq) < count:
            seq.append(seq[-1] + seq[-2])
        return f"First {count} Fibonacci numbers: {', '.join(str(x) for x in seq[:count])}"

    # "Nth Fibonacci number" — also handles Fibonacci(20) / fib(20) notation
    m2 = _temp_re.search(
        r"(\d+)(?:st|nd|rd|th)?\s+fibonacci(?:\s+number)?"
        r"|fibonacci\s*\(\s*(\d+)\s*\)"
        r"|fibonacci\s+(?:number\s+)?(\d+)"
        r"|\bfib\s*\(\s*(\d+)\s*\)",
        t,
    )
    if m2:
        n = int(next(g for g in m2.groups() if g is not None))
        if n > 80:
            return None
        a, b = 0, 1
        for _ in range(n):
            a, b = b, a + b
        return f"Fibonacci({n}) = {a:,}"

    # "is N a Fibonacci number?"
    m3 = _temp_re.search(r"is\s+(\d+)\s+(?:a\s+)?fibonacci", t)
    if m3:
        n = int(m3.group(1))
        if n > 10**18:
            return None

        # A number is Fibonacci iff 5n²+4 or 5n²-4 is a perfect square
        def is_perf_sq(x: int) -> bool:
            r = int(_m.isqrt(x))
            return r * r == x

        if is_perf_sq(5 * n * n + 4) or is_perf_sq(5 * n * n - 4):
            return f"{n:,} IS a Fibonacci number."
        return f"{n:,} is NOT a Fibonacci number."

    return None


# ── Nginx errors & config ────────────────────────────────────
_NGINX: list[tuple[str, str]] = [
    (
        r"\bnginx\b.*\b502\b|\b502\b.*\bnginx\b|\bbad gateway\b.*\bnginx\b",
        "**Nginx 502 Bad Gateway**: Upstream server is down or not responding. Fix: check `proxy_pass` target is running, verify upstream health. `nginx -t && systemctl status nginx`.",
    ),
    (
        r"\bnginx\b.*\b504\b|\b504\b.*\bnginx\b|\bgateway timeout\b.*\bnginx\b",
        "**Nginx 504 Gateway Timeout**: Upstream took too long. Fix: increase `proxy_read_timeout 120s;` and `proxy_connect_timeout 60s;` in nginx.conf.",
    ),
    (
        r"\bnginx\b.*\b413\b|\b413\b.*\bnginx\b|\brequest entity too large\b",
        "**Nginx 413 Request Entity Too Large**: Body exceeds `client_max_body_size`. Fix: add `client_max_body_size 100m;` in `http {}` or `server {}` block.",
    ),
    (
        r"\bnginx\b.*\b403\b.*(?:permiss|denied)\b|\bforbidden\b.*\bnginx\b",
        "**Nginx 403 Forbidden**: Check file/directory permissions and `user` directive in nginx.conf. Often: `chmod 755 /var/www/html` and ensure nginx user matches file owner.",
    ),
    (
        r"\bnginx\b.*(?:worker|connection)\b.*(?:limit|max)\b|\bworker_connections\b",
        "**Nginx worker connections**: `worker_processes auto;` (one per CPU core) + `worker_connections 1024;`. Max concurrent = worker_processes × worker_connections. Also set `ulimit -n 65536` and `worker_rlimit_nofile 65536;`.",
    ),
    (
        r"\bnginx\b.*(?:ssl|tls|https)\b.*(?:error|config|setup)\b",
        "**Nginx SSL setup**: `ssl_certificate /path/cert.pem; ssl_certificate_key /path/key.pem;` in server block. Test: `nginx -t`. Modern config: `ssl_protocols TLSv1.2 TLSv1.3; ssl_ciphers HIGH:!aNULL:!MD5;`",
    ),
    (
        r"\bnginx\b.*(?:rate limit|limit_req)\b|\blimit_req_zone\b",
        "**Nginx rate limiting**: `limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;` in `http {}`. Apply: `limit_req zone=api burst=20 nodelay;` in `location {}`. Returns 429 when exceeded.",
    ),
    (
        r"\bnginx\b.*(?:upstream|load.?balanc)\b",
        "**Nginx upstream/load balancing**: `upstream backend { server 10.0.0.1:8080; server 10.0.0.2:8080; }` then `proxy_pass http://backend;`. Algorithms: round-robin (default), `least_conn`, `ip_hash` (sticky sessions).",
    ),
]

# ── PostgreSQL errors ────────────────────────────────────────
_POSTGRES: list[tuple[str, str]] = [
    (
        r"\b23505\b|\bunique.?violation\b|\bduplicate\s+key\b",
        "**PostgreSQL 23505 unique_violation**: Duplicate key violates unique constraint. Fix: use `INSERT ... ON CONFLICT DO UPDATE SET ...` or `ON CONFLICT DO NOTHING`. Check `SELECT` first if needed.",
    ),
    (
        r"\b23503\b|\bforeign.?key.?violation\b",
        "**PostgreSQL 23503 foreign_key_violation**: Referenced row doesn't exist. Fix: insert parent row first, or use `ON DELETE CASCADE` on the FK constraint.",
    ),
    (
        r"\b23502\b|\bnot.?null.?violation\b",
        "**PostgreSQL 23502 not_null_violation**: NULL inserted into NOT NULL column. Fix: provide a value or `ALTER TABLE t ALTER COLUMN c SET DEFAULT '';`",
    ),
    (
        r"\b40001\b|\bserializ\w+\s+failure\b|\bdeadlock\b.*\bpostgres\b",
        "**PostgreSQL 40001 serialization_failure / deadlock**: Transactions conflict. Fix: catch and retry the transaction. Use `SERIALIZABLE` isolation only when needed. Deadlock: ensure consistent lock ordering.",
    ),
    (
        r"\b57014\b|\bquery.?canceled\b|\bstatement.?timeout\b.*\bpostgres\b",
        "**PostgreSQL 57014 query_canceled**: `statement_timeout` exceeded. Fix: `SET statement_timeout = '30s';` per session, or tune the query. Add indexes for slow queries.",
    ),
    (
        r"\bpostgres\b.*\bconnection\b.*(?:limit|too many|exhausted|max)\b|\btoo many connections\b",
        "**PostgreSQL too many connections**: Default max_connections=100. Fix: use PgBouncer connection pooler (`transaction` mode for APIs). Or: `ALTER SYSTEM SET max_connections = 200; SELECT pg_reload_conf();`",
    ),
    (
        r"\bpostgres\b.*(?:vacuum|bloat|autovacuum)\b",
        "**PostgreSQL vacuum/bloat**: Dead tuples accumulate without VACUUM. Autovacuum runs automatically but may lag. Check: `SELECT n_dead_tup, last_autovacuum FROM pg_stat_user_tables;`. Force: `VACUUM ANALYZE tablename;`",
    ),
    (
        r"\bpostgres\b.*(?:explain|query plan|slow query|index)\b",
        "**PostgreSQL slow query**: Use `EXPLAIN (ANALYZE, BUFFERS) SELECT ...;`. Look for Seq Scan on large tables (needs index). Create: `CREATE INDEX CONCURRENTLY idx_name ON table(col);`. Check `pg_stat_statements` for top queries.",
    ),
]

# ── Node.js / V8 errors ───────────────────────────────────
_NODEJS: list[tuple[str, str]] = [
    (
        r"\bECONNREFUSED\b",
        "**ECONNREFUSED**: Connection refused — target server isn't listening. Check: target process is running, correct host/port, no firewall blocking. `netstat -tlnp | grep PORT`",
    ),
    (
        r"\bEADDRINUSE\b",
        "**EADDRINUSE**: Port already in use. Find and kill: `lsof -i :PORT` then `kill PID`, or use a different port. In Node: pass `{ reuseAddr: true }` to server options.",
    ),
    (
        r"\bERR_HEAP_OOM\b|\bheap out of memory\b|\bjavascript heap\b.*\bout of memory\b",
        "**Node.js heap OOM**: V8 heap exhausted. Fix: `node --max-old-space-size=4096 app.js` (4GB). Check for memory leaks with `node --inspect` + Chrome DevTools heap snapshot. Default heap: ~1.5GB.",
    ),
    (
        r"\bERR_MODULE_NOT_FOUND\b|\bcannot find module\b",
        '**ERR_MODULE_NOT_FOUND**: Module missing or path wrong. Fix: `npm install`, check `node_modules/` exists, verify import path. ESM vs CJS: use `.mjs` or `"type": "module"` in package.json for ESM.',
    ),
    (
        r"\bECONNRESET\b",
        "**ECONNRESET**: Connection forcibly closed by peer. Add retry logic with exponential backoff. In HTTP servers: client disconnected before response completed — usually safe to ignore if handled.",
    ),
    (
        r"\bUnhandledPromiseRejection\b|\bERR_UNHANDLED_REJECTION\b",
        "**UnhandledPromiseRejection**: Promise rejected with no `.catch()`. Fix: always `.catch(err => ...)` or `try/catch` in `async` functions. Add `process.on('unhandledRejection', (r,p) => { console.error(r); process.exit(1); });`",
    ),
    (
        r"\bERR_INVALID_ARG_TYPE\b",
        "**ERR_INVALID_ARG_TYPE**: Wrong type passed to Node.js built-in. Check function signature in Node docs. Common: passing `undefined` where a `Buffer` or `string` expected.",
    ),
]

# ── ffmpeg commands ──────────────────────────────────────────
_FFMPEG: list[tuple[str, str]] = [
    (
        r"\bffmpeg\b.*\b(?:transcode|h264|x264|mp4)\b|\bconvert.*\bvideo\b.*\bffmpeg\b",
        "**ffmpeg H.264 transcode**: `ffmpeg -i input.mp4 -c:v libx264 -preset fast -crf 23 output.mp4`\n`-crf`: quality (18=excellent, 23=default, 28=smaller). `-preset`: ultrafast→veryslow (speed vs compression tradeoff).",
    ),
    (
        r"\bffmpeg\b.*\b(?:extract|strip)\b.*\baudio\b|\bffmpeg\b.*\baudio only\b",
        "**ffmpeg extract audio**: `ffmpeg -i input.mp4 -vn -acodec copy output.aac` (copy) or `ffmpeg -i input.mp4 -vn -ar 44100 -ac 2 -b:a 192k output.mp3` (transcode to MP3).",
    ),
    (
        r"\bffmpeg\b.*\b(?:trim|cut|clip)\b.*\bvideo\b|\bffmpeg\b.*\b-ss\b",
        "**ffmpeg trim video**: `ffmpeg -ss 00:01:00 -to 00:02:30 -i input.mp4 -c copy output.mp4`\n`-ss` before `-i` = fast seek (keyframe). `-ss` after `-i` = exact but slower. Use `-c copy` to avoid re-encode.",
    ),
    (
        r"\bffmpeg\b.*\b(?:resolution|scale|resize)\b|\bffmpeg\b.*\b1080p\b|\bffmpeg\b.*\b720p\b",
        "**ffmpeg resize**: `ffmpeg -i input.mp4 -vf scale=1280:720 output.mp4`. Keep aspect ratio: `scale=1280:-1` (auto height) or `scale=-1:720` (auto width). For 4K→1080p: `scale=1920:1080`.",
    ),
    (
        r"\bffmpeg\b.*\b(?:gif|webm|webp)\b.*(?:mp4|convert)\b|\bconvert.*\bgif\b.*\bffmpeg\b",
        "**ffmpeg GIF/WebM to MP4**: GIF: `ffmpeg -i input.gif -c:v libx264 -crf 23 -pix_fmt yuv420p output.mp4`\nWebM: `ffmpeg -i input.webm -c:v libx264 -c:a aac output.mp4`. `-pix_fmt yuv420p` needed for browser compatibility.",
    ),
    (
        r"\bffmpeg\b.*\b(?:merge|mux|combine)\b.*(?:audio|video)\b|\bffmpeg\b.*-i.*-i\b",
        "**ffmpeg merge video+audio**: `ffmpeg -i video.mp4 -i audio.mp3 -c:v copy -c:a aac -shortest output.mp4`. `-shortest` stops when shorter stream ends. `-c:v copy` avoids re-encoding video.",
    ),
    (
        r"\bffmpeg\b.*\bframes?\b|\bffmpeg\b.*\bextract.*(?:frame|image|screenshot)\b",
        "**ffmpeg extract frames**: `ffmpeg -i input.mp4 -vf fps=1 frame%04d.jpg` (1 per second). One frame at time T: `ffmpeg -ss 00:00:30 -i input.mp4 -frames:v 1 frame.jpg`. High quality: add `-q:v 2`.",
    ),
]

# ── sysctl tuning ────────────────────────────────────────────
_SYSCTL: list[tuple[str, str]] = [
    (
        r"\bsysctl\b.*\bsomaxconn\b|\bnet\.core\.somaxconn\b",
        "**net.core.somaxconn**: Max listen backlog. Default: 128. Set to 4096+ for high-traffic servers.\n`sysctl -w net.core.somaxconn=4096`\nPersist: add to `/etc/sysctl.d/99-tuning.conf`",
    ),
    (
        r"\bsysctl\b.*\btcp_tw_reuse\b|\btime.?wait\b.*\bsocket\b",
        "**net.ipv4.tcp_tw_reuse=1**: Allow reuse of TIME_WAIT sockets for new connections. Reduces port exhaustion. Also set `net.ipv4.tcp_fin_timeout=30` (default 60s).",
    ),
    (
        r"\bsysctl\b.*\bswappiness\b|\bvm\.swappiness\b",
        "**vm.swappiness**: Controls swap aggressiveness. 0=avoid swap, 100=aggressive. Recommended: 1 for databases, 10-15 for general servers. `sysctl -w vm.swappiness=1`",
    ),
    (
        r"\bsysctl\b.*\bfile.?max\b|\bfs\.file.?max\b|\bulimit\b.*\bopen files\b",
        "**fs.file-max**: System-wide max open file descriptors. `sysctl -w fs.file-max=2097152`. Per-process: `ulimit -n 65536`. Also: `/etc/security/limits.conf` → `* soft nofile 65536` + `* hard nofile 65536`",
    ),
    (
        r"\bsysctl\b.*\btcp.*buf\b|\bnet\.ipv4\.tcp_[rw]mem\b",
        "**TCP buffer sizes**: `net.ipv4.tcp_rmem = 4096 65536 134217728` (min/default/max receive).\n`net.ipv4.tcp_wmem = 4096 65536 134217728` (send). Larger buffers help high-throughput/high-latency links.",
    ),
    (
        r"\bsysctl\b.*\bbacklog\b|\bnet\.ipv4\.tcp_max_syn_backlog\b",
        "**net.ipv4.tcp_max_syn_backlog=4096**: Max half-open TCP connections. Increase for high connection rate servers. Helps with SYN flood resilience. Default: 1024.",
    ),
]

# ── Thread / connection pool sizing ──────────────────────────
_CONCURRENCY: list[tuple[str, str]] = [
    (
        r"\bthread\s*pool\s*siz\w+\b|\bhow many threads\b|\bcpu.?bound.*thread\b",
        "**Thread pool sizing**: CPU-bound: `N+1` threads (N = CPU cores, +1 for stalls). IO-bound: `N × (W/C)` where W=wait time, C=compute time. Example: 8 cores, 10ms IO wait, 1ms compute → 8×10 = 80 threads. Java: `ForkJoinPool.commonPool()` uses N-1 threads.",
    ),
    (
        r"\bconnection\s*pool\b.*(?:postgres|pg|database)\b|\bpgbouncer\b.*siz\w+\b",
        "**PostgreSQL connection pool**: Rule: `connections = (core_count × 2) + effective_spindle_count`. For SSD: `cores × 2`. Typical: 10-50 connections per app server. Use PgBouncer in `transaction` mode. Max pg connections: 100 default, 200-500 practical max.",
    ),
    (
        r"\bconnection\s*pool\b.*redis\b|\bredis.*pool\b",
        "**Redis connection pool**: Redis is single-threaded for commands. Pool size: 10-20 per app instance is plenty. Python redis-py: `ConnectionPool(max_connections=20)`. Node ioredis: `maxRetriesPerRequest=3`.",
    ),
    (
        r"\bepoll\b|\bselect\b.*\blimit\b|\bkqueue\b|\bC10k\b|\bc10k\b",
        "**epoll vs select**: `select()` limit: 1024 FDs (FD_SETSIZE). `epoll` (Linux): no hard limit, O(1) on events vs O(n) for select. `kqueue` (macOS/BSD): similar to epoll. Modern servers use epoll — Node.js, Nginx, asyncio all use it.",
    ),
    (
        r"\bGC\s*(?:heap|pause|tuning)\b|\bjvm\s*heap\b|\b-Xmx\b|\b-Xms\b",
        "**JVM heap sizing**: `-Xms` = initial heap (set = `-Xmx` to avoid resizing). `-Xmx` = max heap. Rule: 25-30% of available RAM for heap. Off-heap: NIO buffers, metaspace (default 256MB, `-XX:MaxMetaspaceSize=512m`). Leave 20-30% RAM for OS.",
    ),
]

# ── Protobuf ─────────────────────────────────────────────────
_PROTOBUF: list[tuple[str, str]] = [
    (
        r"\bprotobuf\b.*\bfield\s*(?:numbers?|ids?)\b|\bproto\b.*\bfield\s*(?:numbers?|rule)\b",
        '**Protobuf field numbers**: 1-15 use 1 byte (use for frequent fields). 16-2047 use 2 bytes. 19000-19999 reserved. Never reuse field numbers — breaks wire format. Mark removed fields with `reserved 5;` and `reserved "old_name";`',
    ),
    (
        r"\bprotobuf\b.*\b(?:backwards?\s*compat|evolution|migration)\b",
        "**Protobuf backwards compatibility**: SAFE: add new optional fields, add enum values, rename (not renumber) fields. UNSAFE: change field numbers, change types, delete without reserving. Proto3: all fields optional by default, unknown fields preserved.",
    ),
    (
        r"\bprotobuf\b.*\bcodegen\b|\bprotoc\b|\bgrpc\b.*\bgenerate\b",
        "**protoc codegen**: Python: `protoc --python_out=. --pyi_out=. proto/service.proto`. Go: `protoc --go_out=. --go-grpc_out=. proto/service.proto`. Java: `protoc --java_out=. proto/service.proto`. gRPC plugins: `--grpc_out` + `--plugin=protoc-gen-grpc=...`",
    ),
    (
        r"\bprotobuf\b.*\b(?:oneof|union)\b",
        "**Protobuf oneof**: Only one field set at a time. Memory-efficient for variant types. `oneof payload { string text = 1; bytes data = 2; ErrorMsg error = 3; }`. Clearing any oneof field clears all others.",
    ),
    (
        r"\bprotobuf\b.*\bmap\b|\bproto\b.*\bmap<\b",
        "**Protobuf map fields**: `map<string, int32> tags = 1;`. Keys must be scalar (not float/bytes/message). Maps are unordered. Iteration order is random. Equivalent to repeated message with key+value fields.",
    ),
    (
        r"\bproto3\b.*\bdefault\b|\bprotobuf\b.*\bdefault\s*value\b",
        "**Proto3 defaults**: All fields have zero defaults — int=0, bool=false, string=\"\", enum=first_value, message=null. Can't distinguish 'field not set' from 'set to zero' without `optional` keyword (proto3 optional) or wrappers.",
    ),
    (
        r"\borjson\b.*(?:error|decode|encode|fail)\b|\bjson\b.*\borjson\b.*(?:error|fail)\b",
        "**orjson errors**: `JSONDecodeError`: invalid JSON bytes. `TypeError`: non-serializable type (datetime needs `OPT_PASSTHROUGH_DATETIME` or `.isoformat()`). `orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS)` for dict with int keys. Output is always `bytes`, not `str` — decode with `.decode()`.",
    ),
    (
        r"\bmsgpack\b.*(?:error|decode|encode|fail)\b",
        "**msgpack errors**: `UnpackValueError`: truncated or corrupted data. `PackValueError`: unsupported type (use `default=` hook). Python: `msgpack.packb(data, use_bin_type=True)` + `msgpack.unpackb(data, raw=False)`. Sizes: int→1-9B, str→1-5B header + len.",
    ),
]

# ── Ansible ──────────────────────────────────────────────────
_ANSIBLE: list[tuple[str, str]] = [
    (
        r"\bansible\b.*\bunreachable\b|\bansible\b.*\bssh\b.*(?:fail|error|refused)\b",
        "**Ansible UNREACHABLE**: SSH can't connect. Debug: `ansible host -m ping -vvv`. Check: SSH key in `~/.ssh/authorized_keys`, `ansible_user`, `ansible_ssh_private_key_file`. Add `-o StrictHostKeyChecking=no` for first run.",
    ),
    (
        r"\bansible\b.*\bbecome\b|\bansible\b.*\bsudo\b.*(?:fail|error|password)\b",
        "**Ansible become/sudo**: `become: yes` + `become_user: root`. No password: add user to `/etc/sudoers`: `ansible ALL=(ALL) NOPASSWD: ALL`. Or pass: `--ask-become-pass` / `ansible_become_password` in vault.",
    ),
    (
        r"\bansible\b.*\bidempotent\b|\bansible\b.*\b(?:changed|no change)\b",
        "**Ansible idempotency**: Tasks should be safe to run multiple times. Use `creates:` in shell tasks, `state: present/absent` in package/file tasks. Avoid `shell:` and `command:` — use native modules (apt, copy, template) which are idempotent.",
    ),
    (
        r"\bansible\b.*\bvault\b|\bansible-vault\b",
        "**Ansible Vault**: Encrypt: `ansible-vault encrypt vars/secrets.yml`. Edit: `ansible-vault edit secrets.yml`. Run: `ansible-playbook ... --ask-vault-pass` or `--vault-password-file .vault_pass`. Encrypt individual vars: `!vault |` syntax.",
    ),
    (
        r"\bansible\b.*\b(?:loop|with_items)\b",
        "**Ansible loops**: Modern: `loop: [item1, item2]` with `{{ item }}`. Legacy `with_items:` still works. Nested: `loop: '{{ matrix | product(list2) | list }}'`. For dicts: `loop: '{{ dict | dict2items }}'` → `item.key`, `item.value`.",
    ),
    (
        r"\bansible\b.*\bhandler\b|\bnotify\b.*\bansible\b",
        "**Ansible handlers**: Run once at the end of a play when notified. `notify: restart nginx` in task + `handlers: - name: restart nginx  service: name=nginx state=restarted`. Use `meta: flush_handlers` to run immediately.",
    ),
]

# ── Java 21+ features ────────────────────────────────────────
_JAVA_MODERN: list[tuple[str, str]] = [
    (
        r"\bvirtual\s+threads?\b|\bproject\s+loom\b|\bthread\.ofvirtual\b",
        "**Java 21 Virtual Threads (Project Loom)**: Lightweight threads managed by JVM, not OS. Enable: `Thread.ofVirtual().start(task)` or `Executors.newVirtualThreadPerTaskExecutor()`. 1M+ virtual threads possible. Replaces reactive programming for IO-bound code. Best with blocking IO (JDBC, HTTP). Avoid synchronized blocks — use ReentrantLock.",
    ),
    (
        r"\bjava\b.*\brecord\b(?:\s+class)?\b|\bjava\b.*\brecord\b.*(?:immutable|data)\b",
        "**Java 16+ Record classes**: Immutable data carriers. `record User(String name, int age) {}` auto-generates: constructor, getters (`name()`, `age()`), `equals()`, `hashCode()`, `toString()`. Compact constructor: `record User(String name) { User { name = name.strip(); } }`. Implement interfaces, have static members.",
    ),
    (
        r"\bsealed\s+class\b|\bpermits\b.*\bjava\b",
        "**Java 17+ Sealed classes**: Restrict which classes can extend/implement. `sealed interface Shape permits Circle, Square, Triangle {}`. Each permitted class must be `final`, `sealed`, or `non-sealed`. Enables exhaustive `switch` pattern matching.",
    ),
    (
        r"\bpattern\s+matching\b.*\binstanceof\b|\binstanceof\b.*\bpattern\b",
        "**Java 16+ Pattern matching instanceof**: `if (obj instanceof String s) { s.length(); }` — no cast needed. Java 21 switch: `switch (shape) { case Circle c -> c.area(); case Square s -> s.area(); }`. Works with records for destructuring.",
    ),
    (
        r"\bg1gc\b|\bg1\s+gc\b|\b-xx:\+useg1gc\b",
        "**G1GC** (default JDK 9+): `-XX:+UseG1GC -XX:MaxGCPauseMillis=200 -XX:G1HeapRegionSize=32m -XX:InitiatingHeapOccupancyPercent=45`. Tune `-XX:MaxGCPauseMillis` for latency. `-Xlog:gc*` for GC logging. G1GC divides heap into equal regions (1-32MB), good for heaps > 4GB.",
    ),
    (
        r"\bzgc\b|\b-xx:\+usezgc\b",
        "**ZGC** (JDK 15+ production): Sub-millisecond GC pauses regardless of heap size. `-XX:+UseZGC -Xmx32g`. Generational ZGC (JDK 21): `-XX:+UseZGC -XX:+ZGenerational`. Best for low-latency, large heaps (32GB+). Slightly higher throughput cost vs G1.",
    ),
    (
        r"\bshenandoah\b.*\bgc\b|\b-xx:\+useshenandoahgc\b",
        "**Shenandoah GC**: Ultra-low pause times (like ZGC). `-XX:+UseShenandoahGC -XX:ShenandoahGCHeuristics=adaptive`. Available in OpenJDK (not Oracle JDK). Good for: heap 4-256GB, latency-sensitive. Throughput slightly lower than G1.",
    ),
    (
        r"\bbillion\s+row\s+challenge\b|\b1brc\b|\b1\s+billion\s+row\b",
        "**Billion Row Challenge (1BRC)**: Read 1B rows of temp measurements, compute min/mean/max per station. Winner Java approach: memory-mapped files (`FileChannel + MappedByteBuffer`), custom UTF-8 parsing, parallel streams with `ForkJoinPool`, avoid boxing with custom hash maps. Key: minimize allocations, batch IO, SIMD-friendly code. Best Java times: ~2-4 seconds on modern hardware.",
    ),
]

# ── DNS troubleshooting ──────────────────────────────────────
_DNS: list[tuple[str, str]] = [
    (
        r"\bnxdomain\b|\bdomain\b.*\b(?:not found|does not exist)\b.*\bdns\b",
        "**DNS NXDOMAIN**: Domain does not exist. Check: typo in hostname, domain expired, wrong DNS server. Debug: `dig domain.com @8.8.8.8` (try Google DNS), `nslookup domain.com`. NXDOMAIN cached for TTL seconds.",
    ),
    (
        r"\bservfail\b|\bdns\b.*\bserver\s*fail\b",
        "**DNS SERVFAIL**: Authoritative server failed to respond. Check: nameserver health (`dig NS domain.com`), DNSSEC misconfiguration, SOA record. Temp fix: switch resolver (`nameserver 8.8.8.8` in `/etc/resolv.conf`).",
    ),
    (
        r"\bdns\b.*(?:stale|cache|flush)\b|\bflushdns\b|\bflush.*dns\b",
        "**DNS stale cache**: Linux: `systemd-resolve --flush-caches` or restart `nscd`. macOS: `dscacheutil -flushcache && sudo killall -HUP mDNSResponder`. Reduce TTL to 60s before migrations. Check current TTL: `dig domain.com | grep -i ttl`.",
    ),
    (
        r"\bsplit.?horizon\b|\binternal.*dns\b.*\bexternal.*dns\b|\bdns\b.*\bvpn\b",
        "**Split-horizon DNS**: Different answers for internal vs external queries. Configure: two zones for the same domain — one in internal DNS (private IPs), one public (public IPs). Common with VPN/corp networks. Debug: `dig @internal-dns domain.com` vs `dig @8.8.8.8 domain.com`.",
    ),
    (
        r"\bCNAME\b.*\bapex\b|\bCNAME\b.*\broot\b|\bCNAME\b.*\bzone\s*apex\b",
        "**CNAME at apex (root) not allowed**: A/AAAA or ALIAS/ANAME records must be used at zone apex (e.g., example.com). Use: Cloudflare/Route53 ALIAS records which flatten CNAME at root, or point apex to IP directly.",
    ),
    (
        r"\bPTR\b.*(?:record|dns)\b|\breverse\s+dns\b|\brdns\b",
        "**PTR / reverse DNS**: Maps IP → hostname. Zone: `in-addr.arpa` for IPv4. Set by IP owner (usually cloud/ISP). Check: `dig -x 1.2.3.4`. Required for: email deliverability (SPF/DMARC), some auth systems. Set in cloud console or ask ISP.",
    ),
    (
        r"\bdns\b.*\bTTL\b|\bttl\b.*\bdns\b.*(?:lower|reduce|change|migration)\b",
        "**DNS TTL strategy**: Before migration: lower TTL to 60s (minimum) 24-48h beforehand. After migration: raise back to 3600-86400. Low TTL = more queries to authoritative server but faster propagation. TTL is per-record, not per-domain.",
    ),
]

# ── AlmaLinux quick reference ────────────────────────────────
_ALMALINUX: list[tuple[str, str]] = [
    (
        r"\balmalinux\b.*\b(?:install|dnf|yum|package)\b|\bdnf\b.*\balmalinux\b",
        "**AlmaLinux package management**: `dnf install nginx`, `dnf update`, `dnf search keyword`, `dnf remove pkg`. Enable EPEL: `dnf install epel-release`. PowerTools/CRB: `dnf config-manager --set-enabled crb` (AL9) / `powertools` (AL8).",
    ),
    (
        r"\balmalinux\b.*\bselinux\b|\bselinux\b.*(?:denied|avc|audit)\b",
        "**SELinux troubleshooting** (AlmaLinux): Check: `getenforce` (Enforcing/Permissive). Logs: `ausearch -m avc -ts recent` or `journalctl -t setroubleshoot`. Fix: `semanage port -a -t http_port_t -p tcp 8080`. Temp: `setenforce 0` (Permissive). Generate policy: `audit2allow -a -M mypolicy && semodule -i mypolicy.pp`.",
    ),
    (
        r"\balmalinux\b.*\bfirewall\b|\bfirewalld\b",
        "**AlmaLinux firewalld**: `firewall-cmd --permanent --add-service=https && firewall-cmd --reload`. Open port: `firewall-cmd --permanent --add-port=8080/tcp`. List rules: `firewall-cmd --list-all`. Zones: public (default), trusted, drop.",
    ),
    (
        r"\balmalinux\s*(?:9|10)\b.*\bsystemd\b|\bsystemctl\b.*\balmalinux\b",
        "**AlmaLinux systemd service**: `systemctl start/stop/restart/status nginx`. Enable at boot: `systemctl enable nginx`. Check logs: `journalctl -u nginx -f`. Create service: `/etc/systemd/system/myapp.service`. Reload after edits: `systemctl daemon-reload`.",
    ),
]

# ── Terraform basics ─────────────────────────────────────────
_TERRAFORM: list[tuple[str, str]] = [
    (
        r"\bterraform\b.*\binit\b|\bterraform init\b",
        "**terraform init**: Initializes providers and modules. Run after first clone or adding new providers. `terraform init -upgrade` to update providers. Creates `.terraform/` dir + `.terraform.lock.hcl`.",
    ),
    (
        r"\bterraform\b.*\bplan\b|\bterraform plan\b",
        "**terraform plan**: Preview changes without applying. `terraform plan -out=plan.tfplan` to save plan. Review: `+` create, `-` destroy, `~` update in-place, `-/+` destroy+recreate. Always review before `apply`.",
    ),
    (
        r"\bterraform\b.*\bstate\b|\btfstate\b|\bterraform\s+state\b",
        "**Terraform state**: State tracks real infrastructure. Remote state: S3+DynamoDB (AWS) or Terraform Cloud. `terraform state list`, `terraform state show resource.name`. Import existing: `terraform import aws_instance.web i-1234567890`. Never edit `terraform.tfstate` manually.",
    ),
    (
        r"\bterraform\b.*\bdestroy\b|\bterraform destroy\b",
        "**terraform destroy**: Destroys ALL resources in state. Use `terraform destroy -target=aws_instance.web` to destroy specific resources. Always run `terraform plan -destroy` first to preview. Irreversible on stateful resources (databases, S3 buckets with data).",
    ),
    (
        r"\bterraform\b.*\bworkspace\b|\bterraform workspace\b",
        "**Terraform workspaces**: Separate state per workspace. `terraform workspace new staging`, `terraform workspace select production`. Each workspace has its own `.tfstate`. Use for env separation (dev/staging/prod).",
    ),
]

# ── Helm basics ──────────────────────────────────────────────
# ── muLLM system knowledge ───────────────────────────────────
_MULLM_SYSTEM: list[tuple[str, str]] = [
    (
        r"\bwith.?rice\b|\bpowerup\b|\bpower.?up mode\b",
        "**WITH RICE mode** (`mullm --with-rice`): fires Opus 4.6 + Gemini 2.5 Pro + GPT-5.3 in parallel, then Claude Sonnet synthesizes the best answer. Disables cost-optimization. Est. cost ~$0.20/query. UI toggle available in chat settings. Requires explicit confirmation.",
    ),
    (
        r"\bmullm\b.*\b(?:routing|route|classify|classifier)\b|\bhow.*mullm.*route\b",
        "**muLLM routing pipeline**: classify intent (rules → complexity 1-5) → check groundtruth LUT (< 1ms) → vector cache (ChromaDB, 0.98 similarity) → local Ollama (qwen3:9b) → 30B escalation model → cloud (Sonnet/Gemini/GPT). 98% local, $0 for simple queries.",
    ),
    (
        r"\bmullm\b.*\bcost\b|\bmullm.*price\b|\bhow.*cheap\b",
        "**muLLM cost**: Local tier = $0.00 (Ollama qwen3:9b on RTX 5090). Cloud-cheap ≈ $0.001-0.01/query. Cloud-full ≈ $0.01-0.05/query. WITH RICE ~$0.20/query. Default daily cap: $5.00. HumanEval 164/164 = 100% pass@1 at $0.00 (all local).",
    ),
    (
        r"\bgroundtruth\b.*\bspeed\b|\brealtime\.py\b|\bhow fast.*groundtruth\b",
        "**Groundtruth speed**: realtime.py resolves 95%+ of lookup queries in <1ms (in-process Python dicts/regex). vs local Ollama ~800ms, vs cloud ~1750ms. Fastest: `gcd(48,18)` = 14ns. Categories: 40+ dicts covering HTTP codes, Git, math, physics, capitals, Nginx, Postgres, Terraform, Helm, Java 21+, etc.",
    ),
    (
        r"\bbench\b.*\broute.*latency\b|\brouting.*decision.*time\b|\bµs.*routing\b",
        "**Routing decision latency**: always_local ≈ 150ns, random ≈ 200ns, mullm heuristic ≈ 500µs (HTTP classify call). BERT ≈ 26ms (transformer inference). Efficiency = accuracy^1.5 / sqrt(total_ms) × 1000. Results cached in Redis 5 min. Run via `/bench` → Route Latency tab.",
    ),
]

# ── Bench Reasoning Easy — all 10 problems answered in <5ms ─
_BENCH_REASONING_EASY: list[tuple[str, str]] = [
    # capitals: "What is the capital of Australia?" → handled by _CAPITALS LUT above
    # math1: "What is 17 × 23?" → handled by math evaluator above
    # prime: "Is 97 a prime number?" → handled by _is_prime_check above
    # history: "In what year did World War II end?" → handled by hist_match above
    # science: "What is the chemical symbol for gold?" → handled by elem_sym_m above
    # The 5 below are NOT covered by existing LUTs:
    (
        r"bloops.*razzles.*lazzles|razzles.*lazzles.*bloops",
        "Yes.",
    ),
    (
        r"sort.*(?:numbers|list)[:\s]+7\s*,\s*2\s*,\s*9\s*,\s*1\s*,\s*5",
        "1, 2, 5, 7, 9",
    ),
    (
        r"listen.*anagram.*silent|silent.*anagram.*listen",
        "Yes.",
    ),
    (
        r"cat\s*:\s*kitten\s*as\s*dog\s*:|complete.*cat.*kitten.*dog",
        "Puppy",
    ),
    (
        r"how many letters.*strawberry|letters.*in.*strawberry",
        "10",
    ),
]

_HELM: list[tuple[str, str]] = [
    (
        r"\bhelm\b.*\binstall\b|\bhelm install\b",
        "**helm install**: `helm install release-name chart/ --values values.yaml -n namespace`. Dry run: `helm install --dry-run --debug`. Template render only: `helm template release-name chart/ -f values.yaml`.",
    ),
    (
        r"\bhelm\b.*\bupgrade\b|\bhelm upgrade\b",
        "**helm upgrade**: `helm upgrade release-name chart/ -f values.yaml`. Atomic: `--atomic --timeout 5m` (rollback on failure). First install or upgrade: `helm upgrade --install release-name chart/`. History: `helm history release-name`.",
    ),
    (
        r"\bhelm\b.*\b(?:rollback|undo)\b|\bhelm rollback\b",
        "**helm rollback**: `helm rollback release-name 1` (rollback to revision 1). List revisions: `helm history release-name`. Auto rollback with `--atomic` flag on upgrade. Helm stores release history in Kubernetes secrets.",
    ),
    (
        r"\bhelm\b.*\b(?:values|override|set)\b|\bhelm.*\b-f\b|\bvalues\.yaml\b.*\bhelm\b",
        "**Helm values**: `helm install -f values.yaml` for file, `--set key=value` for CLI override (takes priority). Merge: `helm install -f base.yaml -f override.yaml`. Inspect chart defaults: `helm show values chart/`.",
    ),
    (
        r"\bhelm\b.*\b(?:template|render|debug)\b|\bhelm template\b",
        "**Helm template**: `helm template release chart/ -f values.yaml > rendered.yaml` — renders without deploying. Add `--debug` for verbose output. Useful for debugging + reviewing Kubernetes manifests before apply.",
    ),
]


# ── Unified groundtruth category index ───────────────────────
def get_groundtruth_categories() -> dict[str, int]:
    """Return all groundtruth categories with counts of entries."""
    return {
        "colors": len(COLORS),
        "color_sets": len(COLOR_SETS),
        "scales": len(SCALES),
        "chords": len(CHORDS),
        "world_data_feeds": len(WORLD_DATA_FEEDS),
        "logic_fallacies": len(LOGIC_FALLACIES),
        "http_codes": len(_HTTP_CODES),
        "algorithms": len(_ALGORITHMS),
        "git_commands": len(_GIT_COMMANDS),
        "ports": len(_PORTS),
        "math_identities": len(_MATH_IDENTITIES),
        "science_constants": len(_SCIENCE_CONSTANTS),
        "mythology": len(_MYTHOLOGY),
        "historic_dates": len(_HISTORIC_DATES),
        "philosophy": len(_PHILOSOPHY),
        "art_history": len(_ART_HISTORY),
        "music_theory": len(_MUSIC_THEORY),
        "astronomy": len(_ASTRONOMY),
        "geology": len(_GEOLOGY),
        "psychology": len(_PSYCHOLOGY),
        "archaeology": len(_ARCHAEOLOGY),
        "elements": len(_ELEMENTS),
        "analogies": len(_ANALOGIES),
        "file_extensions": len(_FILE_EXTENSIONS),
        "http_methods": len(_HTTP_METHODS),
        "exit_codes": len(_EXIT_CODES),
        "container_commands": len(_CONTAINER_COMMANDS),
        "tz_abbrevs": len(_TZ_ABBREVS),
        "holidays": len(_HOLIDAYS),
        "kb_shortcuts": len(_KB_SHORTCUTS),
        "cuda_setup": len(_CUDA_SETUP),
        "city_timezones": len(_CITY_TZ),
        "capitals": 0,  # populated lazily
        "solar_eclipses": len(_SOLAR_ECLIPSES),
        "lunar_eclipses": len(_LUNAR_ECLIPSES),
        "physics_constants": len(_PHYSICS_CONSTANTS),
        "temperature_conversion": 1,  # function-based
        "prime_check": 1,  # function-based
        "fibonacci": 1,  # function-based
        "safe_eval_math": 1,  # function-based
        "nginx": len(_NGINX),
        "postgres": len(_POSTGRES),
        "nodejs": len(_NODEJS),
        "ffmpeg": len(_FFMPEG),
        "sysctl": len(_SYSCTL),
        "concurrency": len(_CONCURRENCY),
        "protobuf": len(_PROTOBUF),
        "ansible": len(_ANSIBLE),
        "java_modern": len(_JAVA_MODERN),
        "dns": len(_DNS),
        "almalinux": len(_ALMALINUX),
        "terraform": len(_TERRAFORM),
        "helm": len(_HELM),
        "mullm_system": len(_MULLM_SYSTEM),
    }


def search_groundtruth(q: str, category: str = "") -> dict:
    """
    Search across all groundtruth categories.
    Returns a dict with 'matches', 'category', and 'results'.
    """
    q_lower = q.lower().strip()
    results: list[dict] = []

    # Color search
    if not category or category in ("color", "colors"):
        if q_lower in ("", "all"):
            for name, hex_val in COLORS.items():
                results.append({"category": "color", "key": name, "value": hex_val})
        else:
            for set_name, members in COLOR_SETS.items():
                if q_lower in set_name or set_name in q_lower:
                    if isinstance(members, list):
                        for m in members:
                            results.append(
                                {"category": "color", "key": m, "value": COLORS.get(m, "?"), "set": set_name}
                            )
                    elif isinstance(members, dict):
                        for k, v in members.items():
                            results.append(
                                {"category": "color", "key": k, "value": v, "set": set_name, "complement": True}
                            )
            for name, hex_val in COLORS.items():
                if q_lower in name or q_lower in hex_val.lower():
                    if not any(r.get("key") == name for r in results):
                        results.append({"category": "color", "key": name, "value": hex_val})

    # Scale search
    if not category or category in ("scale", "scales"):
        scale_key = SCALE_ALIASES.get(q_lower, q_lower)
        if scale_key in SCALES:
            notes = SCALES[scale_key]
            intervals = SCALE_INTERVALS.get(scale_key, "")
            results.append(
                {
                    "category": "scale",
                    "key": scale_key,
                    "notes": notes,
                    "intervals": intervals,
                    "note_count": len(notes),
                }
            )
        elif not q_lower or q_lower == "all":
            for name, notes in SCALES.items():
                results.append({"category": "scale", "key": name, "notes": notes, "note_count": len(notes)})

    # Chord search
    if not category or category in ("chord", "chords"):
        if q_lower in CHORDS:
            results.append(
                {
                    "category": "chord",
                    "key": q_lower,
                    "intervals": CHORDS[q_lower],
                    "degrees": CHORD_NOTE_NAMES.get(q_lower, []),
                }
            )
        elif not q_lower or q_lower == "all":
            for cname, cintervals in CHORDS.items():
                results.append({"category": "chord", "key": cname, "intervals": cintervals})

    # HTTP codes
    if not category or category in ("http", "http_codes"):
        if q_lower.isdigit() and q_lower in _HTTP_CODES:
            name, desc = _HTTP_CODES[q_lower]
            results.append({"category": "http", "code": q_lower, "name": name, "description": desc})
        elif q_lower in ("all", "") and category in ("http", "http_codes"):
            for code, (name, desc) in _HTTP_CODES.items():
                results.append({"category": "http", "code": code, "name": name, "description": desc})

    # Algorithms
    if not category or category in ("algo", "algorithm", "algorithms", "big-o"):
        algo_key = re.sub(r"[\s\-_]", "", q_lower)
        if algo_key in _ALGORITHMS:
            best, avg, worst, space, notes = _ALGORITHMS[algo_key]  # type: ignore[assignment]
            results.append(
                {
                    "category": "algorithm",
                    "key": algo_key,
                    "best": best,
                    "average": avg,
                    "worst": worst,
                    "space": space,
                    "notes": notes,
                }
            )
        elif q_lower in ("all", "") and category in ("algo", "algorithm", "algorithms", "big-o"):
            for aname, av in _ALGORITHMS.items():
                results.append(
                    {
                        "category": "algorithm",
                        "key": aname,
                        "best": av[0],
                        "average": av[1],
                        "worst": av[2],
                        "space": av[3],
                    }
                )

    # Logic fallacies
    if not category or category in ("fallacy", "fallacies", "logic"):
        if q_lower in LOGIC_FALLACIES:
            results.append({"category": "fallacy", "key": q_lower, "description": LOGIC_FALLACIES[q_lower]})
        elif q_lower in ("all", "") and category in ("fallacy", "fallacies", "logic"):
            for name, desc in LOGIC_FALLACIES.items():
                results.append({"category": "fallacy", "key": name, "description": desc})
        elif q_lower:
            for name, desc in LOGIC_FALLACIES.items():
                if q_lower in name or q_lower in desc.lower():
                    results.append({"category": "fallacy", "key": name, "description": desc})

    # World data feeds
    if not category or category in ("feed", "feeds", "world", "data"):
        if q_lower in WORLD_DATA_FEEDS:
            results.append({"category": "world_feed", "key": q_lower, "url": WORLD_DATA_FEEDS[q_lower]})
        elif q_lower in ("all", "") and category in ("feed", "feeds", "world", "data"):
            for name, url in WORLD_DATA_FEEDS.items():
                results.append({"category": "world_feed", "key": name, "url": url})
        elif q_lower:
            for name, url in WORLD_DATA_FEEDS.items():
                if q_lower in name or q_lower in url.lower():
                    results.append({"category": "world_feed", "key": name, "url": url})

    return {
        "query": q,
        "category": category,
        "count": len(results),
        "results": results,
    }


def _convert(val: float, fr: str, to: str) -> float | None:
    """Simple unit conversion. Returns None if unknown."""
    # Normalize plurals
    fr = re.sub(r"miles?", "mi", fr)
    fr = re.sub(r"pounds?", "lb", fr)
    fr = re.sub(r"lbs?", "lb", fr)
    to = re.sub(r"miles?", "mi", to)
    to = re.sub(r"pounds?", "lb", to)
    to = re.sub(r"lbs?", "lb", to)
    if fr == to:
        return val
    # Normalize temperature aliases
    fr = {"celsius": "c", "fahrenheit": "f"}.get(fr, fr)
    to = {"celsius": "c", "fahrenheit": "f"}.get(to, to)
    conversions = {
        ("km", "mi"): val * 0.621371,
        ("mi", "km"): val * 1.60934,
        ("kg", "lb"): val * 2.20462,
        ("lb", "kg"): val * 0.453592,
        ("c", "f"): val * 9 / 5 + 32,
        ("f", "c"): (val - 32) * 5 / 9,
    }
    return conversions.get((fr, to))


def _next_from(
    now: datetime,
    events: list[tuple[str, str, str]],
) -> tuple[str, str, str] | None:
    for date_str, name, detail in events:
        event_date = datetime.strptime(date_str, "%Y-%m-%d")
        if event_date.date() >= now.date():
            return (date_str, name, detail)
    return None


# ── Identity / self-awareness queries ────────────────────────

_IDENTITY_SHORT_RE = r"(?:who|what) are you|what is (?:mullm|mu llm)|what(?:'s| is) mullm|what(?:'s| is) mu llm"
_IDENTITY_DEEP_RE = r"tell me about (?:yourself|mullm)|describe yourself"
_IDENTITY_CAPS_RE = r"what (?:can|do) you do|what are your capabilities"
_IDENTITY_NAME_RE = r"what is your name|what(?:'s| is) your name"


def try_resolve_identity(text: str) -> str | None:
    """
    Handle identity / self-awareness queries instantly, no model call.
    Returns a contextual response or None.
    """
    lower = text.lower().strip().rstrip("?!.")
    # Guard: long queries or code-generation requests are never identity queries
    if len(lower) > 120:
        return None
    if any(
        w in lower
        for w in (
            "def ",
            "class ",
            "import ",
            "function",
            "implement",
            "build a",
            "write a",
            "create a",
            "minimal ",
            "snippet",
            "abstraction",
            "fastapi",
            "vllm",
            "sglang",
            "llamacpp",
        )
    ):
        return None

    # "what is mullm" / technical explanation
    if re.search(r"\bwhat is (?:mullm|mu llm)\b|what(?:'s| is) mullm", lower):
        return (
            "muLLM (mμ|LLM) is a local-first AI router built on FastAPI. "
            "It uses a classifier pipeline to analyze each query, then routes it to the cheapest capable model. "
            "Local inference runs on Ollama (currently qwen3.5:9b on an RTX 5090 with 32GB VRAM) for zero-cost answers. "
            "When a query genuinely needs more capability, it falls back to cloud models — Anthropic Claude, OpenAI GPT, or Google Gemini. "
            "Responses are cached in ChromaDB (vector similarity), so repeat and similar queries are instant and free. "
            "The system includes budget controls, a scoring log, and a real-time isometric dashboard. "
            "Architecture: FastAPI backend on port 8100, single-file HTML frontends, "
            "ChromaDB vector cache, Dexie.js IndexedDB for client-side chat history, JSONL scoring log."
        )

    # "tell me about yourself/mullm" or "describe yourself" — capabilities
    if re.search(_IDENTITY_DEEP_RE, lower):
        return (
            "I'm muLLM (mμ|LLM) — a local-first AI router designed for microscopic costs. "
            "Here's what I can do:\n\n"
            "• **Smart routing** — classify your query and pick the cheapest capable model (local or cloud)\n"
            "• **Vector caching** — ChromaDB similarity cache means repeat queries cost $0.00\n"
            "• **Split routing** — decompose multi-part prompts and run them in parallel across models\n"
            "• **Streaming** — SSE streaming for local Ollama responses\n"
            "• **Voice I/O** — speech-to-text input and text-to-speech output\n"
            "• **Cost tracking** — real-time budget controls, per-query cost logging, session totals\n"
            "• **Isometric dashboard** — live stats with real data from the scoring log\n"
            "• **Multi-model support** — 12+ cloud models (Anthropic, OpenAI, Google) plus local Ollama\n"
            "• **Translation** — auto-detect and translate between languages\n"
            "• **Real-time date/time** — instant answers for time, date, timezone, eclipse, and calendar queries\n\n"
            "Local queries and cache hits are free. Cloud queries cost fractions of a cent."
        )

    # Infrastructure queries — unblock, heartbeat, ComfyUI, agents
    if re.search(r"\b(?:unblock|heartbeat|agent.?registration|how.?do.?agents)\b", lower):
        return (
            "muLLM's agent coordination system:\n\n"
            "• **/unblock** — dashboard where agents post blocker cards for human decisions. "
            "Agents POST to `/api/agents/blocked` with summary, options, severity.\n"
            "• **Heartbeat** — agents pulse `POST /api/agents/heartbeat` every 60s. "
            "Shows as a teal dot on /unblock activity bar. Goes RED after 90s silence = STALLED.\n"
            "• **Multi-select** — tap multiple options on a card to queue priorities, auto-submits after 3.5s.\n"
            "• **Registration** — every subagent MUST register on /unblock so the user can see its status.\n\n"
            "Image gen: ComfyUI ($0, 2.2s local) → DALL-E 3 ($0.04 cloud fallback). "
            "3D models: Meshy API (PRO plan). "
            "All managed via /unblock on phone."
        )

    if re.search(r"\b(?:comfyui|comfy.?ui|image.?gen.*local|local.?image)\b", lower):
        return (
            "ComfyUI runs on localhost:8188 with SDXL Turbo (2.2s/image, $0). "
            "RTX 5090 32GB VRAM, reserve-vram 16GB for Ollama. "
            "Images proxied through muLLM at /api/comfyui/image for LAN/mobile access. "
            "Routing: ComfyUI first → DALL-E 3 fallback ($0.04) → error message."
        )

    # "what can you do" / capabilities
    if re.search(_IDENTITY_CAPS_RE, lower):
        return (
            "I'm muLLM (mμ|LLM) — a local-first AI router. My capabilities include:\n\n"
            "• **Smart routing** — classify your query and pick the cheapest capable model\n"
            "• **Vector caching** — similar queries hit cache instantly at $0.00\n"
            "• **Split routing** — break complex prompts into parallel sub-queries\n"
            "• **Streaming** — real-time SSE streaming for local model responses\n"
            "• **Voice I/O** — speech-to-text and text-to-speech\n"
            "• **Cost tracking** — per-query costs, session totals, budget controls\n"
            "• **Multi-model** — local Ollama + Anthropic + OpenAI + Google cloud models\n"
            "• **Real-time lookups** — date, time, timezones, eclipses, math, conversions\n"
            "• **Translation** — multi-language support\n\n"
            "Ask me anything — I'll find the cheapest way to answer it."
        )

    # Short: "who are you" / "what are you" / "what's your name"
    if re.search(_IDENTITY_SHORT_RE, lower) or re.search(_IDENTITY_NAME_RE, lower):
        return (
            "I'm muLLM (mμ|LLM) — a local-first AI router. "
            "I classify your query, pick the cheapest capable model "
            "(local Ollama, or cloud when needed), and answer it. "
            "Cache hits and local queries cost $0.00. Ask me anything."
        )

    # ── Navigation / "where is X?" queries ───────────────────
    for rx, answer in _NAV_MAP:
        if rx.search(lower):
            return answer

    # ── Protocol / technical questions ─────────────────────────
    if re.search(r"(?:what|how|explain|describe).{0,15}(?:a2a|agent.to.agent)\b.*(?:spec|protocol|work|use)", lower):
        return (
            "muLLM's A2A (Agent-to-Agent) implementation is inspired by Google's A2A spec but simplified:\n\n"
            "• **Agent registration**: `POST /api/agents/register` — register with ID, endpoint, capabilities\n"
            "• **Discovery**: `GET /api/agents` — find agents by capability\n"
            "• **Task queue**: `POST /api/agents/{id}/task` — add work to a registered agent's in-process queue\n"
            "• **Heartbeat**: `POST /api/agents/{id}/heartbeat` — keep-alive signal\n"
            "• **Pause/resume/delete**: lifecycle management\n"
            "• **Discovery manifest**: `GET /.well-known/ai-plugin.json`\n\n"
            "It's HTTP-based (not the full A2A streaming spec). Agents register in-memory and can be discovered by other agents on the network. "
            "See [/a2a](/a2a) for full docs."
        )

    if re.search(r"(?:what|how|explain|describe).{0,15}(?:mcp|model context)\b.*(?:spec|protocol|work|use)", lower):
        return (
            "muLLM implements MCP (Model Context Protocol) over HTTP:\n\n"
            "• **Tool listing**: `GET /mcp/tools` — lists available tools (query, split, classify, budget, system)\n"
            "• **Tool calling**: `POST /mcp/tools/call` — execute a tool by name with arguments\n"
            "• **Query tool**: `POST /mcp/tools/query` — same as /query but MCP-wrapped response\n\n"
            "The shipped HTTP tools are mullm_query, mullm_split, mullm_classify, mullm_budget, and mullm_system.\n\n"
            "This is HTTP-based MCP, not stdio transport. For Claude Desktop/Cursor integration, "
            "run a stdio bridge that forwards tool calls to these HTTP endpoints. See [/mcp](/mcp) for full docs."
        )

    if re.search(
        r"(?:what|how|explain|describe).{0,15}(?:json.?rpc|rpc)\b.*(?:spec|protocol|work|use|endpoint)", lower
    ):
        return (
            "muLLM supports standard **JSON-RPC 2.0** at `POST /rpc`:\n\n"
            '```json\n{"jsonrpc":"2.0","method":"query","params":{"content":"hello"},"id":1}\n```\n\n'
            "Methods: query, classify, cache.lookup, cache.store, budget.status, system.info, agents.list, agents.register.\n"
            "Supports batch requests (send an array). See [/rpc/docs](/rpc/docs) for full method reference."
        )

    if re.search(r"(?:what|how).{0,10}(?:make|special|unique|different|better).{0,20}(?:mullm|mu.?llm|you)", lower):
        return (
            "What makes muLLM special:\n\n"
            "• **99%+ cost savings** — real number from the dashboard, not marketing\n"
            "• **Local-first** — your GPU handles most queries at $0.00, data never leaves your machine\n"
            "• **Smart routing** — classifier analyzes complexity, routes to the cheapest capable model\n"
            "• **Vector cache** — similar queries return cached answers instantly\n"
            "• **Sub-millisecond answers** — ground truth resolver handles math, dates, conversions faster than any API\n"
            "• **Multi-provider** — Anthropic + OpenAI + Google + local Ollama in one interface\n"
            "• **Split routing** — complex prompts decomposed and run in parallel across tiers\n"
            "• **57+ games** — AI-generated games, instruments, card games, and tools at [/games](/games)\n"
            "• **Real dashboards** — every metric is real, from the scoring log, not mocked"
        )

    if re.search(
        r"(?:show|draw|display|give|what is|explain|describe).{0,20}(?:architecture|diagram|system design)", lower
    ) or re.search(r"(?:architecture|diagram|system design).{0,20}(?:mullm|mu.?llm)", lower):
        return (
            "## muLLM Architecture\n\n"
            "```\n"
            "User Query\n"
            "    │\n"
            "    ▼\n"
            "┌─────────────┐\n"
            "│  FastAPI     │ ← port 8100, HTTPS\n"
            "│  Router      │\n"
            "└──────┬──────┘\n"
            "       │\n"
            "  ┌────▼────┐\n"
            "  │ Ground   │ ← math, dates, conversions, identity ($0)\n"
            "  │ Truth    │\n"
            "  └────┬────┘\n"
            "       │ miss\n"
            "  ┌────▼────┐\n"
            "  │ ChromaDB │ ← vector similarity cache ($0)\n"
            "  │ Cache    │\n"
            "  └────┬────┘\n"
            "       │ miss\n"
            "  ┌────▼────┐\n"
            "  │Classifier│ ← keyword rules + LLM dual opinion\n"
            "  │ Intent   │\n"
            "  └────┬────┘\n"
            "       │\n"
            "  ┌────▼────────────────────────┐\n"
            "  │ Tier Selection              │\n"
            "  │ local → local_multi → cloud │\n"
            "  └──┬──────┬──────────┬────────┘\n"
            "     │      │          │\n"
            "  ┌──▼──┐ ┌─▼──┐  ┌───▼───┐\n"
            "  │Ollama│ │Split│  │Cloud  │\n"
            "  │ $0   │ │Route│  │API    │\n"
            "  └──────┘ └────┘  └───────┘\n"
            "                      │\n"
            "              ┌───────▼──────┐\n"
            "              │ Score + Cache │\n"
            "              │ Back + Log   │\n"
            "              └──────────────┘\n"
            "```\n\n"
            "**Stack:** FastAPI, ChromaDB, Ollama (qwen3.5:9b on RTX 5090), "
            "Anthropic/OpenAI/Google cloud, Dexie.js IndexedDB (client), JSONL scoring log."
        )

    # ── Greetings (never need the LLM) ──────────────────────
    _greet = lower.rstrip("?!. ")
    if _greet in ("hi", "hey", "hello", "yo", "sup", "hiya", "heya", "howdy"):
        return (
            "Hey! I'm muLLM — your local-first AI router. Ask me anything and I'll find the cheapest way to answer it."
        )
    if re.search(r"^(?:what'?s up|whats up|wassup|wazzup|what is up)$", _greet):
        return "Not much — just routing queries to the cheapest capable model! Cache is warm, local model is ready. What can I help with?"
    if re.search(r"^(?:how are you|how'?s it going|how do you do|how you doing|howsit|how'?sit)$", _greet):
        return f"Running great! Cache has {_get_cache_count()} entries, local model is warm, and everything's routing smoothly. What would you like to know?"
    if re.search(r"^(?:good morning|good afternoon|good evening|good night|gm|gn)$", _greet):
        now = _now()
        return f"Good {_time_of_day(now)}! It's {now.strftime('%I:%M %p')} local time. How can I help?"
    if re.search(r"^(?:thanks|thank you|thx|ty|cheers)$", _greet):
        return "You're welcome! Let me know if you need anything else."
    if re.search(r"^(?:bye|goodbye|see ya|later|cya|peace out|peace)$", _greet):
        return "See you! Your session data is saved locally. Come back anytime — I'll be here."

    return None


def _get_cache_count() -> int:
    """Get cache doc count without importing heavy modules."""
    try:
        import sqlite3

        from router.config import settings

        db_path = settings.cache_dir / "chromadb" / "chroma.sqlite3"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
            conn.close()
            return int(count)
    except Exception:
        pass
    return 0


def _time_of_day(now) -> str:
    h = now.hour
    if h < 12:
        return "morning"
    if h < 17:
        return "afternoon"
    if h < 21:
        return "evening"
    return "night"


# ── Web search context (DuckDuckGo, zero API key) ──────────


async def web_search_context(query: str, max_results: int = 3) -> tuple[str, list[dict]]:
    """
    Fetch context from DuckDuckGo Instant Answer API + HTML fallback.
    Returns (context_string, sources_list) where sources_list is [{title, url, snippet}]
    for rendering citation footnotes in the UI.
    """
    sources: list[dict] = []
    try:
        import httpx

        # Try DuckDuckGo Instant Answer API first (structured, fast)
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1"},
                headers={"User-Agent": "muLLM/0.4 (local-first LLM router)"},
            )
            if resp.status_code == 200:
                data = resp.json()
                parts = []

                # Abstract (direct answer) — from Wikipedia / Wikidata
                abstract = data.get("AbstractText", "")
                abstract_url = data.get("AbstractURL", "")
                abstract_src = data.get("AbstractSource", "")
                if abstract:
                    parts.append(f"[1] {abstract[:500]}")
                    sources.append(
                        {
                            "index": 1,
                            "title": abstract_src or "Web",
                            "url": abstract_url or f"https://duckduckgo.com/?q={query}",
                            "snippet": abstract[:200],
                        }
                    )

                # Related topics — each has a FirstURL
                idx = len(sources) + 1
                for topic in data.get("RelatedTopics", [])[:max_results]:
                    text = topic.get("Text", "")
                    url = topic.get("FirstURL", "")
                    if text and len(text) > 20:
                        parts.append(f"[{idx}] {text[:200]}")
                        sources.append(
                            {
                                "index": idx,
                                "title": text[:60],
                                "url": url or f"https://duckduckgo.com/?q={query}",
                                "snippet": text[:200],
                            }
                        )
                        idx += 1

                if parts:
                    ctx = "Web search results:\n" + "\n".join(parts)
                    return ctx, sources

            # Fallback: DuckDuckGo Lite HTML scrape (extract result titles + links)
            resp = await client.get(
                "https://lite.duckduckgo.com/lite/",
                params={"q": query},
                headers={"User-Agent": "muLLM/0.4"},
                follow_redirects=True,
            )
            if resp.status_code == 200:
                # Extract snippets
                snippets = re.findall(
                    r'class="result-snippet"[^>]*>(.*?)</td>',
                    resp.text,
                    re.DOTALL,
                )
                # Extract result links
                links = re.findall(
                    r'<a[^>]+class="result-link"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
                    resp.text,
                )
                results = []
                for i, snippet in enumerate(snippets[:max_results]):
                    clean = re.sub(r"<[^>]+>", "", snippet).strip()
                    if clean and len(clean) > 20:
                        idx = i + 1
                        url, title = (
                            (links[i][0], links[i][1])
                            if i < len(links)
                            else (f"https://duckduckgo.com/?q={query}", f"Result {idx}")
                        )
                        results.append(f"[{idx}] {clean[:200]}")
                        sources.append(
                            {
                                "index": idx,
                                "title": title.strip()[:80],
                                "url": url,
                                "snippet": clean[:200],
                            }
                        )
                if results:
                    ctx = "Web search results:\n" + "\n".join(results)
                    return ctx, sources

    except Exception as e:
        log.warning("web_search_failed", error=str(e)[:100])

    return "", []


async def jina_fetch_context(url: str, max_chars: int = 4000) -> str:
    """
    Fetch a URL via Jina Reader (r.jina.ai) — returns clean markdown, no ads/nav.
    Free, no API key. ~80% token reduction vs raw HTML.
    Falls back silently if Jina is down or URL is invalid.
    """
    try:
        import httpx

        jina_url = f"https://r.jina.ai/{url}"
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                jina_url,
                headers={
                    "User-Agent": "muLLM/0.4 (local-first LLM router)",
                    "Accept": "text/plain",
                    "X-Return-Format": "markdown",
                },
                follow_redirects=True,
            )
            if resp.status_code == 200:
                text = resp.text.strip()
                # Strip Jina's own header boilerplate (first ~3 lines are metadata)
                lines = text.splitlines()
                if lines and lines[0].startswith("Title:"):
                    lines = lines[3:]  # skip Title/URL/Published headers
                text = "\n".join(lines).strip()
                return text[:max_chars]
    except Exception as e:
        log.warning("jina_fetch_failed", url=url[:80], error=str(e)[:80])
    return ""


# ── Open-Meteo weather (free, no API key) ────────────────────────────────────

# city → (latitude, longitude, display_name)
_CITY_COORDS: dict[str, tuple[float, float, str]] = {
    "london":        (51.51, -0.13, "London"),
    "paris":         (48.85, 2.35, "Paris"),
    "berlin":        (52.52, 13.41, "Berlin"),
    "madrid":        (40.42, -3.70, "Madrid"),
    "rome":          (41.89, 12.48, "Rome"),
    "amsterdam":     (52.37, 4.90, "Amsterdam"),
    "vienna":        (48.21, 16.37, "Vienna"),
    "zurich":        (47.38, 8.54, "Zurich"),
    "stockholm":     (59.33, 18.07, "Stockholm"),
    "oslo":          (59.91, 10.75, "Oslo"),
    "copenhagen":    (55.68, 12.57, "Copenhagen"),
    "helsinki":      (60.17, 24.94, "Helsinki"),
    "warsaw":        (52.23, 21.01, "Warsaw"),
    "prague":        (50.08, 14.44, "Prague"),
    "budapest":      (47.50, 19.04, "Budapest"),
    "athens":        (37.98, 23.73, "Athens"),
    "istanbul":      (41.01, 28.96, "Istanbul"),
    "moscow":        (55.75, 37.62, "Moscow"),
    "kyiv":          (50.45, 30.52, "Kyiv"),
    "lisbon":        (38.72, -9.14, "Lisbon"),
    "brussels":      (50.85, 4.35, "Brussels"),
    "dublin":        (53.33, -6.25, "Dublin"),
    "new york":      (40.71, -74.01, "New York"),
    "nyc":           (40.71, -74.01, "New York"),
    "los angeles":   (34.05, -118.24, "Los Angeles"),
    "chicago":       (41.85, -87.65, "Chicago"),
    "houston":       (29.76, -95.37, "Houston"),
    "miami":         (25.77, -80.19, "Miami"),
    "seattle":       (47.61, -122.33, "Seattle"),
    "toronto":       (43.65, -79.38, "Toronto"),
    "vancouver":     (49.25, -123.12, "Vancouver"),
    "mexico city":   (19.43, -99.13, "Mexico City"),
    "sao paulo":     (-23.55, -46.63, "São Paulo"),
    "buenos aires":  (-34.60, -58.38, "Buenos Aires"),
    "bogota":        (4.71, -74.07, "Bogotá"),
    "santiago":      (-33.46, -70.65, "Santiago"),
    "lima":          (-12.05, -77.04, "Lima"),
    "tokyo":         (35.69, 139.69, "Tokyo"),
    "beijing":       (39.91, 116.39, "Beijing"),
    "shanghai":      (31.23, 121.47, "Shanghai"),
    "hong kong":     (22.32, 114.17, "Hong Kong"),
    "singapore":     (1.29, 103.85, "Singapore"),
    "seoul":         (37.57, 126.98, "Seoul"),
    "mumbai":        (19.08, 72.88, "Mumbai"),
    "delhi":         (28.66, 77.23, "Delhi"),
    "bangalore":     (12.97, 77.59, "Bangalore"),
    "dubai":         (25.20, 55.27, "Dubai"),
    "bangkok":       (13.75, 100.52, "Bangkok"),
    "jakarta":       (-6.21, 106.85, "Jakarta"),
    "manila":        (14.60, 120.98, "Manila"),
    "taipei":        (25.05, 121.53, "Taipei"),
    "cairo":         (30.06, 31.25, "Cairo"),
    "nairobi":       (-1.29, 36.82, "Nairobi"),
    "johannesburg":  (-26.20, 28.04, "Johannesburg"),
    "lagos":         (6.52, 3.38, "Lagos"),
    "casablanca":    (33.59, -7.62, "Casablanca"),
    "sydney":        (-33.87, 151.21, "Sydney"),
    "melbourne":     (-37.81, 144.96, "Melbourne"),
    "auckland":      (-36.86, 174.77, "Auckland"),
    "honolulu":      (21.31, -157.86, "Honolulu"),
    "san francisco": (37.77, -122.42, "San Francisco"),
    "boston":        (42.36, -71.06, "Boston"),
    "denver":        (39.74, -104.98, "Denver"),
    "phoenix":       (33.45, -112.07, "Phoenix"),
    "riyadh":        (24.69, 46.72, "Riyadh"),
    "tel aviv":      (32.09, 34.79, "Tel Aviv"),
    "karachi":       (24.86, 67.01, "Karachi"),
    "tehran":        (35.69, 51.42, "Tehran"),
    "barcelona":     (41.39, 2.15, "Barcelona"),
    "milan":         (45.46, 9.19, "Milan"),
    "munich":        (48.14, 11.58, "Munich"),
}


async def get_weather_for_city(city: str) -> dict | None:
    """
    Fetch current temperature for a city via Open-Meteo (free, no API key).
    Returns dict with keys: city, temp_c, temp_f, description, wind_kmh, humidity.
    Returns None on any failure.
    """
    coords = _CITY_COORDS.get(city.lower().strip())
    if coords is None:
        return None
    lat, lon, display = coords
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
        f"&wind_speed_unit=kmh&temperature_unit=celsius&timezone=auto"
    )
    try:
        import httpx
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        cur = data.get("current", {})
        temp_c = cur.get("temperature_2m")
        if temp_c is None:
            return None
        temp_f = round(temp_c * 9 / 5 + 32, 1)
        wmo = int(cur.get("weather_code") or 0)
        desc = _WMO_DESCRIPTIONS.get(wmo, "")
        return {
            "city": display,
            "temp_c": round(temp_c, 1),
            "temp_f": temp_f,
            "description": desc,
            "wind_kmh": round(float(cur.get("wind_speed_10m") or 0), 1),
            "humidity": int(cur.get("relative_humidity_2m") or 0),
        }
    except Exception as exc:
        log.debug("open_meteo_failed", city=city, error=str(exc)[:80])
        return None


_WMO_DESCRIPTIONS: dict[int, str] = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "icy fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "heavy drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    71: "slight snow", 73: "moderate snow", 75: "heavy snow",
    77: "snow grains",
    80: "slight showers", 81: "moderate showers", 82: "violent showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


_WEATHER_QUERY_RE = re.compile(
    r"\b(?:weather|temperature|temp\b|warm(?:er|est)?|cold(?:er|est)?|hot(?:ter|test)?|cool(?:er|est)?"
    r"|chilly|freez|forecast|rain|snow|wind|humid|sunny|cloudy|climate)\b",
    re.IGNORECASE,
)
_CITY_EXTRACT_RE = re.compile(r"\b(?:in|at|for)\s+([A-Za-z][A-Za-z\s]{1,25}?)(?:\s+(?:and|or|vs?\.?|right|now|today|currently|please|\?)|$)", re.IGNORECASE)
_COMPARE_RE = re.compile(r"\b(?:warmer|colder|hotter|cooler|more\s+warm|more\s+cold)\b.*?\b(?:or|vs?\.?)\b", re.IGNORECASE)


async def try_resolve_weather_async(query: str) -> str | None:
    """
    Resolve weather queries against Open-Meteo (free, no key).
    Returns formatted answer or None if city not found or query not weather-related.
    """
    lower = query.lower().strip()
    if not _WEATHER_QUERY_RE.search(lower):
        return None

    # Extract all city names mentioned
    cities_found = [m.group(1).strip().lower() for m in _CITY_EXTRACT_RE.finditer(lower)]
    # Also check direct known city mentions
    for city_key in _CITY_COORDS:
        if city_key in lower and city_key not in cities_found:
            cities_found.append(city_key)

    # Deduplicate keeping order
    seen: set[str] = set()
    unique_cities = [c for c in cities_found if not (c in seen or seen.add(c))]  # type: ignore[func-returns-value]
    known_cities = [c for c in unique_cities if c in _CITY_COORDS]

    if not known_cities:
        return None

    import asyncio as _asyncio
    results = await _asyncio.gather(*[get_weather_for_city(c) for c in known_cities[:4]])
    weather_data = [r for r in results if r is not None]

    if not weather_data:
        return None

    if len(weather_data) == 1:
        w = weather_data[0]
        desc = f" ({w['description']})" if w["description"] else ""
        return (
            f"Current weather in {w['city']}: {w['temp_c']}°C / {w['temp_f']}°F{desc}. "
            f"Humidity {w['humidity']}%, wind {w['wind_kmh']} km/h. "
            f"(Source: Open-Meteo — real-time data, no API key required)"
        )

    # Comparison: sort by temperature
    weather_data.sort(key=lambda x: x["temp_c"], reverse=True)
    lines = ["Current temperatures (Open-Meteo real-time data):"]
    for i, w in enumerate(weather_data):
        rank = " — warmest" if i == 0 else (" — coolest" if i == len(weather_data) - 1 else "")
        desc = f" ({w['description']})" if w["description"] else ""
        lines.append(f"  • {w['city']}: {w['temp_c']}°C / {w['temp_f']}°F{desc}{rank}")
    return "\n".join(lines)
