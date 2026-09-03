# AppVault Cloud — Automated Provisioning API
# FastAPI backend that provisions AppVault instances on payment.

## Architecture

```
User → Stripe Checkout → Webhook → Provisioning API → Coolify Deploy → URL to User
```

## Project Structure

```
appvault-cloud/
├── main.py              # FastAPI app
├── config.py            # Settings
├── database.py          # SQLite models
├── provisioning.py      # Coolify deploy logic
├── stripe_webhook.py    # Payment handler
├── templates/
│   ├── landing.html     # Pricing page
│   ├── dashboard.html   # User dashboard
│   └── success.html     # Post-payment
├── requirements.txt
└── Dockerfile
```

## Environment Variables

```
COOLIFY_URL=http://169.58.9.191:8000
COOLIFY_TOKEN=xxx
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
DOMAIN=appvault.airepoindex.com
```

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | / | Landing page |
| GET | /dashboard | User dashboard |
| POST | /api/checkout | Create Stripe Checkout session |
| POST | /api/webhook | Stripe payment webhook |
| GET | /api/status/{id} | Check provisioning status |

<!-- deploy marker: persistent volume wiring 20260903-1443 -->
