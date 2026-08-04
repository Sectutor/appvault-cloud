import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

cat = json.load(open(r"C:\Users\emman\appvault-cloud-prod\static\catalog.json", encoding="utf-8"))
apps = cat.get("apps", [])
print("Total apps:", len(apps))
print()
print("=== Sample: n8n ===")
n8n = next(a for a in apps if a["id"] == "n8n")
print(json.dumps(n8n, indent=2, ensure_ascii=False)[:2000])
print()
print("=== Sample: outline (newly enriched) ===")
out = next(a for a in apps if a["id"] == "outline")
print(json.dumps(out, indent=2, ensure_ascii=False)[:1200])
print()
print("=== Field coverage ===")
for fld in ["tagline","long_description","version","author","tags","website","docs_url","forum_url","repository_url","changelog","screenshots","emoji"]:
    count = sum(1 for a in apps if a.get(fld))
    print(f"{fld}: {count}/{len(apps)}")
