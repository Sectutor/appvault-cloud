"""
pilot_funnel.py — pilot landing page, lead capture, admin leads view.
Called from main.py via register_pilot_funnel(app, ...).
"""


def register_pilot_funnel(app, get_db, require_admin, _audit, HTMLResponse,
                          RedirectResponse, Request):
    """Attach pilot funnel routes to the FastAPI app."""

    def _init_leads_table():
        try:
            db = get_db()
            db.execute("""CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT DEFAULT '',
                email TEXT NOT NULL,
                company TEXT DEFAULT '',
                interest TEXT DEFAULT '',
                src TEXT DEFAULT 'direct',
                story TEXT DEFAULT '',
                status TEXT DEFAULT 'new',
                created TEXT DEFAULT (datetime('now'))
            )""")
            db.commit()
            db.close()
        except Exception as e:
            print(f"[leads] init failed: {e}")

    _init_leads_table()

    PILOT_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AppVault Pilot - Own your AI stack in 48 hours</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; background: #0a0e1a; color: #e2e8f0; line-height: 1.6; }
.wrap { max-width: 560px; margin: 60px auto; padding: 0 20px; }
.badge { display:inline-block; padding: 4px 14px; border-radius: 999px; background: rgba(56,189,248,.12); color:#38bdf8; font-size: 12px; font-weight: 700; letter-spacing: .5px; margin-bottom: 18px; }
h1 { font-size: 2rem; margin-bottom: 14px; background: linear-gradient(135deg,#38bdf8,#818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.sub { color: #94a3b8; margin-bottom: 28px; font-size: 15px; }
.card { background: #0f172a; border: 1px solid #1e293b; border-radius: 14px; padding: 28px; }
label { display:block; font-size: 12px; font-weight: 600; color:#94a3b8; margin: 14px 0 6px; }
input, select { width: 100%; padding: 10px 12px; border-radius: 8px; border: 1px solid #334155; background: #0a0e1a; color: #e2e8f0; font-size: 14px; }
input:focus, select:focus { outline: none; border-color: #38bdf8; }
button { width: 100%; margin-top: 22px; padding: 13px; border: none; border-radius: 8px; background: linear-gradient(135deg,#0284c7,#2563eb); color:#fff; font-size: 15px; font-weight: 700; cursor: pointer; }
button:hover { filter: brightness(1.1); }
.muted { color:#64748b; font-size: 13px; margin-top: 16px; text-align:center; }
</style></head><body>
<div class="wrap">
<span class="badge">FREE GUIDED PILOT</span>
<h1>Own your AI stack in 48 hours</h1>
<p class="sub">We deploy the tools you need on your own infrastructure, fully configured. No vendor lock-in. You keep everything.</p>
<div class="card">
<form method="POST" action="/pilot">
<input type="hidden" name="src" value="{src}">
<input type="hidden" name="story" value="{story}">
<label>Your name</label>
<input name="name" required placeholder="Jane Doe">
<label>Work email</label>
<input name="email" type="email" required placeholder="jane@company.com">
<label>Company (optional)</label>
<input name="company" placeholder="Acme Inc">
<label>What do you want to run?</label>
<select name="interest">
<option value="ai-stack">Self-hosted AI stack (chat, models, gateways)</option>
<option value="security">Security and monitoring tools</option>
<option value="automation">Automation and analytics</option>
<option value="not-sure">Not sure, help me choose</option>
</select>
<button type="submit">Request my free pilot</button>
</form>
<p class="muted">48h setup &middot; your hardware or our cloud &middot; cancel anytime</p>
</div>
</div>
</body></html>"""

    @app.get("/pilot")
    async def pilot_page(request: Request, src: str = "direct", story: str = ""):
        """Public pilot landing page - target of every tracked content CTA."""
        html = PILOT_PAGE.replace("{src}", src[:40]).replace("{story}", story[:80])
        return HTMLResponse(html)

    @app.post("/pilot")
    async def pilot_submit(request: Request):
        """Lead capture with content attribution."""
        form = await request.form()
        email = (form.get("email") or "").strip()
        if not email:
            return RedirectResponse("/pilot", status_code=303)
        db = get_db()
        db.execute(
            "INSERT INTO leads (name, email, company, interest, src, story) VALUES (?,?,?,?,?,?)",
            ((form.get("name") or "")[:100], email[:200], (form.get("company") or "")[:120],
             (form.get("interest") or "")[:40], (form.get("src") or "direct")[:40],
             (form.get("story") or "")[:80]))
        db.commit()
        db.close()
        _audit("lead.captured", f"{email} src={form.get('src', 'direct')}")
        return HTMLResponse(
            "<html><head><meta charset='UTF-8'><style>body{font-family:sans-serif;"
            "background:#0a0e1a;color:#e2e8f0;display:flex;align-items:center;"
            "justify-content:center;min-height:100vh;margin:0}.c{text-align:center;"
            "max-width:480px;padding:40px}h1{color:#4ade80}</style></head><body>"
            "<div class='c'><h1>&#10003; You're in.</h1><p>We'll reach out within "
            "one business day to schedule your pilot.</p></div></body></html>")

    @app.get("/admin/leads")
    async def admin_leads(request: Request):
        """Admin: pilot leads with content attribution."""
        if not request.session.get("admin"):
            return RedirectResponse("/login?next=/admin/leads", status_code=302)
        require_admin(request)
        db = get_db()
        rows = db.execute("SELECT * FROM leads ORDER BY id DESC LIMIT 500").fetchall()
        db.close()
        tr = "".join(
            f"<tr><td>{r['id']}</td><td>{r['name']}</td><td>{r['email']}</td>"
            f"<td>{r['company']}</td><td>{r['interest']}</td>"
            f"<td><code>{r['src']}</code></td><td><code>{(r['story'] or '')[:28]}</code></td>"
            f"<td><b>{r['status']}</b></td><td>{r['created']}</td></tr>"
            for r in rows)
        html = (
            f"<!DOCTYPE html><html><head><title>Pilot Leads</title><style>"
            f"body{{font-family:sans-serif;background:#0a0e1a;color:#e2e8f0;padding:24px}}"
            f"table{{border-collapse:collapse;width:100%;font-size:13px}}"
            f"th,td{{border:1px solid #1e293b;padding:8px;text-align:left}}"
            f"th{{background:#0f172a;color:#38bdf8}}code{{color:#38bdf8}}</style></head><body>"
            f"<h1>Pilot Leads ({len(rows)})</h1>"
            f"<table><tr><th>#</th><th>Name</th><th>Email</th><th>Company</th>"
            f"<th>Interest</th><th>Source</th><th>Story</th><th>Status</th>"
            f"<th>Created</th></tr>{tr}</table></body></html>")
        return HTMLResponse(html)
