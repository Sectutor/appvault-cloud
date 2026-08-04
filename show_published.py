import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

src = open(r"C:\Users\emman\appvault-cloud-prod\main.py", encoding="utf-8").read()
lines = src.splitlines()

# Find _app_published definition
for i, l in enumerate(lines):
    if "_app_published" in l and "def" in l:
        print(f"{i+1}: {l}")
        # print next 15 lines
        for j in range(i+1, min(i+16, len(lines))):
            print(f"{j+1}: {lines[j]}")
        break

print()
print("=== Lines 220-230 (GLOBAL_CATALOG load) ===")
for i in range(219, 230):
    print(f"{i+1}: {lines[i]}")
