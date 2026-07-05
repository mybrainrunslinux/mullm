"""Research report export helpers with citation preservation."""

from __future__ import annotations

import html
import re
import time
from typing import Any

URL_RE = re.compile(r"https?://[^\s<>)\]]+")


def _as_text(value: Any) -> str:
    return "" if value is None else str(value)


def _latex_escape(value: str) -> str:
    return (
        value.replace("\\", "\\textbackslash{}")
        .replace("_", "\\_")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("#", "\\#")
        .replace("$", "\\$")
        .replace("{", "\\{")
        .replace("}", "\\}")
    )


def collect_citations(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Normalize structured citations and URL fallbacks from research results."""
    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in results:
        for raw in item.get("citations") or item.get("sources") or []:
            if isinstance(raw, str):
                citation = {"title": raw, "url": raw if raw.startswith(("http://", "https://")) else ""}
            elif isinstance(raw, dict):
                citation = {k: _as_text(v) for k, v in raw.items() if v is not None}
            else:
                continue
            key = citation.get("doi") or citation.get("url") or citation.get("title")
            if key and key not in seen:
                seen.add(key)
                citations.append(citation)
        for url in URL_RE.findall(_as_text(item.get("text", ""))):
            clean = url.rstrip(".,;")
            if clean not in seen:
                seen.add(clean)
                citations.append({"title": clean, "url": clean})
    return citations


def render_markdown(results: list[dict[str, Any]]) -> str:
    lines = ["# muLLM Research Report\n", f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"]
    for item in results:
        lines.append(f"## Query {int(item.get('card', 0)) + 1}: {_as_text(item.get('query'))}\n\n")
        lines.append(f"{_as_text(item.get('text'))}\n\n")
        lines.append(f"*Cost: ${float(item.get('cost', 0.0) or 0.0):.6f}*\n\n---\n\n")
    citations = collect_citations(results)
    if citations:
        lines.append("## Sources\n\n")
        for index, citation in enumerate(citations, 1):
            title = citation.get("title") or citation.get("url") or f"Source {index}"
            url = citation.get("url", "")
            author = citation.get("author") or citation.get("authors") or ""
            year = citation.get("year", "")
            suffix = " ".join(part for part in (author, year) if part)
            lines.append(f"{index}. {title}{f' ({suffix})' if suffix else ''}{f' - {url}' if url else ''}\n")
    return "".join(lines)


def render_latex(results: list[dict[str, Any]]) -> str:
    lines = [
        "\\documentclass{article}\n\\usepackage[utf8]{inputenc}\n\\usepackage{hyperref}\n",
        "\\title{muLLM Research Report}\n",
        f"\\date{{{time.strftime('%Y-%m-%d')}}}\n\\begin{{document}}\n\\maketitle\n\n",
    ]
    for item in results:
        lines.append(f"\\section{{Query {int(item.get('card', 0)) + 1}: {_latex_escape(_as_text(item.get('query')))}}}\n\n")
        lines.append(f"{_latex_escape(_as_text(item.get('text')))}\n\n")
    citations = collect_citations(results)
    if citations:
        lines.append("\\begin{thebibliography}{99}\n")
        for index, citation in enumerate(citations, 1):
            title = _latex_escape(citation.get("title") or citation.get("url") or f"Source {index}")
            url = _latex_escape(citation.get("url", ""))
            author = _latex_escape(citation.get("author") or citation.get("authors") or "")
            year = _latex_escape(citation.get("year", ""))
            details = ", ".join(part for part in (author, title, year) if part)
            if url:
                details = f"{details}. \\url{{{url}}}" if details else f"\\url{{{url}}}"
            lines.append(f"\\bibitem{{mullm-src-{index}}}{details}\n")
        lines.append("\\end{thebibliography}\n")
    lines.append("\\end{document}\n")
    return "".join(lines)


def render_bibtex(results: list[dict[str, Any]]) -> str:
    entries: list[str] = []
    for index, citation in enumerate(collect_citations(results), 1):
        title = citation.get("title") or citation.get("url") or f"Source {index}"
        year = citation.get("year") or time.strftime("%Y")
        author = citation.get("author") or citation.get("authors") or "Unknown"
        url = citation.get("url", "")
        fields = [f"  title = {{{title}}}", f"  author = {{{author}}}", f"  year = {{{year}}}"]
        if url:
            fields.append(f"  url = {{{url}}}")
        if citation.get("doi"):
            fields.append(f"  doi = {{{citation['doi']}}}")
        entries.append(f"@misc{{mullm-src-{index},\n{','.join(fields)}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")


def render_html(results: list[dict[str, Any]]) -> str:
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'><title>muLLM Research Report</title>",
        "<style>body{font-family:Georgia,serif;max-width:800px;margin:2rem auto;color:#111;line-height:1.6}pre{white-space:pre-wrap}.source{margin:.4rem 0}</style>",
        "</head><body><h1>muLLM Research Report</h1>",
        f"<p>Generated: {html.escape(time.strftime('%Y-%m-%d %H:%M:%S'))}</p>",
    ]
    for item in results:
        parts.append(f"<h2>Query {int(item.get('card', 0)) + 1}: {html.escape(_as_text(item.get('query')))}</h2>")
        parts.append(f"<pre>{html.escape(_as_text(item.get('text')))}</pre>")
    citations = collect_citations(results)
    if citations:
        parts.append("<h2>Sources</h2>")
        for index, citation in enumerate(citations, 1):
            title = html.escape(citation.get("title") or citation.get("url") or f"Source {index}")
            url = html.escape(citation.get("url", ""))
            link = f' <a href="{url}">{url}</a>' if url else ""
            parts.append(f"<div class='source'>{index}. {title}{link}</div>")
    parts.append("</body></html>")
    return "".join(parts)
