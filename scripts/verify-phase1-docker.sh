#!/usr/bin/env bash
# Phase 1 Docker smoke checks (step 6). Requires: docker compose up, curl, python3.
set -euo pipefail

API="${API_BASE:-http://localhost:8000}"
GUEST="Authorization: Bearer presentation:guest"
FAIL=0

ok() { echo "OK  $1"; }
fail() { echo "FAIL $1"; FAIL=1; }

echo "=== Phase 1 Docker verification (API=$API) ==="

if [[ "$(curl -s -o /dev/null -w '%{http_code}' "$API/api/v1/health/")" == "200" ]]; then
  ok "health"
else
  fail "health"
fi

POSTS=$(curl -s -H "$GUEST" "$API/api/v1/posts/" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
if [[ "$POSTS" -ge 9 ]]; then ok "presentation posts ($POSTS)"; else fail "presentation posts ($POSTS)"; fi

LLMS=$(curl -s -H "$GUEST" "$API/api/v1/profile/ai/" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('llmModels',[])))")
if [[ "$LLMS" -ge 1 ]]; then ok "presentation ai models ($LLMS)"; else fail "presentation ai models ($LLMS)"; fi

GUEST_POST=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "$GUEST" -H "Content-Type: application/json" \
  -d '{"id":"00000000-0000-0000-0000-000000000099","status":"draft","rubric":null,"text":"x","notes":[],"chats":[]}' \
  "$API/api/v1/posts/")
if [[ "$GUEST_POST" == "403" ]]; then ok "guest write blocked (403)"; else fail "guest write blocked ($GUEST_POST)"; fi

if curl -s -X POST -H "Content-Type: application/json" \
  -d '{"email":"demo@mail.ru","password":"Demo!2026"}' \
  "$API/api/v1/auth/login/" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('token') else 1)"; then
  ok "demo login"
else
  fail "demo login"
fi

if curl -s -X POST -H "$GUEST" -H "Content-Type: application/json" \
  -d '{"text":"hi","scope":"global"}' "$API/api/v1/ai/reply/" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('text') else 1)"; then
  ok "ai json stub"
else
  fail "ai json stub"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "=== All smoke checks passed ==="
else
  echo "=== Some checks failed ==="
  exit 1
fi
