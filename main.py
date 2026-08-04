"""
AppVault Cloud â€” Central Admin Server
Handles: agent registration, job queue, catalog management, admin panel, Stripe
"""

import os, uuid, json, sqlite3, hmac, hashlib, threading, time, subprocess, urllib.request, base64
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from itsdangerous import URLSafeTimedSerializer

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# CONFIG
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

CENTRAL_PORT = int(os.getenv("CENTRAL_PORT", "8000"))
CENTRAL_URL = os.getenv("CENTRAL_URL", f"http://central:{CENTRAL_PORT}")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "appvault-admin")
DB_PATH = os.getenv("DB_PATH", "/data/appvault.db")
CATALOG_PATH = os.getenv("CATALOG_PATH", "/app/static/catalog.json")
COMPOSE_DIR = os.getenv("COMPOSE_DIR", os.path.join(os.path.dirname(DB_PATH), "compose"))
AGENT_POLL_SECONDS = int(os.getenv("AGENT_POLL_SECONDS", "30"))
AGENT_TIMEOUT_SECONDS = int(os.getenv("AGENT_TIMEOUT_SECONDS", "300"))
PAID_LICENSE_KEYS = {k.strip() for k in os.getenv("PAID_LICENSE_KEYS", "").split(",") if k.strip()}

def license_is_valid(key: str) -> bool:
    """A license is valid if in PAID_LICENSE_KEYS env or an active row in licenses."""
    if not key:
        return False
    if key in PAID_LICENSE_KEYS:
        return True
    try:
        db = get_db()
        row = db.execute("SELECT status FROM licenses WHERE key = ?", (key,)).fetchone()
        db.close()
        return row is not None and row["status"] == "active"
    except Exception:
        return False

def generate_license_key() -> str:
    import random
    grp = lambda: "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=4))
    return "APPVAULT-" + "-".join(grp() for _ in range(4))


def bind_license_to_agent(license_key, agent_id):
    """Bind a license key to exactly one server (agent). Returns (plan, note).

    Rules: a license is valid for the agent it is bound to; the first agent to
    activate it claims it; any other agent using the same key is treated as free.
    """
    if not license_key:
        return "free", "no license"
    if license_key in PAID_LICENSE_KEYS:
        return "paid", "env license"
    db = get_db()
    row = db.execute("SELECT status, bound_agent_id FROM licenses WHERE key = ?", (license_key,)).fetchone()
    if not row:
        db.close()
        return "free", "unknown license"
    if row["status"] not in ("active", "grace_period"):
        db.close()
        return "free", "license not active"
    if not row["bound_agent_id"]:
        db.execute("UPDATE licenses SET bound_agent_id=?, activated_at=datetime('now') WHERE key=?",
                   (agent_id, license_key))
        db.commit()
        db.close()
        _audit("license.bound", f"{license_key[:16]} -> agent {agent_id[:8]}")
        return "paid", "bound"
    if row["bound_agent_id"] == agent_id:
        db.close()
        return "paid", "same agent"
    db.close()
    _audit("license.overuse", f"{license_key[:16]} agent {agent_id[:8]} vs bound {row['bound_agent_id'][:8]}")
    return "free", "license bound to another server"

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# APP
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

app = FastAPI(title="AppVault Cloud")
templates = Jinja2Templates(directory="templates")

# Session-based admin login (signed cookie)
SESSION_SECRET = os.getenv("SESSION_SECRET", ADMIN_PASSWORD + "-appvault-session")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=60*60*24*30, same_site="lax")

# Short-lived signed tokens for dashboard links (license key never sits in a URL)
_dash_serializer = URLSafeTimedSerializer(SESSION_SECRET)

def _make_dashboard_token(license_key: str) -> str:
    """Sign a license key for a dashboard link (expires via max_age on load)."""
    return _dash_serializer.dumps(license_key)

