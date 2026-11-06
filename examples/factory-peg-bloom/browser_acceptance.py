"""Exercise generated game code in a real browser, using protected puzzle witnesses."""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from playwright.sync_api import sync_playwright

class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_): pass

puzzles = json.loads(Path('puzzles.json').read_text())
server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(Path.cwd())))
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{server.server_port}'
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1100, 'height': 850})
        errors, external = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(request):
            if request.request.url.startswith(url + '/'):
                request.continue_()
            else:
                external.append(request.request.url)
                request.abort()
        page.route('**/*', route)
        page.emulate_media(reduced_motion='reduce')
        page.goto(url)
        if page.locator('#lid').count():
            page.click('#lid')
        page.wait_for_function("document.querySelectorAll('#board-choice option').length === 3")
        def occupied():
            return sorted(page.locator('#board [data-occupied="true"]').evaluate_all('(els)=>els.map(e=>e.dataset.cell)'))
        def click(cell):
            page.locator(f'#board [data-cell="{cell}"]').click(timeout=2500)
        def counter(n, total):
            value = page.locator('#counter').inner_text()
            assert value == f'Moves: {n} / {total}', value
        for p in puzzles:
            page.select_option('#board-choice', p['id'])
            assert page.locator('#board [data-cell]').count() == len(p['cells'])
            assert occupied() == sorted(p['start']), (p['id'], 'initial state')
            counter(0, len(p['solution']))
            if page.locator('#board .peg-piece').count():
                assert page.locator('#board .peg-piece').count() == len(p['start'])
                assert page.locator('#board [data-occupied="false"] .peg-piece').count() == 0
                assert page.locator('#board .peg-piece').first.bounding_box()['width'] < 30, 'Visible pegs should be small; the click target can be larger'
                # A first move through visible affordances, without consulting the solution.
                found = False
                for peg in page.locator('#board [data-occupied="true"]').all():
                    peg.click()
                    targets = page.locator('#board .target')
                    if targets.count():
                        assert 'legal landing' in targets.first.get_attribute('aria-label')
                        assert 'glowing empty hole' in page.locator('#move-help').inner_text()
                        targets.first.click()
                        assert len(occupied()) == len(p['start']) - 1
                        page.click('#undo')
                        found = True
                        break
                assert found, 'A legal first move must be discoverable from visible controls'
            else:
                peg_color = page.locator('#board [data-occupied="true"]').first.evaluate('(e)=>getComputedStyle(e).backgroundColor')
                hole_color = page.locator('#board [data-occupied="false"]').first.evaluate('(e)=>getComputedStyle(e).backgroundColor')
                assert peg_color != hole_color, 'Occupied pegs and empty holes must have distinct background colors; check CSS selector specificity'
            first = p['solution'][0]
            page.click('#hint')
            assert page.locator(f'#board [data-cell="{first[0]}"].selected').count() == 1, f'hint must select the next solution peg; browser errors: {errors}'
            assert page.locator(f'#board [data-cell="{first[2]}"].target').count() == 1, 'hint must highlight its landing'
            click(first[2])
            counter(1, len(p['solution']))
            page.click('#undo')
            assert occupied() == sorted(p['start']), 'undo must restore board'
            counter(0, len(p['solution']))
            click(first[0]); click(first[2]); page.click('#restart')
            assert occupied() == sorted(p['start']), 'restart must restore board'
            pegs = set(p['start'])
            for i, (a,b,c) in enumerate(p['solution'], 1):
                click(a); click(c)
                pegs.remove(a); pegs.remove(b); pegs.add(c)
                assert occupied() == sorted(pegs), (p['id'], i, 'visible board differs from witness state')
                counter(i, len(p['solution']))
                if i < len(p['solution']):
                    assert 'solved' not in page.locator('#status').inner_text().lower()
            assert occupied() == sorted(p['goal'])
            assert 'solved' in page.locator('#status').inner_text().lower()
            assert page.locator('#board .goal[data-occupied="true"]').count() == len(p['goal'])
            if page.locator('#board-frame').count():
                page.wait_for_function("document.querySelector('#board-frame').dataset.pose === 'top-down'")
                assert page.locator('#next-puzzle').is_visible()
                page.click('#undo')
                assert page.locator('#board-frame').get_attribute('data-pose') == 'angled'
                a,b,c=p['solution'][-1]
                click(a); click(c)
                page.wait_for_function("document.querySelector('#board-frame').dataset.pose === 'top-down'")
            Path('dist').mkdir(exist_ok=True)
            page.screenshot(path=f'dist/{p["id"]}-solved.png', full_page=True)
            print(f'{p["id"]}: real clicks, hint, undo, restart, {len(p["solution"])} jumps and visible final shape PASS')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.click('#restart')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'mobile page overflows horizontally'
        for rect in page.locator('#board button').evaluate_all('(els)=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,right:r.right,width:r.width,height:r.height}})'):
            assert rect['x'] >= 0 and rect['right'] <= 390 and rect['width'] >= 24 and rect['height'] >= 24, rect
        page.screenshot(path='dist/mobile.png', full_page=True)
        assert not errors, errors
        assert not external, external
        browser.close()
        print('PASS: all three puzzles, mobile fit, zero browser exceptions, zero external requests')
finally:
    server.shutdown()
    server.server_close()
