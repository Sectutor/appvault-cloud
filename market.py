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

# ─── App license token signing (Ed25519 JWT, WriterStudio-compatible) ─────
# These helpers live at module level (outside register_market) so they can be
# unit-tested and reused without importing FastAPI. The token format MUST stay
# byte-compatible with the app's verifier (src/lib/server/licensing.ts):
#   header   {"typ":"JWT","alg":"EdDSA"}          (compact JSON, typ first)
#   payload  claims JSON with keys SORTED alphabetically (stableJson)
#   sig      Ed25519 over the ASCII "h.p", base64url, no padding


def normalize_private_key_pem(raw):
    """Tolerant PEM normalizer for LICENSE_PRIVATE_KEY_PEM env values that
    Docker UIs / CI flatten or escape. Returns a clean PKCS8 PEM or None."""
    import base64 as _b64
    import re as _re

    s = (raw or "").strip()
    if not s:
        return None
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1].strip()
    if "\\n" in s:
        s = s.replace("\\n", "\n")
    if "\n" not in s and "BEGIN PRIVATE KEY" in s:
        body = _re.sub(r"[\s]+", "", s)
        body = (body.replace("-----BEGINPRIVATEKEY-----", "")
                    .replace("-----ENDPRIVATEKEY-----", "")
                    .replace("-----BEGIN PRIVATE KEY-----", "")
                    .replace("-----END PRIVATE KEY-----", ""))
        if not body or not _re.fullmatch(r"[A-Za-z0-9+/=]+", body):
            return None
        s = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(
            body[i:i + 64] for i in range(0, len(body), 64)
        ) + "\n-----END PRIVATE KEY-----"
    return s if "\n" in s else None


def sign_app_license_token(private_key_pem, email, ent, plan="annual", days=365):
    """Sign an offline Ed25519 JWT license accepted by WriterStudio's
    /api/license activation. Returns the token string or None on failure."""
    import json as _json
    import time as _time
    import base64 as _b64

    pem = normalize_private_key_pem(private_key_pem)
    if not pem:
        return None
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives import serialization

        key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(key, ed25519.Ed25519PrivateKey):
            return None

        def _b64url(data: bytes) -> str:
            return _b64.urlsafe_b64encode(data).decode().rstrip("=")

        now = int(_time.time())
        claims = {"v": 1, "sub": email, "plan": plan, "ent": ent, "iat": now}
        if plan in ("annual", "trial"):
            claims["exp"] = now + int(days) * 86400
        header = _json.dumps({"typ": "JWT", "alg": "EdDSA"},
                             separators=(",", ":"), ensure_ascii=False)
        payload = _json.dumps({k: claims[k] for k in sorted(claims)},
                              separators=(",", ":"), ensure_ascii=False)
        h = _b64url(header.encode())
        p = _b64url(payload.encode())
        sig = key.sign(f"{h}.{p}".encode())
        return f"{h}.{p}.{_b64url(sig)}"
    except Exception as e:
        print(f"[market] license signing failed: {e}", flush=True)
        return None


# Market purchase → app entitlements. Mirrors the app's TIER_MAP
# ("market_annual"): starter features + BYOK for the yearly market license.
MARKET_APP_ENTITLEMENTS = ["starter", "byok"]
MARKET_LICENSE_DAYS = 365


