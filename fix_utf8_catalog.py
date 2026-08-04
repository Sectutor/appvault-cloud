#!/usr/bin/env python3
"""Fix main.py: open catalog.json with UTF-8 encoding (enriched catalog has emojis)."""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

path = r"C:\Users\emman\appvault-cloud-prod\main.py"
with open(path, encoding="utf-8-sig") as f:
    src = f.read()

# Fix the GLOBAL_CATALOG load
old = """with open(CATALOG_PATH) as f:
    GLOBAL_CATALOG = json.load(f)"""
new = """with open(CATALOG_PATH, encoding="utf-8") as f:
    GLOBAL_CATALOG = json.load(f)"""

if old in src:
    src = src.replace(old, new)
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(src)
    print("FIXED: UTF-8 encoding for GLOBAL_CATALOG load")
else:
    print("Pattern not found, checking...")
    idx = src.find("GLOBAL_CATALOG = json.load")
    print(repr(src[idx-100:idx+50]))
