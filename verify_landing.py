import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

html = open(r"C:\Users\emman\appvault-cloud-prod\templates\landing.html", encoding="utf-8").read()
lines = html.splitlines()
print("Total lines:", len(lines))
print()

# Check key markers
checks = {
    "catalog_json Jinja": "{{ catalog_json|safe }}" in html,
    "apps-grid dynamic container": 'id="apps-grid"' in html,
    "app-detail container": 'id="app-detail"' in html,
    "renderDetail fn": "function renderDetail" in html,
    "handleHash fn": "function handleHash" in html,
    "goBack fn": "function goBack" in html,
    "Learn more": "learn-more" in html,
    "hashchange listener": "hashchange" in html,
    "renderGrid call": "renderGrid();" in html,
    "handleHash call": "handleHash();" in html,
}
for k, v in checks.items():
    print(f"{'✅' if v else '❌'} {k}")

# Check no leftover static app-tags
print()
print("Static app-tag count (should be 0):", html.count('class="app-tag"><div class="emoji">💬'))

# Check JS section near end
print()
print("=== Tail of file (last 30 lines) ===")
for i in range(max(0, len(lines)-30), len(lines)):
    print(f"{i+1:4d}: {lines[i][:110]}")