def _read_dashboard_token(token: str, max_age: int = 7 * 24 * 3600) -> str:
    """Resolve a signed dashboard token back to the license key, or '' if invalid/expired."""
    try:
        return _dash_serializer.loads(token, max_age=max_age) or ""
    except Exception:
        return ""

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
        CREATE TABLE IF NOT EXISTS licenses (
            key TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            tier TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            stripe_session_id TEXT,
            bound_agent_id TEXT DEFAULT '',
            activated_at TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    # Ensure at least one catalog version exists
    row = db.execute("SELECT COUNT(*) as cnt FROM catalog_versions").fetchone()
    if row["cnt"] == 0:
        db.execute("INSERT INTO catalog_versions (version) VALUES (1)")
    # Migration: plan / license_key columns on agents
    cols = [r[1] for r in db.execute("PRAGMA table_info(agents)").fetchall()]
    if "plan" not in cols:
        db.execute("ALTER TABLE agents ADD COLUMN plan TEXT DEFAULT 'free'")
    if "license_key" not in cols:
        db.execute("ALTER TABLE agents ADD COLUMN license_key TEXT DEFAULT ''")
    # Migration: stripe customer/subscription ids on licenses + instances
    lcols = [r[1] for r in db.execute("PRAGMA table_info(licenses)").fetchall()]
    if "stripe_customer_id" not in lcols:
        db.execute("ALTER TABLE licenses ADD COLUMN stripe_customer_id TEXT DEFAULT ''")
    if "stripe_subscription_id" not in lcols:
        db.execute("ALTER TABLE licenses ADD COLUMN stripe_subscription_id TEXT DEFAULT ''")
    if "bound_agent_id" not in lcols:
        db.execute("ALTER TABLE licenses ADD COLUMN bound_agent_id TEXT DEFAULT ''")
    if "activated_at" not in lcols:
        db.execute("ALTER TABLE licenses ADD COLUMN activated_at TEXT DEFAULT ''")
    if "canceled_at" not in lcols:
        db.execute("ALTER TABLE licenses ADD COLUMN canceled_at TEXT DEFAULT ''")
    if "grace_ends_at" not in lcols:
        db.execute("ALTER TABLE licenses ADD COLUMN grace_ends_at TEXT DEFAULT ''")
    icols = [r[1] for r in db.execute("PRAGMA table_info(instances)").fetchall()]
    if "stripe_customer_id" not in icols:
        db.execute("ALTER TABLE instances ADD COLUMN stripe_customer_id TEXT DEFAULT ''")
    if "stripe_subscription_id" not in icols:
        db.execute("ALTER TABLE instances ADD COLUMN stripe_subscription_id TEXT DEFAULT ''")
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

# ---- Login rate limiting + audit log (brute-force protection) ----
RATE_LIMIT_WINDOW = 300   # 5 minutes
RATE_LIMIT_MAX = 10       # max login attempts per IP per window
_login_attempts = {}
_login_lock = threading.Lock()
AUDIT_LOG = os.environ.get("AUDIT_LOG", "/data/audit.log")

def _audit(action, detail=""):
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {action} {detail}\n")
    except Exception:
        pass

def _check_login_rate(client_ip):
    now = time.time()
    with _login_lock:
        ts = [t for t in _login_attempts.get(client_ip, []) if now - t < RATE_LIMIT_WINDOW]
        if len(ts) >= RATE_LIMIT_MAX:
            return False
        return True

def _record_login(client_ip, ok):
    now = time.time()
    with _login_lock:
        ts = [t for t in _login_attempts.get(client_ip, []) if now - t < RATE_LIMIT_WINDOW]
        ts.append(now)
        _login_attempts[client_ip] = ts
    _audit("login", f"{'ok' if ok else 'FAILED'} ip={client_ip}")

def require_admin(request: Request):
    """Verify admin via session cookie or Basic auth."""
    # 1) Session cookie (set by /login page)
    if request.session.get("admin"):
        return True
    # 2) Basic auth (API clients / curl)
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
    # 3) Browser request -> redirect to login page
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        raise HTTPException(status_code=303, headers={"Location": "/login?next=/admin"})
    raise HTTPException(status_code=401, detail="Unauthorized",
                        headers={"WWW-Authenticate": 'Basic realm="AppVault Admin"'})


def get_agent_plan(agent_id):
    """Get agent's plan, respecting grace period.

    Grace period: when a subscription is canceled, the agent keeps 'paid' for
    14 days (grace_ends_at), then drops to 'free'. Running containers are never
    touched — enforcement is at the install/update layer only.
    """
    db = get_db()
    row = db.execute("SELECT plan, license_key FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if not row or not row["plan"]:
        db.close()
        return "free"
    if row["plan"] == "free":
        db.close()
        return "free"
    # Agent is 'paid' — check if the license is still active or in grace period
    if row["license_key"]:
        lic = db.execute("SELECT status, grace_ends_at FROM licenses WHERE key = ?", (row["license_key"],)).fetchone()
        if not lic:
            db.close()
            return "free"
        if lic["status"] == "active":
            db.close()
            return "paid"
        if lic["status"] == "grace_period" and lic["grace_ends_at"]:
            # Check if grace period has expired
            try:
                from datetime import datetime
                grace_end = datetime.fromisoformat(lic["grace_ends_at"])
                if datetime.utcnow() < grace_end:
                    db.close()
                    return "paid"
                else:
                    # Grace period expired — downgrade now
                    db.execute("UPDATE agents SET plan='free' WHERE id=?", (agent_id,))
                    db.commit()
                    db.close()
                    _audit("agent.grace_expired", f"agent {agent_id[:8]} -> free")
                    return "free"
            except Exception:
                db.close()
                return "paid"
        # License revoked or other status
        if lic["status"] != "active":
            db.execute("UPDATE agents SET plan='free' WHERE id=?", (agent_id,))
            db.commit()
            db.close()
            return "free"
    db.close()
    return row["plan"] if row["plan"] else "free"

def set_agent_plan(agent_id, plan):
    db = get_db()
    db.execute("UPDATE agents SET plan=? WHERE id=?", (plan, agent_id))
    db.commit()
    db.close()

class AgentRegister(BaseModel):
    agent_id: Optional[str] = None
    name: str
    os: str = "unknown"
    docker_version: str = "unknown"
    app_version: str = "unknown"
    license_key: Optional[str] = None

class JobStatusUpdate(BaseModel):
    agent_id: str
    api_key: str
    status: str
    result: Optional[str] = None

@app.post("/api/agent/register")
async def agent_register(data: AgentRegister, request: Request):
    """Agent registers itself on startup. Returns API key."""
    agent_id = data.agent_id or str(uuid.uuid4())
    api_key = generate_api_key()
    ip = request.client.host if request.client else "unknown"
    
    db = get_db()
    existing = db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)).fetchone()
    
    if existing:
        # Re-register: update info, keep API key; plan follows license binding
        current_key = db.execute("SELECT api_key FROM agents WHERE id = ?", (agent_id,)).fetchone()["api_key"]
        plan, _ = bind_license_to_agent(data.license_key or "", agent_id)
        db.execute("""
            UPDATE agents SET name=?, os=?, docker_version=?, app_version=?, ip_address=?, plan=?, license_key=?, status='online', last_seen=datetime('now')
            WHERE id=?
        """, (data.name, data.os, data.docker_version, data.app_version, ip, plan, data.license_key or "", agent_id))
        api_key = current_key
    else:
        plan, _ = bind_license_to_agent(data.license_key or "", agent_id)
        db.execute("""
            INSERT INTO agents (id, name, os, docker_version, app_version, ip_address, api_key, plan, license_key, status, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'online', datetime('now'))
        """, (agent_id, data.name, data.os, data.docker_version, data.app_version, ip, api_key, plan, data.license_key or ""))
    
    db.commit()
    db.close()
    return {"agent_id": agent_id, "api_key": api_key, "status": "registered"}

