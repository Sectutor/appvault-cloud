import json

with open(r"C:\Users\emman\appvault-cloud-prod\static\catalog.json", encoding="utf-8") as f:
    cat = json.load(f)

print("Top keys:", list(cat.keys()))
apps = cat.get("apps", [])
print("App count:", len(apps))
print()
print("=== First app full structure ===")
print(json.dumps(apps[0], indent=2, ensure_ascii=False))
print()
print("=== All app ids (id | name | category | port | hidden) ===")
for a in apps:
    print(f"{a.get('id')} | {a.get('name')} | cat={a.get('category')} | port={a.get('container_port')} | hidden={a.get('hidden')}")

# Check for any existing enrichment fields
print()
print("=== Existing enrichment fields? ===")
for fld in ["tagline", "long_description", "version", "author", "tags", "website", "docs_url", "forum_url", "repository_url", "changelog", "screenshots", "image", "emoji"]:
    count = sum(1 for a in apps if a.get(fld))
    print(f"{fld}: {count}/{len(apps)}")
