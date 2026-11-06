from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

Path("dist").mkdir(exist_ok=True)
with ZipFile("dist/csv-json.zip", "w", compression=ZIP_DEFLATED) as archive:
    for name in ("convert.py", "README.md", "contract.md"):
        info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, Path(name).read_bytes())
print("Packaged dist/csv-json.zip")
