"""Local secret storage helpers.

The default remains environment variables for compatibility, but setup can use
`pass` when available so provider keys never need to live in a project `.env`.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Literal

PASS_PREFIX = os.getenv("MULLM_PASS_PREFIX", "mullm")
KEYRING_SERVICE = os.getenv("MULLM_KEYRING_SERVICE", "mullm")
SecretBackendName = Literal["auto", "keyring", "pass", "env"]


PROVIDER_ENV_MAP = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "venice": "VENICE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "meshy": "MESHY_API_KEY",
    "civitai": "CIVITAI_API_KEY",
    "civit_ai": "CIVIT_AI_API_KEY",
    "xai": "XAI_API_KEY",
    "cohere": "COHERE_API_KEY",
    "sambanova": "SAMBANOVA_API_KEY",
    "together": "TOGETHER_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "nim": "NIM_API_KEY",
    "nim_url": "NIM_BASE_URL",
    "vllm_url": "VLLM_BASE_URL",
    "tabbyapi": "TABBYAPI_API_KEY",
    "tabbyapi_url": "TABBYAPI_BASE_URL",
    "litellm": "LITELLM_BASE_URL",
    "litellm_key": "LITELLM_API_KEY",
    "ibm": "IBM_BAM_API_KEY",
    "ibm_url": "IBM_BAM_BASE_URL",
    "omniroute": "OMNIROUTE_BASE_URL",
    "omniroute_key": "OMNIROUTE_API_KEY",
    "kling": "KLING_API_KEY",
    "kling_url": "KLING_BASE_URL",
    "veo": "VEO_API_KEY",
    "seedance2": "SEEDANCE_API_KEY",
    "seedance2_url": "SEEDANCE_BASE_URL",
    "topologyai": "TOPOLOGYAI_API_KEY",
    "topologyai_url": "TOPOLOGYAI_BASE_URL",
    "tripo": "TRIPO_API_KEY",
    "tripo_url": "TRIPO_BASE_URL",
    "rodin": "RODIN_API_KEY",
    "rodin_url": "RODIN_BASE_URL",
    "sana_wm": "SANA_WM_API_KEY",
    "sana_wm_url": "SANA_WM_BASE_URL",
    "sana_wm_path": "SANA_WM_LOCAL_PATH",
    "brave_search": "BRAVE_SEARCH_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "serpapi": "SERPAPI_API_KEY",
    "google_cse": "GOOGLE_CSE_API_KEY",
    "google_cse_id": "GOOGLE_CSE_ID",
    "kagi": "KAGI_API_KEY",
    "exa": "EXA_API_KEY",
    "runpod": "RUNPOD_API_KEY",
    "runpod_url": "RUNPOD_BASE_URL",
    "vastai": "VASTAI_API_KEY",
    "vastai_url": "VASTAI_BASE_URL",
    "huggingface": "HUGGINGFACE_API_KEY",
    "huggingface_url": "HUGGINGFACE_BASE_URL",
    "aws_bedrock": "AWS_BEDROCK_PROFILE",
    "gcp_vertex": "GCP_VERTEX_PROJECT",
    "azure_ai": "AZURE_AI_API_KEY",
    "azure_ai_url": "AZURE_AI_BASE_URL",
    "digitalocean": "DIGITALOCEAN_API_KEY",
    "digitalocean_url": "DIGITALOCEAN_BASE_URL",
    "private_gpu": "PRIVATE_GPU_API_KEY",
    "private_gpu_url": "PRIVATE_GPU_BASE_URL",
}


def _custom_provider_env(provider: str) -> str | None:
    """Map custom OpenAI-compatible provider ids to scoped env vars."""
    prefix = "custom_"
    if not provider.startswith(prefix):
        return None
    suffix = provider[len(prefix):]
    kind = "api_key"
    if suffix.endswith("_url"):
        suffix = suffix[:-4]
        kind = "base_url"
    elif suffix.endswith("_model"):
        suffix = suffix[:-6]
        kind = "model"
    if not suffix:
        return None
    if not all(c.isalnum() or c == "_" for c in suffix):
        return None
    name = suffix.upper()
    if kind == "base_url":
        return f"MULLM_CUSTOM_{name}_BASE_URL"
    if kind == "model":
        return f"MULLM_CUSTOM_{name}_MODEL"
    return f"MULLM_CUSTOM_{name}_API_KEY"


def env_var_for_provider(provider: str) -> str | None:
    return PROVIDER_ENV_MAP.get(provider) or _custom_provider_env(provider)


def keyring_available() -> bool:
    try:
        import keyring  # type: ignore
    except Exception:
        return False
    try:
        backend = keyring.get_keyring()
    except Exception:
        return False
    backend_id = f"{backend.__class__.__module__}.{backend.__class__.__name__}".lower()
    return bool(backend and "fail" not in backend_id)


def keyring_name(env_var: str) -> str:
    return env_var


def store_keyring_secret(env_var: str, value: str) -> None:
    if not keyring_available():
        raise RuntimeError("OS keychain backend is not available")
    import keyring  # type: ignore

    keyring.set_password(KEYRING_SERVICE, keyring_name(env_var), value)


def load_keyring_secret(env_var: str) -> str | None:
    if not keyring_available():
        return None
    import keyring  # type: ignore

    return keyring.get_password(KEYRING_SERVICE, keyring_name(env_var)) or None


def delete_keyring_secret(env_var: str) -> None:
    if not keyring_available():
        raise RuntimeError("OS keychain backend is not available")
    import keyring  # type: ignore
    from keyring.errors import PasswordDeleteError  # type: ignore

    try:
        keyring.delete_password(KEYRING_SERVICE, keyring_name(env_var))
    except PasswordDeleteError:
        pass


def keyring_selftest() -> dict:
    env_var = "_MULLM_SELFTEST_DO_NOT_USE"
    secret = "mullm-keyring-selftest-ok"
    store_keyring_secret(env_var, secret)
    try:
        loaded = load_keyring_secret(env_var)
        return {"ok": loaded == secret, "service": KEYRING_SERVICE, "name": keyring_name(env_var)}
    finally:
        delete_keyring_secret(env_var)


def pass_available() -> bool:
    return bool(shutil.which("pass"))


def pass_name(env_var: str) -> str:
    return f"{PASS_PREFIX}/{env_var}"


def store_pass_secret(env_var: str, value: str) -> None:
    if not pass_available():
        raise RuntimeError("pass is not installed")
    proc = subprocess.run(
        ["pass", "insert", "-m", pass_name(env_var)],
        input=value + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "pass insert failed")


def load_pass_secret(env_var: str) -> str | None:
    if not pass_available():
        return None
    proc = subprocess.run(["pass", "show", pass_name(env_var)], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return None
    first_line = proc.stdout.splitlines()[0] if proc.stdout.splitlines() else ""
    return first_line or None


def delete_pass_secret(env_var: str) -> None:
    if not pass_available():
        raise RuntimeError("pass is not installed")
    proc = subprocess.run(["pass", "rm", "-f", pass_name(env_var)], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "pass rm failed")


def pass_selftest() -> dict:
    env_var = "_MULLM_SELFTEST_DO_NOT_USE"
    secret = "mullm-pass-selftest-ok"
    store_pass_secret(env_var, secret)
    try:
        loaded = load_pass_secret(env_var)
        return {"ok": loaded == secret, "name": pass_name(env_var)}
    finally:
        delete_pass_secret(env_var)


def load_pass_secrets_into_env() -> list[str]:
    loaded: list[str] = []
    for env_var in sorted(set(PROVIDER_ENV_MAP.values())):
        if os.environ.get(env_var):
            continue
        value = load_secret(env_var, backend="auto")
        if value:
            os.environ[env_var] = value
            loaded.append(env_var)
    return loaded


def _write_env_secret(env_var: str, value: str, path: Path = Path(".env")) -> None:
    existing: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key, _, old_value = stripped.partition("=")
                existing[key.strip()] = old_value.strip()
    existing[env_var] = value
    path.write_text("\n".join(f"{key}={val}" for key, val in existing.items()) + "\n", encoding="utf-8")
    path.chmod(0o600)


def resolve_secret_backend(requested: str | None = None) -> str:
    backend = (requested or os.getenv("MULLM_SECRET_BACKEND", "auto")).strip().lower()
    if backend == "auto":
        if keyring_available():
            return "keyring"
        return "env"
    if backend not in {"keyring", "pass", "env"}:
        raise RuntimeError("secret backend must be auto, keyring, pass, or env")
    return backend


def store_secret(env_var: str, value: str, backend: str | None = None) -> str:
    selected = resolve_secret_backend(backend)
    if selected == "keyring":
        store_keyring_secret(env_var, value)
    elif selected == "pass":
        store_pass_secret(env_var, value)
    elif selected == "env":
        _write_env_secret(env_var, value)
    else:
        raise RuntimeError(f"unsupported secret backend: {selected}")
    return selected


def load_secret(env_var: str, backend: str | None = None) -> str | None:
    requested = (backend or os.getenv("MULLM_SECRET_BACKEND", "auto")).strip().lower()
    if requested == "auto":
        for candidate in ("keyring", "pass"):
            value = load_secret(env_var, backend=candidate)
            if value:
                return value
        return None
    selected = resolve_secret_backend(requested)
    if selected == "keyring":
        return load_keyring_secret(env_var)
    if selected == "pass":
        return load_pass_secret(env_var)
    if selected == "env":
        return os.environ.get(env_var)
    return None


def secret_backends_status() -> dict:
    selected = resolve_secret_backend("auto")
    return {
        "default": selected,
        "keyring": {
            "available": keyring_available(),
            "service": KEYRING_SERVICE,
            "can_write": keyring_available(),
            "setup_hint": "Uses the OS keychain when the Python keyring backend is available.",
        },
        "pass": {
            "available": pass_available(),
            "prefix": PASS_PREFIX,
            "can_write": pass_available(),
            "setup_hint": "Requires GPG and an initialized pass store. muLLM never sees your GPG passphrase.",
        },
        "env": {
            "available": True,
            "can_write": True,
            "setup_hint": "Writes .env in the project directory with 0600 permissions.",
        },
    }


def env_file_status(path: Path = Path(".env")) -> dict:
    if path == Path(".env"):
        path = Path(os.getenv("MULLM_ENV_FILE", ".env")).expanduser()
    if not path.exists():
        return {"exists": False, "path": str(path)}
    mode = stat.S_IMODE(path.stat().st_mode)
    return {
        "exists": True,
        "path": str(path),
        "mode": oct(mode),
        "owner_only": mode in (0o400, 0o600),
        "immutable_supported": bool(shutil.which("chattr")),
    }


def harden_env_file(path: Path = Path(".env"), readonly: bool = True) -> dict:
    if path == Path(".env"):
        path = Path(os.getenv("MULLM_ENV_FILE", ".env")).expanduser()
    if not path.exists():
        raise FileNotFoundError(str(path))
    path.chmod(0o400 if readonly else 0o600)
    return env_file_status(path)
