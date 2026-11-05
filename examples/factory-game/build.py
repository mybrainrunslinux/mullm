from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

Path("dist").mkdir(exist_ok=True)
with ZipFile("dist/game.zip", "w", ZIP_DEFLATED) as archive:
    for name in ("index.html", "game.js"):
        archive.write(name)
