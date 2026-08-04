import io, sys, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

src = open(r"C:\Users\emman\appvault-repo\manager\enrich_catalog.py", encoding="utf-8").read()
# Find all top-level ENRICHMENT keys (app ids)
keys = re.findall(r'^\s{4}"([a-z0-9-]+)":\s*\{', src, re.MULTILINE)
print("Apps in previous enrichment:", len(keys))
print(keys)

# Load the enriched repo catalog to get the data directly
cat = json.load(open(r"C:\Users\emman\appvault-repo\manager\catalog.json", encoding="utf-8"))
apps = cat.get("apps", [])
print()
print("Repo catalog apps:", len(apps))
for a in apps:
    extra = {k: a.get(k) for k in ["tagline","long_description","version","author","tags","website","docs_url","forum_url","repository_url","changelog","screenshots"] if a.get(k)}
    print(f"{a['id']}: {len(extra)} enriched fields")
