#!/usr/bin/env bash
#
# System install of caelum as a systemd service on Debian / Raspberry Pi OS.
# Run as root from a clone of this repository; re-run it after `git pull` to
# upgrade. Idempotent: an existing config, env file and accounts are kept.
#
#   sudo git clone https://github.com/roman-dvorak/caelum /opt/caelum
#   sudo /opt/caelum/scripts/install-system.sh [options]
#
# Options:
#   --camera BACKEND    picamera2 | opencv | mock — only used to seed a new
#                       config.json (default: picamera2 on a Raspberry Pi,
#                       mock elsewhere)
#   --web-dist DIR      a built caelum-web apps/local-web/dist to serve at /
#   --user NAME         service account (default: caelum)
#   --no-start          install everything but don't enable/start the service
#
# Layout:
#   <clone>/            code + .venv (the directory this script lives in)
#   <clone>/web/        copy of --web-dist
#   /etc/caelum/        caelum.env, config.json, default.json, auth.json
#   /var/lib/caelum/    captured data (CAELUM_DATA_DIR)
set -euo pipefail

PREFIX="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR=/etc/caelum
DATA_DIR=/var/lib/caelum
SVC_USER=caelum
CAMERA=""
WEB_DIST=""
START=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --camera) CAMERA="$2"; shift 2 ;;
    --web-dist) WEB_DIST="$(cd "$2" && pwd)"; shift 2 ;;
    --user) SVC_USER="$2"; shift 2 ;;
    --no-start) START=0; shift ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 64 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "run as root (sudo $0)" >&2
  exit 1
fi

IS_PI=0
if grep -qs "Raspberry Pi" /proc/device-tree/model; then IS_PI=1; fi
if [[ -z "$CAMERA" ]]; then
  if [[ $IS_PI -eq 1 ]]; then CAMERA=picamera2; else CAMERA=mock; fi
fi
case "$CAMERA" in picamera2|opencv|mock) ;; *) echo "bad --camera: $CAMERA" >&2; exit 64 ;; esac

echo "==> Installing system packages"
PKGS=(python3 python3-venv python3-pip redis-server rsync)
# libcamera has no PyPI wheel — apt's picamera2 is the only way to get it.
if [[ "$CAMERA" == picamera2 ]]; then PKGS+=(python3-picamera2); fi
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq "${PKGS[@]}"

echo "==> Service account '$SVC_USER'"
if ! id "$SVC_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SVC_USER"
fi
# video: /dev/video*, /dev/media* (V4L2 webcams and libcamera alike).
usermod -aG video "$SVC_USER"
install -d -o "$SVC_USER" -g "$SVC_USER" -m 0750 "$CONFIG_DIR" "$DATA_DIR"

echo "==> Python environment in $PREFIX/.venv"
VENV_ARGS=()
PIP_ARGS=()
if [[ "$CAMERA" == picamera2 ]]; then
  # See scripts/constraints-rpi.txt for why both of these are needed.
  VENV_ARGS+=(--system-site-packages)
  PIP_ARGS+=(-c "$PREFIX/scripts/constraints-rpi.txt")
fi
if [[ ! -x "$PREFIX/.venv/bin/python" ]]; then
  python3 -m venv "${VENV_ARGS[@]}" "$PREFIX/.venv"
fi
"$PREFIX/.venv/bin/pip" install -q --upgrade pip
"$PREFIX/.venv/bin/pip" install -q "${PIP_ARGS[@]}" "$PREFIX"

echo "==> Configuration in $CONFIG_DIR"
# default.json is shipped defaults, refreshed on every upgrade; config.json
# is the live document and is only ever seeded, never overwritten.
install -o "$SVC_USER" -g "$SVC_USER" -m 0640 "$PREFIX/config/default.json" "$CONFIG_DIR/default.json"
if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
  "$PREFIX/.venv/bin/python" - "$CONFIG_DIR" "$CAMERA" <<'EOF'
import json, sys, pathlib
d, camera = pathlib.Path(sys.argv[1]), sys.argv[2]
cfg = json.loads((d / "default.json").read_text())
cfg["camera"]["backend"] = camera
if camera == "opencv":
    cfg["camera"]["sensor_id"] = "0"
(d / "config.json").write_text(json.dumps(cfg, indent=2) + "\n")
EOF
  chown "$SVC_USER:$SVC_USER" "$CONFIG_DIR/config.json"
  echo "    seeded config.json (camera.backend=$CAMERA) — set location in the web UI"
fi

WEB_DIR="$PREFIX/web"
if [[ -n "$WEB_DIST" ]]; then
  echo "==> Web UI from $WEB_DIST"
  if [[ ! -f "$WEB_DIST/index.html" ]]; then
    echo "$WEB_DIST has no index.html — pass caelum-web's apps/local-web/dist" >&2
    exit 1
  fi
  rsync -a --delete "$WEB_DIST/" "$WEB_DIR/"
fi

if [[ ! -f "$CONFIG_DIR/caelum.env" ]]; then
  cat > "$CONFIG_DIR/caelum.env" <<EOF
# Bootstrap settings for the caelum service — see .env.example in the repo.
CAELUM_CONFIG_DIR=$CONFIG_DIR
CAELUM_DATA_DIR=$DATA_DIR
CAELUM_WEB_DIR=$WEB_DIR
CAELUM_HTTP_HOST=0.0.0.0
CAELUM_HTTP_PORT=8000
CAELUM_REDIS_URL=redis://127.0.0.1:6379/0
CAELUM_LOG_LEVEL=INFO
# The service account's login shell is nologin; the web terminal needs a real one.
CAELUM_TERMINAL_SHELL=/bin/bash
EOF
  chmod 0640 "$CONFIG_DIR/caelum.env"
  chown "root:$SVC_USER" "$CONFIG_DIR/caelum.env"
fi

echo "==> systemd unit"
sed -e "s|@PREFIX@|$PREFIX|g" -e "s|@USER@|$SVC_USER|g" \
    -e "s|@CONFIG_DIR@|$CONFIG_DIR|g" -e "s|@DATA_DIR@|$DATA_DIR|g" \
    "$PREFIX/systemd/caelum.service.template" > /etc/systemd/system/caelum.service

if [[ $START -eq 1 ]]; then
  systemctl daemon-reload
  systemctl enable --now redis-server
  systemctl enable caelum
  systemctl restart caelum
fi

PORT="$(sed -n 's/^CAELUM_HTTP_PORT=//p' "$CONFIG_DIR/caelum.env")"
echo
echo "caelum installed (camera=$CAMERA)."
[[ -d "$WEB_DIR" ]] || echo "No web UI installed — the API runs alone. Re-run with --web-dist to add it."
echo "Open http://$(hostname -I 2>/dev/null | awk '{print $1}'):${PORT:-8000}/"
echo "First admin password (created on first start): $CONFIG_DIR/initial-admin-password.txt"
echo "Logs: journalctl -u caelum -f"
