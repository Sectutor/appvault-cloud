"""
market.py — AppVault Market: in-app sales of proprietary apps.

Model:
  - Free tier: open-source catalog apps (never sold)
  - Market: proprietary apps (ours + invited publishers), yearly license,
    fixed per-app pricing, 30-day money-back
  - Secure: same license + Tailscale hosting add-on

Tables:
  market_products  — the storefront catalog of sellable apps
  app_licenses     — yearly per-app licenses (365-day, bound to agent)

Public endpoints (registered on the central FastAPI app):
  GET  /api/market                 — storefront listing
  GET  /api/market/{app_id}        — product detail
  POST /api/market/{app_id}/checkout — Stripe Checkout (one-time yearly payment)
  GET  /api/market/{app_id}/entitlement?agent_id=  — does this agent own it?
  POST /api/market/webhook         — Stripe webhook (purchase + refund)

Admin:
  GET/POST /admin/market           — manage products
"""


def register_market(app, get_db, require_admin, _audit, HTMLResponse,
                    RedirectResponse, Request, jsonify, DOMAIN):
    import json as _json
    import os as _os
    import re as _re
    import time as _time
    import uuid as _uuid
    from fastapi.responses import JSONResponse as _JR

    STRIPE_SECRET_KEY = _os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = _os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    # ── schema ────────────────────────────────────────────────────────────
    def _init_tables():
        try:
            db = get_db()
            db.executescript("""
            CREATE TABLE IF NOT EXISTS market_products (
                app_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                tagline TEXT DEFAULT '',
                description TEXT DEFAULT '',
                category TEXT DEFAULT 'productivity',
                publisher TEXT DEFAULT 'AppVault',
                price_yearly_cents INTEGER NOT NULL,
                value_anchor_cents INTEGER DEFAULT 0,
                currency TEXT DEFAULT 'usd',
                deploy_desktop INTEGER DEFAULT 1,
                deploy_secure INTEGER DEFAULT 0,
                secure_price_yearly_cents INTEGER DEFAULT 0,
                screenshots TEXT DEFAULT '[]',
                features TEXT DEFAULT '[]',
                faq TEXT DEFAULT '[]',
                icon_emoji TEXT DEFAULT '💎',
                active INTEGER DEFAULT 1,
                coming_soon INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS app_licenses (
                key TEXT PRIMARY KEY,
                app_id TEXT NOT NULL,
                email TEXT NOT NULL,
                agent_id TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                expires_at TEXT NOT NULL,
                stripe_session_id TEXT,
                stripe_payment_intent TEXT DEFAULT '',
                refunded INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            """)
            db.commit()
            db.close()
        except Exception as e:
            print(f"[market] init failed: {e}")

    _init_tables()

    # ── helpers ───────────────────────────────────────────────────────────
    def _gen_key(app_id):
        return f"AVM-{app_id.upper()[:8]}-{_uuid.uuid4().hex[:12].upper()}"

    def _expiry_date(days=365):
        import datetime
        return (datetime.datetime.utcnow() +
                datetime.timedelta(days=days)).strftime("%Y-%m-%d")

    def _license_valid(key):
        db = get_db()
        row = db.execute(
            "SELECT status, expires_at, refunded FROM app_licenses WHERE key=?",
            (key,)).fetchone()
        db.close()
        if not row or row["status"] != "active" or row["refunded"]:
            return False
        return row["expires_at"] >= _time.strftime("%Y-%m-%d")

    def _seed_defaults():
        """Seed launch products if table empty."""
        db = get_db()
        n = db.execute("SELECT COUNT(*) c FROM market_products").fetchone()["c"]
        if n == 0:
            db.executescript("""
            INSERT INTO market_products
              (app_id, name, tagline, description, category, publisher,
               price_yearly_cents, value_anchor_cents, icon_emoji,
               deploy_desktop, deploy_secure, secure_price_yearly_cents,
               features, coming_soon)
            VALUES
             ('complianceos', 'ComplianceOS / GRC Suite',
              'Full GRC program: policies, controls, audits, risk register, evidence management.',
              'ComplianceOS is a complete governance-risk-compliance platform for SMBs and MSPs.
Run your entire compliance program - policy library, control mapping, audit trails,
risk quantification and client management - on your own infrastructure. Your data never
leaves your network. Includes all premium modules and 12 months of updates.',
              'security', 'AppVault (Sectutor)',
              99900, 240000, '🛡️', 1, 1, 59900,
              '["Policy & control library with framework mapping","Risk register with quantification","Audit trail & evidence collection","Multi-client management for MSPs","Runs fully offline on your hardware","12 months of updates included"]',
              0),
             ('writerstudio', 'WriterStudioAI',
              'AI book writing studio - voice-matched chapters, covers, KDP-ready exports.',
              'WriterStudioAI turns an idea into a publish-ready book. Plan with the AI agent,
generate voice-matched chapters with your own API keys, then use the publishing engine:
print-ready PDF, ePub, cover wrap with spine math and the full KDP metadata suite.
Your manuscripts and API keys stay on your own infrastructure.',
              'ai', 'AppVault (Sectutor)',
              9900, 29400, '✍️', 1, 0, 0,
              '["Voice-matched AI chapter generation (BYOK)","Print-ready KDP PDF + ePub exports","Paperback cover wrap with spine math","KDP metadata suite: keywords, categories, blurb","Runs fully offline on your hardware","12 months of updates included"]',
              0);
            """)
            db.commit()
        # One-time data migration: flip the launch placeholder row for
        # writerstudio to live now that the installable app + license bridge
        # exist. Keyed on the old placeholder description so a deliberate
        # later coming_soon=1 (with updated copy) is never overridden.
        try:
            db = get_db()
            db.execute(
                """UPDATE market_products
                   SET coming_soon=0, deploy_desktop=1,
                       description='WriterStudioAI turns an idea into a publish-ready book. Plan with the AI agent,
generate voice-matched chapters with your own API keys, then use the publishing engine:
print-ready PDF, ePub, cover wrap with spine math and the full KDP metadata suite.
Your manuscripts and API keys stay on your own infrastructure.',
                       features='["Voice-matched AI chapter generation (BYOK)","Print-ready KDP PDF + ePub exports","Paperback cover wrap with spine math","KDP metadata suite: keywords, categories, blurb","Runs fully offline on your hardware","12 months of updates included"]'
                   WHERE app_id='writerstudio' AND coming_soon=1
                     AND description LIKE 'WriterStudioAI is a desktop AI writing studio%'""")
            db.commit()
            db.close()
        except Exception as _mig_err:
            print(f"[market] writerstudio migration skipped: {_mig_err}")

    _seed_defaults()

    # ── public API ────────────────────────────────────────────────────────
    @app.get("/api/market")
    async def market_list():
        db = get_db()
        rows = db.execute(
            "SELECT * FROM market_products WHERE active=1 ORDER BY price_yearly_cents DESC"
        ).fetchall()
        db.close()
        out = []
        for r in rows:
            d = dict(r)
            d["features"] = _json.loads(d.get("features") or "[]")
            d["screenshots"] = _json.loads(d.get("screenshots") or "[]")
            d["faq"] = _json.loads(d.get("faq") or "[]")
            out.append(d)
        return _JR({"products": out})

    @app.get("/api/market/{app_id}")
    async def market_detail(app_id: str):
        db = get_db()
        r = db.execute("SELECT * FROM market_products WHERE app_id=? AND active=1",
                       (app_id,)).fetchone()
        db.close()
        if not r:
            return _JR({"error": "not found"}), 404
        d = dict(r)
        for f in ("features", "screenshots", "faq"):
            d[f] = _json.loads(d.get(f) or "[]")
        return _JR(d)

    @app.post("/api/market/{app_id}/checkout")
    async def market_checkout(app_id: str, request: Request):
        body = await request.json()
        email = (body.get("email") or "").strip()
        agent_id = (body.get("agent_id") or "").strip()
        include_secure = bool(body.get("secure", False))

        if not STRIPE_SECRET_KEY:
            return _JR({"error": "checkout-not-configured",
                        "detail": "Stripe is not configured on this instance"}), 503

        import stripe
        stripe.api_key = STRIPE_SECRET_KEY

        db = get_db()
        prod = db.execute(
            "SELECT * FROM market_products WHERE app_id=? AND active=1",
            (app_id,)).fetchone()
        if not prod:
            db.close()
            return _JR({"error": "not found"}), 404
        if prod["coming_soon"]:
            db.close()
            return _JR({"error": "coming-soon"}), 400

        total = prod["price_yearly_cents"]
        lines = [{
            "price_data": {
                "currency": prod["currency"],
                "product_data": {
                    "name": f"{prod['name']} — 1 year license",
                    "description": (prod["tagline"] or "")[:300],
                },
                "unit_amount": prod["price_yearly_cents"],
            },
            "quantity": 1,
        }]
        if include_secure and prod["deploy_secure"] and prod["secure_price_yearly_cents"]:
            total += prod["secure_price_yearly_cents"]
            lines.append({
                "price_data": {
                    "currency": prod["currency"],
                    "product_data": {"name": f"{prod['name']} — Secure Hosting (1 year)"},
                    "unit_amount": prod["secure_price_yearly_cents"],
                },
                "quantity": 1,
            })

        key = _gen_key(app_id)
        db.execute(
            """INSERT INTO app_licenses (key, app_id, email, agent_id, status, expires_at)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (key, app_id, email, agent_id, _expiry_date()))
        db.execute(
            "INSERT INTO instances (id, email, tier, status, license_key) VALUES (?, ?, ?, 'pending', ?)",
            (f"mkt-{_uuid.uuid4().hex[:12]}", email, f"market:{app_id}", key))
        db.commit()
        db.close()

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=lines,
                mode="payment",   # ONE-TIME yearly contract - no subscription
                customer_email=email or None,
                success_url=f"https://{DOMAIN}/market/acknowledge?key={key}",
                cancel_url=f"https://{DOMAIN}/market",
                metadata={
                    "kind": "market_purchase",
                    "app_id": app_id,
                    "license_key": key,
                    "agent_id": agent_id,
                    "email": email,
                    "secure": "1" if include_secure else "0",
                },
            )
        except Exception as e:
            print(f"[market] checkout failed: {e}", flush=True)
            return _JR({"error": "checkout-failed", "detail": str(e)[:200]}), 500

        _audit("market.checkout", f"{app_id} key={key[:14]}...")
        return _JR({"url": session.url, "license_key": key})

    @app.get("/api/market/{app_id}/entitlement")
    async def market_entitlement(app_id: str, agent_id: str = ""):
        """Does an agent own a valid license for this app?
        Also accepts a license key directly via ?key="""
        db = get_db()
        key = None
        # resolve via query param handled by FastAPI below
        rows = db.execute(
            """SELECT key, status, expires_at, refunded FROM app_licenses
               WHERE app_id=? AND (?='' OR agent_id=?)
               ORDER BY created_at DESC""",
            (app_id, agent_id, agent_id)).fetchall()
        db.close()
        now = _time.strftime("%Y-%m-%d")
        for row in rows:
            if row["status"] == "active" and not row["refunded"] and row["expires_at"] >= now:
                return _JR({"licensed": True, "expires_at": row["expires_at"],
                            "key": row["key"]})
        return _JR({"licensed": False})

    # ── WriterStudioAI bridge ────────────────────────────────────────────
    async def _issue_writerstudio_license(email: str, order_id: str):
        """Call WriterStudioAI's webhook to issue + email its offline Ed25519 license.

        Yearly Market license -> 365-day app token the buyer activates in the
        app (Settings -> License). Failures are logged only; the Market license
        itself was already activated by the caller.
        """
        url = _os.environ.get("WRITERSTUDIO_WEBHOOK_URL", "")
        secret = _os.environ.get("APPVAULT_WEBHOOK_SECRET", "")
        if not email or not url or not secret:
            return
        import hmac as _hmac
        import hashlib as _hashlib
        body = _json.dumps({"app": "aiwriter", "email": email, "tier": "market_annual",
                            "plan": "annual", "expDays": 365, "order_id": order_id})
        sig = _hmac.new(secret.encode(), body.encode(), _hashlib.sha256).hexdigest()
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, content=body.encode(),
                                         headers={"Content-Type": "application/json", "x-signature": sig},
                                         timeout=15)
                _audit("market.writerstudio", f"{email} status={resp.status_code}")
        except Exception as e:
            _audit("market.writerstudio.error", f"{email} {e}")

    # ── Stripe webhook (shared endpoint pattern from main.py; separate kind) ──
    @app.post("/api/market/webhook")
    async def market_webhook(request: Request):
        payload = await request.body()
        sig = request.headers.get("stripe-signature", "")
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        try:
            if STRIPE_WEBHOOK_SECRET:
                event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
            else:
                event = _json.loads(payload)
        except Exception as e:
            return _JR({"error": str(e)}), 400

        etype = event.get("type", "") if isinstance(event, dict) else event.type
        data = event.get("data", {}).get("object", {}) if isinstance(event, dict) else event.data.object

        if etype == "checkout.session.completed":
            meta = data.get("metadata") or {}
            if meta.get("kind") != "market_purchase":
                return _JR({"received": True, "ignored": "not-market"})
            key = meta.get("license_key", "")
            email = meta.get("email", "")
            agent_id = meta.get("agent_id", "")
            db = get_db()
            db.execute(
                """UPDATE app_licenses SET status='active', stripe_session_id=?,
                   stripe_payment_intent=?,
                   email=CASE WHEN ?='' THEN email ELSE ? END,
                   agent_id=CASE WHEN ?='' THEN agent_id ELSE ? END
                   WHERE key=? AND status='pending'""",
                (data.get("id"), data.get("payment_intent") or "",
                 email, email, agent_id, agent_id, key))
            db.commit()
            db.close()
            _audit("market.purchase", f"activated {key[:14]}... {meta.get('app_id')}")

            # WriterStudioAI: also issue the app-internal offline license key
            if meta.get("app_id") == "writerstudio":
                row_email = ""
                try:
                    db = get_db()
                    r = db.execute("SELECT email FROM app_licenses WHERE key=?", (key,)).fetchone()
                    db.close()
                    row_email = r["email"] if r else ""
                except Exception:
                    pass
                await _issue_writerstudio_license(row_email or email, data.get("id", ""))
        elif etype == "charge.refunded":
            # Refund -> revoke the license (30-day money-back enforcement)
            payment_intent = data.get("payment_intent") or ""
            db = get_db()
            db.execute(
                "UPDATE app_licenses SET refunded=1, status='revoked' "
                "WHERE stripe_session_id=? OR stripe_payment_intent=?",
                (data.get("id"), payment_intent))
            db.commit()
            db.close()
            _audit("market.refund", f"revoked license (pi:{payment_intent[:18]}...)")

        return _JR({"received": True})

    # ── admin UI ──────────────────────────────────────────────────────────
    @app.get("/admin/market")
    async def admin_market(request: Request):
        if not request.session.get("admin"):
            return RedirectResponse("/login?next=/admin/market", status_code=302)
        require_admin(request)
        db = get_db()
        prods = [dict(r) for r in db.execute(
            "SELECT * FROM market_products ORDER BY name").fetchall()]
        lic_count = db.execute(
            "SELECT app_id, COUNT(*) c FROM app_licenses WHERE status='active' GROUP BY app_id"
        ).fetchall()
        recent = [dict(r) for r in db.execute(
            "SELECT * FROM app_licenses ORDER BY created_at DESC LIMIT 20").fetchall()]
        db.close()
        counts = {r["app_id"]: r["c"] for r in lic_count}

        rows_html = ""
        for p in prods:
            rows_html += (
                f"<tr><td><b>{p['name']}</b><br><code>{p['app_id']}</code></td>"
                f"<td>${p['price_yearly_cents']/100:,.0f}/yr</td>"
                f"<td>{p['publisher']}</td>"
                f"<td>{counts.get(p['app_id'], 0)} sold</td>"
                f"<td>{'🚧 soon' if p['coming_soon'] else ('🟢 active' if p['active'] else '🔴 off')}</td></tr>")
        lic_rows = "".join(
            f"<tr><td><code>{r['key'][:20]}…</code></td><td>{r['app_id']}</td>"
            f"<td>{r['email']}</td><td>{r['status']}</td>"
            f"<td>{r['expires_at']}</td><td>{r['created_at']}</td></tr>"
            for r in recent)

        html = f"""<!DOCTYPE html><html><head><title>Market Admin</title><style>
body{{font-family:sans-serif;background:#0a0e1a;color:#e2e8f0;padding:24px}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-bottom:28px}}
th,td{{border:1px solid #1e293b;padding:8px;text-align:left}}
th{{background:#0f172a;color:#38bdf8}}code{{color:#38bdf8}}
h1,h2{{color:#38bdf8}}</style></head><body>
<h1>💎 AppVault Market</h1>
<h2>Products</h2>
<table><tr><th>App</th><th>Price</th><th>Publisher</th><th>Sold</th><th>Status</th></tr>
{rows_html}</table>
<h2>Recent Licenses</h2>
<table><tr><th>Key</th><th>App</th><th>Email</th><th>Status</th><th>Expires</th><th>Created</th></tr>
{lic_rows or '<tr><td colspan=6>No licenses yet</td></tr>'}</table>
</body></html>"""
        return HTMLResponse(html)

    print("[central] market registered (/api/market, /admin/market)")
