#!/usr/bin/env bash
# Start Docker stack with LLM context logs for one chat.
# Usage: ./scripts/docker-up-log.sh <chat-id> [docker compose args…]
#   chat-id: gc1 (from /gchat/?id=gc1), post chat id, or post:postId:chatId
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CHAT_ID="${1:-}"
if [ -z "$CHAT_ID" ]; then
  echo "Usage: $0 <chat-id> [docker compose args…]" >&2
  echo "  Examples:" >&2
  echo "    $0 gc1" >&2
  echo "    $0 pc1" >&2
  echo "    $0 post:21:pc1" >&2
  exit 1
fi
shift

export AI_CONTEXT_LOG=1
export AI_CONTEXT_LOG_CHAT="$CHAT_ID"

echo "[docker-up-log] AI_CONTEXT_LOG=1 AI_CONTEXT_LOG_CHAT=$CHAT_ID"
docker compose up -d --build "$@"
echo "[docker-up-log] stack running in background; tailing backend logs (Ctrl+C = only exit logs)"
exec docker compose logs --tail=0 -f backend
