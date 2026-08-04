@echo off
cd /d C:\Users\emman\appvault-cloud-prod
set CENTRAL_PORT=8000
set CENTRAL_URL=http://localhost:8000
set ADMIN_USERNAME=admin
set ADMIN_PASSWORD=appvault-admin
set DB_PATH=C:\Users\emman\appvault-cloud-prod\data\appvault.db
set CATALOG_PATH=C:\Users\emman\appvault-cloud-prod\static\catalog.json
set DOMAIN=localhost:8000
for /f "delims=" %i in (C:\Users\emman\stripe-test.key) do set STRIPE_SECRET_KEY=%i
start /b python -m uvicorn main:app --host 0.0.0.0 --port 8000
