"""Self-contained AppVault central shim — only /api/market/* + /health.

Avoids importing main.py because main.py's SessionMiddleware is incompatible
with the starlette version that pip resolves from the loose requirements.txt
(`SessionMiddleware.__init__() got an unexpected keyword argument 'httponly'`).
This shim imports market.py directly and runs it with a minimal FastAPI app,
the same way the local end-to-end test does it.

Drop this file into the central repo alongside main.py, then start with:
  uvicorn _market_only:app --host 0.0.0.0 --port 8000

The full main.py can be reintroduced once requirements.txt pins a starlette
that accepts `httponly=` (e.g. by adding `starlette<0.40`).
"""
import os
import sys
import sqlite3
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Persistent DB path; created on first run. Same default as main.py.
DB_PATH = os.environ.get("DB_PATH", os.path.join(HERE, "data", "appvault.db"))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.environ["DB_PATH"] = DB_PATH  # so market's get_db() finds it


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def require_admin(request):  # not used for /api/market/*
    return True


def audit(kind, msg):
    print(f"[audit] {kind} {msg}", flush=True)


app = FastAPI(title="AppVault Central (market-only shim)", version="market-shim-1")


@app.get("/health")
def health():
    return {"ok": True, "role": "central", "shim": "market-only"}


@app.get("/")
def root():
    return {"ok": True, "service": "appvault-central", "endpoints": ["/api/market", "/health"]}


# Register the real market module on this minimal app. Uses the same args
# the production main.py does.
import market  # noqa: E402

market.register_market(
    app, get_db, require_admin, audit,
    JSONResponse, JSONResponse, Request, JSONResponse,
    DOMAIN=os.environ.get("DOMAIN", "appvault.airepoindex.com"),
)
print(f"[shim] /api/market/* registered | DB: {DB_PATH}", flush=True)
print(f"[shim] signing key: {'LOADED' if os.environ.get('LICENSE_PRIVATE_KEY_PEM') else 'MISSING'}", flush=True)
