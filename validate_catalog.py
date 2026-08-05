#!/usr/bin/env python3
"""Validate every catalog entry has a complete, installable spec.

The productization guarantee: if an app passes this validator AND the local
install test, it will install + verify identically on every client. Run before
every catalog change:

    python validate_catalog.py [path/to/catalog.json]

Exit code 0 = all entries spec-complete (warnings may exist). 1 = errors.
"""
import json
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "static/catalog.json"

REQUIRED = ["id", "name", "category", "container_port", "free_tier"]
IMAGE_OR_COMPOSE = ["image", "compose_url"]
HC_REQUIRED = ["port", "path", "expect"]

errors = []
warnings = []

with open(PATH, encoding="utf-8") as f:
    cat = json.load(f)

apps = cat.get("apps", [])
if not isinstance(apps, list) or not apps:
    print("ERROR: catalog has no apps list")
    sys.exit(1)

ids = [a.get("id") for a in apps]
dupes = {i for i in ids if ids.count(i) > 1}
if dupes:
    errors.append(f"duplicate app ids: {sorted(dupes)}")

for a in apps:
    aid = a.get("id", "<no-id>")
    # 1) required core fields
    for field in REQUIRED:
        if field not in a or a.get(field) in (None, "", []):
            errors.append(f"{aid}: missing required field '{field}'")
    # 2) image XOR compose_url
    has_img = bool(a.get("image"))
    has_comp = bool(a.get("compose_url") or a.get("is_stack"))
    if not has_img and not has_comp:
        errors.append(f"{aid}: needs 'image' (single container) or 'compose_url' (stack)")
    if has_img and has_comp:
        warnings.append(f"{aid}: has BOTH image and compose_url — engine uses compose_url (stack path)")
    # 3) healthcheck spec (the verification contract)
    hc = a.get("healthcheck") or {}
    for field in HC_REQUIRED:
        if field not in hc or hc.get(field) in (None, "", []):
            errors.append(f"{aid}: healthcheck missing '{field}' (need port/path/expect)")
    if hc.get("port") and a.get("container_port") and int(hc.get("port")) != int(a.get("container_port")):
        warnings.append(f"{aid}: healthcheck port {hc.get('port')} != container_port {a.get('container_port')} "
                        f"(ok only if the UI port differs from the health port)")
    expect = hc.get("expect") or []
    if not isinstance(expect, list) or not all(isinstance(e, int) for e in expect):
        errors.append(f"{aid}: healthcheck expect must be a list of ints, got {expect!r}")
    # 4) timeouts + resources
    for field in ("boot_timeout", "min_mem_mb", "min_disk_gb"):
        v = a.get(field)
        if v is None or (isinstance(v, (int, float)) and v <= 0):
            errors.append(f"{aid}: missing/zero '{field}' (boot_timeout, min_mem_mb, min_disk_gb)")
    # 5) env entries must be KEY=VALUE
    for e in a.get("env", []):
        if "=" not in str(e):
            errors.append(f"{aid}: env entry without '=': {e!r}")
    # 6) deps must have name + image
    for dep in a.get("deps", []):
        if not dep.get("name") or not dep.get("image"):
            errors.append(f"{aid}: dep missing name/image: {dep}")
    # 7) volumes: named volumes must be listed in compose_url stacks OR be valid names
    for v in a.get("volumes", []):
        if not isinstance(v, str) or ":" not in v:
            warnings.append(f"{aid}: volume entry looks off: {v!r}")
    # 8) port sanity: extra_ports values must be numbers (no ${VAR:-} indirection)
    for cp, hp in (a.get("extra_ports") or {}).items():
        if not str(hp).isdigit():
            errors.append(f"{aid}: extra_port {cp} has non-literal host port {hp!r} "
                          f"(determinism: use a literal number)")
    # 9) web_path normalization
    wp = a.get("web_path")
    if wp and not str(wp).startswith("/"):
        warnings.append(f"{aid}: web_path should start with '/': {wp!r}")

print(f"checked {len(apps)} apps: {len(errors)} errors, {len(warnings)} warnings")
for e in errors:
    print("  ERROR  ", e)
for w in warnings:
    print("  WARN   ", w)
sys.exit(1 if errors else 0)
