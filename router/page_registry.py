"""Page registry and module gate helpers for the muLLM UI."""

from __future__ import annotations

from pathlib import Path

from router.config import settings

CORE_PAGES = [
    {"href": "/", "label": "Home", "group": "core", "color": "#14B8A6"},
    {"href": "/chat", "label": "Chat", "group": "core", "color": "#14B8A6"},
    {"href": "/dashboard", "label": "Dashboard", "group": "core", "color": "#3B82F6"},
    {"href": "/cost", "label": "Cost", "group": "core", "color": "#22C55E"},
    {"href": "/setup", "label": "Setup", "group": "core", "color": "#F59E0B"},
    {"href": "/translate", "label": "Translate", "group": "core", "color": "#A78BFA"},
    {"href": "/privacy", "label": "Privacy", "group": "core", "color": "#94A3B8"},
    {"href": "/security", "label": "Security", "group": "core", "color": "#EF4444"},
    {"href": "/troubleshoot", "label": "Debug", "group": "core", "color": "#FBBF24"},
    {"href": "/urls", "label": "URLs", "group": "core", "color": "#38BDF8"},
]

DEMO_PAGES = [
    {"href": "/demo", "label": "Demo", "group": "demo", "color": "#10B981"},
    {"href": "/bench", "label": "Bench", "group": "demo", "color": "#F97316"},
    {"href": "/megabench", "label": "MegaBench", "group": "research", "color": "#F97316"},
    {"href": "/investors", "label": "Investors", "group": "demo", "color": "#22C55E"},
    {"href": "/research", "label": "Research", "group": "demo", "color": "#3B82F6"},
    {"href": "/review", "label": "Review", "group": "research", "color": "#A78BFA"},
    {"href": "/onnx", "label": "ONNX", "group": "research", "color": "#38BDF8"},
    {"href": "/performance", "label": "Perf", "group": "demo", "color": "#FB923C"},
    {"href": "/showcase", "label": "Showcase", "group": "demo", "color": "#EC4899"},
    {"href": "/compare", "label": "Compare", "group": "demo", "color": "#14B8A6"},
    {"href": "/compare3d", "label": "Compare 3D", "group": "research", "color": "#2DD4BF"},
    {"href": "/dataviz", "label": "DataViz", "group": "research", "color": "#22D3EE"},
    {"href": "/dataviz3d", "label": "Data 3D", "group": "research", "color": "#22D3EE"},
    {"href": "/pareto", "label": "Pareto", "group": "research", "color": "#84CC16"},
    {"href": "/minitest", "label": "MiniTest", "group": "research", "color": "#FACC15"},
    {"href": "/accuracy", "label": "Accuracy", "group": "research", "color": "#34D399"},
    {"href": "/competitive", "label": "Competitive", "group": "research", "color": "#FB7185"},
]

