#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-$HOME/homebrew/plugins/DeckMind}"

cd "$PLUGIN_DIR"

if command -v pnpm >/dev/null 2>&1; then
  pnpm run build
else
  npm run build
fi

mkdir -p "$TARGET_DIR"

rsync -a --delete \
  --exclude 'node_modules' \
  --exclude 'src' \
  --exclude 'scripts' \
  --exclude 'tsconfig.json' \
  --exclude 'rollup.config.js' \
  "$PLUGIN_DIR"/ "$TARGET_DIR"/

if [[ "${RESTART_DECKY:-0}" == "1" ]]; then
  sudo systemctl restart plugin_loader
fi

printf 'DeckMind plugin deployed to %s\n' "$TARGET_DIR"
