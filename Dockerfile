# AppVault Cloud — Central Admin Server
# Build context: canonical source of truth = ~/appvault-cloud-prod
FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl --no-install-recommends && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Admin credentials (overridable via env)
ENV ADMIN_USERNAME=admin
ENV ADMIN_PASSWORD=appvault-admin

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
