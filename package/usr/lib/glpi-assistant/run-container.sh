#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE=glpi-assistant:3.4.0-beta.1
DATA_DIR=/var/lib/glpi-assistant/data
NAME=glpi-assistant

mkdir -p "$DATA_DIR"
chmod 700 "$DATA_DIR" || true

exec /usr/bin/docker run --rm --name "$NAME" \
  --pull never \
  --network host \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=128m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 256 \
  --memory 1g --memory-swap 1g --cpus 2 \
  -v /etc/ssl/certs:/etc/ssl/certs:ro \
  -v "$DATA_DIR:/data:rw" \
  "$IMAGE"
