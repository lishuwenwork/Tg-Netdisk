#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
runtime=$(mktemp -d /tmp/tg-netdisk-container-check.XXXXXX)
name="tg-netdisk-check-$(date +%s)"
case "$runtime" in /tmp/tg-netdisk-container-check.*) ;; *) exit 1;; esac
mkdir -p "$runtime/data" "$runtime/media" "$runtime/secrets"
cp "$root/desktop/icon.png" "$runtime/media/cover.png"
ln -s /run/secrets/password "$runtime/media/escape.png"
ln -s /data "$runtime/media/outside"
python3 - "$runtime" <<'PY'
import base64, pathlib, secrets, sys
root=pathlib.Path(sys.argv[1])
(root/'secrets/password').write_text(secrets.token_urlsafe(24))
(root/'secrets/key').write_bytes(base64.urlsafe_b64encode(secrets.token_bytes(32)))
PY
chmod 700 "$runtime" "$runtime/data" "$runtime/secrets"
chmod 600 "$runtime/secrets/password" "$runtime/secrets/key"
chown -R 10001:10001 "$runtime"
cleanup() { docker stop -t 30 "$name" >/dev/null 2>&1 || true; docker rm "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM
docker run -d --name "$name" --network=host --cap-drop ALL --security-opt no-new-privileges:true \
  -e TG_BIND=127.0.0.1 -e TG_PORT=18082 -e TG_PUBLIC_ORIGIN=http://localhost:18082 \
  -e TG_WEB_PASSWORD_FILE=/run/secrets/password -e TG_SECRET_KEY_FILE=/run/secrets/key \
  -v "$runtime/data:/data" -v "$runtime/media:/media:ro" -v "$runtime/secrets:/run/secrets:ro" \
  "${TG_DOCKER_IMAGE:-tg-netdisk:web-check}" >/dev/null
wait_ready() {
  for attempt in $(seq 1 60); do
    if curl -fsS http://localhost:18082/api/health >/dev/null 2>&1; then return; fi
    sleep 1
  done
  docker logs "$name"
  exit 1
}
wait_ready
python3 "$root/scripts/probe-web.py" --url http://localhost:18082 --password-file "$runtime/secrets/password" --cookie-file "$runtime/cookies" --phase initial
if grep -q '0123456789abcdef0123456789abcdef' "$runtime/data/credentials.enc"; then exit 1; fi
docker stop -t 30 "$name" >/dev/null
test "$(docker inspect -f '{{.State.ExitCode}}' "$name")" = 0
docker start "$name" >/dev/null
wait_ready
python3 "$root/scripts/probe-web.py" --url http://localhost:18082 --password-file "$runtime/secrets/password" --cookie-file "$runtime/cookies" --phase restart
echo "Docker runtime passed: non-root, static assets, login, server media, Range, encrypted secrets, persistent draft and graceful restart."
