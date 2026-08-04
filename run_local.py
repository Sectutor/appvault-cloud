"""Local dev launcher for AppVault central server."""
import os, sys

os.environ.setdefault("CENTRAL_PORT", "8000")
os.environ.setdefault("CENTRAL_URL", "http://localhost:8000")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "appvault-admin")
os.environ.setdefault("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "appvault.db"))
os.environ.setdefault("CATALOG_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "catalog.json"))
os.environ.setdefault("DOMAIN", "localhost:8000")
os.environ.setdefault("AGENT_POLL_SECONDS", "30")
os.environ.setdefault("AGENT_TIMEOUT_SECONDS", "300")

# Stripe test prices (created in Stripe test mode)
os.environ.setdefault("STRIPE_PRICE_PRO", "price_1U0dv108dNwwNbqfJUCnTreQ")
os.environ.setdefault("STRIPE_PRICE_PRO_YEARLY", "price_1U0dv108dNwwNbqfyZCap4JZ")

# Load Stripe test key
key_path = r"C:\Users\emman\stripe-test.key"
if not os.environ.get("STRIPE_SECRET_KEY") and os.path.exists(key_path):
    with open(key_path) as f:
        os.environ["STRIPE_SECRET_KEY"] = f.read().strip()
    print(f"[run_local] Loaded STRIPE_SECRET_KEY from {key_path}")

import uvicorn
print("[run_local] Starting AppVault central on http://localhost:8000")
uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
