#!/usr/bin/env python3
"""Patch landing.html: dynamic app catalog + Cloudron-style detail view.
1. Replace static apps-grid with dynamic container + detail placeholder.
2. Add detail-view CSS before </style>.
3. Add detail-view JS (renderDetail, handleHash, goBack, SEO) before </script>.
"""
import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

path = r"C:\Users\emman\appvault-cloud-prod\templates\landing.html"
with open(path, encoding="utf-8") as f:
    html = f.read()

orig_len = len(html)

# ── 1. Replace static apps section ─────────────────────────────────────
old_apps_start = html.find('<section id="apps"')
old_apps_end = html.find('<section id="pricing"')
if old_apps_start == -1 or old_apps_end == -1:
    print("ERROR: could not find apps/pricing sections")
    sys.exit(1)

new_apps_section = '''<section id="apps" style="background:#0f172a;">
    <div class="container">
        <h2>📦 Full App Catalog</h2>
        <p class="section-sub">53 apps, ready to install. Free users see the full catalog — install limit set by admin. Pro unlocks unlimited installs + every new app we add.</p>
        <div id="apps-grid" class="apps-grid"></div>
        <div id="app-detail" style="display:none;"></div>
        <p id="apps-more" style="text-align:center;margin-top:20px;color:#64748b;font-size:14px;">Full catalog — click any app to learn more</p>
        <p style="text-align:center;margin-top:8px;"><a href="#pricing" style="color:#38bdf8;">🔓 Unlock unlimited installs — $19/mo</a></p>
    </div>
</section>

'''
html = html[:old_apps_start] + new_apps_section + html[old_apps_end:]
print("1. Replaced static apps section")

# ── 2. Add detail-view CSS before </style> ─────────────────────────────
detail_css = '''
        /* ── App detail view (Cloudron-style) ── */
        .app-tag { cursor: pointer; transition: border-color 0.2s, transform 0.2s; text-decoration: none; display: block; }
        .app-tag:hover { border-color: #38bdf8; transform: translateY(-2px); }
        .app-tag .learn-more { display: block; margin-top: 8px; font-size: 0.72rem; color: #38bdf8; font-weight: 600; }
        .detail { max-width: 820px; margin: 0 auto; padding: 24px 0; }
        .detail-back { color: #60a5fa; text-decoration: none; font-size: 14px; display: inline-flex; align-items: center; gap: 6px; margin-bottom: 20px; cursor: pointer; background: none; border: none; }
        .detail-back:hover { text-decoration: underline; }
        .detail-header { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; }
        .detail-icon { width: 56px; height: 56px; border-radius: 12px; background: #1e293b; border: 1px solid #334155; display: flex; align-items: center; justify-content: center; font-size: 28px; }
        .detail-title { font-size: 26px; font-weight: 700; color: #fff; }
        .detail-tagline { font-size: 15px; color: #94a3b8; margin-top: 4px; }
        .detail-meta { font-size: 13px; color: #64748b; display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 20px; }
        .detail-meta span { background: #1e293b; border: 1px solid #334155; padding: 3px 10px; border-radius: 20px; }
        .detail-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 24px; }
        .detail-actions a { padding: 8px 18px; border: 1px solid #334155; border-radius: 8px; color: #94a3b8; text-decoration: none; font-size: 13px; font-weight: 600; }
        .detail-actions a:hover { border-color: #38bdf8; color: #38bdf8; }
        .detail-section { margin-bottom: 24px; }
        .detail-section h3 { font-size: 14px; font-weight: 600; color: #e2e8f0; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
        .detail-desc { font-size: 15px; color: #cbd5e1; line-height: 1.7; white-space: pre-line; }
        .detail-tags { display: flex; flex-wrap: wrap; gap: 8px; }
        .detail-tags .tag { padding: 4px 12px; border-radius: 20px; background: rgba(56,189,248,0.12); color: #38bdf8; font-size: 12px; font-weight: 600; }
        .detail-changelog { font-size: 14px; color: #94a3b8; line-height: 1.7; white-space: pre-line; background: #1e293b; border-radius: 8px; padding: 16px; border: 1px solid #334155; }
        .detail-screenshots { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 8px; }
        .detail-screenshots img { width: 240px; border-radius: 8px; border: 1px solid #334155; flex-shrink: 0; }
        .detail-install-cta { margin-top: 28px; padding: 20px; background: #1e293b; border: 1px solid #334155; border-radius: 12px; text-align: center; }
        .detail-install-cta p { color: #94a3b8; font-size: 14px; margin-bottom: 12px; }
'''

style_end = html.rfind("</style>")
if style_end == -1:
    print("ERROR: no </style> found")
    sys.exit(1)
html = html[:style_end] + detail_css + html[style_end:]
print("2. Added detail-view CSS")

