#!/usr/bin/env python3
"""Upgrade catalog recipes to the verified-install spec.

Adds healthcheck / boot_timeout / min_mem_mb / min_disk_gb to every app and
fixes known-broken recipes (nextcloud DB dep, listmonk image+DB, traefik
literal ports). Deterministic: same spec on every client -> same result.
"""
import json, copy, sys

PATH = r"D:\DATA_INTELLFENCE\WebDev\AppVault\central\static\catalog.json"

with open(PATH, encoding="utf-8") as f:
    cat = json.load(f)

apps = cat.setdefault("apps", [])

DEFAULT_EXPECT = [200, 301, 302, 307, 401, 403, 404]

def cat_defaults(a):
    """Category-based sensible defaults (only applied when fields are absent)."""
    c = (a.get("category") or "").lower()
    if c == "ai":
        return {"boot_timeout": 300, "min_mem_mb": 2048, "min_disk_gb": 3}
    if c == "database":
        return {"boot_timeout": 60, "min_mem_mb": 512, "min_disk_gb": 2}
    if c in ("media", "productivity", "networking"):
        return {"boot_timeout": 180, "min_mem_mb": 1024, "min_disk_gb": 2}
    return {"boot_timeout": 150, "min_mem_mb": 512, "min_disk_gb": 2}

# ── Per-app recipe fixes ─────────────────────────────────────────────────
OVERRIDES = {
    "nextcloud": {
        "deps": [{
            "name": "app-nextcloud-db",
            "image": "mariadb:10.11",
            "env": [
                "MARIADB_DATABASE=nextcloud",
                "MARIADB_USER=nextcloud",
                "MARIADB_PASSWORD=nextcloud",
                "MARIADB_ROOT_PASSWORD=nextcloud",
            ],
            "volumes": ["nextcloud-db-data:/var/lib/mysql"],
        }],
        "healthcheck": {"port": 80, "path": "/index.php/login", "expect": [200, 302]},
        "boot_timeout": 300,
        "min_mem_mb": 1024,
        "min_disk_gb": 5,
    },
    "listmonk": {
        "image": "listmonk/listmonk:latest",
        "deps": [{
            "name": "app-listmonk-db",
            "image": "postgres:15-alpine",
            "env": [
                "POSTGRES_DB=listmonk",
                "POSTGRES_USER=listmonk",
                "POSTGRES_PASSWORD=listmonk",
            ],
            "volumes": ["listmonk-db-data:/var/lib/postgresql/data"],
        }],
        "healthcheck": {"port": 9000, "path": "/", "expect": [200, 302, 401, 403]},
        "boot_timeout": 120,
        "min_mem_mb": 512,
        "min_disk_gb": 2,
    },
    "traefik": {
        # Literal deterministic ports — the ${VAR:-default} indirection produced
        # malformed bindings ("invalid IP 8088") on some hosts.
        "extra_ports": {"80": "8088", "443": "8445"},
        # Enable the web dashboard on :8080 (static config via env, no args needed)
        "env": ["TRAEFIK_API_INSECURE=true", "TRAEFIK_API_DASHBOARD=true"],
        "healthcheck": {"port": 8080, "path": "/", "expect": [200, 302, 401, 404]},
        "boot_timeout": 60,
        "min_mem_mb": 256,
        "min_disk_gb": 1,
    },
}

changed = 0
for a in apps:
    aid = a.get("id", "")
    ov = OVERRIDES.get(aid, {})
    for k, v in ov.items():
        a[k] = copy.deepcopy(v)
        changed += 1
    # defaults for missing spec fields
    dfl = cat_defaults(a)
    if not a.get("healthcheck"):
        a["healthcheck"] = {
            "port": a.get("container_port") or 80,
            "path": "/",
            "expect": list(DEFAULT_EXPECT),
        }
        changed += 1
    for k, v in dfl.items():
        if a.get(k) in (None, ""):
            a[k] = v
            changed += 1

with open(PATH, "w", encoding="utf-8") as f:
    json.dump(cat, f, indent=2, ensure_ascii=False)

# sanity re-load
with open(PATH, encoding="utf-8") as f:
    chk = json.load(f)
missing = [a["id"] for a in chk["apps"] if not a.get("healthcheck")]
print(f"OK: {len(chk['apps'])} apps, {changed} field updates, apps without healthcheck: {missing or 'none'}")
