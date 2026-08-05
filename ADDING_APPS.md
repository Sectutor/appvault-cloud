# Adding a new app to the catalog — the guaranteed way

Every app must pass the **verified-install contract**: an install only reports
success after the app actually serves HTTP, and the same spec produces the same
result on every client machine. This document is the checklist for adding an
app so it NEVER lands half-broken (the historical failure mode: listmonk with an
empty image, traefik with malformed ports, nextcloud without its database).

---

## Step 0 — Research the app (30 min)

Get these facts from the official image docs / Docker Hub / GitHub:

| Fact | Where it goes |
|---|---|
| Official image name + tag | `image` |
| Web UI port inside the container | `container_port` |
| Persistent data paths | `volumes` |
| Required env (secrets, DB URLs, public URLs) | `env` |
| Database / Redis / companion services | `deps` |
| First-run behavior (migrations? default admin?) | `education` |
| Login path / health path for verification | `healthcheck.path` |
| Memory/disk footprint | `min_mem_mb`, `min_disk_gb` |

## Step 1 — Write the catalog entry

Edit `central/static/catalog.json` — new app in the `apps` array. **Every**
entry must include:

```json
{
  "id": "myapp",                      // lowercase, unique, used for container name app-myapp
  "name": "My App",
  "description": "What it does",
  "category": "productivity",         // ai | productivity | media | database | networking | security | automation ...
  "image": "org/myapp:latest",        // OR "compose_url" for multi-container stacks
  "container_port": 8080,             // web UI port INSIDE the container
  "web_path": "/",                    // subpath if the UI serves under one (e.g. /admin/)
  "volumes": ["myapp-data:/data"],    // named volume:container path
  "env": ["MYAPP_ADMIN_PASS=__AUTO__"],  // KEY=VALUE; __AUTO__ = random secret per install
  "extra_ports": {"80": "8087"},      // additional host ports — LITERAL NUMBERS ONLY (no ${VAR}!)
  "deps": [{                          // companion containers (DB/redis) — optional
    "name": "app-myapp-db",
    "image": "postgres:15-alpine",
    "env": ["POSTGRES_DB=myapp", "POSTGRES_USER=myapp", "POSTGRES_PASSWORD=myapp"],
    "volumes": ["myapp-db-data:/var/lib/postgresql/data"]
  }],
  "healthcheck": {                    // THE verification contract
    "port": 8080,                     // port inside the container to probe
    "path": "/",                      // path that proves the app is ready
    "expect": [200, 301, 302, 401, 403, 404]  // codes that count as "alive"
  },
  "boot_timeout": 180,                // seconds to become ready (slow AI apps: 300)
  "min_mem_mb": 512,                  // host must have this much free
  "min_disk_gb": 2,
  "free_tier": true,                  // true = all clients; false = premium (license)
  "education": {
    "docs_url": "https://docs.example.com",
    "quick_start": "One sentence on first-run setup.",
    "default_login": {"username": "admin", "password": "set on first login"},
    "setup_steps": ["Step 1", "Step 2"]
  }
}
```

### Rules (non-negotiable — these prevent the historical bugs)
1. **`image` XOR `compose_url`** — never both, never neither.
2. **`extra_ports` host ports are literal numbers** — `${VAR:-default}` indirection
   produced `invalid IP 8088` malformed containers. If a port must vary, use the
   engine's stable-port mechanism instead (`host_port` derivation).
3. **Every app has a `healthcheck`** with the correct probe port/path. If the
   image is scratch (no shell/curl/wget — e.g. `traefik`), the engine's
   caddy-probe covers it; pick the path that returns an expected code.
4. **DB/Redis dependencies go in `deps`** — the engine creates them with the app
   and rolls everything back on failure. Never assume "the client already has a
   database" (that was the nextcloud bug).
5. **`boot_timeout` reflects reality** — first boot with migrations is slow.
   Too low = verified install fails and rolls back; the client sees a clear error.
6. **`free_tier` is explicit** — missing = ambiguous gating.

## Step 2 — Validate

```bash
cd central
python validate_catalog.py static/catalog.json   # MUST exit 0
```

The validator checks: required fields, image/compose presence, healthcheck
completeness, literal ports, env syntax, dep completeness, boot_timeout and
resource minimums. **Do not ship with errors.**

