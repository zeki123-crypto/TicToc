#!/usr/bin/env bash
#
# One-time server setup for a fresh Ubuntu/Debian VPS (e.g. Hetzner CX22).
# Installs Docker Engine + the Compose plugin and enables Docker on boot.
#
# Usage (as root or with sudo):
#   bash deploy/setup.sh
#
set -euo pipefail

echo "==> Updating package index…"
apt-get update -y

echo "==> Installing prerequisites…"
apt-get install -y --no-install-recommends ca-certificates curl git

echo "==> Installing Docker Engine + Compose plugin…"
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
else
    echo "    Docker already installed, skipping."
fi

echo "==> Enabling Docker to start on boot…"
systemctl enable --now docker

echo
echo "✅ Done. Docker version:"
docker --version
docker compose version

echo
echo "Next steps:"
echo "  1) git clone the repo (or it is already here)"
echo "  2) cp .env.example .env  &&  edit .env (set BOT_TOKEN)"
echo "  3) docker compose up -d --build"
