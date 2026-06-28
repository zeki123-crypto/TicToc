#!/usr/bin/env bash
#
# Pull the latest code and (re)start the bot stack.
# Run from the repository root or anywhere — it cd's to the repo automatically.
#
#   bash deploy/deploy.sh
#
set -euo pipefail

# Move to the repository root (parent of this script's directory).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

if [ ! -f .env ]; then
    echo "❌ .env not found. Copy .env.example to .env and set BOT_TOKEN first."
    exit 1
fi

echo "==> Pulling latest code…"
git pull --ff-only || echo "    (skipped git pull — not a clean fast-forward)"

echo "==> Building & starting containers…"
docker compose up -d --build

echo "==> Pruning old images…"
docker image prune -f >/dev/null 2>&1 || true

echo
echo "✅ Deployed. Recent logs:"
docker compose logs --tail=30 bot
