"""
Groundtruth category loader — called once at server startup.

Reads enabled_categories from [groundtruth] section of mullm.toml.
Core categories are always registered. Optional categories are gated
by the enabled_categories list.

Default enabled_categories (if not set in config):
  arithmetic, datetime, http_status, unit_conversion, git_commands,
  big_o, big_o_ds, ports

Optional (add to enabled_categories to enable):
  wcag, live/weather/crypto, gaming, ue5
"""
from __future__ import annotations


def _read_enabled_categories() -> list[str]:
    """
    Read groundtruth.enabled_categories from TOML config.
    Falls back to the default set if not configured.

    Note: router.config.Settings does not currently flatten [groundtruth]
    from mullm.toml, so we load the TOML directly here.
    """
    default = [
        "arithmetic", "datetime", "http_status", "unit_conversion",
        "git_commands", "big_o", "big_o_ds", "ports",
    ]
    try:
        import tomllib
        from pathlib import Path
        def _load(p):
            return tomllib.loads(p.read_text(encoding="utf-8"))

        # Try project-local mullm.toml first
        for candidate in (Path.cwd() / "mullm.toml", Path.home() / ".mullm" / "config.toml"):
            if candidate.exists():
                data = _load(candidate)
                gt = data.get("groundtruth", {})
                enabled = gt.get("enabled_categories")
                if enabled is not None:
                    return list(enabled)
    except Exception:
        pass

    return default


def load_categories(enabled: list[str] | None = None) -> None:
    """
    Load groundtruth categories. Call once during FastAPI lifespan startup.

    Args:
        enabled: explicit list of categories to enable, or None to read
                 from mullm.toml / defaults.
    """
    from .core import register_all_core
    register_all_core()

    if enabled is None:
        enabled = _read_enabled_categories()

    enabled_set = set(enabled)

    if "wcag" in enabled_set:
        from .wcag import register_wcag
        register_wcag()

    if enabled_set & {"live", "weather", "crypto"}:
        try:
            from .live import register_live
            register_live()
        except Exception:
            pass  # Redis or network not available — skip live category

    if "gaming" in enabled_set:
        try:
            from .optional.gaming import register_gaming
            register_gaming()
        except Exception:
            pass

    if "ue5" in enabled_set:
        try:
            from .optional.ue5 import register_ue5
            register_ue5()
        except Exception:
            pass
