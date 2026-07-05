"""
muLLM agent roles and workflows — multi-step LLM pipelines.

Roles: general, vision, coder, critic
Workflows: sketch_to_app, research_and_summarize, code_review
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("mullm.agents")

try:
    import ollama  # type: ignore
    _ollama = ollama
except ImportError:
    _ollama = None  # type: ignore

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

AGENT_ROLES: dict[str, dict[str, str]] = {
    "general": {
        "model": "qwen3-coder-65k:latest",
        "system": "You are a helpful, concise assistant. Respond directly and clearly.",
    },
    "vision": {
        "model": "llava:latest",
        "system": "You are a vision assistant. Describe images accurately and in detail.",
    },
    "coder": {
        "model": "qwen3-coder-65k:latest",
        "system": (
            "You are an expert software engineer. Write clean, working code. "
            "Include types. No unnecessary prose. Use mermaid for diagrams."
        ),
    },
    "critic": {
        "model": "qwen3-coder-65k:latest",
        "system": (
            "You are a code critic. Review the given code for correctness, style, "
            "and performance. Be direct and specific."
        ),
    },
}

WORKFLOWS: dict[str, dict[str, Any]] = {
    "sketch_to_app": {
        "name": "Sketch to App",
        "description": "Turn a rough sketch or description into working code",
        "steps": [
            {"role": "coder", "prompt": "Write a complete implementation for: {input}"},
            {"role": "critic", "prompt": "Review this code and suggest improvements:\n{coder}"},
        ],
    },
    "research_and_summarize": {
        "name": "Research & Summarize",
        "description": "Research a topic and produce a structured summary",
        "steps": [
            {"role": "general", "prompt": "Research the following and list key facts: {input}"},
            {"role": "general", "prompt": "Summarize these findings into a concise report:\n{general}"},
        ],
    },
    "code_review": {
        "name": "Code Review",
        "description": "Write code then review it",
        "steps": [
            {"role": "coder", "prompt": "Write code for: {input}"},
            {"role": "critic", "prompt": "Review this code:\n{coder}"},
        ],
    },
}


@dataclass
class AgentStep:
    role: str
    prompt_template: str
    depends_on: list[str] = field(default_factory=list)
    result: str = ""
    latency_ms: float = 0.0
    tokens: int = 0


async def run_agent_step(step: AgentStep, context: dict[str, str]) -> AgentStep:
    """Run one agent step, substituting {key} placeholders from context."""
    role_config = AGENT_ROLES.get(step.role, AGENT_ROLES["general"])
    model = role_config["model"]
    system = role_config["system"]

    prompt = step.prompt_template
    for key, value in context.items():
        prompt = prompt.replace(f"{{{key}}}", value)

    t0 = time.monotonic()
    try:
        if _ollama is None:
            raise RuntimeError("ollama not installed")
        resp = _ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        text = resp.get("message", {}).get("content", "")
        text = _THINK_RE.sub("", text).strip()
        step.tokens = resp.get("eval_count", 0) + resp.get("prompt_eval_count", 0)
    except Exception as exc:
        logger.warning("Agent step %r failed: %s", step.role, exc)
        text = f"Agent error: {exc}"
        step.tokens = 0

    step.result = text
    step.latency_ms = (time.monotonic() - t0) * 1000
    return step


async def run_workflow(workflow_id: str, prompt: str) -> dict[str, Any]:
    """Execute a named workflow and return a structured result dict."""
    if workflow_id not in WORKFLOWS:
        return {
            "error": f"Unknown workflow: {workflow_id!r}",
            "available": list(WORKFLOWS.keys()),
        }

    wf = WORKFLOWS[workflow_id]
    wf_steps = wf["steps"]
    context: dict[str, str] = {"input": prompt}
    executed: list[dict] = []
    total_tokens = 0
    total_latency = 0.0

    for step_def in wf_steps:
        role = step_def["role"]
        tmpl = step_def["prompt"]
        step = AgentStep(role=role, prompt_template=tmpl)
        step = await run_agent_step(step, context)
        context[role] = step.result
        total_tokens += step.tokens
        total_latency += step.latency_ms
        executed.append({
            "role": role,
            "result": step.result,
            "tokens": step.tokens,
            "latency_ms": round(step.latency_ms, 2),
        })

    final_output = executed[-1]["result"] if executed else ""
    return {
        "workflow": workflow_id,
        "steps": executed,
        "total_tokens": total_tokens,
        "total_latency_ms": round(total_latency, 2),
        "total_cost": 0.0,
        "final_output": final_output,
    }
