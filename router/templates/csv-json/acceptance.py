"""Independent black-box checks; intentionally not included in generation context."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

converter = Path("convert.py").resolve()
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    source, output = root / "input.csv", root / "output.json"

    def run():
        return subprocess.run([sys.executable, str(converter), str(source), str(output)],
                              capture_output=True, timeout=5)

    cases = [
        ('name,code\nAda,001\n', [{"name": "Ada", "code": "001"}]),
        ('\ufeffname,note\r\nZoë,"a,b"\r\n猫,"two\nlines"\r\n',
         [{"name": "Zoë", "note": "a,b"}, {"name": "猫", "note": "two\nlines"}]),
        ('x,y\na,\n', [{"x": "a", "y": ""}]),
        ('x,y\n', []),
    ]
    for content, expected in cases:
        source.write_text(content, encoding="utf-8")
        result = run()
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert json.loads(output.read_text(encoding="utf-8")) == expected, f"Incorrect conversion for {content!r}"
        first = output.read_bytes()
        assert run().returncode == 0
        assert output.read_bytes() == first, "Output must be deterministic"
    for content in ['', 'x,x\n1,2\n', 'x, \n1,2\n', 'x,y\n1\n', 'x,y\n1,2,3\n', 'x\n"unclosed']:
        source.write_text(content, encoding="utf-8")
        for exists in (True, False):
            output.write_text("keep me") if exists else output.unlink(missing_ok=True)
            result = run()
            assert result.returncode != 0 and result.stderr, f"Invalid CSV {content!r} must fail clearly"
            assert output.read_text() == "keep me" if exists else not output.exists()
    source.unlink()
    result = run()
    assert result.returncode != 0 and result.stderr
    source.write_text('x\n1\n')
    result = subprocess.run([sys.executable, str(converter), str(source), str(source)], capture_output=True, timeout=5)
    assert result.returncode != 0 and source.read_text() == 'x\n1\n'
    assert subprocess.run([sys.executable, str(converter)], capture_output=True, timeout=5).returncode != 0
print("PASS: quoted CSV, Unicode, empty fields, validation, deterministic output, preservation, CLI")
