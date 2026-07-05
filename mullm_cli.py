"""
mullm_cli — top-level CLI entry point for muLLM.
Delegates to router.cli for the full argument parser; this module
also exposes cmd_serve for direct programmatic use and package import.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence


def cmd_serve(
    apks: Sequence[Path] | None = None,
    host: str = "0.0.0.0",
    port: int = 6856,
    workers: int = 1,
    reload: bool = False,
) -> None:
    """Start the muLLM server, optionally serving pre-built APKs.

    apks: list of Path objects to pre-built .apk files.  Keyed by stem for
    O(1) lookup — apk_map = {p.name: p for p in apks} — so duplicate filenames
    are resolved deterministically (last one wins per name).
    """
    apk_map = {p.name: p for p in apks} if apks else {}

    import uvicorn
    from router.main import app

    if apk_map:
        import logging
        logging.getLogger("mullm.cli").info(
            "Serving %d pre-built APK(s): %s", len(apk_map), list(apk_map)
        )

    uvicorn.run(
        app,
        host=host,
        port=port,
        workers=workers,
        reload=reload,
    )


def main() -> None:
    """CLI entry point — full argparse interface lives in router.cli."""
    from router.cli import main as _main
    _main()


if __name__ == "__main__":
    main()
