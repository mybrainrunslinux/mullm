from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
Path('dist').mkdir(exist_ok=True)
with ZipFile('dist/workspace.zip','w',ZIP_DEFLATED) as z:
 for name in ('index.html','ui.mjs','style.css','product.json','workflow.mjs'):
  assert Path(name).stat().st_size
  z.write(name)
print('Packaged dist/workspace.zip')
