"""Pluggable realtime/groundtruth resolver registry.

Users can add small Python files under ``~/.mullm/realtime_plugins``. A plugin may
expose either:

```
def resolve(text: str) -> str | None: ...
```

or:

```
PATTERNS = [(r"^hello$", "world")]
```

These plugins run locally and synchronously, so they must stay small and
deterministic. They are opt-in code execution from the user's own config
directory, not remotely downloaded code.
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

Resolver = Callable[[str], str | None]
DEFAULT_PLUGIN_DIR = Path.home() / ".mullm" / "realtime_plugins"


@dataclass
class RealtimePlugin:
    name: str
    resolver: Resolver | None = None
    patterns: list[tuple[re.Pattern[str], str | Resolver]] = field(default_factory=list)

    def resolve(self, text: str) -> str | None:
        if self.resolver:
            result = self.resolver(text)
            if result:
                return result
        for pattern, answer in self.patterns:
            match = pattern.search(text)
            if not match:
                continue
            if callable(answer):
                return answer(text)
            return answer
        return None


_plugins: list[RealtimePlugin] = []
_loaded_dirs: set[Path] = set()


def register_plugin(plugin: RealtimePlugin) -> None:
    _plugins.append(plugin)


def clear_plugins() -> None:
    _plugins.clear()
    _loaded_dirs.clear()


def list_plugins() -> list[dict[str, int | str]]:
    return [
        {"name": plugin.name, "patterns": len(plugin.patterns), "has_resolver": int(plugin.resolver is not None)}
        for plugin in _plugins
    ]


def _plugin_from_module(path: Path, module: ModuleType) -> RealtimePlugin | None:
    resolver = getattr(module, "resolve", None)
    if resolver is not None and not callable(resolver):
        resolver = None

    patterns: list[tuple[re.Pattern[str], str | Resolver]] = []
    for item in getattr(module, "PATTERNS", []):
        if not isinstance(item, list | tuple) or len(item) != 2:
            continue
        raw_pattern, answer = item
        if not isinstance(raw_pattern, str):
            continue
        if not isinstance(answer, str) and not callable(answer):
            continue
        patterns.append((re.compile(raw_pattern, re.IGNORECASE), answer))

    if not resolver and not patterns:
        return None
    name = str(getattr(module, "PLUGIN_NAME", path.stem))
    return RealtimePlugin(name=name, resolver=resolver, patterns=patterns)


def load_user_plugins(plugin_dir: Path = DEFAULT_PLUGIN_DIR) -> list[str]:
    plugin_dir = plugin_dir.expanduser().resolve()
    if plugin_dir in _loaded_dirs or not plugin_dir.is_dir():
        return []
    loaded: list[str] = []
    for path in sorted(plugin_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"mullm_user_realtime_{path.stem}", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plugin = _plugin_from_module(path, module)
        if plugin is not None:
            register_plugin(plugin)
            loaded.append(plugin.name)
    _loaded_dirs.add(plugin_dir)
    return loaded


def resolve_with_plugins(text: str) -> str | None:
    load_user_plugins()
    for plugin in list(_plugins):
        try:
            result = plugin.resolve(text)
        except Exception:
            continue
        if result:
            return result
    return None