@app.post("/api/agent/heartbeat")
async def agent_heartbeat(request: Request):
    """Agent sends heartbeat to show it's alive. Also refreshes plan (grace period check)."""
    body = await request.json()
    agent_id = body.get("agent_id")
    api_key = body.get("api_key")
    
    if not verify_agent(agent_id, api_key):
        raise HTTPException(status_code=401, detail="Invalid auth")
    
    # Refresh plan — handles grace period expiration on the agent record
    current_plan = get_agent_plan(agent_id)
    
    db = get_db()
    db.execute("UPDATE agents SET status='online', last_seen=datetime('now') WHERE id=?", (agent_id,))
    db.commit()
    db.close()
    return {"status": "ok", "server_time": datetime.utcnow().isoformat(), "plan": current_plan}

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
    plan = get_agent_plan(agent_id)
    return {"version": version, "plan": plan}

def _app_published(a):
    """An app is published (sent to clients) unless explicitly unpublished/disabled."""
    if a.get("published") is False:
        return False
    if a.get("disabled"):
        return False
    return True

@app.get("/api/agent/catalog")
async def agent_get_catalog(agent_id: str = Query(...), api_key: str = Query(...)):
    """Agent downloads latest catalog."""
    if not verify_agent(agent_id, api_key):
        raise HTTPException(status_code=401, detail="Invalid auth")
    
    version = get_catalog_version()
    plan = get_agent_plan(agent_id)
    # Unpublished/disabled apps are NEVER sent to any client (free or paid).
    published = [a for a in GLOBAL_CATALOG.get("apps", []) if _app_published(a)]
    if plan == "paid":
        apps = [a for a in published if (not a.get("hidden")) or str(a.get("id", "")).startswith("central-")]
    else:
        # Free agents: show free apps + PREMIUM apps marked as locked (for upsell UX).
        apps = []
        for a in published:
            if a.get("hidden") and not str(a.get("id", "")).startswith("central-"):
                continue
            if a.get("free_tier"):
                apps.append(a)
            else:
                locked = dict(a)
                locked["locked"] = True
                locked["requires_paid"] = True
                locked["status"] = "locked"
                apps.append(locked)
    return {"version": version, "plan": plan, "apps": apps}

@app.get("/api/agent/compose/{app_id}")
async def agent_get_compose(app_id: str):
    """Serve a catalog stack app's docker-compose.yml hosted by central.

    ADDITIVE: only used by stack apps whose catalog `compose_url` points here
    (e.g. `http://central:8000/api/agent/compose/twenty`). No existing routes
    or behavior are changed.
    """
    import os as _os
    safe = app_id.replace("/", "").replace("..", "").strip()
    if not safe:
        raise HTTPException(status_code=404, detail="Not found")
    path = _os.path.join(COMPOSE_DIR, safe + ".yml")
    if not _os.path.exists(path):
        return JSONResponse({"error": "compose not found"}, status_code=404)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return Response(content=content, media_type="text/yaml")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ADMIN ENDPOINTS (protected, not for distribution)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/admin"):
    """Admin login page."""
    if request.session.get("admin"):
        return RedirectResponse(next, status_code=303)
    return templates.TemplateResponse(request, "login.html", {"request": request, "next": next, "error": None})

@app.post("/login")
async def login_submit(request: Request):
    """Validate admin credentials, set session cookie."""
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")
    next_url = form.get("next", "/admin")
    # Real client IP: behind Caddy all requests share the bridge IP, so use X-Forwarded-For (last hop = appended by Caddy)
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        client_ip = xff.split(",")[-1].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"
    if not _check_login_rate(client_ip):
        _audit("login", f"RATE-LIMITED ip={client_ip}")
        return templates.TemplateResponse(request, "login.html", {
            "request": request, "next": next_url,
            "error": "Too many login attempts — try again in a few minutes"
        })
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        _record_login(client_ip, True)
        request.session["admin"] = True
        return RedirectResponse(next_url, status_code=303)
    _record_login(client_ip, False)
    return templates.TemplateResponse(request, "login.html", {
        "request": request, "next": next_url, "error": "Invalid credentials"
    })

