"""
AppVault Cloud â€” Central Admin Server
Handles: agent registration, job queue, catalog management, admin panel, Stripe
"""

import os, uuid, json, sqlite3, hmac, hashlib, threading, time, subprocess, urllib.request, base64
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# CONFIG
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

CENTRAL_PORT = int(os.getenv("CENTRAL_PORT", "8000"))
CENTRAL_URL = os.getenv("CENTRAL_URL", f"http://central:{CENTRAL_PORT}")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "appvault-admin")
DB_PATH = os.getenv("DB_PATH", "/data/appvault.db")
CATALOG_PATH = os.getenv("CATALOG_PATH", "/app/static/catalog.json")
AGENT_POLL_SECONDS = int(os.getenv("AGENT_POLL_SECONDS", "30"))
AGENT_TIMEOUT_SECONDS = int(os.getenv("AGENT_TIMEOUT_SECONDS", "300"))

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# APP
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

app = FastAPI(title="AppVault Cloud")
templates = Jinja2Templates(directory="templates")

# Check Docker CLI availability (optional â€” used only for auto-import)
try:
    r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                       capture_output=True, text=True, timeout=10)
    DOCKER_AVAILABLE = r.returncode == 0
except:
    DOCKER_AVAILABLE = False
if DOCKER_AVAILABLE:
    print(f"[boot] Docker CLI available â€” auto-import enabled")
else:
    print(f"[boot] Docker CLI not available â€” auto-import disabled")

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DATABASE
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS instances (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            tier TEXT NOT NULL,
            stripe_session_id TEXT,
            status TEXT DEFAULT 'pending',
            url TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            os TEXT DEFAULT 'unknown',
            docker_version TEXT DEFAULT 'unknown',
            app_version TEXT DEFAULT 'unknown',
            ip_address TEXT,
            api_key TEXT UNIQUE,
            status TEXT DEFAULT 'offline',
            last_seen TEXT,
            registered_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS agent_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL,
            action TEXT NOT NULL,
            app_id TEXT NOT NULL,
            params TEXT DEFAULT '{}',
            status TEXT DEFAULT 'pending',
            result TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT,
            FOREIGN KEY (agent_id) REFERENCES agents(id)
        );
        CREATE TABLE IF NOT EXISTS catalog_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version INTEGER NOT NULL DEFAULT 1,
            published_at TEXT DEFAULT (datetime('now'))
        );
    """)
    # Ensure at least one catalog version exists
    row = db.execute("SELECT COUNT(*) as cnt FROM catalog_versions").fetchone()
    if row["cnt"] == 0:
        db.execute("INSERT INTO catalog_versions (version) VALUES (1)")
    db.commit()
    db.close()

init_db()

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# GLOBAL CATALOG
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

with open(CATALOG_PATH) as f:
    GLOBAL_CATALOG = json.load(f)

def get_catalog_version() -> int:
    db = get_db()
    row = db.execute("SELECT MAX(version) as v FROM catalog_versions").fetchone()
    db.close()
    return row["v"] if row and row["v"] else 1

def increment_catalog_version() -> int:
    db = get_db()
    db.execute("INSERT INTO catalog_versions (version) SELECT COALESCE(MAX(version), 0) + 1 FROM catalog_versions")
    db.commit()
    new_ver = db.execute("SELECT MAX(version) as v FROM catalog_versions").fetchone()["v"]
    db.close()
    return new_ver

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# AGENT AUTH
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def generate_api_key() -> str:
    return hashlib.sha256(f"{uuid.uuid4()}{time.time()}{os.urandom(16)}".encode()).hexdigest()[:32]

def verify_agent(agent_id: str, api_key: str) -> bool:
    if not agent_id or not api_key:
        return False
    db = get_db()
    row = db.execute("SELECT api_key FROM agents WHERE id = ? AND status != 'disabled'", (agent_id,)).fetchone()
    db.close()
    return row is not None and row["api_key"] == api_key

def require_admin(request: Request):
    """Verify admin credentials or raise 401 with WWW-Authenticate header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            import base64
            decoded = base64.b64decode(auth[6:]).decode()
            username, password = decoded.split(":", 1)
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                return True
        except:
            pass
    from fastapi.responses import JSONResponse
    raise JSONResponse(status_code=401, content={"detail": "Unauthorized"},
                       headers={"WWW-Authenticate": 'Basic realm="AppVault Admin"'})


