#!/usr/bin/env bash
# One command on a VM prepared by cloud-init.yaml (PRD 18.10): writes the settings and secrets, copies the match
# data to its folder, starts the stack and runs the smoke test. Running it again keeps the secrets it made.
#
#   sudo OPENROUTER_API_KEY=<key> bash deploy/up.sh --host api.example.com \
#     [--web-origin https://<account>.<zone>.web.core.windows.net]... [--image ghcr.io/<owner>/offball@sha256:<digest>] \
#     [--ci-key "ssh-ed25519 AAAA... offball-ci"]
#
# Without --image it builds the image from this checkout. Without an OpenRouter key, given in the environment or
# typed when asked, the stack runs with no graphics (PRD 14.14).
set -euo pipefail

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; }

HOST="" ORIGINS="" IMAGE="" CI_KEY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST=$2; shift 2 ;;
    --web-origin) ORIGINS="${ORIGINS:+$ORIGINS,}$2"; shift 2 ;;
    --image) IMAGE=$2; shift 2 ;;
    --ci-key) CI_KEY=$2; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[ -n "$HOST" ] || { usage >&2; exit 2; }
[ "$(id -u)" -eq 0 ] || { echo "Run it as root: sudo bash $0 ..." >&2; exit 1; }
command -v docker >/dev/null || { echo "Docker isn't installed: start the VM with deploy/cloud-init.yaml." >&2; exit 1; }
id deploy >/dev/null 2>&1 || { echo "There's no deploy user: start the VM with deploy/cloud-init.yaml." >&2; exit 1; }

REPO=$(cd "$(dirname "$0")/.." && pwd)
ETC=/etc/offball
DATA=/srv/offball
install -d -m 755 "$ETC"
install -d -m 750 -g deploy "$ETC/secrets"
install -d -m 755 -o deploy -g deploy "$ETC/release"
install -d -m 755 -o 10001 -g 10001 "$DATA" "$DATA/datasets" "$DATA/media" "$DATA/files"

# A run without --web-origin keeps the origins an earlier run set.
if [ -z "$ORIGINS" ] && [ -f "$ETC/settings.env" ]; then
  ORIGINS=$(sed -n 's/^OFFBALL_WEB_ORIGINS=//p' "$ETC/settings.env")
fi

echo "Writing $ETC/settings.env"
cat >"$ETC/settings.env" <<EOF
# Written by deploy/up.sh: this machine's settings (PRD 18.14). Nothing secret.
API_HOST=$HOST
OFFBALL_WEB_ORIGINS=${ORIGINS:-*}
OFFBALL_DATA=$DATA/datasets
OFFBALL_MEDIA=$DATA/media
OFFBALL_FILES=$DATA/files
OFFBALL_SETTINGS=$ETC/settings.env
OFFBALL_SECRETS=$ETC/secrets/offball.env
EOF
chmod 644 "$ETC/settings.env"

# The image to run. deploy.sh replaces it with each release.
release="$ETC/release/current.env"
if [ -n "$IMAGE" ] || [ ! -f "$release" ]; then
  printf 'OFFBALL_IMAGE=%s\n' "${IMAGE:-offball:local}" >"$release"
  chown deploy:deploy "$release"
fi

# Secrets: made once and kept. Readable by root and the deploy user, which runs Compose for CI.
secrets="$ETC/secrets/offball.env"
touch "$secrets"
chgrp deploy "$secrets"
chmod 640 "$secrets"
if ! grep -q '^VALKEY_PASSWORD=' "$secrets"; then
  pw=$(openssl rand -hex 24)
  printf 'VALKEY_PASSWORD=%s\nVALKEY_URL=valkey://:%s@valkey:6379/0\n' "$pw" "$pw" >>"$secrets"
  echo "Made a Valkey password"
fi
if ! grep -q '^OPENROUTER_API_KEY=' "$secrets"; then
  key=${OPENROUTER_API_KEY:-}
  if [ -z "$key" ] && [ -t 0 ]; then
    read -rsp "OpenRouter key (Enter to run without graphics): " key
    echo
  fi
  if [ -n "$key" ]; then
    printf 'OPENROUTER_API_KEY=%s\n' "$key" >>"$secrets"
    echo "Stored the OpenRouter key"
  fi
fi

# Match data: the sets this checkout has. Truth never leaves the repository (PRD 12.9).
for set in league showcase smoke golden matchday; do
  if [ -d "$REPO/datasets/$set" ]; then
    rm -rf "${DATA:?}/datasets/$set"
    cp -a "$REPO/datasets/$set" "$DATA/datasets/"
  fi
done
chown -R 10001:10001 "$DATA/datasets"

# CI's deploy key may run deploy.sh and nothing else (PRD 18.11).
if [ -n "$CI_KEY" ]; then
  keys=/home/deploy/.ssh/authorized_keys
  install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
  line="command=\"bash $REPO/deploy/deploy.sh\",restrict $CI_KEY"
  touch "$keys"
  grep -qxF "$line" "$keys" || echo "$line" >>"$keys"
  chown deploy:deploy "$keys"
  chmod 600 "$keys"
  echo "Added CI's deploy key"
fi

compose() {
  docker compose -f "$REPO/deploy/compose.yaml" --env-file "$ETC/settings.env" --env-file "$release" \
    --profile vm "$@"
}
if grep -q '^OFFBALL_IMAGE=offball:local$' "$release"; then
  echo "Building the image from this checkout"
  compose build offball
else
  compose pull offball
fi
compose up -d --wait --remove-orphans

bash "$REPO/deploy/smoke.sh"
echo "OffBall is up at https://$HOST/api/health"