@app.get("/logout")
async def logout(request: Request):
    """Clear admin session."""
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Admin dashboard — list agents, jobs, catalog."""
    require_admin(request)
    db = get_db()
    agents = db.execute("SELECT * FROM agents ORDER BY last_seen DESC").fetchall()
    jobs = db.execute("""
        SELECT j.*, a.name as agent_name FROM agent_jobs j
        LEFT JOIN agents a ON j.agent_id = a.id
        ORDER BY j.created_at DESC LIMIT 100
    """).fetchall()
    licenses = db.execute("""
        SELECT l.*, (SELECT COUNT(*) FROM agents a WHERE a.license_key = l.key) as agent_count
        FROM licenses l ORDER BY l.created_at DESC
    """).fetchall()
    db.close()
    
    return templates.TemplateResponse(request, "admin.html", {
        "request": request,
        "agents": [dict(a) for a in agents],
        "jobs": [dict(j) for j in jobs],
        "catalog": GLOBAL_CATALOG,
        "licenses": [dict(l) for l in licenses],
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
    
    return templates.TemplateResponse(request, "admin_agent.html", {
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
        # New apps are published immediately (visible to clients) and premium
        # (paid-only) by default; admin can unpublish or mark free any time.
        "published": True,
        "free_tier": bool(body.get("free_tier", False)),
    }
    
    if is_stack:
        app_entry["type"] = "stack"
        app_entry["is_stack"] = True
        if body.get("compose_url"):
            app_entry["compose_url"] = body["compose_url"]
        if body.get("services"):
            app_entry["services"] = body["services"]
        app_entry["image"] = ""  # Stacks don't need an image
    
    # Extra ports (setup/secondary ports) -> published on random host ports by the agent
    extra_ports = body.get("extra_ports") or body.get("extraPorts") or []
    if isinstance(extra_ports, dict):
        extra_ports = list(extra_ports.keys())
    if isinstance(extra_ports, (list, tuple)):
        ep = {}
        for p in extra_ports:
            p = str(p).strip()
            if p and p.isdigit():
                ep[p] = "auto"
        extra_ports = ep
    if extra_ports:
        app_entry["extra_ports"] = extra_ports

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
    _audit("catalog.add", app_entry["id"])
    
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
    _audit("catalog.remove", app_id)
    return {"status": "removed", "app_id": app_id, "new_catalog_version": new_version}

@app.post("/admin/catalog/apps/{app_id}/free")
async def admin_toggle_free(app_id: str, request: Request):
    """Admin: mark/unmark an app as free-tier. Persists to catalog.json and bumps version."""
    require_admin(request)
    body = await request.json()
    is_free = bool(body.get("free", True))
    app = next((a for a in GLOBAL_CATALOG.get("apps", []) if a.get("id") == app_id), None)
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    app["free_tier"] = is_free
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(GLOBAL_CATALOG, f, indent=2)
    _audit("catalog.free", f"{app_id} -> {'free' if is_free else 'paid-only'}")
    new_version = increment_catalog_version()
    free_count = sum(1 for a in GLOBAL_CATALOG.get("apps", []) if a.get("free_tier"))
    return {"status": "ok", "app_id": app_id, "free": is_free,
            "free_count": free_count, "new_catalog_version": new_version}

@app.post("/admin/licenses")
async def admin_create_license(request: Request):
    """Admin: manually create a license key."""
    require_admin(request)
    body = await request.json()
    email = body.get("email", "").strip()
    tier = body.get("tier", "pro")
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    key = generate_license_key()
    db = get_db()
    db.execute("INSERT INTO licenses (key, email, tier, status) VALUES (?, ?, ?, 'active')", (key, email, tier))
    db.commit()
    db.close()
    _audit("license.created", f"{tier} {email} key={key[:16]}...")
    return {"status": "ok", "key": key, "email": email, "tier": tier}

@app.post("/admin/licenses/{license_key}/revoke")
async def admin_revoke_license(license_key: str, request: Request):
    """Revoke a license - agents using it drop to free immediately."""
    require_admin(request)
    db = get_db()
    db.execute("UPDATE licenses SET status='revoked' WHERE key=?", (license_key,))
    db.execute("UPDATE agents SET plan='free' WHERE license_key=?", (license_key,))
    db.commit()
    db.close()
    _audit("license.revoked", license_key[:16])
    return {"status": "ok", "key": license_key, "revoked": True}

@app.post("/admin/licenses/{license_key}/activate")
async def admin_activate_license(license_key: str, request: Request):
    """Re-activate a license."""
    require_admin(request)
    db = get_db()
    db.execute("UPDATE licenses SET status='active' WHERE key=?", (license_key,))
    db.commit()
    db.close()
    _audit("license.activated", license_key[:16])
    return {"status": "ok", "key": license_key, "active": True}

@app.post("/admin/catalog/apps/{app_id}/disable")
async def admin_toggle_disabled(app_id: str, request: Request):
    """Admin: disable or re-enable an app for EVERYONE (free + paid).

    Backwards-compatible alias for publish/unpublish: disabled == unpublished.
    """
    require_admin(request)
    body = await request.json()
    disabled = bool(body.get("disabled", True))
    app = next((a for a in GLOBAL_CATALOG.get("apps", []) if a.get("id") == app_id), None)
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    app["disabled"] = disabled
    app["published"] = not disabled
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(GLOBAL_CATALOG, f, indent=2)
    _audit("catalog.disable", f"{app_id} -> {'disabled' if disabled else 'enabled'}")
    new_version = increment_catalog_version()
    return {"status": "ok", "app_id": app_id, "disabled": disabled,
            "published": app["published"], "new_catalog_version": new_version}

@app.post("/admin/catalog/apps/{app_id}/publish")
async def admin_toggle_published(app_id: str, request: Request):
    """Admin: publish or unpublish an app. Unpublished apps are NOT sent to any client.

    Body: {"published": true|false}
    """
    require_admin(request)
    body = await request.json()
    published = bool(body.get("published", True))
    app = next((a for a in GLOBAL_CATALOG.get("apps", []) if a.get("id") == app_id), None)
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    app["published"] = published
    app["disabled"] = not published
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(GLOBAL_CATALOG, f, indent=2)
    _audit("catalog.publish", f"{app_id} -> {'published' if published else 'unpublished'}")
    new_version = increment_catalog_version()
    return {"status": "ok", "app_id": app_id, "published": published,
            "new_catalog_version": new_version}

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

@app.post("/admin/agents/{agent_id}/plan")
async def admin_set_agent_plan(agent_id: str, request: Request):
    """Admin: set an agent's plan (free/paid)."""
    require_admin(request)
    body = await request.json()
    plan = body.get("plan", "free")
    if plan not in ("free", "paid"):
        raise HTTPException(status_code=400, detail="Plan must be free or paid")
    set_agent_plan(agent_id, plan)
    return {"status": "ok", "agent_id": agent_id, "plan": plan}



