import functools
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import threading
from playwright.sync_api import sync_playwright
class Handler(SimpleHTTPRequestHandler):
 def log_message(self,*_): pass
config=json.loads(Path('product.json').read_text())
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(Path.cwd())))
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True)
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(f'http://127.0.0.1:{server.server_port}')
  page.wait_for_selector('.metric')
  assert page.locator('#title').inner_text()==config['title']
  key=config['fields'][0]['key'];value='A deliberately edited project'
  page.fill('#input-'+key,value);page.reload();page.wait_for_selector('.metric')
  assert page.input_value('#input-'+key)==value,'edited brief must survive reload'
  page.click('#tab-evidence');assert page.locator('.empty').is_visible()
  page.fill('#source-form [name=title]','Customer conversation')
  page.fill('#source-form [name=owner]','Northstar')
  page.fill('#source-form [name=claim]','Participant prefers a smaller pilot')
  page.fill('#source-form [name=url]','https://example.com/interview-notes')
  page.click('#source-form button');assert page.locator('.source').count()==1
  assert page.locator('.source .status').inner_text()=='Not reviewed'
  page.locator('.source input[type=checkbox]').check();assert page.locator('.source .status').inner_text()=='Human-reviewed'
  page.locator('.source button').click();assert page.locator('.empty').is_visible()
  page.click('#restore');assert page.locator('.source').count()==1
  page.click('#tab-decisions');page.fill('#decision-form textarea','Run a small pilot; reconsider after five interviews.');page.click('#decision-form button');assert page.locator('#decisions li').count()==1
  with page.expect_download() as d:page.click('#export')
  exported=json.loads(Path(d.value.path()).read_text());assert exported['input'][key]==value and len(exported['sources'])==1 and len(exported['decisions'])==1
  page.click('#tab-plan');Path('dist').mkdir(exist_ok=True);page.screenshot(path='dist/desktop.png',full_page=True)
  page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),'mobile horizontal overflow'
  page.screenshot(path='dist/mobile.png',full_page=True)
  assert not errors,errors
  browser.close();print('PASS: useful output, editable persistent brief, evidence provenance, review labels, restore, decision log, export, mobile fit, no browser errors')
finally:server.shutdown();server.server_close()
