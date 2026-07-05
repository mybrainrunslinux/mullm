"""Language pack metadata and setup selection helpers."""

from __future__ import annotations

SUPPORTED_LANGUAGE_CODES = ("de", "es", "fr", "hu", "it")

LANGUAGE_PACKS: dict[str, dict[str, object]] = {
    "en": {
        "name": "English",
        "always_enabled": True,
        "pairs": [],
        "notes": "English remains available as the routing and fallback language.",
    },
    "de": {
        "name": "German",
        "always_enabled": False,
        "pairs": ["en-de", "de-en"],
        "notes": "Text input/output, translation fallback through English, TTS/STT when installed.",
    },
    "es": {
        "name": "Spanish",
        "always_enabled": False,
        "pairs": ["en-es", "es-en"],
        "notes": "Text input/output, translation fallback through English, TTS/STT when installed.",
    },
    "fr": {
        "name": "French",
        "always_enabled": False,
        "pairs": ["en-fr", "fr-en"],
        "notes": "Text input/output, translation fallback through English, TTS/STT when installed.",
    },
    "hu": {
        "name": "Hungarian",
        "always_enabled": False,
        "pairs": ["en-hu", "hu-en"],
        "notes": "Multilingual classifier training target; mixed Hungarian/English prompts supported.",
    },
    "it": {
        "name": "Italian",
        "always_enabled": False,
        "pairs": ["en-it", "it-en"],
        "notes": "Text input/output, translation fallback through English, TTS/STT when installed.",
    },
}


def normalize_enabled_languages(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    values: list[str]
    if raw is None:
        values = []
    elif isinstance(raw, str):
        values = [part.strip().lower() for part in raw.split(",")]
    else:
        values = [str(part).strip().lower() for part in raw]
    enabled = ["en"]
    for code in values:
        if code in SUPPORTED_LANGUAGE_CODES and code not in enabled:
            enabled.append(code)
    return enabled


def language_payload(enabled_raw: str, installed_pairs: dict[str, bool] | None = None) -> dict[str, object]:
    installed_pairs = installed_pairs or {}
    enabled = normalize_enabled_languages(enabled_raw)
    languages = []
    for code, meta in LANGUAGE_PACKS.items():
        pairs = list(meta["pairs"])
        languages.append(
            {
                "code": code,
                "name": meta["name"],
                "enabled": code in enabled,
                "always_enabled": bool(meta["always_enabled"]),
                "pairs": pairs,
                "installed_pairs": {pair: bool(installed_pairs.get(pair, False)) for pair in pairs},
                "tts": code == "en" or code in enabled,
                "stt": code == "en" or code in enabled,
                "notes": meta["notes"],
            }
        )
    return {
        "enabled": enabled,
        "primary": "en",
        "english_required": True,
        "languages": languages,
        "install_command": "mullm1-language-pack --list",
    }
