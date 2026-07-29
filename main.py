# AppVault Cloud — Automated Provisioning API
# FastAPI backend that provisions AppVault instances on payment.

import os
import uuid
import httpx
import sqlite3
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# ═══════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════

COOLIFY_URL = os.getenv("COOLIFY_URL", "http://169.58.9.191:8000")
COOLIFY_TOKEN = os.getenv("COOLIFY_TOKEN", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
DOMAIN = os.getenv("DOMAIN", "appvault.airepoindex.com")

# ═══════════════════════════════════════════════
# APP
# ═══════════════════════════════════════════════

app = FastAPI(title="AppVault Cloud")
templates = Jinja2Templates(directory="templates")

# ═══════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════

def get_db():
    conn = sqlite3.connect("appvault.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS instances (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            tier TEXT NOT NULL,
            stripe_session_id TEXT,
            status TEXT DEFAULT 'pending',
            url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()
    db.close()

init_db()

# ═══════════════════════════════════════════════
# COOLIFY PROVISIONING
# ═══════════════════════════════════════════════

async def provision_instance(instance_id: str, email: str, tier: str) -> Optional[str]:
    """Deploy AppVault on Coolify and return the URL."""
    
    # Generate subdomain from email
    subdomain = email.split("@")[0].lower().replace(".", "-").replace("_", "-")
    subdomain = f"{subdomain}-{instance_id[:6]}"
    url = f"https://{subdomain}.{DOMAIN}"
    
    # Prepare environment variables based on tier
    env = {
        "API_KEY": str(uuid.uuid4()).replace("-", "")[:32],
        "ADMIN_ENABLED": "true",
        "ADMIN_EMAIL": email,
        "HEIMDALL_PORT": "8085",
        "APP_MANAGER_PORT": "8086",
    }
    
    if tier == "starter":
        env["FREE_LIMIT"] = "10"
    elif tier == "pro":
        env["FREE_LIMIT"] = "25"
    elif tier == "power":
        env["FREE_LIMIT"] = "999"
    
    # Deploy via Coolify API
    headers = {"Authorization": f"Bearer {COOLIFY_TOKEN}"}
    
    async with httpx.AsyncClient() as client:
        # Create application on Coolify
        payload = {
            "project_uuid": "uuc85ypiss34ajm4qcjfeekx",
            "environment_name": "production",
            "application_type": "django",
            "application_name": f"appvault-{instance_id[:8]}",
            "application_fqdn": url,
            "domains": url,
            "git_repository": "https://github.com/Sectutor/appvault.git",
            "git_branch": "master",
            "build_pack": "dockercompose",
            "docker_compose_domains": {url: "app-manager"},
            "ports_exposes": "8085,8086",
            "env": env,
        }
        
        try:
            resp = await client.post(
                f"{COOLIFY_URL}/api/v1/applications",
                json=payload,
                headers=headers,
                timeout=30
            )
            if resp.status_code == 201:
                # Trigger deploy
                deploy_resp = await client.post(
                    f"{COOLIFY_URL}/api/v1/deploy",
                    json={"uuid": "uuc85ypiss34ajm4qcjfeekx", "force": True},
                    headers=headers,
                    timeout=30
                )
                return url
        except Exception as e:
            print(f"Provisioning error: {e}")
    
    return None

# ═══════════════════════════════════════════════
# STRIPE WEBHOOK
# ═══════════════════════════════════════════════

@app.post("/api/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe payment completion."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    # Verify webhook signature
    if STRIPE_WEBHOOK_SECRET:
        try:
            import stripe
            stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    # Parse event
    import json
    event = json.loads(payload)
    
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email") or session.get("customer_details", {}).get("email")
        metadata = session.get("metadata", {})
        instance_id = metadata.get("instance_id")
        tier = metadata.get("tier", "starter")
        
        if instance_id and email:
            # Update database
            db = get_db()
            db.execute(
                "UPDATE instances SET status = 'provisioning', stripe_session_id = ?, updated_at = ? WHERE id = ?",
                (session["id"], datetime.utcnow().isoformat(), instance_id)
            )
            db.commit()
            db.close()
            
            # Provision instance
            url = await provision_instance(instance_id, email, tier)
            
            if url:
                db = get_db()
                db.execute(
                    "UPDATE instances SET status = 'active', url = ?, updated_at = ? WHERE id = ?",
                    (url, datetime.utcnow().isoformat(), instance_id)
                )
                db.commit()
                db.close()
    
    return JSONResponse({"status": "ok"})

# ═══════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════

@app.get("/")
async def landing(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})

@app.get("/dashboard")
async def dashboard(request: Request, email: str = None):
    if not email:
        return templates.TemplateResponse("dashboard.html", {"request": request, "instances": []})
    
    db = get_db()
    instances = db.execute("SELECT * FROM instances WHERE email = ?", (email,)).fetchall()
    db.close()
    
    return templates.TemplateResponse("dashboard.html", {"request": request, "instances": instances})

@app.post("/api/checkout")
async def create_checkout(request: Request):
    """Create Stripe Checkout session."""
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    
    body = await request.json()
    tier = body.get("tier", "starter")
    email = body.get("email")
    
    prices = {
        "starter": "price_xxx_starter",  # Replace with actual Stripe price IDs
        "pro": "price_xxx_pro",
        "power": "price_xxx_power",
    }
    
    # Create instance record
    instance_id = str(uuid.uuid4())
    db = get_db()
    db.execute(
        "INSERT INTO instances (id, email, tier, status) VALUES (?, ?, ?, 'pending')",
        (instance_id, email, tier)
    )
    db.commit()
    db.close()
    
    # Create Stripe session
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": prices[tier], "quantity": 1}],
        mode="subscription",
        success_url=f"https://{DOMAIN}/dashboard?email={email}",
        cancel_url=f"https://{DOMAIN}",
        customer_email=email,
        metadata={"instance_id": instance_id, "tier": tier},
    )
    
    return JSONResponse({"url": session.url})

@app.get("/api/status/{instance_id}")
async def check_status(instance_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM instances WHERE id = ?", (instance_id,)).fetchone()
    db.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found")
    
    return {
        "id": row["id"],
        "status": row["status"],
        "url": row["url"],
        "tier": row["tier"],
        "created_at": row["created_at"],
    }

# ═══════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════

@app.get("/health")
async def health():
    return {"status": "ok"}
