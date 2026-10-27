#!/usr/bin/env bash
# The only command CI's deploy key may run on the VM (PRD 18.10, 18.11): run a release's image, by digest, and
# smoke-test it, going back to the image before if the test fails; or go back on request (OPS-6).
#
#   bash deploy/deploy.sh deploy ghcr.io/<owner>/offball@sha256:<digest>
#   bash deploy/deploy.sh rollback
#
# Over SSH the words come from the command CI sends, and only these two actions run.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
ETC=/etc/offball
CURRENT=$ETC/release/current.env
PREVIOUS=$ETC/release/previous.env

read -r -a words <<<"${SSH_ORIGINAL_COMMAND:-$*}"
action=${words[0]:-}
ref=${words[1]:-}

compose() {
  docker compose -f "$REPO/deploy/compose.yaml" --env-file "$ETC/settings.env" --env-file "$CURRENT" \
    --profile vm "$@"
}
image_in() { sed -n 's/^OFFBALL_IMAGE=//p' "$1"; }

run() {
  printf 'OFFBALL_IMAGE=%s\n' "$1" >"$CURRENT"
  [ "$1" = "offball:local" ] || compose pull offball
  compose up -d --wait --remove-orphans
}

case "$action" in
  deploy)
    if ! [[ "$ref" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]]; then
      echo "deploy takes an image by digest: ghcr.io/<owner>/offball@sha256:<digest>" >&2
      exit 2
    fi
    before=$(image_in "$CURRENT")
    if [ "$before" = "$ref" ]; then
      echo "Already running $ref"
      exit 0
    fi
    run "$ref"
    if ! bash "$REPO/deploy/smoke.sh"; then
      echo "Going back to $before" >&2
      run "$before"
      exit 1
    fi
    printf 'OFFBALL_IMAGE=%s\n' "$before" >"$PREVIOUS"
    echo "Running $ref"
    ;;
  rollback)
    [ -f "$PREVIOUS" ] || { echo "There's no earlier release to go back to." >&2; exit 1; }
    now=$(image_in "$CURRENT")
    back=$(image_in "$PREVIOUS")
    run "$back"
    printf 'OFFBALL_IMAGE=%s\n' "$now" >"$PREVIOUS"
    bash "$REPO/deploy/smoke.sh"
    echo "Back on $back"
    ;;
  *)
    echo "Usage: deploy.sh deploy <image by digest> | deploy.sh rollback" >&2
    exit 2
    ;;
esac