@app.post("/api/agent/register")
async def agent_register(data: AgentRegister, request: Request):
    """Agent registers itself on startup. Returns API key."""
    agent_id = data.agent_id or str(uuid.uuid4())
    api_key = generate_api_key()
    ip = request.client.host if request.client else "unknown"
    
    db = get_db()
    existing = db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)).fetchone()
    
    if existing:
        # Re-register: update info, keep API key
        current_key = db.execute("SELECT api_key FROM agents WHERE id = ?", (agent_id,)).fetchone()["api_key"]
        db.execute("""
            UPDATE agents SET name=?, os=?, docker_version=?, app_version=?, ip_address=?, status='online', last_seen=datetime('now')
            WHERE id=?
        """, (data.name, data.os, data.docker_version, data.app_version, ip, agent_id))
        api_key = current_key
    else:
        db.execute("""
            INSERT INTO agents (id, name, os, docker_version, app_version, ip_address, api_key, status, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'online', datetime('now'))
        """, (agent_id, data.name, data.os, data.docker_version, data.app_version, ip, api_key))
    
    db.commit()
    db.close()
    return {"agent_id": agent_id, "api_key": api_key, "status": "registered"}

@app.post("/api/agent/heartbeat")
async def agent_heartbeat(request: Request):
    """Agent sends heartbeat to show it's alive."""
    body = await request.json()
    agent_id = body.get("agent_id")
    api_key = body.get("api_key")
    
    if not verify_agent(agent_id, api_key):
        raise HTTPException(status_code=401, detail="Invalid auth")
    
    db = get_db()
    db.execute("UPDATE agents SET status='online', last_seen=datetime('now') WHERE id=?", (agent_id,))
    db.commit()
    db.close()
    return {"status": "ok", "server_time": datetime.utcnow().isoformat()}

@app.get("/api/agent/jobs")
async def agent_get_jobs(agent_id: str = Query(...), api_key: str = Query(...)):
    """Agent polls for pending jobs."""
    if not verify_agent(agent_id, api_key):
        raise HTTPException(status_code=401, detail="Invalid auth")
    
    db = get_db()
    rows = db.execute(
        "SELECT id, action, app_id, params, created_at FROM agent_jobs WHERE agent_id=? AND status='pending' ORDER BY created_at ASC",
        (agent_id,)
    ).fetchall()
    db.close()
    
    jobs = []
    for row in rows:
        jobs.append({
            "id": row["id"],
            "action": row["action"],
            "app_id": row["app_id"],
            "params": json.loads(row["params"]) if row["params"] else {},
            "created_at": row["created_at"],
        })
    
    return {"jobs": jobs}

@app.post("/api/agent/jobs/{job_id}/status")
async def agent_update_job_status(job_id: int, data: JobStatusUpdate):
    """Agent reports job completion or failure."""
    if not verify_agent(data.agent_id, data.api_key):
        raise HTTPException(status_code=401, detail="Invalid auth")
    
    db = get_db()
    row = db.execute("SELECT id FROM agent_jobs WHERE id=? AND agent_id=?", (job_id, data.agent_id)).fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")
    
    db.execute(
        "UPDATE agent_jobs SET status=?, result=?, completed_at=datetime('now') WHERE id=?",
        (data.status, data.result, job_id)
    )
    db.commit()
    db.close()
    return {"status": "ok"}

@app.get("/api/agent/catalog/version")
async def agent_catalog_version(agent_id: str = Query(...), api_key: str = Query(...)):
    """Agent checks if catalog needs updating."""
    if not verify_agent(agent_id, api_key):
        raise HTTPException(status_code=401, detail="Invalid auth")
    
    version = get_catalog_version()
    return {"version": version}

