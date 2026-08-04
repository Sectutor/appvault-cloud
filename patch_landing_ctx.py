#!/usr/bin/env python3
"""Patch main.py: add _landing_ctx and pass catalog to landing/pricing templates."""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

path = r"C:\Users\emman\appvault-cloud-prod\main.py"
with open(path, encoding="utf-8-sig") as f:
    src = f.read()

OLD = '''@app.get("/")
async def landing(request: Request):
    return templates.TemplateResponse(request, "landing.html", {"request": request})

@app.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request):
    return templates.TemplateResponse(request, "landing.html", {"request": request})'''

NEW = '''@app.get("/")
async def landing(request: Request):
    ctx = _landing_ctx(request)
    return templates.TemplateResponse(request, "landing.html", ctx)

@app.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request):
    ctx = _landing_ctx(request)
    return templates.TemplateResponse(request, "landing.html", ctx)

def _landing_ctx(request: Request):
    """Build landing page context: visible (non-hidden) catalog apps with rich fields."""
    apps = [a for a in GLOBAL_CATALOG.get("apps", []) if not a.get("hidden")]
    return {
        "request": request,
        "catalog": {"apps": apps},
        "catalog_json": json.dumps({"apps": apps}, ensure_ascii=False),
    }'''

if OLD in src:
    src = src.replace(OLD, NEW)
    # Write back with BOM to preserve original encoding
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(src)
    print("PATCHED main.py landing/pricing routes")
else:
    print("OLD TEXT NOT FOUND - checking what's there...")
    idx = src.find('@app.get("/")')
    print(repr(src[idx:idx+400]))