def register_market(app, get_db, require_admin, _audit, HTMLResponse,
                    RedirectResponse, Request, jsonify, DOMAIN):
    import json as _json
    import os as _os
    import re as _re
    import time as _time
    import uuid as _uuid
    from fastapi.responses import JSONResponse as _JR

    def _err(payload, status):
        """FastAPI-compatible error response (Flask-style (body, status) tuples
        are NOT supported by FastAPI and would return 200 with a broken body)."""
        return _JR(payload, status_code=status)

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
                app_token TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            );
            """)
            # Existing DBs (created before app_token) need the column added.
            try:
                db.execute("ALTER TABLE app_licenses ADD COLUMN app_token TEXT DEFAULT ''")
            except Exception:
                pass  # column already exists
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
            return _err({"error": "not found"}, 404)
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
            return _err({"error": "checkout-not-configured",
                         "detail": "Stripe is not configured on this instance"}, 503)

        import stripe
        stripe.api_key = STRIPE_SECRET_KEY

        db = get_db()
        prod = db.execute(
            "SELECT * FROM market_products WHERE app_id=? AND active=1",
            (app_id,)).fetchone()
        if not prod:
            db.close()
            return _err({"error": "not found"}, 404)
        if prod["coming_soon"]:
            db.close()
            return _err({"error": "coming-soon"}, 400)

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
                    "order_id": key,  # our order reference = the AVM license key
                    "agent_id": agent_id,
                    "email": email,
                    "secure": "1" if include_secure else "0",
                },
            )
        except Exception as e:
            print(f"[market] checkout failed: {e}", flush=True)
            return _err({"error": "checkout-failed", "detail": str(e)[:200]}, 500)

        _audit("market.checkout", f"{app_id} key={key[:14]}...")
        return _JR({"url": session.url, "license_key": key})

    @app.get("/api/market/{app_id}/entitlement")
    async def market_entitlement(app_id: str, agent_id: str = "", key: str = ""):
        """Does an agent own a valid license for this app?
        Lookup by agent_id (default) or by license key directly via ?key="""
        db = get_db()
        key = (key or "").strip()
        if key:
            rows = db.execute(
                """SELECT key, status, expires_at, refunded, app_token FROM app_licenses
                   WHERE app_id=? AND key=?""",
                (app_id, key)).fetchall()
        else:
            rows = db.execute(
                """SELECT key, status, expires_at, refunded, app_token FROM app_licenses
                   WHERE app_id=? AND (?='' OR agent_id=?)
                   ORDER BY created_at DESC""",
                (app_id, agent_id, agent_id)).fetchall()
        db.close()
        now = _time.strftime("%Y-%m-%d")
        for row in rows:
            if row["status"] == "active" and not row["refunded"] and row["expires_at"] >= now:
                resp = {"licensed": True, "expires_at": row["expires_at"],
                        "key": row["key"]}
                # The signed offline app token: the agent injects it into the
                # app container (LICENSE_KEY env) at install time so buyer
                # activation is automatic, not frontend-dependent.
                try:
                    resp["app_token"] = row["app_token"] or ""
                except Exception:
                    resp["app_token"] = ""
                return _JR(resp)
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
        # Fail-closed: never accept webhooks without a configured signing
        # secret. Without this, any unauthenticated POST could mint an
        # active license for any email + AVM-key. Match main.py's pattern.
        if not STRIPE_WEBHOOK_SECRET:
            print("[market] Rejected webhook: STRIPE_WEBHOOK_SECRET not configured", flush=True)
            return _err({"error": "webhook not configured"}, 503)

        payload = await request.body()
        sig = request.headers.get("stripe-signature", "")
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        try:
            event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        except Exception as e:
            return _err({"error": str(e)}, 400)

        etype = event.get("type", "") if isinstance(event, dict) else event.type
        data = event.get("data", {}).get("object", {}) if isinstance(event, dict) else event.data.object

        if etype == "checkout.session.completed":
            meta = data.get("metadata") or {}
            if meta.get("kind") != "market_purchase":
                return _JR({"received": True, "ignored": "not-market"})
            key = meta.get("license_key", "")
            email = meta.get("email", "")
            agent_id = meta.get("agent_id", "")
            app_id = meta.get("app_id", "")

            # Sign the vendor app's offline license token (Ed25519 JWT) so the
            # buyer can activate the app itself, not just the AppVault install.
            # The signing key NEVER leaves this server; the app only embeds the
            # public half. Failure to sign is logged but does not fail the
            # webhook — the AppVault-level license still activates below.
            app_token = sign_app_license_token(
                _os.environ.get("LICENSE_PRIVATE_KEY_PEM", ""),
                email or "buyer@appvault.local",
                MARKET_APP_ENTITLEMENTS,
                plan="annual", days=MARKET_LICENSE_DAYS)
            if not app_token and email:
                print("[market] WARNING: app token not signed "
                      "(LICENSE_PRIVATE_KEY_PEM missing/unparseable on central)",
                      flush=True)

            db = get_db()
            db.execute(
                """UPDATE app_licenses SET status='active', stripe_session_id=?,
                   stripe_payment_intent=?,
                   email=CASE WHEN ?='' THEN email ELSE ? END,
                   agent_id=CASE WHEN ?='' THEN agent_id ELSE ? END,
                   app_token=CASE WHEN ?='' THEN app_token ELSE ? END
                   WHERE key=? AND status='pending'""",
                (data.get("id"), data.get("payment_intent") or "",
                 email, email, agent_id, agent_id,
                 app_token, app_token, key))
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

            # Email the buyer their app license key (delivery of record; the
            # agent also injects it at install time). Non-fatal on failure.
            if app_token and email:
                try:
                    db = get_db()
                    pr = db.execute("SELECT name FROM market_products WHERE app_id=?",
                                    (meta.get("app_id", ""),)).fetchone()
                    db.close()
                    prod_name = (pr["name"] if pr else None) or meta.get("app_id") or "AppVault Market app"
                    from main import send_email  # runtime import avoids cycle
                    send_email(
                        email,
                        f"Your {prod_name} License Key — Activate Now",
                        f"""<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:32px">
  <h2>Welcome to {_re.escape(prod_name)}! 🎉</h2>
  <p>Thank you for your purchase (AppVault order <code>{_re.escape(key)}</code>).
     Your <strong>1-Year Market License</strong> is below.</p>
  <h3>How to Activate</h3>
  <ol>
    <li>Open {_re.escape(prod_name)} in your AppVault dashboard (it activates automatically when installed through AppVault).</li>
    <li>Otherwise: <strong>Settings → License</strong> → paste your key → <strong>Activate</strong>.</li>
  </ol>
  <div style="background:#f5f5f5;border-radius:8px;padding:16px;margin:24px 0">
    <p style="margin:0 0 8px;font-size:12px;color:#666;font-weight:600;text-transform:uppercase;letter-spacing:.05em">Your License Key</p>
    <p style="margin:0;font-family:monospace;font-size:12px;word-break:break-all">{app_token}</p>
  </div>
  <p style="color:#666;font-size:14px">✅ Valid for <strong>{MARKET_LICENSE_DAYS} days</strong> — renewals issue a fresh key.<br>
  ✅ Works <strong>100% offline</strong> — no internet connection required after activation.</p>
