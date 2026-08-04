import io, sys, urllib.request, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

def get(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read().decode("utf-8", errors="replace")

# 1. Landing page
status, html = get("http://localhost:8000/")
print(f"=== GET / -> {status}, {len(html)} bytes ===")
print("Contains 'Full App Catalog':", "Full App Catalog" in html)
print("Contains 'Learn more':", "learn-more" in html)
print("Contains 'catalog_json':", "CATALOG_APPS" in html)
print("Contains n8n in embedded catalog:", '"n8n"' in html)
print("Contains emoji for n8n (📝):", "📝" in html)
print("Contains renderDetail:", "function renderDetail" in html)
print()

# 2. Check the embedded catalog has tagline data
import re
m = re.search(r'var CATALOG_APPS = (.*?);\n', html, re.S)
if m:
    try:
        data = json.loads(m.group(1))
        apps = data.get("apps", [])
        print(f"Embedded apps: {len(apps)}")
        n8n = next((a for a in apps if a["id"]=="n8n"), None)
        if n8n:
            print("n8n tagline:", n8n.get("tagline", "MISSING")[:60])
            print("n8n emoji:", n8n.get("emoji", "MISSING"))
            print("n8n has long_description:", bool(n8n.get("long_description")))
    except Exception as e:
        print("JSON parse error:", e)
        print(m.group(1)[:200])
else:
    print("Could not find CATALOG_APPS in HTML")

# 3. Check a sample of visible apps are embedded
print()
print("=== Visible apps in embedded catalog ===")
try:
    data = json.loads(m.group(1))
    for a in data["apps"][:8]:
        print(f"  {a['id']} | {a.get('emoji')} | {a.get('tagline','')[:40]}")
    print(f"  ... ({len(data['apps'])} total)")
except Exception as e:
    print("err", e)
