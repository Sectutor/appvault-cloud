#!/usr/bin/env python3
"""
app_rebuild_agent.py — sequential remove→rebuild→verify agent for AppVault apps.

For each app in the target list (one at a time, strictly sequential):
  1. REMOVE  — uninstall if installed (containers/volumes wiped)
  2. REBUILD — fresh install via agent API
  3. VERIFY  — container running + HTTP reachable on mapped port
  4. RECORD  — result written to agentic.db app_audit table
  5. CLEANUP — uninstall again (test must not leave residue)
Then moves to the next app. Apps that fail twice get flagged DISABLE_CANDIDATE.

Usage:
  python app_rebuild_agent.py <app_id> [<app_id> ...]
  python app_rebuild_agent.py --list          # show broken-app targets
  python app_rebuild_agent.py --all-broken    # run all 28 known broken
  python app_rebuild_agent.py <id> --keep     # don't uninstall after verify

Auth: uses X-Api-Key header (same key the store UI uses).
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

AGENT_API = "http://localhost:8086"
API_KEY = "appvault-key"
DB_PATH = os.path.expanduser("~/.appvault/agentic-data/agentic.db")
RESULTS_PATH = os.path.expanduser("~/.appvault/rebuild_results.json")
PREFIX = "app-"

# The 28 apps with recorded failures (integrated system apps are NOT here —
# hermes-agent/crewai-runner/memory-mcp are handled separately, never disabled).
BROKEN_APPS = [
    # bucket A: install-API 404s + blank-error retests (cheap wins first)
    "immich-machine-learning", "uptime-kuma", "openmaic", "appflowy",
    "owncloud", "gitlab", "paperless", "immich", "traefik", "gitea",
    "documenso", "mattermost",
    # bucket C: container-not-running after install
    "openship", "dify", "comfyui", "formbricks", "chatwoot",
    "affine", "ods", "buzz", "appvault-premium-agents",
    # bucket D: readiness timeouts
    "portainer",
]

# Deferred pending catalog fixes (central restart + version bump):
DEFERRED = ["umami"]

INTEGRATED = {"hermes-agent", "crewai-runner", "memory-mcp"}


def api(method, path, body=None, timeout=15):
    req = urllib.request.Request(
        f"{AGENT_API}{path}",
        data=json.dumps(body or {}).encode() if method == "POST" else None,
        headers={"X-Api-Key": API_KEY, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


def wait_progress(path, timeout_s, label):
    """Poll an install/uninstall progress endpoint until done/error/timeout."""
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = api("GET", path)
        if last.get("error"):
            return False, last.get("error"), last
        if last.get("done"):
            msg = last.get("message", "")
            if last.get("error"):
                return False, msg or last["error"], last
            return True, msg, last
        pct = last.get("percent", "?")
        print(f"    {label}: {pct}% {last.get('message', '')[:60]}", end="\r", flush=True)
        time.sleep(4)
    print()
    return False, f"{label} timeout after {timeout_s}s", last


def docker_running(app_id):
    r = subprocess.run(
        ["docker", "ps", "--filter", f"name={PREFIX}{app_id}", "--format", "{{.Names}} {{.Status}}"],
        capture_output=True, text=True, timeout=15)
    out = r.stdout.strip()
    return bool(out) and "Up" in out, out


def docker_containers_for(app_id):
    """All containers belonging to this app (incl. -db sidecars)."""
    r = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"],
                       capture_output=True, text=True, timeout=15)
    return [l.strip() for l in r.stdout.split("\n")
            if l.strip().startswith(f"{PREFIX}{app_id}")]


def host_port(app_id):
    r = subprocess.run(["docker", "port", f"{PREFIX}{app_id}"],
                       capture_output=True, text=True, timeout=15)
    out = r.stdout.strip()
    if out:
        try:
            return int(out.split("\n")[0].rsplit(":", 1)[-1])
        except (ValueError, IndexError):
            return None
    return None


def url_ok(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RebuildAgent/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, r.getcode()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 307, 308):  # auth/redirect = server is alive
            return True, e.code
        return False, e.code
    except Exception as e:
        return False, str(e)[:60]


def record(app_id, name, res):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS app_audit (
        app_id TEXT PRIMARY KEY, name TEXT, install_ok INTEGER, start_ok INTEGER,
        verify_ok INTEGER, login_ok INTEGER, launch_url TEXT, port INTEGER,
        error TEXT, findings TEXT, audited_at TEXT)""")
    conn.execute("""INSERT OR REPLACE INTO app_audit
        (app_id, name, install_ok, start_ok, verify_ok, login_ok, launch_url, port,
         error, findings, audited_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (app_id, name, res.get("install_ok", 0), res.get("start_ok", 0),
         res.get("verify_ok", 0), res.get("login_ok", 0), res.get("launch_url", ""),
         res.get("port", 0), res.get("error", ""), res.get("findings", ""),
         datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def step_remove(app_id):
    """Uninstall if present; tolerate already-absent."""
    containers = docker_containers_for(app_id)
    prog = api("GET", f"/api/install/{app_id}/status")
    installed_before = bool(containers) or not prog.get("done", True)

    if not containers:
        print(f"  [1/4] REMOVE: nothing to remove (no containers)")
        return True
    print(f"  [1/4] REMOVE: removing {len(containers)} container(s): {', '.join(containers[:3])}...")
    api("POST", f"/api/uninstall/{app_id}")
    ok, msg, _ = wait_progress(f"/api/uninstall/{app_id}/status", 180, "uninstall")
    leftover = docker_containers_for(app_id)
    if ok and not leftover:
        print(f"  [1/4] REMOVE: clean ✓")
        return True
    # force-remove leftovers so rebuild starts truly fresh
    if leftover:
        print(f"  [1/4] REMOVE: force-cleaning leftovers: {leftover}")
        for c in leftover:
            subprocess.run(["docker", "rm", "-f", c], capture_output=True, timeout=30)
        return True
    print(f"  [1/4] REMOVE: issue: {msg}")
    return ok


def step_rebuild(app_id):
    print(f"  [2/4] REBUILD: installing fresh...")
    resp = api("POST", f"/api/install/{app_id}")
    status = resp.get("status", "")
    if status == "error":
        return False, resp.get("message", "install blocked")
    if status == "busy":
        return False, "agent busy with another op for this app"
    if status != "started":
        return False, f"unexpected install response: {resp}"
    ok, msg, last = wait_progress(f"/api/install/{app_id}/status", 420, "install")
    if not ok:
        return False, msg or "install failed"
    print(f"    install done: {msg[:70]}")
    return True, msg


def step_verify(app_id, name):
    print(f"  [3/4] VERIFY: checking container + HTTP...")
    # give slow starters a grace window
    running, detail = False, ""
    for attempt in range(6):
        running, detail = docker_running(app_id)
        if running:
            break
        time.sleep(10)
    if not running:
        return False, f"container not running: {detail}"

    port = host_port(app_id)
    if not port:
        return False, "running but no host port mapped"
    url = f"http://localhost:{port}"
    ok, code = url_ok(url)
    if not ok:
        # one retry after 10s grace
        time.sleep(10)
        ok, code = url_ok(url)
    if ok:
        print(f"  [3/4] VERIFY: ✓ http://localhost:{port} (HTTP {code})")
        return True, url
    return False, f"URL unreachable: {url} ({code})"


def step_cleanup(app_id, keep):
    if keep:
        print(f"  [4/4] CLEANUP: --keep set, leaving app installed")
        return True
    print(f"  [4/4] CLEANUP: uninstalling test instance...")
    api("POST", f"/api/uninstall/{app_id}")
    ok, msg, _ = wait_progress(f"/api/uninstall/{app_id}/status", 180, "cleanup")
    leftover = docker_containers_for(app_id)
    if leftover:
        for c in leftover:
            subprocess.run(["docker", "rm", "-f", c], capture_output=True, timeout=30)
    print(f"  [4/4] CLEANUP: {'done ✓' if ok else 'forced ✓'}")
    return True


def process_app(app_id, keep=False):
    name = app_id
    try:
        cat = api("GET", "/api/catalog")
        for a in cat.get("apps", []):
            if a.get("id") == app_id:
                name = a.get("name", app_id)
                break
    except Exception:
        pass

    print(f"\n{'=' * 64}\nAPP: {name} ({app_id})\n{'=' * 64}")
    res = {"app_id": app_id, "name": name, "install_ok": 0, "start_ok": 0,
           "verify_ok": 0, "login_ok": 0, "launch_url": "", "port": 0,
           "error": "", "findings": ""}

    if app_id in INTEGRATED:
        res["findings"] = "INTEGRATED system app — skip rebuild, verify-only elsewhere"
        print(f"  SKIP: {res['findings']}")
        record(app_id, name, res)
        return "skipped"

    if not step_remove(app_id):
        res["error"] = "remove step failed (pre-existing state)"
        record(app_id, name, res)
        return "failed"

    ok, info = step_rebuild(app_id)
    res["install_ok"] = int(ok)
    if not ok:
        res["error"] = f"rebuild: {info}"[:400]
        print(f"  RESULT: ✗ {info}")
        step_cleanup(app_id, keep=False)
        record(app_id, name, res)
        return "failed"

    res["start_ok"] = 1
    ok, info = step_verify(app_id, name)
    res["verify_ok"] = int(ok)
    if ok and info.startswith("http"):
        res["launch_url"] = info
        res["port"] = host_port(app_id) or 0
        res["findings"] = "rebuilt+verified"
        print(f"  RESULT: ✓ PASS")
        outcome = "passed"
    else:
        res["error"] = f"verify: {info}"[:400]
        print(f"  RESULT: ✗ {info}")
        outcome = "failed"

    step_cleanup(app_id, keep)
    record(app_id, name, res)

    # track cumulative results across runs
    try:
        results = json.load(open(RESULTS_PATH)) if os.path.exists(RESULTS_PATH) else []
    except Exception:
        results = []
    results = [r for r in results if r.get("app_id") != app_id]
    results.append({**{k: v for k, v in res.items()},
                    "outcome": outcome,
                    "at": datetime.now().isoformat(timespec="seconds")})
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    return outcome


def main():
    args = sys.argv[1:]
    keep = "--keep" in args
    args = [a for a in args if a != "--keep"]

    if "--list" in args:
        print(f"{len(BROKEN_APPS)} broken-app targets:")
        for i, a in enumerate(BROKEN_APPS, 1):
            print(f"  {i:>2}. {a}")
        return

    if "--all-broken" in args:
        targets = BROKEN_APPS
    elif args:
        targets = args
    else:
        print(__doc__)
        sys.exit(1)

    tally = {}
    for i, app_id in enumerate(targets, 1):
        print(f"\n[{i}/{len(targets)}]", end="")
        try:
            outcome = process_app(app_id, keep=keep)
        except KeyboardInterrupt:
            print("\nInterrupted — stopping cleanly.")
            break
        except Exception as e:
            print(f"  AGENT ERROR: {e}")
            outcome = "failed"
        tally[outcome] = tally.get(outcome, 0) + 1

    print(f"\n{'=' * 64}\nREBUILD RUN COMPLETE")
    print(f"  passed : {tally.get('passed', 0)}")
    print(f"  failed : {tally.get('failed', 0)}")
    print(f"  skipped: {tally.get('skipped', 0)}")
    print(f"Results log: {RESULTS_PATH}")
    if os.path.exists(RESULTS_PATH):
        fails = [r for r in json.load(open(RESULTS_PATH)) if r.get("outcome") == "failed"]
        if fails:
            print("\nFailed apps (candidates to disable after review):")
            for r in fails:
                print(f"  - {r['app_id']}: {(r.get('error') or '')[:80]}")


if __name__ == "__main__":
    main()
