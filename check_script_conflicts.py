import json, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

cat = json.load(open(r"C:\Users\emman\appvault-cloud-prod\static\catalog.json", encoding="utf-8"))
issues = []
for a in cat.get("apps", []):
    for fld in ["long_description", "description", "changelog", "tagline"]:
        v = a.get(fld) or ""
        if "</script" in v.lower() or "{{" in v or "{%" in v:
            issues.append((a["id"], fld))
if issues:
    print("ISSUES FOUND:")
    for i in issues:
        print(" ", i)
else:
    print("No script-tag or Jinja conflicts in catalog fields ✅")

# Also test that JSON is valid and will embed cleanly
s = json.dumps({"apps": cat["apps"]}, ensure_ascii=False)
print(f"catalog_json size: {len(s)} chars")
print("Contains </script>:", "</script" in s.lower())