</div>""")
                except Exception as e:
                    print(f"[market] license email failed: {e}", flush=True)
        elif etype == "charge.refunded":
            # Refund -> revoke the license (30-day money-back enforcement).
            # The offline app token cannot be revoked remotely (by design the
            # app verifies offline); the annual expiry bounds the exposure and
            # the token is cleared here so the agent stops delivering it.
            payment_intent = data.get("payment_intent") or ""
            db = get_db()
            db.execute(
                "UPDATE app_licenses SET refunded=1, status='revoked', app_token='' "
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

    # ── post-purchase pages (Stripe success/cancel URLs point here) ──────
    @app.get("/market/acknowledge")
    async def market_acknowledge(key: str = ""):
        """Stripe success landing page. The license itself is activated by the
        /api/market/webhook (checkout.session.completed); this page just tells
        the buyer what happens next and shows their key for safe-keeping."""
        key = (key or "").strip()[:40]
        safe_key = _re.sub(r"[^A-Za-z0-9\-]", "", key)
        html = f"""<!DOCTYPE html><html><head><title>License activated — AppVault Market</title><style>
body{{font-family:sans-serif;background:#0a0e1a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.box{{max-width:520px;padding:36px;background:#0f172a;border:1px solid #1e293b;border-radius:14px;text-align:center}}
h1{{color:#4ade80;font-size:20px;margin:0 0 10px}}p{{color:#94a3b8;font-size:14px;line-height:1.6}}
code{{display:inline-block;margin:14px 0;padding:8px 14px;background:#0a0e1a;border:1px solid #334155;border-radius:8px;color:#38bdf8;font-size:13px;user-select:all}}
</style></head><body><div class="box">
<h1>✅ Payment received — license active</h1>
<p>Your yearly license is being activated right now (usually instant).</p>
{f'<p>Keep your license key:</p><code>{safe_key}</code>' if safe_key else ''}
<p><b style="color:#e2e8f0;">Next step:</b> go back to your AppVault dashboard,
open the 💎 <b>Market</b> tab (or the app's Install button) — the app is now
unlocked for this machine.</p>
<p style="font-size:12px;">30-day money-back guarantee · support@appvault.com</p>
</div></body></html>"""
        return HTMLResponse(html)

    @app.get("/market")
    async def market_landing():
        """Stripe cancel_url target — send the buyer back to central's root."""
        return RedirectResponse("/", status_code=302)

    print("[central] market registered (/api/market, /admin/market)")