@app.get("/api/agent/catalog")
async def agent_get_catalog(agent_id: str = Query(...), api_key: str = Query(...)):
    """Agent downloads latest catalog."""
    if not verify_agent(agent_id, api_key):
        raise HTTPException(status_code=401, detail="Invalid auth")
    
    version = get_catalog_version()
    return {"version": version, "apps": GLOBAL_CATALOG.get("apps", [])}

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ADMIN ENDPOINTS (protected, not for distribution)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Admin dashboard â€” list agents, jobs, catalog."""
    require_admin(request)
    db = get_db()
    agents = db.execute("SELECT * FROM agents ORDER BY last_seen DESC").fetchall()
    jobs = db.execute("""
        SELECT j.*, a.name as agent_name FROM agent_jobs j
        LEFT JOIN agents a ON j.agent_id = a.id
        ORDER BY j.created_at DESC LIMIT 100
    """).fetchall()
    db.close()
    
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "agents": [dict(a) for a in agents],
        "jobs": [dict(j) for j in jobs],
        "catalog": GLOBAL_CATALOG,
        "catalog_version": get_catalog_version(),
    })

@app.post("/admin/agents/{agent_id}/jobs")
async def admin_push_job(agent_id: str, request: Request):
    """Admin pushes an install/uninstall job to a specific agent."""
    body = await request.json()
    action = body.get("action", "install")
    app_id = body.get("app_id", "")
    params = body.get("params", {})
    
    if action not in ("install", "uninstall", "restart"):
        raise HTTPException(status_code=400, detail="Invalid action")
    if not app_id:
        raise HTTPException(status_code=400, detail="app_id required")
    
    db = get_db()
    # Verify agent exists
    agent = db.execute("SELECT id FROM agents WHERE id=?", (agent_id,)).fetchone()
    if not agent:
        db.close()
        raise HTTPException(status_code=404, detail="Agent not found")
    
    cur = db.cursor()
    cur.execute(
        "INSERT INTO agent_jobs (agent_id, action, app_id, params, status) VALUES (?, ?, ?, ?, 'pending')",
        (agent_id, action, app_id, json.dumps(params))
    )
    job_id = cur.lastrowid
    db.commit()
    db.close()
    
    return {"job_id": job_id, "status": "queued", "agent_id": agent_id, "action": action, "app_id": app_id}

@app.get("/admin/agents/{agent_id}", response_class=HTMLResponse)
async def admin_agent_detail(agent_id: str, request: Request):
    """Admin views agent details and job history."""
    db = get_db()
    agent = db.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
    if not agent:
        db.close()
        raise HTTPException(status_code=404, detail="Agent not found")
    
    jobs = db.execute(
        "SELECT * FROM agent_jobs WHERE agent_id=? ORDER BY created_at DESC LIMIT 50",
        (agent_id,)
    ).fetchall()
    installed = db.execute(
        "SELECT app_id, status FROM agent_jobs WHERE agent_id=? AND action='install' AND status='completed' GROUP BY app_id ORDER BY completed_at DESC",
        (agent_id,)
    ).fetchall()
    db.close()
    
    return templates.TemplateResponse("admin_agent.html", {
        "request": request,
        "agent": dict(agent),
        "catalog": GLOBAL_CATALOG,
        "jobs": [dict(j) for j in jobs],
        "installed": [dict(i) for i in installed],
    })

@app.post("/admin/catalog/apps")
async def admin_add_app(request: Request):
    """Admin adds an app to the global catalog."""
    require_admin(request)
    body = await request.json()
    is_stack = body.get("is_stack", False) or body.get("type") == "stack"
    app_entry = {
        "id": body.get("id"),
        "name": body.get("name"),
        "description": body.get("description", ""),
        "image": body.get("image", ""),
        "container_port": body.get("container_port"),
        "volumes": body.get("volumes", []),
        "env": body.get("env", []),
        "category": body.get("category", "other"),
        "min_ram_mb": body.get("min_ram_mb", 256),
    }
    
    if is_stack:
        app_entry["type"] = "stack"
        app_entry["is_stack"] = True
        if body.get("compose_url"):
            app_entry["compose_url"] = body["compose_url"]
        if body.get("services"):
            app_entry["services"] = body["services"]
        app_entry["image"] = ""  # Stacks don't need an image
    
    if not app_entry["id"] or not app_entry["name"]:
        raise HTTPException(status_code=400, detail="id and name are required")
    if not is_stack and not app_entry.get("image"):
        raise HTTPException(status_code=400, detail="image is required for non-stack apps")
    
    # Check for duplicate
    for existing in GLOBAL_CATALOG.get("apps", []):
        if existing["id"] == app_entry["id"]:
            raise HTTPException(status_code=409, detail=f"App '{app_entry['id']}' already exists")
    
    GLOBAL_CATALOG.setdefault("apps", []).append(app_entry)
    
    # Persist to disk
    with open(CATALOG_PATH, "w") as f:
        json.dump(GLOBAL_CATALOG, f, indent=2)
    
    new_version = increment_catalog_version()
    
    return {"status": "added", "app_id": app_entry["id"], "new_catalog_version": new_version}

@app.delete("/admin/catalog/apps/{app_id}")
async def admin_remove_app(app_id: str, request: Request):
    """Admin removes an app from the global catalog."""
    require_admin(request)
    before = len(GLOBAL_CATALOG.get("apps", []))
    GLOBAL_CATALOG["apps"] = [a for a in GLOBAL_CATALOG.get("apps", []) if a["id"] != app_id]
    after = len(GLOBAL_CATALOG["apps"])
    
    if before == after:
        raise HTTPException(status_code=404, detail=f"App '{app_id}' not found")
    
    with open(CATALOG_PATH, "w") as f:
        json.dump(GLOBAL_CATALOG, f, indent=2)
    
    new_version = increment_catalog_version()
    return {"status": "removed", "app_id": app_id, "new_catalog_version": new_version}

@app.post("/admin/catalog/apps/{app_id}/education")
async def admin_update_education(app_id: str, request: Request):
    """Admin updates education data (video_url, etc.) for an app."""
    require_admin(request)
    data = await request.json()
    
    # Find and update the app in the global catalog
    for a in GLOBAL_CATALOG.get("apps", []):
        if a["id"] == app_id:
            if "education" not in a:
                a["education"] = {}
            for key, val in data.items():
                a["education"][key] = val
            # Persist to disk (same pattern as admin_add_app)
            with open(CATALOG_PATH, "w") as f:
                json.dump(GLOBAL_CATALOG, f, indent=2)
            new_version = increment_catalog_version()
            return {"status": "updated", "app_id": app_id, "new_catalog_version": new_version}
    
    return {"error": "App not found"}, 404

@app.post("/admin/catalog/publish")
async def admin_publish_catalog(request: Request):
    require_admin(request)
    """Force publish a new catalog version (agents will pick it up)."""
    new_version = increment_catalog_version()
    return {"status": "published", "new_catalog_version": new_version}

@app.post("/admin/agents/{agent_id}/touch")
async def admin_touch_agent(agent_id: str):
    """Mark an agent as online (for testing without real agent)."""
    db = get_db()
    db.execute("UPDATE agents SET status='online', last_seen=datetime('now') WHERE id=?", (agent_id,))
    db.commit()
    db.close()
    return {"status": "touched", "agent_id": agent_id}

@app.post("/api/agent/ping")
async def agent_ping(request: Request):
    """Simple ping endpoint for agent connectivity test."""
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    return {
        "status": "pong",
        "server_time": datetime.utcnow().isoformat(),
        "catalog_version": get_catalog_version(),
        "catalog_apps": len(GLOBAL_CATALOG.get("apps", [])),
    }

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# BACKGROUND: Mark stale agents as offline
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def stale_agent_watcher():
    while True:
        try:
            db = get_db()
            cutoff = (datetime.utcnow() - timedelta(seconds=AGENT_TIMEOUT_SECONDS)).isoformat()
            db.execute("UPDATE agents SET status='offline' WHERE last_seen < ? AND status='online'", (cutoff,))
            db.commit()
            db.close()
        except Exception as e:
            print(f"[stale_watcher] Error: {e}")
        time.sleep(60)

threading.Thread(target=stale_agent_watcher, daemon=True).start()

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# STRIPE / PROVISIONING (existing)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

COOLIFY_URL = os.getenv("COOLIFY_URL", "http://169.58.9.191:8000")
COOLIFY_TOKEN = os.getenv("COOLIFY_TOKEN", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
DOMAIN = os.getenv("DOMAIN", "appvault.airepoindex.com")

async def provision_coolify(instance_id: str, email: str, tier: str) -> Optional[str]:
    """Deploy AppVault on Coolify and return the URL."""
    import httpx
    subdomain = email.split("@")[0].lower().replace(".", "-").replace("_", "-")
    subdomain = f"{subdomain}-{instance_id[:6]}"
    url = f"https://{subdomain}.{DOMAIN}"
    
    env = {
        "API_KEY": str(uuid.uuid4()).replace("-", "")[:32],
        "ADMIN_ENABLED": "true",
        "ADMIN_EMAIL": email,
        "HEIMDALL_PORT": "8085",
        "APP_MANAGER_PORT": "8086",
    }
    tier_limits = {"starter": "10", "pro": "25", "power": "999"}
    env["FREE_LIMIT"] = tier_limits.get(tier, "10")
    
    headers = {"Authorization": f"Bearer {COOLIFY_TOKEN}"}
    
    async with httpx.AsyncClient() as client:
        try:
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
            resp = await client.post(f"{COOLIFY_URL}/api/v1/applications", json=payload, headers=headers, timeout=30)
            if resp.status_code == 201:
                await client.post(f"{COOLIFY_URL}/api/v1/deploy", json={"uuid": "uuc85ypiss34ajm4qcjfeekx", "force": True}, headers=headers, timeout=30)
                return url
        except Exception as e:
            print(f"Provisioning error: {e}")
    return None

@app.post("/api/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe payment completion."""
    import json as json_lib
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    if STRIPE_WEBHOOK_SECRET:
        try:
            import stripe
            stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    event = json_lib.loads(payload)
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email") or session.get("customer_details", {}).get("email")
        metadata = session.get("metadata", {})
        instance_id = metadata.get("instance_id")
        tier = metadata.get("tier", "starter")
        
        if instance_id and email:
            db = get_db()
            db.execute("UPDATE instances SET status='provisioning', stripe_session_id=?, updated_at=datetime('now') WHERE id=?", (session["id"], instance_id))
            db.commit()
            db.close()
            
            url = await provision_coolify(instance_id, email, tier)
            if url:
                db = get_db()
                db.execute("UPDATE instances SET status='active', url=?, updated_at=datetime('now') WHERE id=?", (url, instance_id))
                db.commit()
                db.close()
    
    return JSONResponse({"status": "ok"})

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
    prices = {"starter": "price_xxx_starter", "pro": "price_xxx_pro", "power": "price_xxx_power"}
    
    instance_id = str(uuid.uuid4())
    db = get_db()
    db.execute("INSERT INTO instances (id, email, tier, status) VALUES (?, ?, ?, 'pending')", (instance_id, email, tier))
    db.commit()
    db.close()
    
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
    return {"id": row["id"], "status": row["status"], "url": row["url"], "tier": row["tier"], "created_at": row["created_at"]}

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# AUTO-IMPORT APP FROM GITHUB
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

