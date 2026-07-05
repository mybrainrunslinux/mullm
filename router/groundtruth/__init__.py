"""
muLLM groundtruth package.

Public API:
  lookup(query)         → (answer, category) | None
  register_category(p) → None
  list_categories()     → list[str]
  CategoryPlugin        — dataclass for building category plugins
"""
from .registry import CategoryPlugin, list_categories, lookup, register_category

__all__ = ["lookup", "register_category", "list_categories", "CategoryPlugin"]
