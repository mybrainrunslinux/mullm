from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
files = ['index.html', 'style.css', 'app.mjs', 'engine.mjs', 'render.mjs', 'puzzles.json']
Path('dist').mkdir(exist_ok=True)
with ZipFile('dist/peg-bloom.zip', 'w', ZIP_DEFLATED) as archive:
    for name in files:
        path = Path(name)
        assert path.stat().st_size, name
        archive.write(path, name)
print('Packaged dist/peg-bloom.zip')
