import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

src = open(r"C:\Users\emman\appvault-cloud-prod\main.py", encoding="utf-8").read()
lines = src.splitlines()
# Show the landing route area (1300-1315) and template setup (top)
print("=== Template setup (top) ===")
for i, l in enumerate(lines[:60]):
    if "template" in l.lower() or "Jinja" in l or "TEMPLATES" in l or "FileResponse" in l or "StaticFiles" in l:
        print(f"{i+1:4d}: {l}")

print()
print("=== Landing route (1295-1320) ===")
for i in range(1294, min(1320, len(lines))):
    print(f"{i+1:4d}: {lines[i]}")

print()
print("=== GLOBAL_CATALOG usage ===")
for i, l in enumerate(lines):
    if "GLOBAL_CATALOG" in l:
        print(f"{i+1:4d}: {l}")
