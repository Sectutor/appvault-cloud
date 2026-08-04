#!/usr/bin/env python3
"""Fix all catalog.json open() calls in main.py to use UTF-8."""
import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

path = r"C:\Users\emman\appvault-cloud-prod\main.py"
with open(path, encoding="utf-8-sig") as f:
    src = f.read()

# Fix all open(CATALOG_PATH ...) patterns
patterns = [
    ('open(CATALOG_PATH) as f:', 'open(CATALOG_PATH, encoding="utf-8") as f:'),
    ('open(CATALOG_PATH, "w") as f:', 'open(CATALOG_PATH, "w", encoding="utf-8") as f:'),
]
count = 0
for old, new in patterns:
    n = src.count(old)
    src = src.replace(old, new)
    count += n

with open(path, "w", encoding="utf-8-sig") as f:
    f.write(src)
print(f"Fixed {count} open() calls")

# Verify no remaining non-UTF8 opens
leftover = [m for m in re.findall(r'open\(CATALOG_PATH[^)]*\)', src) if 'encoding' not in m]
print("Remaining without encoding:", leftover)