GITHUB_API = "https://api.github.com"
CONTAINER_REGISTRIES = {
    "ghcr.io": "ghcr.io/%s/%s:latest",
    "docker.io": "docker.io/%s/%s:latest",
}

def parse_docker_compose_services(content):
    """Parse a docker-compose.yml and extract service info."""
    import yaml
    try:
        compose = yaml.safe_load(content)
    except:
        return []
    
    services = []
    for name, svc in (compose.get("services", {}) or {}).items():
        info = {"name": name, "ports": [], "image": "", "env": [], "volumes": [], "build": False}
        
        # Detect ports
        ports = svc.get("ports", [])
        for p in ports:
            if isinstance(p, str) and ":" in p:
                host_port, container_port = p.split(":")[0], p.split(":")[1]
                info["ports"].append({"host": host_port.strip(), "container": container_port.strip()})
            elif isinstance(p, (int, str)):
                info["ports"].append({"host": str(p), "container": str(p)})
        
        # Detect image or build
        if svc.get("image"):
            info["image"] = svc["image"]
        if svc.get("build"):
            info["build"] = True
        
        # Detect env vars (from environment: section)
        env_dict = svc.get("environment", {}) or {}
        if isinstance(env_dict, dict):
            for k, v in env_dict.items():
                if v:
                    info["env"].append(f"{k}={v}")
        
        # Detect volumes
        vols = svc.get("volumes", []) or []
        for v in vols:
            if isinstance(v, str) and ":" in v:
                info["volumes"].append(v)
        
        # Detect profiles (optional services)
        profiles = svc.get("profiles", []) or []
        if profiles:
            info["profiles"] = profiles
            info["optional"] = True
        
        services.append(info)
    
    return services

