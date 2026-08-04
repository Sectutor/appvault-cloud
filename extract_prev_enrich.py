import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

cat = json.load(open(r"C:\Users\emman\appvault-repo\manager\catalog.json", encoding="utf-8"))
apps = cat.get("apps", [])
FIELDS = ["tagline","long_description","version","author","tags","website","docs_url","forum_url","repository_url","changelog","screenshots"]

# Dump enrichment dict to a JSON file for reuse
enrich = {}
for a in apps:
    d = {}
    for f in FIELDS:
        if a.get(f) is not None:
            d[f] = a[f]
    if d:
        enrich[a["id"]] = d

with open(r"C:\Users\emman\appvault-cloud-prod\_prev_enrichment.json", "w", encoding="utf-8") as f:
    json.dump(enrich, f, indent=2, ensure_ascii=False)

print("Dumped", len(enrich), "app enrichments")
print("IDs:", list(enrich.keys()))