## Step 3 — Test on the local agent (the guarantee)

```bash
# 1) reload the catalog (local central bind-mounts the file) + bump version
docker restart appvault-central
docker exec appvault-central python -c "import sqlite3; db=sqlite3.connect('/data/appvault.db'); db.execute('INSERT INTO catalog_versions (version) SELECT COALESCE(MAX(version),0)+1 FROM catalog_versions'); db.commit()"

# 2) wait for the local agent to resync (~60s), then verify it sees the entry
curl -s http://localhost:8086/api/catalog | python -c "import json,sys; d=json.load(sys.stdin); a=next((x for x in d['apps'] if x['id']=='myapp'), None); print(a['status'], a.get('healthcheck'))"

# 3) INSTALL through the engine (no docker run by hand!)
curl -s -X POST http://localhost:8086/api/install/myapp
# poll the status until done/error:
curl -s http://localhost:8086/api/install/myapp/status
```

**Pass = `stage: done`** and `docker ps` shows the app + its deps, and
`curl -s -o /dev/null -w '%{http_code}' http://localhost:<host_port>/` returns
an expected code.

**Fail = the engine rolled back and reported why** — fix the recipe, repeat.
`install_error` will show in the store UI.

## Step 4 — Determinism test (uninstall → reinstall)

```bash
curl -s -X POST http://localhost:8086/api/uninstall/myapp
# wait for done
curl -s -X POST http://localhost:8086/api/install/myapp
# wait for done — same result, same stable host port
```

If it verifies twice in a row, it will verify on every client (ports are
deterministic per app-id, deps are created fresh, verification is spec-driven).

## Step 5 — Ship to clients

```bash
# commit + push the catalog
cd central && git add static/catalog.json && git commit -m "catalog: add myapp (verified)" && git push origin master

# VPS central (the file must land at /data/catalog.json — the container's CATALOG_PATH):
scp static/catalog.json ubuntu@<vps>:/tmp/catalog.json
ssh ubuntu@<vps> "sudo docker cp /tmp/catalog.json appvault-central:/data/catalog.json && sudo docker restart appvault-central && sudo docker exec appvault-central python -c \"import sqlite3; db=sqlite3.connect('/data/appvault.db'); db.execute('INSERT INTO catalog_versions (version) SELECT COALESCE(MAX(version),0)+1 FROM catalog_versions'); db.commit()\""

# agents pick up the new version automatically (phone-home sync)
```

## Step 6 — Verify on the VPS (paid-plan path)

On the VPS: `POST /api/install/myapp` → poll status → `curl` the
`https://<vps-host>:<app-https-port>/` URL (auto-registered by the Caddy sync —
no manual Caddyfile edits).

---

## The guarantee in one sentence
**An app is "in the catalog" only when: validator passes → local verified install
→ reinstall verified → shipped to both centrals → VPS verified.** Anything less
and clients get the old failure modes.

---

## Updating apps for all clients (the update channel)

**The catalog IS the update channel.** To ship a new version of an app to every client:

1. **Bump the image tag** in `catalog.json` (e.g. `"n8nio/n8n:latest"` → a new pinned tag, or move the pin forward for versioned tags).
2. Commit + push, then sync BOTH centrals (local bind-mount + VPS `/data/catalog.json`) and bump the version on both — agents auto-sync within ~60s.
3. **Clients see "🔄 Update"** on the app's card (`update_available` = installed image ≠ catalog image).
4. Client clicks Update → the engine:
   - pulls the new image
   - recreates the container from the **spec** — same volumes (named + unified data dir), same stable host port (recorded in agent state), same deps (DBs untouched)
   - **waits for the healthcheck** before reporting success
   - **on failure: rolls back to the previous image** (still local) and reports the reason
5. Stacks (`compose_url`) update by re-running the verified stack installer (compose volumes persist).

**Data preservation is by construction:** the engine never touches volumes, never recreates dependency containers, and the container name/port never change (ports are recorded in `agent_state.json`). Data safety was proven with n8n across three consecutive updates (image changed nightly → latest, volume mount identical, port unchanged).

**Admin API:** `POST /api/update/<app_id>` (status via `/api/install/<app_id>/status`).
