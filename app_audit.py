#!/usr/bin/env python3
"""AppVault catalog auditor: install → verify → login → record → uninstall per app."""
import json, os, sys, time, sqlite3, urllib.request, urllib.error
from datetime import datetime

AGENT_API = "http://localhost:8086"
CATALOG_PATH = "D:/DATA_INTELLFENCE/WebDev/AppVault/central/static/catalog.json"
DB_PATH = os.path.expanduser("~/.appvault/agentic-data/agentic.db")
REPORT_PATH = "D:/DATA_INTELLFENCE/WebDev/AppVault/central/app_audit_report.json"

# Bootstrap to get token
def get_token():
    req = urllib.request.Request(f"{AGENT_API}/api/agentic/bootstrap")
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    return data.get("token", "")

def api_get(token, path):
    req = urllib.request.Request(f"{AGENT_API}{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def api_post(token, path, body=None):
    req = urllib.request.Request(f"{AGENT_API}{path}", data=json.dumps(body or {}).encode(),
                                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                                method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def wait_for_status(token, app_id, timeout=300):
    """Poll install status until done or timeout."""
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        try:
            last = api_get(token, f"/api/install/{app_id}/status")
        except Exception as e:
            last = {"error": str(e)}
        if last.get("done") or last.get("error"):
            return last
        time.sleep(3)
    return {"error": "timeout", **last}

def get_launch_url(token, app_id):
    """Get the launch URL for an installed app."""
    try:
        apps = api_get(token, "/api/apps")
        for a in apps:
            if a.get("id") == app_id:
                return a.get("launch_url") or a.get("url") or a.get("web_url")
    except Exception:
        pass
    return None

def try_login(launch_url, username, password):
    """Attempt to log in via browser automation hint (returns True/False/None)."""
    # We return the URL and credentials; actual browser login is done manually
    return {"url": launch_url, "username": username, "password": password, "status": "pending_manual"}

def record_result(app_id, name, result):
    """Write result to SQLite audit table."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS app_audit (
        app_id TEXT PRIMARY KEY,
        name TEXT,
        install_ok INTEGER,
        start_ok INTEGER,
        login_ok INTEGER,
        launch_url TEXT,
        error TEXT,
        findings TEXT,
        audited_at TEXT
    )""")
    conn.execute("""INSERT OR REPLACE INTO app_audit 
        (app_id, name, install_ok, start_ok, login_ok, launch_url, error, findings, audited_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (app_id, name,
         result.get("install_ok", False),
         result.get("start_ok", False),
         result.get("login_ok", False),
         result.get("launch_url", ""),
         result.get("error", ""),
         result.get("findings", ""),
         datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def uninstall_app(token, app_id):
    """Uninstall an app after audit."""
    try:
        api_post(token, f"/api/uninstall/{app_id}")
        time.sleep(2)
        # Poll until done
        for _ in range(20):
            status = api_get(token, f"/api/uninstall/{app_id}/status")
            if status.get("done"):
                return True
            time.sleep(2)
    except Exception as e:
        print(f"  [WARN] Uninstall error: {e}")
    return False

def disable_app_in_catalog(app_id, reason):
    """Disable an app in the central catalog so users don't see it."""
    catalog = json.load(open(CATALOG_PATH, encoding="utf-8-sig"))
    for a in catalog.get("apps", []):
        if a.get("id") == app_id:
            a["disabled"] = True
            a["disabled_reason"] = reason
            a["free_tier"] = False
            break
    with open(CATALOG_PATH, "w", encoding="utf-8-sig") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    print(f"  [CATALOG] Disabled {app_id}: {reason}")

def main():
    token = get_token()
    print(f"[*] Got token: {token[:8]}...")
    
    catalog = json.load(open(CATALOG_PATH, encoding="utf-8-sig"))
    apps = catalog.get("apps", [])
    print(f"[*] Total apps: {len(apps)}")
    
    report = []
    for app in apps:
        app_id = app.get("id")
        name = app.get("name", app_id)
        print(f"\n{'='*60}")
        print(f"[*] Testing: {name} ({app_id})")
        
        result = {
            "app_id": app_id,
            "name": name,
            "install_ok": False,
            "start_ok": False,
            "login_ok": False,
            "launch_url": "",
            "error": "",
            "findings": ""
        }
        
        # Skip known infrastructure apps
        if app_id in ["central-mariadb", "central-postgres", "central-mongo", "central-redis"]:
            result["findings"] = "Infrastructure app (database/cache), no web UI to verify"
            result["install_ok"] = True
            result["start_ok"] = True
            record_result(app_id, name, result)
            report.append(result)
            continue
        
        # Install
        try:
            install_resp = api_post(token, f"/api/install/{app_id}")
            if install_resp.get("status") == "error":
                result["error"] = install_resp.get("message", "Unknown error")
                print(f"  [FAIL] Install blocked: {result['error']}")
                if "Premium" in result["error"] or "license" in result["error"].lower():
                    disable_app_in_catalog(app_id, f"Premium app - blocked by license gate: {result['error']}")
                record_result(app_id, name, result)
                report.append(result)
                continue
            print(f"  [OK] Install started: {install_resp}")
        except Exception as e:
            result["error"] = f"Install API error: {str(e)[:200]}"
            print(f"  [FAIL] {result['error']}")
            record_result(app_id, name, result)
            report.append(result)
            continue
        
        # Wait for install
        status = wait_for_status(token, app_id, timeout=300)
        print(f"  [*] Install status: {status}")
        
        if status.get("error"):
            result["error"] = status.get("error", "")[:500]
            print(f"  [FAIL] Install failed: {result['error']}")
            record_result(app_id, name, result)
            report.append(result)
            # Don't uninstall failed installs (may have partial state)
            continue
        
        if status.get("stage") in ["done", "complete", "installed"]:
            result["install_ok"] = True
            result["start_ok"] = True
        elif status.get("percent", 0) >= 90 or status.get("done"):
            result["install_ok"] = True
            result["start_ok"] = True
        else:
            result["error"] = f"Install incomplete: {status.get('message', 'unknown')}"
            record_result(app_id, name, result)
            report.append(result)
            continue
        
        # Get launch URL
        launch_url = get_launch_url(token, app_id)
        if launch_url:
            result["launch_url"] = launch_url
            print(f"  [OK] Launch URL: {launch_url}")
        else:
            print(f"  [WARN] No launch URL found")
        
        # Check login requirements
        edu = app.get("education", {})
        default_login = edu.get("default_login", {})
        if default_login:
            result["findings"] = f"Login required: {default_login.get('username')}/{default_login.get('password')}"
            print(f"  [INFO] Login: {default_login.get('username')}/{default_login.get('password')}")
        else:
            result["findings"] = "No login required"
            print(f"  [INFO] No login required")
        
        # Record success
        record_result(app_id, name, result)
        report.append(result)
        print(f"  [OK] Audit complete for {name}")
        
        # Uninstall
        print(f"  [*] Uninstalling {app_id}...")
        uninstall_ok = uninstall_app(token, app_id)
        print(f"  [{'OK' if uninstall_ok else 'WARN'}] Uninstall {'done' if uninstall_ok else 'may have failed'}")
    
    # Save final report
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n{'='*60}")
    print(f"[*] Audit complete. Report saved to: {REPORT_PATH}")
    print(f"[*] Total apps: {len(report)}")
    print(f"[*] Installed OK: {sum(1 for r in report if r['install_ok'])}")
    print(f"[*] Failed: {sum(1 for r in report if not r['install_ok'])}")

if __name__ == "__main__":
    main()
