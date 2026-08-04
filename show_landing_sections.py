import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

html = open(r"C:\Users\emman\appvault-cloud-prod\templates\landing.html", encoding="utf-8").read()
lines = html.splitlines()

print("=== Apps section (lines 290-330) ===")
for i in range(289, min(330, len(lines))):
    print(f"{i+1:4d}: {lines[i]}")

print()
print("=== Script section (lines 470-end) ===")
for i in range(469, len(lines)):
    print(f"{i+1:4d}: {lines[i]}")