DEV_PAGES = [
    {"href": "/code", "label": "Code", "group": "dev", "color": "#60A5FA"},
    {"href": "/studio", "label": "Studio", "group": "studio", "color": "#EC4899"},
    {"href": "/scene", "label": "Scene", "group": "studio", "color": "#EC4899"},
    {"href": "/assets", "label": "Assets", "group": "studio", "color": "#38BDF8"},
    {"href": "/asset-manager", "label": "Asset Manager", "group": "studio", "color": "#38BDF8"},
    {"href": "/forest3d", "label": "Forest 3D", "group": "studio", "color": "#22C55E"},
    {"href": "/games", "label": "Games", "group": "studio", "color": "#F472B6"},
    {"href": "/gamesystems", "label": "Game Systems", "group": "studio", "color": "#F97316"},
    {"href": "/physics", "label": "Physics", "group": "studio", "color": "#00BFA5"},
    {"href": "/dialogue", "label": "Dialogue", "group": "studio", "color": "#A78BFA"},
    {"href": "/skyrail-archer", "label": "Skyrail Archer", "group": "studio", "color": "#60A5FA"},
    {"href": "/capyballista", "label": "Capy Ballista", "group": "studio", "color": "#F97316"},
    {"href": "/3d", "label": "3D", "group": "studio", "color": "#F59E0B"},
    {"href": "/terrain", "label": "Terrain", "group": "studio", "color": "#22C55E"},
    {"href": "/comfyui", "label": "ComfyUI", "group": "studio", "color": "#8B5CF6"},
    {"href": "/image", "label": "Image", "group": "studio", "color": "#EC4899"},
    {"href": "/video", "label": "Video", "group": "studio", "color": "#8B5CF6"},
    {"href": "/videoeditor", "label": "Video Editor", "group": "studio", "color": "#8B5CF6"},
    {"href": "/tts", "label": "Voice Studio", "group": "studio", "color": "#F59E0B"},
    {"href": "/musaic", "label": "Audio Studio", "group": "studio", "color": "#F59E0B"},
    {"href": "/foley", "label": "Foley", "group": "studio", "color": "#F59E0B"},
    {"href": "/drums", "label": "Drums", "group": "studio", "color": "#EF4444"},
    {"href": "/textures", "label": "Textures", "group": "studio", "color": "#FB923C"},
    {"href": "/lighting", "label": "Lighting", "group": "studio", "color": "#FACC15"},
    {"href": "/swords", "label": "Swords", "group": "studio", "color": "#F97316"},
    {"href": "/bows", "label": "Bows", "group": "studio", "color": "#F97316"},
    {"href": "/siege", "label": "Siege", "group": "studio", "color": "#F97316"},
    {"href": "/rigs", "label": "Rigs", "group": "studio", "color": "#60A5FA"},
    {"href": "/walks", "label": "Walks", "group": "studio", "color": "#60A5FA"},
    {"href": "/mcp", "label": "MCP & A2A", "group": "dev", "color": "#A78BFA"},
    {"href": "/a2a", "label": "A2A", "group": "dev", "color": "#A78BFA"},
    {"href": "/rpc", "label": "JSON-RPC", "group": "dev", "color": "#60A5FA"},
    {"href": "/tests", "label": "Tests", "group": "dev", "color": "#FBBF24"},
]

STUDIO_PAGE_NAMES = {
    "3d",
    "apks",
    "asset-manager",
    "assets",
    "bows",
    "capyballista",
    "comfyui",
    "compare3d",
    "forest3d",
    "foley",
    "games",
    "games3d1",
    "games3d2",
    "games3d3",
    "dialogue",
    "drums",
    "gamesystems",
    "physics",
    "image",
    "lighting",
    "musaic",
    "rigs",
    "scene",
    "siege",
    "skyrail-archer",
    "studio",
    "swords",
    "terrain",
    "textures",
    "tts",
    "video",
    "videoeditor",
    "walks",
}

DEV_PAGE_NAMES = {
    "code",
    "debug",
    "tests",
    "unblock",
}


def studio_enabled() -> bool:
    return settings.ui_mode == "dev" or settings.enable_studio


def dev_pages_enabled() -> bool:
    return settings.ui_mode == "dev"


def page_allowed(page: str) -> bool:
    # Studio/dev pages are mode-gated; provider/API availability is handled in-page.
    html_page = "studio" if page == "scene" else page
    if page in STUDIO_PAGE_NAMES:
        return studio_enabled()
    if page in DEV_PAGE_NAMES:
        return dev_pages_enabled()
    if (Path(__file__).parent / f"{html_page}.html").is_file():
        return True
    return True


def visible_pages() -> list[dict[str, str]]:
    pages = list(CORE_PAGES)
    if settings.ui_mode in ("demo", "dev"):
        pages.extend(DEMO_PAGES)
    if settings.ui_mode == "dev":
        pages.extend(DEV_PAGES)
    elif settings.enable_studio:
        pages.extend(page for page in DEV_PAGES if page["group"] == "studio")
    return pages
