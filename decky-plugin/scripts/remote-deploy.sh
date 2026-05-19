#!/usr/bin/env bash
# 从 Mac 一键部署 plugin + runtime 到 Steam Deck
#
# 用法:
#   DECK_HOST=192.168.x.x ./remote-deploy.sh
#   DECK_HOST=deck@192.168.x.x ./remote-deploy.sh
#   DECK_HOST=deck@192.168.x.x RESTART=1 ./remote-deploy.sh

set -euo pipefail

DECK_HOST="${DECK_HOST:?请设置 DECK_HOST，例如 export DECK_HOST=deck@192.168.1.50}"
[[ "$DECK_HOST" == *"@"* ]] || DECK_HOST="deck@$DECK_HOST"

PLUGIN_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_DIR="$(cd -- "$PLUGIN_DIR/.." && pwd)"

PLUGIN_REMOTE="/home/deck/homebrew/plugins/DeckMind"
RUNTIME_REMOTE="/home/deck/deckmind/runtime"

echo "==> 本地构建 plugin 前端"
cd "$PLUGIN_DIR"
if command -v pnpm >/dev/null 2>&1; then
  pnpm install --silent
  pnpm run build
else
  npm install --silent
  npm run build
fi

echo "==> 准备远端目录"
ssh "$DECK_HOST" "mkdir -p $PLUGIN_REMOTE $RUNTIME_REMOTE"

echo "==> 同步 plugin 到 $PLUGIN_REMOTE"
rsync -avz --delete \
  --exclude 'node_modules' --exclude 'src' --exclude 'scripts' \
  --exclude 'tsconfig.json' --exclude 'rollup.config.js' \
  --exclude '__pycache__' \
  "$PLUGIN_DIR"/ "$DECK_HOST:$PLUGIN_REMOTE/"

echo "==> 同步 runtime 到 $RUNTIME_REMOTE"
rsync -avz --delete \
  --exclude 'decky-plugin' --exclude 'node_modules' \
  --exclude '__pycache__' --exclude 'dist' --exclude '.venv' \
  --exclude 'tests' \
  "$AGENT_DIR"/ "$DECK_HOST:$RUNTIME_REMOTE/"

echo "==> 修权限"
ssh "$DECK_HOST" "sudo chown -R deck:deck $PLUGIN_REMOTE $RUNTIME_REMOTE"

if [[ "${RESTART:-1}" == "1" ]]; then
  echo "==> 重启 Decky"
  ssh "$DECK_HOST" "sudo systemctl restart plugin_loader"
fi

echo "==> 状态检查"
ssh "$DECK_HOST" "ls $RUNTIME_REMOTE/main.py && echo '✅ runtime/main.py 存在'"

echo "Done."
