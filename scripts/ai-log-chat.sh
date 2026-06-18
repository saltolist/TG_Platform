#!/usr/bin/env bash
# Set LLM context log filter on a running backend (AI_CONTEXT_LOG=1 required).
#
# Usage:
#   ./scripts/ai-log-chat.sh <chat-id>        # set filter + show backend logs here
#   ./scripts/ai-log-chat.sh <chat-id> -n     # set filter only (logs in other terminal)
#   ./scripts/ai-log-chat.sh -                # clear filter
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CHAT_ID=""
FOLLOW=1

for arg in "$@"; do
  case "$arg" in
    -n | --no-follow) FOLLOW=0 ;;
    -h | --help)
      echo "Usage: $0 <chat-id> [-n]" >&2
      echo "  id from /gchat/?id=… or /post/<postId>/?chat=…" >&2
      echo "  -n  only set filter, do not tail backend logs" >&2
      echo "  $0 -   clear filter" >&2
      exit 0
      ;;
    -) CHAT_ID="" ;;
    -*)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
    *)
      if [ -z "$CHAT_ID" ] && [ "$arg" != "-n" ] && [ "$arg" != "--no-follow" ]; then
        CHAT_ID="$arg"
      fi
      ;;
  esac
done

if [ $# -eq 0 ]; then
  echo "Usage: $0 <chat-id> [-n]" >&2
  echo "  Examples: $0 gc1   $0 2504077a-491d-44e7-a8b8-16f78f6f11d2" >&2
  exit 1
fi

# Clearing filter — never follow logs.
if [ $# -eq 1 ] && [ "${1:-}" = "-" ]; then
  CHAT_ID=""
  FOLLOW=0
fi

API_BASE="${API_BASE:-http://localhost:8000}"
BODY=$(python3 -c "import json,sys; print(json.dumps({'chatId': sys.argv[1]}))" "$CHAT_ID")

response=$(curl -sS -w "\n%{http_code}" -X PUT "${API_BASE}/api/v1/dev/ai-context-log/" \
  -H "Content-Type: application/json" \
  -d "$BODY")
http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" = "404" ]; then
  echo "AI context log выключен. Добавьте AI_CONTEXT_LOG=1 в .env и перезапустите backend:" >&2
  echo "  docker compose up -d --build backend" >&2
  exit 1
fi

if [ "$http_code" != "200" ]; then
  echo "Ошибка ($http_code): $body" >&2
  exit 1
fi

if [ -n "$CHAT_ID" ]; then
  echo "[ai-log-chat] фильтр → $CHAT_ID"
  echo "[ai-log-chat] отправьте сообщение в этом чате — ниже появятся AI REQUEST / AI RESPONSE"
else
  echo "[ai-log-chat] фильтр сброшен"
fi

if [ "$FOLLOW" -eq 1 ] && [ -n "$CHAT_ID" ]; then
  echo "[ai-log-chat] docker compose logs -f backend  (Ctrl+C — выход, Docker продолжит работать)"
  echo ""
  exec docker compose logs --tail=0 -f backend
fi
