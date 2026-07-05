import pytest
from httpx import ASGITransport, AsyncClient

from router.main import app
from router.research_exports import collect_citations, render_bibtex, render_latex, render_markdown


RESULTS = [
    {
        "card": 0,
        "query": "SANA-WM refiner",
        "text": "Project page: https://nvlabs.github.io/Sana/WM/",
        "cost": 0.01,
        "citations": [
            {
                "title": "SANA-WM",
                "author": "NVIDIA",
                "year": "2026",
                "url": "https://nvlabs.github.io/Sana/WM/",
            }
        ],
    }
]


def test_research_export_helpers_preserve_citations():
    citations = collect_citations(RESULTS)

    assert citations[0]["title"] == "SANA-WM"
    assert "Sources" in render_markdown(RESULTS)
    assert "\\begin{thebibliography}" in render_latex(RESULTS)
    assert "@misc{mullm-src-1" in render_bibtex(RESULTS)


@pytest.mark.asyncio
async def test_research_export_endpoint_supports_bibtex():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/research/export", json={"format": "bibtex", "results": RESULTS})

    assert response.status_code == 200
    assert "SANA-WM" in response.text
    assert "research-report.bib" in response.headers["content-disposition"]
