"""
muLLM backend subsystem.

Public API:
    BackendProtocol  — structural Protocol all backends satisfy
    BackendResponse  — unified response dataclass
    register_backend — add a backend to the registry
    get_backend      — look up a backend by name
    list_backends    — list all registered backend names
    OpenAICompatBackend — generic OpenAI-wire-compatible backend
"""
from .openai_compat import OpenAICompatBackend
from .protocol import (
    BackendProtocol,
    BackendResponse,
    get_backend,
    list_backends,
    register_backend,
)

__all__ = [
    "BackendProtocol",
    "BackendResponse",
    "register_backend",
    "get_backend",
    "list_backends",
    "OpenAICompatBackend",
]
