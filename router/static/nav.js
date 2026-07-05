// nav.js — muLLM shared navigation
// Include in any page: <script src="/static/nav.js"></script>

(function () {
  // Primary nav — pages that ship and work
  var PRIMARY = [
    { href: '/',          label: 'Chat' },
    { href: '/dashboard', label: 'Dashboard' },
    { href: '/translate', label: 'Translate' },
    { href: '/privacy',   label: 'Privacy' },
    { href: '/security',  label: 'Security' },
    { href: '/setup',     label: 'Setup' },
  ];

  // Secondary nav — specialty pages in the modal
  var SECONDARY = [
    { href: '/troubleshoot', label: 'Debug',      color: '#FBBF24' },
  ];

  var NAV_STYLES = [
    '#mullm-nav {',
    '  position: sticky; top: 0; z-index: 100;',
    '  display: flex; align-items: center; gap: 0;',
    '  background: #0f172a; border-bottom: 1px solid #1e293b;',
    '  padding: 0 1rem; height: 44px; font-family: system-ui, sans-serif;',
    '}',
    '#mullm-nav .mn-brand {',
    '  font-weight: 700; font-size: 1rem; margin-right: 1.5rem;',
    '  text-decoration: none; white-space: nowrap;',
    '}',
    '#mullm-nav .mn-brand .mu { color: #F59E0B; }',
    '#mullm-nav .mn-brand .llm { color: #94A3B8; }',
    '#mullm-nav .mn-primary { display: flex; gap: 0.1rem; flex: 1; overflow: hidden; }',
    '#mullm-nav .mn-link {',
    '  color: #94A3B8; text-decoration: none; padding: 0.25rem 0.6rem;',
    '  border-radius: 4px; font-size: 0.85rem; white-space: nowrap;',
    '  transition: background 0.15s, color 0.15s;',
    '}',
    '#mullm-nav .mn-link:hover { background: #1e293b; color: #f1f5f9; }',
    '#mullm-nav .mn-link.active { background: #1e3a5f; color: #60a5fa; cursor: pointer; }',
    '#mullm-nav .mn-link.active:hover { background: #1e4a7f; color: #93c5fd; }',
    '#mullm-nav .mn-more {',
    '  color: #F59E0B; font-size: 0.8rem; padding: 0.2rem 0.5rem;',
    '  border: 1px solid rgba(245,158,11,0.27); border-radius: 4px; cursor: pointer;',
    '  background: transparent; white-space: nowrap; font-family: system-ui, sans-serif;',
    '}',
    '#mullm-nav .mn-more:hover { background: rgba(245,158,11,0.13); }',
    '#mn-modal-bg {',
    '  display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.53);',
    '  z-index: 200; align-items: flex-start; justify-content: flex-end;',
    '  padding: 48px 1rem 0;',
    '}',
    '#mn-modal-bg.open { display: flex; }',
    '#mn-modal {',
    '  background: #0f172a; border: 1px solid #334155;',
    '  border-radius: 10px; padding: 1rem; width: 320px; max-height: 80vh;',
    '  overflow-y: auto; box-shadow: 0 20px 60px rgba(0,0,0,0.67);',
    '}',
    '#mn-modal h3 {',
    '  color: #94A3B8; font-size: 0.75rem; margin: 0 0 0.75rem;',
    '  letter-spacing: 0.1em; text-transform: uppercase;',
    '  font-family: system-ui, sans-serif;',
    '}',
    '#mn-modal .mn-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.4rem; }',
    '#mn-modal .mn-card {',
    '  display: block; padding: 0.5rem 0.7rem; border-radius: 6px;',
    '  font-size: 0.85rem; text-decoration: none; transition: opacity 0.15s;',
    '  border: 1px solid transparent; font-family: system-ui, sans-serif;',
    '}',
    '#mn-modal .mn-card:hover { opacity: 0.75; }',
    '#mn-modal .mn-card.mn-soon { opacity: 0.85; }',
    '#mullm-footer {',
    '  text-align: center; padding: 1rem; font-size: 0.72rem; color: #475569;',
    '  border-top: 1px solid #1e293b; margin-top: 3rem;',
    '  font-family: system-ui, sans-serif;',
    '}',
    '#mullm-footer a { color: #64748b; text-decoration: none; }',
    '#mullm-footer a:hover { color: #94A3B8; }',
  ].join('\n');

  function buildNav() {
    var links = PRIMARY.map(function (p) {
      return '<a class="mn-link" href="' + p.href + '">' + p.label + '</a>';
    }).join('');

    var cards = SECONDARY.map(function (s) {
      return (
        '<a class="mn-card mn-soon" href="' + s.href + '" ' +
        'style="color:' + s.color + ';border-color:' + s.color + '33;background:' + s.color + '11">' +
        s.label +
        '</a>'
      );
    }).join('');

    return (
      '<nav id="mullm-nav" role="navigation" aria-label="muLLM navigation">' +
        '<a class="mn-brand" href="/">' +
          '<span class="mu">mμ|</span><span class="llm">LLM</span>' +
        '</a>' +
        '<div class="mn-primary">' + links + '</div>' +
        '<button class="mn-more" ' +
          'onclick="document.getElementById(\'mn-modal-bg\').classList.toggle(\'open\')">' +
          'More &#9660;' +
        '</button>' +
      '</nav>' +
      '<div id="mn-modal-bg" ' +
           'onclick="if(event.target===this)this.classList.remove(\'open\')">' +
        '<div id="mn-modal">' +
          '<h3>More pages</h3>' +
          '<div class="mn-grid">' + cards + '</div>' +
        '</div>' +
      '</div>'
    );
  }

  function buildFooter() {
    return (
      '<footer id="mullm-footer">' +
        '<span>muLLM &mdash; local-first AI routing &mdash; ' +
        '<a href="https://0101technology.com" target="_blank" rel="noopener">' +
          '0101 Technology' +
        '</a>' +
        ' &mdash; Apache 2.0</span>' +
      '</footer>'
    );
  }

  function markActiveLink() {
    var path = window.location.pathname;
    var links = document.querySelectorAll('#mullm-nav .mn-link');
    for (var i = 0; i < links.length; i++) {
      var href = links[i].getAttribute('href');
      if (
        href === path ||
        (path !== '/' && href !== '/' && path.indexOf(href) === 0)
      ) {
        links[i].classList.add('active');
      }
    }
  }

  function applyPageManifest(manifest) {
    if (!manifest || !manifest.pages) return;
    PRIMARY = (manifest.primary || manifest.pages.slice(0, 6)).map(function (p) {
      return { href: p.href, label: p.label };
    });
    var primaryHrefs = {};
    PRIMARY.forEach(function (p) { primaryHrefs[p.href] = true; });
    SECONDARY = manifest.pages.filter(function (p) {
      return !primaryHrefs[p.href];
    });
    var oldNav = document.getElementById('mullm-nav');
    var oldModal = document.getElementById('mn-modal-bg');
    if (oldNav) oldNav.remove();
    if (oldModal) oldModal.remove();
    var wrapper = document.createElement('div');
    wrapper.innerHTML = buildNav();
    Array.prototype.slice.call(wrapper.childNodes).reverse().forEach(function (node) {
      document.body.insertBefore(node, document.body.firstChild);
    });
    markActiveLink();
  }

  function injectStyles() {
    if (document.getElementById('mullm-nav-style')) return;
    var style = document.createElement('style');
    style.id = 'mullm-nav-style';
    style.textContent = NAV_STYLES;
    document.head.appendChild(style);
  }

  function init() {
    injectStyles();

    // Inject nav + modal at top of body
    var wrapper = document.createElement('div');
    wrapper.innerHTML = buildNav();
    // insertBefore each child in reverse so order is preserved
    var children = Array.prototype.slice.call(wrapper.childNodes).reverse();
    children.forEach(function (node) {
      document.body.insertBefore(node, document.body.firstChild);
    });

    markActiveLink();

    fetch('/api/pages')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(applyPageManifest)
      .catch(function () {});

    // Inject footer at bottom of body
    document.body.insertAdjacentHTML('beforeend', buildFooter());
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    // DOM already ready (script loaded with defer or after DOMContentLoaded)
    init();
  }
})();
