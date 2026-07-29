#!/bin/bash
# AppVault Cloud — Demo Deploy Script
# Run this on any fresh Ubuntu VPS to deploy AppVault in one command.
#
# Usage:
#   curl -fsSL https://appvault.airepoindex.com/deploy.sh | bash
#   OR
#   wget -qO- https://appvault.airepoindex.com/deploy.sh | bash

set -e

echo "╔══════════════════════════════════════════════╗"
echo "║       AppVault Cloud — Deploy Script        ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ═══════════════════════════════════════════════
# STEP 1 — Check Docker
# ═══════════════════════════════════════════════
echo "Step 1: Checking Docker..."

if command -v docker &> /dev/null; then
    echo "  ✅ Docker already installed"
else
    echo "  Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
    echo "  ✅ Docker installed"
fi

# ═══════════════════════════════════════════════
# STEP 2 — Download AppVault assets
# ═══════════════════════════════════════════════
echo ""
echo "Step 2: Downloading AppVault assets..."

RELEASE_URL="https://github.com/Sectutor/appvault-releases/releases/download/v1.0.5/appvault-assets.zip"
ASSETS_ZIP="/tmp/appvault-assets.zip"
APP_DIR="$HOME/AppVault"

curl -fsSL "$RELEASE_URL" -o "$ASSETS_ZIP"
echo "  ✅ Downloaded"

# ═══════════════════════════════════════════════
# STEP 3 — Extract assets
# ═══════════════════════════════════════════════
echo ""
echo "Step 3: Extracting assets..."

if [ -d "$APP_DIR" ]; then
    rm -rf "$APP_DIR"
fi
mkdir -p "$APP_DIR"
unzip -q "$ASSETS_ZIP" -d "$APP_DIR"
rm "$ASSETS_ZIP"
echo "  ✅ Extracted to $APP_DIR"

# ═══════════════════════════════════════════════
# STEP 4 — Deploy AppVault
# ═══════════════════════════════════════════════
echo ""
echo "Step 4: Starting AppVault..."

cd "$APP_DIR"

# Generate secrets if not set
if [ ! -f .env ]; then
    echo "API_KEY=$(openssl rand -hex 16)" > .env
    echo "ADMIN_ENABLED=true" >> .env
    echo "HEIMDALL_PORT=8085" >> .env
    echo "APP_MANAGER_PORT=8086" >> .env
    echo "FREE_LIMIT=25" >> .env
fi

docker compose down --remove-orphans 2>/dev/null || true
docker rm -f heimdall app-manager 2>/dev/null || true
docker compose up -d --build

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║       ✅ AppVault is ready!                  ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "  Open: http://localhost:8085"
echo ""
echo "  To update later:"
echo "    cd $APP_DIR && docker compose pull && docker compose up -d"
echo ""