@app.post("/api/agent/subscription")
async def agent_subscription_status(request: Request):
    """Agent checks its subscription status — shows plan, grace period, license info."""
    body = await request.json()
    agent_id = body.get("agent_id")
    api_key = body.get("api_key")

    if not verify_agent(agent_id, api_key):
        raise HTTPException(status_code=401, detail="Invalid auth")

    db = get_db()
    agent = db.execute("SELECT plan, license_key FROM agents WHERE id=?", (agent_id,)).fetchone()
    if not agent:
        db.close()
        raise HTTPException(status_code=404, detail="Agent not found")

    result = {
        "agent_id": agent_id,
        "plan": agent["plan"] or "free",
        "license_key": agent["license_key"] or "",
    }

    if agent["license_key"]:
        lic = db.execute("SELECT status, grace_ends_at, email FROM licenses WHERE key=?", (agent["license_key"],)).fetchone()
        if lic:
            result["license_status"] = lic["status"]
            result["grace_ends_at"] = lic["grace_ends_at"] or ""
            result["email"] = lic["email"] or ""
            if lic["status"] == "grace_period" and lic["grace_ends_at"]:
                from datetime import datetime
                try:
                    grace_end = datetime.fromisoformat(lic["grace_ends_at"])
                    remaining = (grace_end - datetime.utcnow()).days
                    result["grace_days_remaining"] = max(0, remaining)
                except Exception:
                    result["grace_days_remaining"] = 0
    db.close()
    return JSONResponse(result)

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
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "price_xxx_pro")
STRIPE_PRICE_PRO_YEARLY = os.getenv("STRIPE_PRICE_PRO_YEARLY", "price_xxx_pro_yearly")
# Starter/Power tiers deprecated — kept for backward compat (not in checkout)
STRIPE_PRICE_STARTER = os.getenv("STRIPE_PRICE_STARTER", "price_xxx_starter")
STRIPE_PRICE_POWER = os.getenv("STRIPE_PRICE_POWER", "price_xxx_power")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
MAIL_FROM = os.getenv("MAIL_FROM", "AppVault <no-reply@airepoindex.com>")
INSTALL_URL = os.getenv("INSTALL_URL", "https://144.217.89.129/install.sh")

def send_email(to, subject, html):
    if not SMTP_HOST:
        try:
            with open("/data/emails.log", "a") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} TO={to} SUBJECT={subject}\n{html}\n---\n")
        except Exception:
            pass
        _audit("email.logged", f"to={to} subject={subject} (SMTP not configured)")
        return False
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.starttls()
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(MAIL_FROM, [to], msg.as_string())
        _audit("email.sent", f"to={to} subject={subject}")
        return True
    except Exception as e:
        _audit("email.error", f"to={to} {e}")
        return False

async def provision_coolify(instance_id: str, email: str, tier: str) -> Optional[str]:
    """Deploy AppVault on Coolify and return the URL."""
    import httpx
    subdomain = email.split("@")[0].lower().replace(".", "-").replace("_", "-")
    subdomain = f"{subdomain}-{instance_id[:6]}"
    url = f"https://{subdomain}.{DOMAIN}"
    
    env = {
        "API_KEY": str(uuid.uuid4()).replace("-", "")[:32],
        "ADMIN_ENABLED": "false",
        "ADMIN_EMAIL": email,
        "HEIMDALL_PORT": "8085",
        "APP_MANAGER_PORT": "8086",
    }
    # Dynamic: FREE_LIMIT = number of apps the admin marked free (no hardcoded count)
    free_count = sum(1 for a in GLOBAL_CATALOG.get("apps", []) if a.get("free_tier"))
    env["FREE_LIMIT"] = str(free_count)
    
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

# --- Stripe subscription lifecycle (added 2026-08-04) ---

