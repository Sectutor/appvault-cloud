import io, sys, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

def get(url):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None, str(e)

for url in ["http://localhost:8000/", "http://localhost:8000/pricing", "http://localhost:8000/health"]:
    status, body = get(url)
    if status:
        print(f"{url} -> {status} | {len(body)} bytes")
    else:
        print(f"{url} -> ERROR: {body}")

# Check server log tail for errors
print()
print("=== server.log tail ===")
try:
    log = open(r"C:\Users\emman\appvault-cloud-prod\server.log", encoding="utf-8", errors="replace").read()
    print(log[-1500:])
except Exception as e:
    print("log error:", e)
