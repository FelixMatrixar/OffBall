#!/usr/bin/env bash
# The post-deploy smoke test (PRD 18.10): the API answers, the event bus is ready, and a 60x run of a smoke match
# puts frames on the stream, and a graphic as well when the agents have a model.
#
#   deploy/smoke.sh [base URL]      # defaults to the API on this machine, http://127.0.0.1:8000
set -euo pipefail

BASE=${1:-http://127.0.0.1:8000}
fail() { echo "Smoke test failed: $*" >&2; exit 1; }

for _ in $(seq 1 60); do
  curl -fsS "$BASE/api/health" >/dev/null 2>&1 && break
  sleep 2
done
health=$(curl -fsS "$BASE/api/health") || fail "the API doesn't answer at $BASE"
curl -fsS "$BASE/api/ready" >/dev/null || fail "the event bus isn't ready"

# The overlap in smk4 (golden case `overlap`), from a start that moves by up to 2 s each time, so every check
# is a new run rather than a finished one joined again.
from_ms=$((158840 - ($(date +%s) % 50) * 40))
url="$BASE/api/matches/smk4/stream?period=1&from_ms=$from_ms&to_ms=191040&speed=60&close_at_end=true"
stream=$(mktemp)
trap 'rm -f "$stream"' EXIT

if grep -q '"model_configured":true' <<<"$health"; then
  # With a model the stream stays open until the crew has finished every moment in the window, which takes minutes
  # on a real model, so the test stops at the first graphic (PRD 18.10).
  curl -fsSN --max-time "${SMOKE_GRAPHIC_S:-600}" "$url" >"$stream" &
  reader=$!
  while kill -0 "$reader" 2>/dev/null && ! grep -q '"type":"overlay.upsert"' "$stream"; do
    sleep 1
  done
  kill "$reader" 2>/dev/null || true
  wait "$reader" 2>/dev/null || true
  frames=$(grep -c '"type":"frame"' "$stream" || true)
  graphics=$(grep -c '"type":"overlay.upsert"' "$stream" || true)
  [ "$frames" -gt 0 ] || fail "the stream carried no frames"
  [ "$graphics" -gt 0 ] || fail "the agents have a model, but no graphic reached the stream within ${SMOKE_GRAPHIC_S:-600} s"
  echo "Smoke test passed: $frames frames and a graphic from a 60x run of smk4."
else
  curl -fsSN --max-time 300 "$url" >"$stream" || fail "the stream broke off"
  frames=$(grep -c '"type":"frame"' "$stream" || true)
  [ "$frames" -gt 0 ] || fail "the stream carried no frames"
  echo "Smoke test passed: $frames frames from a 60x run of smk4. No model is set, so no graphics air."
fi
