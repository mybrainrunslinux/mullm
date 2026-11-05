"""Check Factory/Unblock controls in Chromium against an existing local server.

Install Playwright and Chromium in a tooling environment, then run this script
with the server URL. All decision requests are intercepted; no real run changes.
"""
import json
import sys
from urllib.parse import parse_qs

from playwright.sync_api import sync_playwright


def main(base):
    hostile = '<img src=x onerror="window.injected=true">'
    card = {
        'session_id': 'agent-browser-test', 'run_id': 'browser-test',
        'agent_type': hostile, 'severity': 'high', 'summary': 'Choose ' + hostile,
        'context': hostile, 'options': ['Keep "quoted" ' + hostile, 'Stop'],
        'resolved': False, 'status': 'needs_human', 'color': 'orange',
        'block_reason': 'clarification', 'elapsed_s': 60, 'tier': 'local',
        'links': [{'label': 'Preview', 'url': 'https://example.org/preview'}],
    }
    run = {'run_id': 'browser-test', 'name': 'Browser test', 'status': 'needs_human',
           'plan': [], 'tasks': [], 'elapsed_seconds': 1}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for surface in ('factory', 'unblock'):
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            errors, decisions = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            context.route('**/api/factory/runs', lambda route: route.fulfill(
                content_type='application/json', body=json.dumps({'runs': [run]})))
            context.route('**/api/sessions', lambda route: route.fulfill(
                content_type='application/json', body=json.dumps({'sessions': [card]})))

            def answer(route):
                request = route.request
                data = request.post_data or ''
                choice = (json.loads(data)['choice'] if 'application/json' in
                          request.headers.get('content-type', '') else parse_qs(data)['choice'][0])
                decisions.append(choice)
                route.fulfill(content_type='application/json', body=json.dumps({'choice': choice}))

            context.route('**/api/sessions/*/unblock', answer)
            page.goto(base.rstrip('/') + '/' + surface + '#agent-browser-test')
            page.get_by_role('button', name=card['options'][0], exact=True).wait_for()
            assert page.locator('img[src="x"]').count() == 0
            assert page.evaluate('window.injected') is None
            if surface == 'unblock':
                page.locator('.card-expand').wait_for()
                assert page.get_by_role('button', name='SKIP', exact=True).count() == 0
                page.get_by_role('button', name='Write an answer').click()
                page.locator('#modalText').fill('Use a small team workflow')
                page.evaluate('submitUnblock()')
                assert decisions == ['Use a small team workflow']
            else:
                page.get_by_role('button', name=card['options'][0], exact=True).click()
                page.wait_for_timeout(100)
                assert decisions == [card['options'][0]]
            assert page.get_by_role('link', name='Preview', exact=True).count() == 1
            assert not errors, errors
            context.close()
        browser.close()
    print('PASS: literal agent text, exact decisions, deep links, clarification and preview controls')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'https://127.0.0.1:6856')
