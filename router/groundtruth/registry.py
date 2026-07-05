"""
Groundtruth registry engine.

Each category is a CategoryPlugin with pattern handlers and/or a resolver
callable. The registry tries all registered categories and returns the first
match as (answer, category_name), or None if nothing matched.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Plugin dataclass
# ---------------------------------------------------------------------------

@dataclass
class CategoryPlugin:
    name: str
    patterns: list[tuple[re.Pattern, Callable[[re.Match], str]]] = field(default_factory=list)
    resolver: Callable[[str], str | None] | None = None  # for dynamic lookups


# ---------------------------------------------------------------------------
# Registry state
# ---------------------------------------------------------------------------

_categories: dict[str, CategoryPlugin] = {}
_core_loaded: bool = False


_GENERATION_OR_CODE_RE = re.compile(
    r"\b("
    r"write|implement|build|create|generate|refactor|patch|fix|debug|"
    r"unit\s+tests?|typescript|javascript|python|rust|go|java|c\+\+|"
    r"class|function|serialization|range\s+query|b\+?\s*tree|readme\.md"
    r")\b",
    re.IGNORECASE,
)


def _should_skip_groundtruth(query: str) -> bool:
    """
    Keep deterministic lookup tables on the zero-false-positive path.

    The original muLLM router intentionally refused long or technical prompts
    in the fast-path lookup layer. Broad lookup entries such as HTTP DELETE are
    correct for "what is DELETE?" and dangerous for "implement delete in a
    B+ tree". Complex prompts must reach classification/cache/model routing.
    """
    q = query.strip()
    if len(q) > 180:
        return True
    if len(q) > 70 and _GENERATION_OR_CODE_RE.search(q):
        return True
    return False


def register_category(plugin: CategoryPlugin) -> None:
    """Register a CategoryPlugin by name. Later registrations overwrite earlier ones."""
    _categories[plugin.name] = plugin


def list_categories() -> list[str]:
    """Return names of all currently registered categories."""
    return list(_categories.keys())


def _ensure_core_loaded() -> None:
    """Load core categories on first lookup if load_categories() was never called."""
    global _core_loaded
    if not _core_loaded:
        _core_loaded = True
        try:
            from .core import register_all_core
            register_all_core()
        except Exception:
            pass
        try:
            from router.realtime import try_resolve_locally
            register_category(CategoryPlugin(name="realtime", resolver=try_resolve_locally))
        except Exception:
            pass


def lookup(query: str) -> tuple[str, str] | None:
    """
    Try all registered categories in registration order.

    Returns (answer, category_name) on the first match, or None to fall through.
    Zero false-positive contract: handlers must only return a result when 100% certain.
    """
    _ensure_core_loaded()
    q = query.strip()
    if _should_skip_groundtruth(q):
        return None
    for cat in _categories.values():
        for pattern, handler in cat.patterns:
            m = pattern.search(q)
            if m:
                try:
                    result = handler(m)
                    if result:
                        return (result, cat.name)
                except Exception:
                    continue
        if cat.resolver:
            try:
                result = cat.resolver(q)
                if result:
                    return (result, cat.name)
            except Exception:
                continue
    return None
