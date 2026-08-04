import io, sys, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Load previous enrich script to see structure
src = open(r"C:\Users\emman\appvault-repo\manager\enrich_catalog.py", encoding="utf-8").read()
print("=== enrich_catalog.py first 80 lines ===")
print("\n".join(src.splitlines()[:80]))
print()
print("=== How many apps does it define? ===")
# Count occurrences of app id assignments
import re
ids = re.findall(r'"(id|app_id)"\s*:\s*"([^"]+)"', src)
print("id references:", len(ids))
# Check metadata dict structure
idx = src.find("METADATA")
if idx > 0:
    print(src[idx:idx+1500])