def _set_license_status(sub_id, status):
    """Set license status by subscription id; downgrade agents when revoked."""
    db = get_db()
    rows = db.execute("SELECT key FROM licenses WHERE stripe_subscription_id = ?", (sub_id,)).fetchall()
    keys = []
    for r in rows:
        keys.append(r["key"])
        db.execute("UPDATE licenses SET status=? WHERE key=?", (status, r["key"]))
        if status != "active":
            db.execute("UPDATE agents SET plan='free' WHERE license_key=?", (r["key"],))
    db.commit()
    db.close()
    return keys


async def _handle_checkout_completed(session):
    email = session.get("customer_email") or session.get("customer_details", {}).get("email")
    metadata = session.get("metadata", {})
    instance_id = metadata.get("instance_id")
    agent_id = metadata.get("agent_id")
    tier = metadata.get("tier", "starter")
    customer_id = session.get("customer", "") or ""
    subscription_id = session.get("subscription", "") or ""

    if email:
        license_key = generate_license_key()
        db = get_db()
        try:
            db.execute(
                "INSERT OR REPLACE INTO licenses (key, email, tier, status, stripe_session_id, stripe_customer_id, stripe_subscription_id) "
                "VALUES (?, ?, ?, 'active', ?, ?, ?)",
                (license_key, email, tier, session.get("id", ""), customer_id, subscription_id),
            )
        except Exception:
            pass
        # Auto-bind license to agent (agent-initiated checkout)
        if agent_id:
            db.execute("UPDATE licenses SET bound_agent_id=?, activated_at=datetime('now') WHERE key=?", (agent_id, license_key))
            db.execute("UPDATE agents SET plan='paid', license_key=? WHERE id=?", (license_key, agent_id))
            _audit("agent.upgraded", f"agent {agent_id[:8]} -> paid key={license_key[:16]}")
        if instance_id:
            db.execute(
                "UPDATE instances SET status='paid', stripe_session_id=?, stripe_customer_id=?, stripe_subscription_id=?, updated_at=datetime('now') WHERE id=?",
                (session.get("id", ""), customer_id, subscription_id, instance_id),
            )
        db.commit()
        db.close()
        _audit("license.issued", f"{tier} -> {email} key={license_key[:16]}...")

        subject = "Your AppVault license is ready"
        dash_link = "https://" + DOMAIN + "/dashboard?t=" + _make_dashboard_token(license_key)
        html = (
            "<p>Hi,</p><p>Your AppVault <b>" + tier + "</b> plan is active. Here's your license key:</p>"
            '<p style="font-family:monospace;font-size:18px;background:#f1f5f9;padding:12px;border-radius:8px;"><b>' + license_key + "</b></p>"
            "<p>Deploy AppVault on your own VPS in one line:</p>"
            "<p><code>curl -fsSL " + INSTALL_URL + " | sudo bash -s -- --license " + license_key + "</code></p>"
            "<p>Then open the app's <b>Security</b> tab and join your Tailscale network.</p>"
            '<p>Manage your subscription: <a href="' + dash_link + '">' + dash_link + "</a></p>"
            '<p>Need more servers? Each server needs its own license — buy another at <a href="https://' + DOMAIN + '/#pricing">' + DOMAIN + "/#pricing</a></p>"
            "<p>Questions? Just reply to this email.</p>"
        )
        send_email(email, subject, html)


async def _handle_subscription_updated(sub):
    from datetime import datetime, timedelta
    sub_id = sub.get("id", "")
    status = sub.get("status", "")
    if not sub_id:
        return
    if status == "canceled":
        # Start 14-day grace period (same logic as subscription_deleted)
        grace_end = (datetime.utcnow() + timedelta(days=14)).isoformat()
        db = get_db()
        rows = db.execute("SELECT key FROM licenses WHERE stripe_subscription_id=? AND status='active'", (sub_id,)).fetchall()
        for r in rows:
            db.execute("UPDATE licenses SET status='grace_period', canceled_at=datetime('now'), grace_ends_at=? WHERE key=?", (grace_end, r["key"]))
        db.commit()
        db.close()
        _audit("license.grace_period", f"subscription updated {sub_id} grace_until={grace_end}")
    if status in ("unpaid", "past_due", "incomplete_expired"):
        keys = _set_license_status(sub_id, "revoked")
        if keys:
            _audit("license.revoked", f"subscription {sub_id} ({status}) keys={[k[:16] for k in keys]}")
    else:
        keys = _set_license_status(sub_id, "active")
        if keys:
            _audit("license.activated", f"subscription {sub_id} ({status})")


async def _handle_subscription_deleted(sub):
    """Subscription canceled — start 14-day grace period instead of immediate revoke.

    During grace period:
    - License status = 'grace_period', grace_ends_at = now + 14 days
    - Agent plan stays 'paid' (get_agent_plan checks grace_ends_at)
    - Agent keeps getting premium updates
    After grace period:
    - Next agent sync/catalog check sees grace_ends_at passed
    - get_agent_plan downgrades agent to 'free'
    - Premium installs/updates blocked, running containers untouched
    """
    from datetime import datetime, timedelta
    sub_id = sub.get("id", "")
    if not sub_id:
        return
    grace_end = (datetime.utcnow() + timedelta(days=14)).isoformat()
    db = get_db()
    rows = db.execute("SELECT key FROM licenses WHERE stripe_subscription_id=? AND status='active'", (sub_id,)).fetchall()
    keys = []
    for r in rows:
        keys.append(r["key"])
        db.execute("UPDATE licenses SET status='grace_period', canceled_at=datetime('now'), grace_ends_at=? WHERE key=?", (grace_end, r["key"]))
    db.commit()
    db.close()
    if keys:
        _audit("license.grace_period", f"subscription {sub_id} grace_until={grace_end} keys={[k[:16] for k in keys]}")


