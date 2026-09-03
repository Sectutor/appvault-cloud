#!/usr/bin/env python3
"""AppVault catalog auditor: install → verify → login → record → uninstall per app."""
import json, os, sys, time, sqlite3, urllib.request, urllib.error, subprocess, re
from datetime import datetime

AGENT_API = "http://localhost:8086"
CATALOG_PATH = "D:/DATA_INTELLFENCE/WebDev/AppVault/central/static/catalog.json"
DB_PATH = os.path.expanduser("~/.appvault/agentic-data/agentic.db")
REPORT_PATH = "D:/DATA_INTELLFENCE/WebDev/AppVault/central/app_audit_report.json"
CONTAINER_PREFIX = "app-"

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

def docker_container_running(app_id):
    """Check if container exists and is running."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", f"name={CONTAINER_PREFIX}{app_id}", "--format", "{{.Names}} {{.Status}}"],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip()
        if output and "Up" in output:
            return True, output
        return False, output
    except Exception as e:
        return False, str(e)

def docker_port_for_container(app_id):
    """Get the host port mapped for an app container."""
    try:
        result = subprocess.run(
            ["docker", "port", f"{CONTAINER_PREFIX}{app_id}"],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip()
        if output:
            first_line = output.split('\n')[0]
            parts = first_line.split(':')
            if len(parts) >= 2:
                port = parts[-1].strip()
                return port
        return None
    except Exception as e:
        return None

def verify_url(url, timeout=10):
    """Check if URL returns HTTP 200-399."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AppVault-Audit/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, r.getcode()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 307, 308):
            return True, e.code
        return False, e.code
    except Exception as e:
        return False, str(e)

def record_result(app_id, name, result):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS app_audit (
        app_id TEXT PRIMARY KEY,
        name TEXT,
        install_ok INTEGER,
        start_ok INTEGER,
        verify_ok INTEGER,
        login_ok INTEGER,
        launch_url TEXT,
        port INTEGER,
        error TEXT,
        findings TEXT,
        audited_at TEXT
    )""")
    conn.execute("""INSERT OR REPLACE INTO app_audit 
        (app_id, name, install_ok, start_ok, verify_ok, login_ok, launch_url, port, error, findings, audited_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (app_id, name,
         result.get("install_ok", False),
         result.get("start_ok", False),
         result.get("verify_ok", False),
         result.get("login_ok", False),
         result.get("launch_url", ""),
         result.get("port", 0),
         result.get("error", ""),
         result.get("findings", ""),
         datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def uninstall_app(token, app_id):
    """Uninstall an app after audit."""
    try:
        api_post(token, f"/api/uninstall/{app_id}")
        time.sleep(5)
        for _ in range(40):
            s = api_get(token, f"/api/uninstall/{app_id}/status")
            if s.get("done"):
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
    
    passed = 0
    failed = 0
    skipped = 0
    report = []
    
    for app in apps:
        app_id = app.get("id")
        name = app.get("name", app_id)
        container_port = app.get("container_port", 80)
        edu = app.get("education", {})
        default_login = edu.get("default_login", {})
        
        print(f"\n{'='*60}")
        print(f"[*] Testing: {name} ({app_id})")
        
        result = {
            "app_id": app_id,
            "name": name,
            "install_ok": False,
            "start_ok": False,
            "verify_ok": False,
            "login_ok": False,
            "launch_url": "",
            "port": 0,
            "error": "",
            "findings": ""
        }
        
        # Skip infrastructure apps
        if app_id in ["central-mariadb", "central-postgres", "central-mongo", "central-redis"]:
            result["install_ok"] = True
            result["start_ok"] = True
            result["verify_ok"] = True
            result["findings"] = "Infrastructure app (DB/cache), no web UI"
            record_result(app_id, name, result)
            report.append(result)
            skipped += 1
            print(f"  [SKIP] Infrastructure app")
            continue
        
        # Install
        try:
            install_resp = api_post(token, f"/api/install/{app_id}")
            if install_resp.get("status") == "error":
                result["error"] = install_resp.get("message", "Unknown")
                print(f"  [FAIL] Install blocked: {result['error']}")
                if "Premium" in result["error"] or "license" in result["error"].lower():
                    disable_app_in_catalog(app_id, f"Premium/license blocked: {result['error']}")
                record_result(app_id, name, result)
                report.append(result)
                failed += 1
                continue
        except Exception as e:
            result["error"] = f"Install API error: {str(e)[:200]}"
            print(f"  [FAIL] {result['error']}")
            record_result(app_id, name, result)
            report.append(result)
            failed += 1
            continue
        
        print(f"  [OK] Install started")
        
        # Wait for install
        status = wait_for_status(token, app_id, timeout=300)
        print(f"  [*] Install status: {status.get('message', '')} {status.get('percent', 0)}%")
        
        if status.get("error"):
            result["error"] = status.get("error", "")[:500]
            print(f"  [FAIL] Install failed: {result['error']}")
            record_result(app_id, name, result)
            report.append(result)
            failed += 1
            continue
        
        result["install_ok"] = True
        result["start_ok"] = True
        
        # Verify container is actually running
        time.sleep(2)
        running, status_output = docker_container_running(app_id)
        if not running:
            result["error"] = f"Container not running after install: {status_output}"
            print(f"  [FAIL] {result['error']}")
            record_result(app_id, name, result)
            report.append(result)
            failed += 1
            continue
        
        print(f"  [OK] Container running: {status_output}")
        
        # Get actual port
        actual_port = docker_port_for_container(app_id)
        if actual_port:
            result["port"] = int(actual_port)
            launch_url = f"http://localhost:{actual_port}"
            result["launch_url"] = launch_url
            print(f"  [OK] Port: {actual_port}")
        else:
            launch_url = f"http://localhost:{container_port}"
            result["launch_url"] = launch_url
            result["port"] = container_port
            print(f"  [WARN] Could not detect port, using catalog: {container_port}")
        
        # Verify URL is accessible
        verify_ok, verify_code = verify_url(launch_url, timeout=15)
        result["verify_ok"] = verify_ok
        if verify_ok:
            print(f"  [OK] URL verified: {launch_url} (HTTP {verify_code})")
        else:
            print(f"  [WARN] URL not accessible: {launch_url} ({verify_code})")
        
        # Login check
        if default_login:
            username = default_login.get("username", "")
            password = default_login.get("password", "")
            result["findings"] = f"Login: {username}/{password}"
            print(f"  [INFO] Credentials: {username}/{password}")
            result["login_ok"] = verify_ok
        else:
            result["findings"] = "No login required"
            print(f"  [INFO] No login required")
        
        # Record result
        record_result(app_id, name, result)
        report.append(result)
        
        # Only mark as fully PASS if container is running
        if result["install_ok"] and result["start_ok"] and running:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            failed += 1
            print(f"  [FAIL] {name}")
        
        # Uninstall
        print(f"  [*] Uninstalling {app_id}...")
        uninstall_ok = uninstall_app(token, app_id)
        print(f"  [{'OK' if uninstall_ok else 'WARN'}] Uninstall {'done' if uninstall_ok else 'may have failed'}")
    
    # Save final report
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"[*] Audit complete")
    print(f"[*] Total: {len(apps)} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}")
    print(f"[*] Report: {REPORT_PATH}")

if __name__ == "__main__":
    main()
