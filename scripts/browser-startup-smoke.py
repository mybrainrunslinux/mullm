"""Exercise an installed desktop launch in real browsers, with normal TLS checks."""
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright


def main():
    # Run this script with the freshly installed wheel's Python environment.
    launcher_path = Path(sys.executable).parent / ('mullm.exe' if os.name == 'nt' else 'mullm')
    assert launcher_path.is_file(), 'Install the wheel into this Python environment first'
    launcher = str(launcher_path)
    with tempfile.TemporaryDirectory(prefix='mullm-browser-startup-') as temp:
        root = Path(temp)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        # Leave TLS settings untouched: this must exercise the shipped default.
        env = {k: v for k, v in os.environ.items() if not k.startswith('MULLM_')}
        env.update(MULLM_STATE_DIR=str(root), MULLM_PORT=str(port),
                   MULLM_OPEN_BROWSER='0', DISABLE_CLOUD='1', PYTHONUNBUFFERED='1')
        base = f'http://127.0.0.1:{port}'
        with (root / 'server.log').open('w') as log:
            # The executable belongs to this interpreter environment; no shell is used.
            proc = subprocess.Popen([launcher], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
                    try:
                        connection.request('GET', '/health')
                        response = connection.getresponse()
                        assert response.status == 200
                        health = json.loads(response.read())
                        break
                    except Exception:
                        if proc.poll() is not None:
                            raise RuntimeError((root / 'server.log').read_text())
                        time.sleep(.2)
                    finally:
                        connection.close()
                else:
                    raise RuntimeError('Default HTTP startup failed: ' + (root / 'server.log').read_text())
                assert not (root / 'cache/data/certs').exists(), 'Desktop startup generated a certificate'
                # Same installed executable and literal argument, without a shell.
                status = subprocess.run([launcher, '--status'], cwd=root, env=env,
                                        capture_output=True, text=True, timeout=15)
                assert status.returncode == 0, status.stderr + status.stdout
                with sync_playwright() as p:
                    for name in ('firefox', 'chromium'):
                        browser = getattr(p, name).launch()
                        context = browser.new_context()  # No ignore_https_errors or certificate exception.
                        page = context.new_page()
                        for path in ('/setup', '/chat'):
                            response = page.goto(base + path, wait_until='domcontentloaded')
                            assert response.ok
                            assert page.url == base + path
                            assert page.evaluate('window.isSecureContext'), name
                            assert page.locator('body').inner_text().strip()
                            check = page.evaluate("fetch('/health').then(r => r.json())")
                            assert check['version'] == health['version']
                        print(f'PASS {name}: default HTTP setup/chat, secure context, same-origin API')
                        browser.close()
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


if __name__ == '__main__':
    main()
