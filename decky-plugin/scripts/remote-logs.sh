#!/usr/bin/env bash
# 从 Mac 跟 Steam Deck 上 DeckMind 的日志
#
# 用法:
#   DECK_HOST=deck@192.168.x.x ./remote-logs.sh           # 实时跟
#   DECK_HOST=deck@192.168.x.x ./remote-logs.sh 200       # 最近 200 行
#   DECK_HOST=deck@192.168.x.x FILTER=deckmind ./remote-logs.sh

set -euo pipefail

DECK_HOST="${DECK_HOST:?请设置 DECK_HOST，例如 export DECK_HOST=deck@192.168.1.50}"
[[ "$DECK_HOST" == *"@"* ]] || DECK_HOST="deck@$DECK_HOST"

LINES="${1:-}"
FILTER="${FILTER:-deckmind\|DeckMind}"

if [[ -n "$LINES" ]]; then
  ssh "$DECK_HOST" "sudo journalctl -u plugin_loader -n $LINES --no-pager | grep -iE '$FILTER' || sudo journalctl -u plugin_loader -n $LINES --no-pager"
else
  echo "==> 实时跟踪 plugin_loader 日志 (Ctrl+C 退出)"
  ssh "$DECK_HOST" "sudo journalctl -u plugin_loader -f --no-pager"
fi