# ── 3. Add detail-view JS before </script> ─────────────────────────────
detail_js = '''
// ── Dynamic app catalog + Cloudron-style detail view ──
var CATALOG_APPS = {{ catalog_json|safe }};
var CATALOG_DATA = CATALOG_APPS && CATALOG_APPS.apps ? CATALOG_APPS.apps : [];

function esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function appById(id) {
    for (var i = 0; i < CATALOG_DATA.length; i++) {
        if (CATALOG_DATA[i].id === id) return CATALOG_DATA[i];
    }
    return null;
}
function renderGrid() {
    var grid = document.getElementById('apps-grid');
    if (!grid) return;
    var html = '';
    for (var i = 0; i < CATALOG_DATA.length; i++) {
        var a = CATALOG_DATA[i];
        var emoji = a.emoji || '📦';
        var pro = a.free_tier ? '' : '<div class="pro-badge">PRO</div>';
        html += '<a class="app-tag" href="#app/' + esc(a.id) + '" style="text-decoration:none;">'
              + '<div class="emoji">' + emoji + '</div>'
              + '<div class="name">' + esc(a.name) + '</div>'
              + '<div class="cat">' + esc(a.category || '') + '</div>'
              + pro
              + '<div class="learn-more">Learn more →</div>'
              + '</a>';
    }
    grid.innerHTML = html;
}
function renderDetail(app) {
    var grid = document.getElementById('apps-grid');
    var detail = document.getElementById('app-detail');
    var more = document.getElementById('apps-more');
    if (grid) grid.style.display = 'none';
    if (more) more.style.display = 'none';
    var tags = (app.tags || []).map(function(t){ return '<span class="tag">' + esc(t) + '</span>'; }).join('');
    var shots = (app.screenshots || []).map(function(s){ return '<img src="' + esc(s) + '" alt="screenshot">'; }).join('');
    var desc = esc(app.long_description || app.description || '');
    var links = [];
    if (app.website) links.push('<a href="' + esc(app.website) + '" target="_blank">Website</a>');
    if (app.docs_url) links.push('<a href="' + esc(app.docs_url) + '" target="_blank">Documentation</a>');
    if (app.forum_url) links.push('<a href="' + esc(app.forum_url) + '" target="_blank">Community</a>');
    if (app.repository_url) links.push('<a href="' + esc(app.repository_url) + '" target="_blank">Source</a>');
    var html = '<div class="detail">'
        + '<button class="detail-back" onclick="goBack()">&larr; Back to App Store</button>'
        + '<div class="detail-header">'
        + '<div class="detail-icon">' + (app.emoji || '📦') + '</div>'
        + '<div><div class="detail-title">' + esc(app.name) + '</div>'
        + '<div class="detail-tagline">' + esc(app.tagline || app.description || '') + '</div></div></div>'
        + '<div class="detail-meta">'
        + (app.version ? '<span>v' + esc(app.version) + '</span>' : '')
        + (app.author ? '<span>' + esc(app.author) + '</span>' : '')
        + (app.category ? '<span>' + esc(app.category) + '</span>' : '')
        + (app.min_ram_mb ? '<span>' + esc(app.min_ram_mb) + 'MB+ RAM</span>' : '')
        + '</div>'
        + '<div class="detail-actions">' + links.join('') + '</div>'
        + (app.screenshots && app.screenshots.length ? '<div class="detail-section"><h3>Screenshots</h3><div class="detail-screenshots">' + shots + '</div></div>' : '')
        + '<div class="detail-section"><h3>About ' + esc(app.name) + '</h3><div class="detail-desc">' + desc + '</div></div>'
        + (tags ? '<div class="detail-section"><h3>Tags</h3><div class="detail-tags">' + tags + '</div></div>' : '')
        + (app.changelog ? '<div class="detail-section"><h3>Changelog</h3><div class="detail-changelog">' + esc(app.changelog) + '</div></div>' : '')
        + '<div class="detail-install-cta"><p>Self-host ' + esc(app.name) + ' on your own machine</p>'
        + '<a class="btn-primary" href="#pricing">Get AppVault — Free</a></div>'
        + '</div>';
    if (detail) { detail.innerHTML = html; detail.style.display = 'block'; }
    document.title = (app.name ? app.name + ' - AppVault' : 'AppVault');
    var descEl = document.querySelector('meta[name="description"]');
    if (descEl) descEl.setAttribute('content', (app.tagline || app.description || ''));
    var h = document.getElementById('apps');
    if (h) h.scrollIntoView({behavior:'smooth'});
}
function goBack() {
    history.pushState(null, '', window.location.pathname);
    showGrid();
}
function showGrid() {
    var grid = document.getElementById('apps-grid');
    var detail = document.getElementById('app-detail');
    var more = document.getElementById('apps-more');
    if (grid) { grid.style.display = ''; }
    if (detail) { detail.style.display = 'none'; detail.innerHTML = ''; }
    if (more) more.style.display = '';
    document.title = 'AppVault — Your AI App Store';
}
function handleHash() {
    var m = location.hash.match(/^#app\\/(.+)$/);
    if (m) {
        var app = appById(m[1]);
        if (app) { renderDetail(app); return; }
    }
    showGrid();
}
window.addEventListener('hashchange', handleHash);
renderGrid();
handleHash();
'''

script_end = html.rfind("</script>")
if script_end == -1:
    print("ERROR: no </script> found")
    sys.exit(1)
html = html[:script_end] + detail_js + html[script_end:]
print("3. Added detail-view JS")

with open(path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Done. {orig_len} -> {len(html)} bytes")