async def _handle_invoice_paid(inv):
    sub_id = inv.get("subscription", "")
    if sub_id:
        _set_license_status(sub_id, "active")
        _audit("license.renewed", f"invoice paid subscription={sub_id}")


async def _handle_invoice_failed(inv):
    sub_id = inv.get("subscription", "")
    customer = inv.get("customer", "")
    print(f"[stripe] invoice.payment_failed subscription={sub_id} customer={customer}", flush=True)
    _audit("invoice.failed", f"subscription={sub_id} customer={customer}")
    # Stripe retries automatically; customer.subscription.updated revokes on unpaid.


@app.post("/api/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe events: checkout, subscription lifecycle, invoices."""
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
    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        await _handle_checkout_completed(obj)
    elif etype == "customer.subscription.updated":
        await _handle_subscription_updated(obj)
    elif etype == "customer.subscription.deleted":
        await _handle_subscription_deleted(obj)
    elif etype == "invoice.payment_succeeded":
        await _handle_invoice_paid(obj)
    elif etype == "invoice.payment_failed":
        await _handle_invoice_failed(obj)
    else:
        print(f"[stripe] Unhandled event type: {etype}", flush=True)

    return JSONResponse({"status": "ok"})


@app.post("/api/agent/billing-portal")
async def agent_billing_portal(request: Request):
    """Agent creates a Stripe Customer Portal session to manage its subscription."""
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    body = await request.json()
    agent_id = body.get("agent_id")
    api_key = body.get("api_key")

    if not verify_agent(agent_id, api_key):
        raise HTTPException(status_code=401, detail="Invalid auth")

    # Get the Stripe customer ID from the agent's license
    db = get_db()
    agent = db.execute("SELECT license_key FROM agents WHERE id=?", (agent_id,)).fetchone()
    if not agent or not agent["license_key"]:
        db.close()
        raise HTTPException(status_code=400, detail="No license found")

    lic = db.execute("SELECT stripe_customer_id FROM licenses WHERE key=?", (agent["license_key"],)).fetchone()
    db.close()

    if not lic or not lic["stripe_customer_id"]:
        raise HTTPException(status_code=400, detail="No subscription found for this license")

    try:
        session = stripe.billing_portal.Session.create(
            customer=lic["stripe_customer_id"],
            return_url=f"https://{DOMAIN}/dashboard",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Billing portal creation failed: {str(e)}")
    return JSONResponse({"url": session.url})

@app.post("/api/billing-portal")
async def billing_portal(request: Request):
    """Create a Stripe Customer Portal session (requires a valid license key)."""
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    body = await request.json()
    key = (body.get("license_key") or "").strip() or request.session.get("license_key", "")
    if not key:
        raise HTTPException(status_code=400, detail="license_key is required")

    db = get_db()
    lic = db.execute("SELECT * FROM licenses WHERE key = ?", (key,)).fetchone()
    db.close()
    if not lic or lic["status"] != "active":
        raise HTTPException(status_code=403, detail="Invalid or inactive license")

    customer_id = (lic["stripe_customer_id"] or "").strip()
    if not customer_id:
        try:
            customers = stripe.Customer.list(email=lic["email"], limit=1)
            if customers.data:
                customer_id = customers.data[0].id
        except Exception:
            customer_id = ""
    if not customer_id:
        raise HTTPException(status_code=404, detail="No Stripe customer found for this license")

    try:
        portal = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"https://{DOMAIN}/dashboard?k={key}",
        )
        _audit("portal.created", lic["email"])
        return JSONResponse({"url": portal.url})
    except Exception as e:
        print(f"[stripe] Portal creation failed: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"Portal session creation failed: {str(e)}")
@app.get("/")
async def landing(request: Request):
    return templates.TemplateResponse(request, "landing.html", {"request": request})

@app.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request):
    return templates.TemplateResponse(request, "landing.html", {"request": request})

@app.get("/dashboard")
async def dashboard(request: Request, k: str = None, t: str = None):
    """License-key authenticated dashboard: session cookie + short-lived signed link."""
    ctx = {"request": request, "license": None, "instances": [], "error": None}

    # Legacy raw-key links: validate, set session, redirect to a clean URL.
    if k:
        db = get_db()
        lic = db.execute("SELECT * FROM licenses WHERE key = ?", (k,)).fetchone()
        db.close()
        if lic and lic["status"] == "active":
            request.session["license_key"] = k
            return RedirectResponse("/dashboard", status_code=302)
        ctx["error"] = "Invalid or inactive license key."
        return templates.TemplateResponse(request, "dashboard.html", ctx)

    if t:
        key = _read_dashboard_token(t)
        if not key:
            ctx["error"] = "This link has expired. Enter your license key below."
            return templates.TemplateResponse(request, "dashboard.html", ctx)
    else:
        key = request.session.get("license_key", "")

    if not key:
        return templates.TemplateResponse(request, "dashboard.html", ctx)

    db = get_db()
    lic = db.execute("SELECT * FROM licenses WHERE key = ?", (key,)).fetchone()
    if not lic or lic["status"] != "active":
        db.close()
        request.session.pop("license_key", None)
        ctx["error"] = "Invalid or inactive license key."
        return templates.TemplateResponse(request, "dashboard.html", ctx)
    request.session["license_key"] = key
    licenses = db.execute("SELECT * FROM licenses WHERE email = ? ORDER BY created_at DESC", (lic["email"],)).fetchall()
    instances = db.execute("SELECT * FROM instances WHERE email = ?", (lic["email"],)).fetchall()
    db.close()
    ctx["license"] = lic
    ctx["licenses"] = licenses
    ctx["instances"] = instances
    ctx["install_url"] = INSTALL_URL
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@app.post("/api/dashboard/login")
async def dashboard_login(request: Request):
    """Exchange a license key for a session (key entry form)."""
    body = await request.json()
    key = (body.get("license_key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="license_key is required")
    db = get_db()
    lic = db.execute("SELECT * FROM licenses WHERE key = ?", (key,)).fetchone()
    db.close()
    if not lic or lic["status"] != "active":
        raise HTTPException(status_code=403, detail="Invalid or inactive license key")
    request.session["license_key"] = key
    _audit("dashboard.login", lic["email"])
    return JSONResponse({"ok": True})

@app.post("/api/checkout")
async def create_checkout(request: Request):
    """Create Stripe Checkout session. Tiers: pro (monthly/yearly)."""
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    body = await request.json()
    tier = body.get("tier", "pro")
    billing = body.get("billing", "monthly")  # monthly | yearly
    email = body.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="email is required")

    # Resolve price: only "pro" tier is purchasable; yearly uses annual price
    if tier == "pro" and billing == "yearly":
        price_id = STRIPE_PRICE_PRO_YEARLY
    elif tier == "pro":
        price_id = STRIPE_PRICE_PRO
    else:
        # Legacy tiers (starter/power) are deprecated — route to pro monthly
        price_id = STRIPE_PRICE_PRO

    if not price_id or price_id.startswith("price_xxx"):
        raise HTTPException(status_code=503, detail="Checkout not configured yet (missing Stripe price)")

    instance_id = str(uuid.uuid4())
    db = get_db()
    db.execute("INSERT INTO instances (id, email, tier, status) VALUES (?, ?, ?, 'pending')",
               (instance_id, email, f"{tier}-{billing}"))
    db.commit()
    db.close()

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=f"https://{DOMAIN}/dashboard",
            cancel_url=f"https://{DOMAIN}",
            customer_email=email,
            metadata={"instance_id": instance_id, "tier": tier, "billing": billing, "email": email},
        )
    except Exception as e:
        print(f"[stripe] Checkout session creation failed: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"Checkout session creation failed: {str(e)}")
    _audit("checkout.created", f"{tier}-{billing} {email}")
    return JSONResponse({"url": session.url})

@app.post("/api/agent/checkout")
async def agent_checkout(request: Request):
    """Agent-initiated checkout — agent pays to upgrade itself to Pro.

    The agent's agent_id is passed through Stripe metadata so the webhook
    can auto-bind the license to the specific agent after payment.
    """
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    body = await request.json()
    agent_id = body.get("agent_id")
    api_key = body.get("api_key")
    billing = body.get("billing", "monthly")  # monthly | yearly

    if not verify_agent(agent_id, api_key):
        raise HTTPException(status_code=401, detail="Invalid auth")

    # Get agent's existing email (from license or agent record)
    db = get_db()
    agent = db.execute("SELECT license_key FROM agents WHERE id=?", (agent_id,)).fetchone()
    email = ""
    if agent and agent["license_key"]:
        lic = db.execute("SELECT email FROM licenses WHERE key=?", (agent["license_key"],)).fetchone()
        if lic:
            email = lic["email"]
    db.close()

    # Resolve price
    if billing == "yearly":
        price_id = STRIPE_PRICE_PRO_YEARLY
    else:
        price_id = STRIPE_PRICE_PRO

    if not price_id or price_id.startswith("price_xxx"):
        raise HTTPException(status_code=503, detail="Checkout not configured yet (missing Stripe price)")

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=body.get("return_url") or f"https://{DOMAIN}/dashboard",
            cancel_url=body.get("cancel_url") or f"https://{DOMAIN}",
            customer_email=email or None,
            metadata={"agent_id": agent_id, "tier": "pro", "billing": billing, "email": email or ""},
        )
    except Exception as e:
        print(f"[stripe] Agent checkout session creation failed: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"Checkout session creation failed: {str(e)}")
    _audit("agent.checkout", f"agent {agent_id[:8]} billing={billing}")
    return JSONResponse({"url": session.url})

@app.get("/api/status/{instance_id}")
async def check_status(instance_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM instances WHERE id = ?", (instance_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found")
    return {"id": row["id"], "status": row["status"], "url": row["url"], "tier": row["tier"], "created_at": row["created_at"]}

@app.get("/api/license/{license_key}")
async def check_license(license_key: str):
    """Public license verification."""
    db = get_db()
    row = db.execute("SELECT key, email, tier, status, created_at FROM licenses WHERE key = ?", (license_key,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail="License not found")
    return dict(row)

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
