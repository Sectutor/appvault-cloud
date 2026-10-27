"""Webhook ownership: only paid AppVault Checkout sessions mint a licence.

The Stripe account is shared with other products. These tests sign payloads
the same way Stripe does and post them to /api/webhook.
"""

import hashlib
import hmac
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout

_TMP = tempfile.mkdtemp(prefix="appvault-webhook-")
os.environ["ADMIN_PASSWORD"] = "testpw"
os.environ["DB_PATH"] = os.path.join(_TMP, "appvault.db")
os.environ["CATALOG_PATH"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "static", "catalog.json"
)
os.environ["AUDIT_LOG"] = os.path.join(_TMP, "audit.log")
os.environ["DISABLE_ADMIN"] = "true"
os.environ["STRIPE_WEBHOOK_SECRET"] = "test-webhook-signing-secret"
os.environ["STRIPE_SECRET_KEY"] = ""
os.environ["STRIPE_PRICE_PRO"] = "price_appvault_monthly_test"
os.environ["STRIPE_PRICE_PRO_YEARLY"] = "price_appvault_yearly_test"
os.environ["STRIPE_PRICE_STARTER"] = "price_xxx_starter"
os.environ["STRIPE_PRICE_POWER"] = "price_xxx_power"
os.environ.pop("STRIPE_APPVAULT_PRICE_IDS", None)

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PRICE_MONTHLY = "price_appvault_monthly_test"
PRICE_YEARLY = "price_appvault_yearly_test"
WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]


def _sign(payload: bytes, secret: str) -> str:
    timestamp = int(time.time())
    signed = f"{timestamp}.".encode() + payload
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def _event(event_id, etype, obj):
    return {"id": event_id, "object": "event", "type": etype, "data": {"object": obj}}


def _session(**overrides):
    session = {
        "id": "cs_test_session",
        "object": "checkout.session",
        "payment_status": "paid",
        "status": "complete",
        "mode": "subscription",
        "customer_email": None,
        "customer_details": None,
        "customer": "",
        "subscription": "",
        "metadata": {},
    }
    session.update(overrides)
    return session


class StripeWebhookOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._client_cm = TestClient(main.app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._client_cm.__exit__(None, None, None)

    def _post(self, event, signature=None):
        body = json.dumps(event).encode()
        headers = {"content-type": "application/json"}
        if signature is not None:
            headers["stripe-signature"] = signature
        else:
            headers["stripe-signature"] = _sign(body, WEBHOOK_SECRET)
        buf = io.StringIO()
        with redirect_stdout(buf):
            resp = self.client.post("/api/webhook", content=body, headers=headers)
        return resp, buf.getvalue()

    def _license(self, key):
        db = main.get_db()
        try:
            return db.execute("SELECT * FROM licenses WHERE key = ?", (key,)).fetchone()
        finally:
            db.close()

    def _licenses_for_email(self, email):
        db = main.get_db()
        try:
            return db.execute("SELECT * FROM licenses WHERE email = ?", (email,)).fetchall()
        finally:
            db.close()

    def test_foreign_paid_session_ignored_with_200(self):
        """Other products' paid checkouts must not receive an AppVault licence."""
        cases = [
            (
                "evt_foreign_grc",
                "buyer@grcompliance.example",
                {"product": "grcompliance"},
                "price_grc_licence",
            ),
            (
                "evt_foreign_sectutor",
                "buyer@sectutor.example",
                {"site": "sectutor.com"},
                "price_sectutor_hosting",
            ),
            (
                "evt_foreign_empty_meta",
                "buyer@other-product.example",
                {},
                "price_some_other_product",
            ),
        ]
        for event_id, email, metadata, price_id in cases:
            with self.subTest(event_id=event_id):
                metadata = dict(metadata)
                metadata.setdefault("price_id", price_id)
                event = _event(
                    event_id,
                    "checkout.session.completed",
                    _session(
                        id="cs_" + event_id,
                        customer_email=email,
                        customer="cus_test_should_not_log",
                        metadata=metadata,
                        payment_status="paid",
                    ),
                )
                resp, log = self._post(event)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json().get("status"), "ok")
                self.assertEqual(self._licenses_for_email(email), [])
                self.assertIn("reason=not-appvault", log)
                self.assertNotIn(email, log)
                self.assertNotIn("cus_test_should_not_log", log)

    def test_appvault_paid_session_licenses(self):
        lic = "APPVAULT-TEST-PAID-0001"
        email = "buyer@appvault.example"
        db = main.get_db()
        db.execute(
            "INSERT INTO licenses (key, email, tier, status) VALUES (?, ?, 'pro', 'pending')",
            (lic, email),
        )
        db.commit()
        db.close()

        event = _event(
            "evt_appvault_paid",
            "checkout.session.completed",
            _session(
                id="cs_appvault_paid",
                customer_email=email,
                customer="cus_appvault_buyer",
                subscription="sub_appvault_test",
                metadata={
                    "product": "appvault",
                    "price_id": PRICE_MONTHLY,
                    "license_key": lic,
                    "tier": "pro",
                    "email": email,
                },
                payment_status="paid",
            ),
        )
        resp, log = self._post(event)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "ok")
        self.assertNotIn("Ignored", log)
        row = self._license(lic)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["email"], email)
        self.assertEqual(row["tier"], "pro")
        self.assertEqual(row["stripe_session_id"], "cs_appvault_paid")
        self.assertEqual(row["stripe_subscription_id"], "sub_appvault_test")
        self.assertEqual(len(self._licenses_for_email(email)), 1)

    def test_unpaid_appvault_session_ignored(self):
        lic = "APPVAULT-TEST-UNPAID-0001"
        email = "unpaid@appvault.example"
        db = main.get_db()
        db.execute(
            "INSERT INTO licenses (key, email, tier, status) VALUES (?, ?, 'pro', 'pending')",
            (lic, email),
        )
        db.commit()
        db.close()

        event = _event(
            "evt_appvault_unpaid",
            "checkout.session.completed",
            _session(
                id="cs_appvault_unpaid",
                customer_email=email,
                customer="cus_unpaid_should_not_log",
                metadata={
                    "product": "appvault",
                    "price_id": PRICE_MONTHLY,
                    "license_key": lic,
                    "tier": "pro",
                },
                payment_status="unpaid",
            ),
        )
        resp, log = self._post(event)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "ok")
        self.assertIn("reason=unpaid", log)
        self.assertNotIn(email, log)
        self.assertNotIn("cus_unpaid_should_not_log", log)
        row = self._license(lic)
        self.assertEqual(row["status"], "pending")

    def test_unknown_event_returns_200(self):
        email = "nobody@example.com"
        event = _event(
            "evt_unknown_customer",
            "customer.created",
            {"id": "cus_unknown_person", "object": "customer", "email": email},
        )
        resp, log = self._post(event)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "ok")
        self.assertIn("type=customer.created", log)
        self.assertNotIn(email, log)
        self.assertNotIn("cus_unknown_person", log)
        self.assertEqual(self._licenses_for_email(email), [])

    def test_foreign_price_with_appvault_marker_ignored(self):
        """metadata.product is not enough when the price is not AppVault's."""
        lic = "APPVAULT-TEST-BADPRICE-0001"
        email = "badprice@appvault.example"
        db = main.get_db()
        db.execute(
            "INSERT INTO licenses (key, email, tier, status) VALUES (?, ?, 'pro', 'pending')",
            (lic, email),
        )
        db.commit()
        db.close()

        event = _event(
            "evt_bad_price",
            "checkout.session.completed",
            _session(
                id="cs_bad_price",
                customer_email=email,
                metadata={
                    "product": "appvault",
                    "price_id": "price_sectutor_hosting",
                    "license_key": lic,
                },
                # Line items are authoritative and disagree with metadata.
                line_items={
                    "object": "list",
                    "data": [{"price": {"id": "price_sectutor_hosting", "product": "prod_sectutor"}}],
                },
                payment_status="paid",
            ),
        )
        resp, log = self._post(event)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("reason=price-not-allowlisted", log)
        self.assertNotIn(email, log)
        self.assertEqual(self._license(lic)["status"], "pending")

    def test_invalid_signature_rejected(self):
        lic = "APPVAULT-TEST-BADSIG-0001"
        email = "badsig@appvault.example"
        db = main.get_db()
        db.execute(
            "INSERT INTO licenses (key, email, tier, status) VALUES (?, ?, 'pro', 'pending')",
            (lic, email),
        )
        db.commit()
        db.close()
        event = _event(
            "evt_bad_sig",
            "checkout.session.completed",
            _session(
                customer_email=email,
                metadata={
                    "product": "appvault",
                    "price_id": PRICE_MONTHLY,
                    "license_key": lic,
                },
                payment_status="paid",
            ),
        )
        resp, _log = self._post(event, signature="t=1,v1=deadbeef")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._license(lic)["status"], "pending")

    def test_checkout_creation_sets_ownership_marker(self):
        captured = {}

        class _Session:
            url = "https://checkout.stripe.test/c/pay_test"

        def _create(**kwargs):
            captured.update(kwargs)
            return _Session()

        import stripe

        original = stripe.checkout.Session.create
        stripe.checkout.Session.create = _create
        try:
            resp = self.client.post(
                "/api/checkout",
                json={"tier": "pro", "billing": "monthly", "email": "buyer@appvault.example"},
            )
        finally:
            stripe.checkout.Session.create = original

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(captured["line_items"], [{"price": PRICE_MONTHLY, "quantity": 1}])
        meta = captured["metadata"]
        self.assertEqual(meta["product"], "appvault")
        self.assertEqual(meta["price_id"], PRICE_MONTHLY)
        self.assertEqual(meta["tier"], "pro")
        self.assertTrue(meta["license_key"])
        sub = captured["subscription_data"]["metadata"]
        self.assertEqual(sub["product"], "appvault")
        self.assertEqual(sub["price_id"], PRICE_MONTHLY)

    def test_extra_allowlist_price_from_env_licenses(self):
        os.environ["STRIPE_APPVAULT_PRICE_IDS"] = "price_legacy_appvault"
        lic = "APPVAULT-TEST-LEGACY-0001"
        email = "legacy@appvault.example"
        db = main.get_db()
        db.execute(
            "INSERT INTO licenses (key, email, tier, status) VALUES (?, ?, 'pro', 'pending')",
            (lic, email),
        )
        db.commit()
        db.close()
        try:
            event = _event(
                "evt_legacy_price",
                "checkout.session.completed",
                _session(
                    id="cs_legacy_price",
                    customer_email=email,
                    metadata={
                        "product": "appvault",
                        "price_id": "price_legacy_appvault",
                        "license_key": lic,
                        "tier": "pro",
                    },
                    payment_status="paid",
                ),
            )
            resp, log = self._post(event)
        finally:
            os.environ.pop("STRIPE_APPVAULT_PRICE_IDS", None)
        self.assertEqual(resp.status_code, 200, log)
        self.assertNotIn(email, log)
        self.assertEqual(self._license(lic)["status"], "active")

    def test_malformed_event_returns_200(self):
        resp, log = self._post({"id": "evt_malformed", "object": "event"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "ok")
        self.assertIn("reason=malformed", log)

    def test_agent_checkout_creation_sets_ownership_marker(self):
        db = main.get_db()
        db.execute(
            "INSERT INTO agents (id, name, api_key, status) VALUES (?, ?, ?, 'online')",
            ("agent-webhook-test", "webhook-test", "agent-api-key-test-value"),
        )
        db.commit()
        db.close()
        captured = {}

        class _Session:
            url = "https://checkout.stripe.test/c/pay_agent"

        def _create(**kwargs):
            captured.update(kwargs)
            return _Session()

        import stripe

        original = stripe.checkout.Session.create
        stripe.checkout.Session.create = _create
        try:
            resp = self.client.post(
                "/api/agent/checkout",
                json={
                    "agent_id": "agent-webhook-test",
                    "api_key": "agent-api-key-test-value",
                    "billing": "yearly",
                },
            )
        finally:
            stripe.checkout.Session.create = original

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(captured["line_items"], [{"price": PRICE_YEARLY, "quantity": 1}])
        meta = captured["metadata"]
        self.assertEqual(meta["product"], "appvault")
        self.assertEqual(meta["price_id"], PRICE_YEARLY)
        self.assertEqual(meta["agent_id"], "agent-webhook-test")
        self.assertEqual(captured["subscription_data"]["metadata"]["product"], "appvault")


if __name__ == "__main__":
    unittest.main()
