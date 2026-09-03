"""AppVault Central — local-only shim for production-like flow on this PC.

This is the SAME code path a real production central runs (market.py +
main.py's minimal middleware), but it boots standalone, persists its DB
to data/appvault-local.db, and runs as a long-lived process the
appvault-agent on this machine can reach at host.docker.internal:8010.

Why this exists: the production central at appvault.airepoindex.com was
never deployed, so for now this PC plays the role of the central. The
signing, webhook, and email paths here are identical to what a real
production central will run; only the host differs.
"""
import os
import sys
import sqlite3
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Use a persistent DB in a stable location so licenses survive restarts.
DB_PATH = os.path.join(HERE, "data", "appvault-local.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.environ["DB_PATH"] = DB_PATH

# Pin the signing key to the project's matching private key. The app's
# embedded public key was rotated to match this exact file.
PRIV_KEY_PATH = r"D:\OneDrive - Intellfence\WebDev\AIWriter\private_key.pem"
if os.path.exists(PRIV_KEY_PATH):
    with open(PRIV_KEY_PATH, "r", encoding="utf-8") as f:
        os.environ["LICENSE_PRIVATE_KEY_PEM"] = f.read().strip()
else:
    print(f"WARNING: private key not found at {PRIV_KEY_PATH}", file=sys.stderr)

# Central will refuse to start without these. Set safe local-test defaults.
os.environ.setdefault("ADMIN_PASSWORD", "local-central-not-secret")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_local_dev_only_replace_in_production")
# Stripe keys come from env (set by launch script, not committed).
os.environ.setdefault("STRIPE_SECRET_KEY", "")
os.environ.setdefault("DOMAIN", "127.0.0.1:8010")
os.environ.setdefault("CENTRAL_URL", "http://127.0.0.1:8010")

# Import market and register its routes. The market module also pulls in
# its own dependencies (cryptography, etc.).
import market  # noqa: E402


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def require_admin(request):  # not used for /api/market/*
    return True


def audit(kind, msg):
    print(f"[audit] {kind} {msg}", flush=True)


app = FastAPI(title="AppVault Central (local)", version="local-only")


@app.get("/health")
def health():
    return {"ok": True, "role": "central", "local": True}


@app.get("/")
def root():
    return {"ok": True, "service": "appvault-central-local", "db": DB_PATH}


# Register the real market module (same as main.py does)
market.register_market(
    app, get_db, require_admin, audit,
    JSONResponse, JSONResponse, Request, JSONResponse,
    DOMAIN=os.environ.get("DOMAIN", "127.0.0.1:8010"),
)
print(f"[local-central] /api/market/* registered | DB: {DB_PATH}", flush=True)
print(f"[local-central] signing key: {'LOADED' if os.environ.get('LICENSE_PRIVATE_KEY_PEM') else 'MISSING'}", flush=True)
print(f"[local-central] stripe key:   {'LOADED' if os.environ.get('STRIPE_SECRET_KEY') else 'NOT SET (checkout will 503, webhook signing still works)'}", flush=True)
