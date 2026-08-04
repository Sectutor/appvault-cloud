import io, sys, urllib.request, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Fetch the page and simulate what the JS would produce for #app/n8n
req = urllib.request.Request("http://localhost:8000/")
with urllib.request.urlopen(req, timeout=10) as r:
    html = r.read().decode("utf-8", errors="replace")

# Extract embedded catalog
m = re.search(r'var CATALOG_APPS = (.*?);\nvar CATALOG_DATA', html, re.S)
if not m:
    m = re.search(r'var CATALOG_APPS = (.*?);', html, re.S)
data = json.loads(m.group(1))
apps = data["apps"]

# Simulate renderDetail for n8n (replicate the JS logic in Python to verify output)
def sim_detail(app):
    tags = ''.join(f'<span class="tag">{t}</span>' for t in (app.get('tags') or []))
    shots = ''.join(f'<img src="{s}" alt="screenshot">' for s in (app.get('screenshots') or []))
    desc = app.get('long_description') or app.get('description') or ''
    links = []
    if app.get('website'): links.append('Website')
    if app.get('docs_url'): links.append('Documentation')
    if app.get('forum_url'): links.append('Community')
    if app.get('repository_url'): links.append('Source')
    return {
        "name": app.get('name'),
        "emoji": app.get('emoji'),
        "tagline": app.get('tagline'),
        "version": app.get('version'),
        "author": app.get('author'),
        "links": links,
        "desc_len": len(desc),
        "tags": app.get('tags'),
        "changelog": bool(app.get('changelog')),
        "screenshots": len(app.get('screenshots') or []),
        "min_ram_mb": app.get('min_ram_mb'),
    }

n8n = next(a for a in apps if a["id"] == "n8n")
print("=== Simulated detail render for n8n ===")
for k, v in sim_detail(n8n).items():
    print(f"  {k}: {v}")

print()
print("=== All 52 apps: check detail fields present ===")
missing = []
for a in apps:
    if not a.get('long_description') and not a.get('description'):
        missing.append(a['id'])
    if not a.get('emoji'):
        missing.append(a['id'] + ' (no emoji)')
    if not a.get('category'):
        missing.append(a['id'] + ' (no category)')
print("Apps missing critical fields:", missing if missing else "NONE ✅")

print()
print("=== Pro vs Free breakdown ===")
free = sum(1 for a in apps if a.get('free_tier'))
print(f"Free tier: {free} | Pro (paid): {len(apps)-free}")

print()
print("=== Category breakdown ===")
cats = {}
for a in apps:
    c = a.get('category', 'unknown')
    cats[c] = cats.get(c, 0) + 1
for c, n in sorted(cats.items()):
    print(f"  {c}: {n}")
