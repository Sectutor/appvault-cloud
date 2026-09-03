# AppVault Cloud — Central Admin Server
# Build context: canonical source of truth = central/ in D:\DATA_INTELLFENCE\WebDev\AppVault
FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl --no-install-recommends && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# A07 — Admin credentials MUST be supplied at deploy time via env. We no
# longer bake a default password into the image; the container will fail
# to start loudly if ADMIN_PASSWORD is unset, instead of running with a
# well-known password.
ENV ADMIN_USERNAME=admin
# ADMIN_PASSWORD is intentionally NOT set here. Compose / k8s / CI must
# pass `-e ADMIN_PASSWORD=...` (preferably from a secret manager).
# Reference: see install.sh which generates a 16-char random password on
# first boot and writes it to /opt/appvault/.env (chmod 600).

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