@app.post("/admin/catalog/auto-import")
async def admin_auto_import(request: Request):
    """
    Auto-detect app configuration from a GitHub repo URL or Docker image name.
    Accepts: {"url": "https://github.com/user/repo"} or {"image": "user/app:tag"}
    Returns a generated catalog entry that can be reviewed and added.
    """
    body = await request.json()
    url = body.get("url", "")
    image_name = body.get("image", "")
    
    result = {"source_url": url or "", "image": image_name or "", "is_stack": False}
    user_repo = None
    
    if url and "github.com" in url:
        parts = url.rstrip("/").split("/")
        if len(parts) >= 2:
            user_repo = "/".join(parts[-2:])
    
    # Step 1: Check if this is a docker-compose stack first
    is_stack = False
    services = []
    if user_repo and url:
        try:
            # Check for docker-compose.yml in the repo
            api = f"{GITHUB_API}/repos/{user_repo}/contents/docker-compose.yml"
            req = urllib.request.Request(api, headers={"User-Agent": "AppVault"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                if data.get("content"):
                    import base64
                    compose_content = base64.b64decode(data["content"]).decode()
                    services = parse_docker_compose_services(compose_content)
                    if services:
                        is_stack = True
                        result["is_stack"] = True
                        result["services"] = services
        except:
            pass
    
    # Step 2: Try to pull a pre-built image (if not a stack)
    if not is_stack and image_name:
        try:
            r = subprocess.run(
                ["docker", "pull", image_name],
                capture_output=True, text=True, timeout=120
            )
            if r.returncode != 0:
                alt_image = image_name.replace("ghcr.io/", "docker.io/")
                r = subprocess.run(
                    ["docker", "pull", alt_image],
                    capture_output=True, text=True, timeout=120
                )
                if r.returncode == 0:
                    image_name = alt_image
                    result["image"] = alt_image
                else:
                    if "/" in image_name:
                        parts = image_name.split("/")
                        simple = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
                        r = subprocess.run(
                            ["docker", "pull", simple],
                            capture_output=True, text=True, timeout=120
                        )
                        if r.returncode == 0:
                            image_name = simple
                            result["image"] = simple
                        else:
                            return {"error": f"Image '{image_name}' not found anywhere"}, 404
                    else:
                        return {"error": f"Image '{image_name}' not found"}, 404
        except subprocess.TimeoutExpired:
            return {"error": "Image pull timed out (>120s)"}, 408
    
    # Step 3: Build the entry (stack or single image)
    if is_stack:
        # Stack mode: use docker-compose info
        # Use the first service's main port for the launch URL
        main_port = "3000"
        all_ports = []
        all_env = []
        all_volumes = []
        for svc in services:
            for p in svc.get("ports", []):
                all_ports.append(p["host"])
                if not main_port or main_port == "3000":
                    main_port = p["host"]
            all_env.extend(svc.get("env", []))
            all_volumes.extend(svc.get("volumes", []))
        
        ports = [int(p) for p in all_ports if p.isdigit()] or [3000]
        result["container_port"] = ports[0]
        result["detected_ports"] = all_ports
        result["env"] = all_env
        result["volumes"] = all_volumes
        result["compose_url"] = f"https://raw.githubusercontent.com/{user_repo}/main/docker-compose.yml"
        config = {}  # No image to inspect for stacks
    else:
        # Single image mode: inspect the image
        try:
            r = subprocess.run(
                ["docker", "image", "inspect", image_name],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode != 0:
                return {"error": "Failed to inspect image"}, 500
            img = json.loads(r.stdout)[0]
        except:
            return {"error": "Failed to parse image metadata"}, 500
        
        config = img.get("Config", {})
        
        exposed_ports = config.get("ExposedPorts", {})
        ports = []
        for p in exposed_ports.keys():
            port_num = p.split("/")[0]
            if port_num.isdigit():
                ports.append(int(port_num))
        
        if not ports:
            ports = [80, 3000, 8080, 5000, 8000, 20128]
        
        main_port = ports[0]
        result["container_port"] = main_port
        result["detected_ports"] = ports
        
        env = config.get("Env", [])
        useful_env = []
        for e in env:
            if "=" in e:
                key = e.split("=")[0]
                val = e.split("=", 1)[1]
                skip_patterns = ["PATH=", "NODE_", "YARN_", "NPM_", "DEBIAN_", "HOME=", 
                               "LANG=", "TERM=", "TZ=", "LC_", "PYTHON", "JAVA_",
                               "SSL_", "GPG_", "APK_", "NGINX_"]
                if not any(key.startswith(p.rstrip("*").rstrip("=")) for p in skip_patterns):
                    if not any(placeholder in val.lower() for placeholder in 
                             ["your_", "changeme", "example.com", "your-domain"]):
                        useful_env.append(e)
        result["env"] = useful_env
        
        vols_config = config.get("Volumes", {})
        result["volumes"] = list(vols_config.keys())
    
    # Step 7: Determine app name and ID
    repo_short = image_name.split("/")[-1].split(":")[0] if "/" in image_name else image_name.split(":")[0]
    app_id = repo_short.lower().replace("_", "-").replace(".", "")
    app_name = repo_short.replace("-", " ").title()
    
    # Try to get better name from GitHub API
    if url and "github.com" in url:
        try:
            parts = url.rstrip("/").split("/")
            user, repo = parts[-2], parts[-1]
            api_url = f"{GITHUB_API}/repos/{user}/{repo}"
            req = urllib.request.Request(api_url, headers={"User-Agent": "AppVault"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                gh_data = json.loads(resp.read())
                # Use the repo name, not description
                if gh_data.get("name"):
                    app_name = gh_data["name"].replace("-", " ").replace("_", " ").title()
                result["description"] = (gh_data.get("description", "") or "")[:200]
                result["github_stars"] = gh_data.get("stargazers_count", 0)
                result["docs_url"] = f"{url}#readme"
        except:
            pass
    
    # Fix ID for stacks (no image name to derive from)
    if is_stack and not app_id and user_repo:
        app_id = user_repo.split("/")[-1].lower()
    result["id"] = app_id
    result["name"] = app_name
    result["category"] = auto_detect_category(app_name, result.get("description", ""), ports)
    result["min_ram_mb"] = auto_detect_ram(config)
    
    # Step 8: Generate education data
    result["education"] = {
        "docs_url": result.get("docs_url") or (f"https://github.com/{'/'.join(image_name.split('/')[:2])}#readme" if url else ""),
        "quick_start": f"{app_name} runs on port {main_port}. After install, open the URL and follow the app's setup wizard." if ports else f"{app_name} has been installed and is running.",
        "setup_steps": [
            f"Open http://localhost:{main_port}/ in your browser",
            "Follow the on-screen setup wizard",
            "Configure the app for your needs"
        ]
    }
    
    return result

def auto_detect_category(name, description, ports):
    """Guess the best category based on name, description, and ports."""
    text = (name + " " + description).lower()
    
    if any(w in text for w in ["ai", "llm", "agent", "chat", "gpt", "llama", "ollama", "openai", "model"]):
        return "ai"
    if any(w in text for w in ["database", "db", "postgres", "mysql", "mariadb", "redis", "sql"]):
        return "database"
    if any(w in text for w in ["media", "video", "music", "photo", "movie", "tv", "stream", "podcast", "jellyfin"]):
        return "media"
    if any(w in text for w in ["automation", "workflow", "n8n", "node-red", "zapier", "trigger"]):
        return "automation"
    if any(w in text for w in ["git", "dev", "code", "ide", "vscode", "server", "portainer", "ci/cd", "docker"]):
        return "development"
    if any(w in text for w in ["network", "proxy", "vpn", "dns", "router", "firewall", "adblock", "pihole", "traefik"]):
        return "networking"
    if any(w in text for w in ["wiki", "doc", "note", "book", "blog", "cms", "wordpress", "file", "cloud", "sync"]):
        return "productivity"
    if any(w in text for w in ["password", "vault", "auth", "identity", "sso"]):
        return "networking"
    
    return "productivity"  # Default

def auto_detect_ram(config):
    """Estimate minimum RAM based on image layers and base OS."""
    # Default to 256MB, which covers most small web apps
    return 256

@app.get("/health")
async def health():
    db = get_db()
    online = db.execute("SELECT COUNT(*) as cnt FROM agents WHERE status='online'").fetchone()["cnt"]
    db.close()
    return {"status": "ok", "agents_online": online, "catalog_version": get_catalog_version(), "catalog_apps": len(GLOBAL_CATALOG.get("apps", []))}
