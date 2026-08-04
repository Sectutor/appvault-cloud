import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Check repo catalog for icon/emoji fields
cat = json.load(open(r"C:\Users\emman\appvault-repo\manager\catalog.json", encoding="utf-8"))
apps = cat.get("apps", [])
print("=== Repo catalog: any icon/emoji/color fields? ===")
for a in apps:
    extras = {k: a.get(k) for k in ["icon","emoji","color","image"] if a.get(k)}
    if extras:
        print(a["id"], "->", extras)
        break
# Check what fields n8n has in repo
n8n = next(a for a in apps if a["id"] == "n8n")
print()
print("=== n8n full record in repo ===")
print(json.dumps(n8n, indent=2, ensure_ascii=False))

# Cloud-prod catalog - check image fields for icon possibilities
ccat = json.load(open(r"C:\Users\emman\appvault-cloud-prod\static\catalog.json", encoding="utf-8"))
capps = ccat.get("apps", [])
print()
print("=== Cloud-prod apps missing enrichment (visible) ===")
repo_ids = set(a["id"] for a in apps)
for a in capps:
    if a["id"] not in repo_ids and not a.get("hidden"):
        print(f"{a['id']} | {a['name']} | cat={a.get('category')} | image={a.get('image')}")
