import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

html = open(r"C:\Users\emman\appvault-cloud-prod\templates\landing.html", encoding="utf-8").read()
lines = html.splitlines()
print("TOTAL LINES:", len(lines))
print()
# Print the beginning (head + CSS start)
for i, l in enumerate(lines[:60]):
    print(f"{i+1:4d}: {l}")
print("...")
# Find section markers
import re
for i, l in enumerate(lines):
    if re.match(r"<section", l) or "<h2" in l or "<script" in l or "</body>" in l or "apps-grid" in l:
        print(f"{i+1:4d}: {l.strip()[:100]}")
