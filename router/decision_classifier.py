"""System One wire adapter for local Kev and Jev-compatible gateways.

Hosted billing is intentionally not implicit: this adapter only connects to a
literal loopback address. A paid hosted classifier needs budget reservations
before it can be enabled in the request pipeline.
"""
from __future__ import annotations

import ipaddress
import math
from urllib.parse import urlsplit

from router.models import IntentCategory


def request_payload(text: str, model: str) -> dict:
    return {
        "model": model, "state": text[:4000],
        "questions": {
            "intent": {"type": "choice", "instructions": "Select the primary intent of the user request.",
                       "criteria": {c.value: c.value for c in IntentCategory}},
            "complexity": {"type": "choice", "instructions": "Rate the difficulty of completing the request.",
                           "criteria": {"1": "Trivial lookup", "2": "Simple single-step task",
                                        "3": "Moderate multistep task", "4": "Complex expert task",
                                        "5": "Demanding research or architecture"}},
        },
    }


def parse_response(data: dict) -> dict:
    answers = data["answers"]
    intent, complexity = answers["intent"], answers["complexity"]
    category = IntentCategory(intent["choice"]).value
    level = int(complexity["choice"])
    confidence = min(float(intent["confidence"]), float(complexity["confidence"]))
    if not 1 <= level <= 5 or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Invalid System One classification")
    return {"category": category, "complexity": level, "confidence": confidence}


def classify(text: str, settings) -> dict | None:
    import httpx

    url = urlsplit(settings.classifier_http_url)
    try:
        local = ipaddress.ip_address(url.hostname or "").is_loopback
    except ValueError:
        local = False
    if not local or url.scheme not in ("http", "https") or url.username or url.password:
        return None
    headers = {"User-Agent": "mullm-classifier/1.0"}
    if settings.classifier_http_api_key:
        headers["Authorization"] = "Bearer " + settings.classifier_http_api_key.get_secret_value()
    with httpx.Client(timeout=settings.classifier_http_timeout_seconds, follow_redirects=False,
                      trust_env=False) as client:
        response = client.post(settings.classifier_http_url,
                               json=request_payload(text, settings.classifier_http_model or "kev-latest"),
                               headers=headers)
    response.raise_for_status()
    return parse_response(response.json())
