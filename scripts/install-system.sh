#!/usr/bin/env bash
#
# Installs (or upgrades) caelum as a systemd service on Debian / Raspberry Pi
# OS from a release wheel — no source checkout, no build on the device.
#
#   curl -fsSL https://github.com/roman-dvorak/caelum/releases/latest/download/install.sh | sudo bash
#   curl -fsSL .../install.sh | sudo bash -s -- --camera opencv
#
# Options:
#   --wheel FILE|URL    install this wheel instead of the newest one in the manifest
#   --manifest URL      release manifest to read (default: latest GitHub release)
#   --camera BACKEND    picamera2 | opencv | mock — only used to seed a new
#                       config.json (default: picamera2 on a Raspberry Pi,
#                       mock elsewhere); picamera2 also selects the apt
#                       camera stack and the numpy pins that go with it
#   --user NAME         service account (default: caelum)
#   --no-start          install everything but don't enable/start the service
#
# Re-running it with a newer wheel upgrades; config, accounts and data are
# kept. Day-to-day upgrades are meant to happen from the web UI instead
# (System -> Software update), into the same layout:
#
#   /opt/caelum/releases/<version>/venv   one venv per release
#   /opt/caelum/current, previous         symlinks: running / rollback target
#   /opt/caelum/bin/caelum-launch         boot guard, systemd's ExecStart
#   /etc/caelum/                          caelum.env, config.json, auth.json
#   /var/lib/caelum/                      captured data
set -euo pipefail

# Wrapped in a function so that bash has read the whole script before running
# any of it — under `curl | bash`, apt-get would otherwise eat the rest of the
# script from stdin.
main() {
PREFIX=/opt/caelum
CONFIG_DIR=/etc/caelum
DATA_DIR=/var/lib/caelum
MANIFEST_URL=https://github.com/roman-dvorak/caelum/releases/latest/download/manifest.json
SVC_USER=caelum
CAMERA=""
WHEEL=""
START=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wheel) WHEEL="$2"; shift 2 ;;
    --manifest) MANIFEST_URL="$2"; shift 2 ;;
    --camera) CAMERA="$2"; shift 2 ;;
    --user) SVC_USER="$2"; shift 2 ;;
    --no-start) START=0; shift ;;
    -h|--help) echo "see the comment at the top of install-system.sh"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 64 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "run as root (sudo)" >&2
  exit 1
fi
if [[ -d "$PREFIX/.git" ]]; then
  echo "$PREFIX is a git checkout from an older install method — move it aside first" >&2
  exit 1
fi

if [[ -z "$CAMERA" ]]; then
  if grep -qs "Raspberry Pi" /proc/device-tree/model; then CAMERA=picamera2; else CAMERA=mock; fi
fi
case "$CAMERA" in picamera2|opencv|mock) ;; *) echo "bad --camera: $CAMERA" >&2; exit 64 ;; esac

echo "==> System packages"
PKGS=(python3 python3-venv redis-server curl unzip)
# libcamera has no PyPI wheel — apt's picamera2 is the only way to get it.
if [[ "$CAMERA" == picamera2 ]]; then PKGS+=(python3-picamera2); fi
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq "${PKGS[@]}" >/dev/null

echo "==> Release wheel"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
if [[ -z "$WHEEL" ]]; then
  curl -fsSL "$MANIFEST_URL" -o "$WORK/manifest.json"
  # Newest release; its wheel path is relative to the manifest's URL.
  read -r VERSION WHEEL_REF SHA256 < <(python3 - "$WORK/manifest.json" <<'EOF'
import json, sys
releases = json.load(open(sys.argv[1]))["releases"]
key = lambda r: [int(p) if p.isdigit() else -1 for p in r["version"].replace("-", ".").split(".")]
r = max(releases, key=key)
print(r["version"], r["wheel"], r.get("sha256") or "-")
EOF
)
  case "$WHEEL_REF" in
    http://*|https://*) WHEEL="$WHEEL_REF" ;;
    *) WHEEL="${MANIFEST_URL%/*}/$WHEEL_REF" ;;
  esac
  echo "    newest release in manifest: $VERSION"
else
  SHA256=-
fi
case "$WHEEL" in
  http://*|https://*)
    curl -fsSL "$WHEEL" -o "$WORK/${WHEEL##*/}"
    WHEEL="$WORK/${WHEEL##*/}" ;;
  *) [[ -f "$WHEEL" ]] || { echo "no such wheel: $WHEEL" >&2; exit 1; } ;;
esac
if [[ "$SHA256" != - ]]; then
  echo "$SHA256  $WHEEL" | sha256sum -c --quiet -
fi
VERSION="$(basename "$WHEEL" | sed -n 's/^caelum-\([^-]*\)-.*\.whl$/\1/p')"
[[ -n "$VERSION" ]] || { echo "$(basename "$WHEEL") is not a caelum wheel" >&2; exit 1; }

echo "==> Service account '$SVC_USER'"
if ! id "$SVC_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SVC_USER"
fi
# video: /dev/video*, /dev/media* (V4L2 webcams and libcamera alike).
usermod -aG video "$SVC_USER"
install -d -o "$SVC_USER" -g "$SVC_USER" -m 0750 "$CONFIG_DIR" "$DATA_DIR"
# The service account owns the release tree: web updates run as it.
install -d -o "$SVC_USER" -g "$SVC_USER" -m 0755 "$PREFIX" "$PREFIX/releases"
install -d -m 0755 "$PREFIX/bin"

RELEASE="$PREFIX/releases/$VERSION"
if [[ "$(readlink "$PREFIX/current" 2>/dev/null)" == "releases/$VERSION" && -x "$RELEASE/venv/bin/caelum" ]]; then
  echo "==> $VERSION is already installed — refreshing configuration only"
else
  echo "==> Installing caelum $VERSION into $RELEASE"
  rm -rf "$RELEASE"
  VENV_ARGS=()
  PIP_ARGS=()
  if [[ "$CAMERA" == picamera2 ]]; then
    # apt's picamera2 is built against the system numpy; the wheel carries
    # the matching pins (caelum/constraints-rpi.txt).
    VENV_ARGS+=(--system-site-packages)
    install -d "$RELEASE"
    unzip -p "$WHEEL" caelum/constraints-rpi.txt > "$RELEASE/constraints.txt"
    PIP_ARGS+=(-c "$RELEASE/constraints.txt")
  fi
  python3 -m venv "${VENV_ARGS[@]}" "$RELEASE/venv"
  # The service account's own pip cache (its home is $DATA_DIR) — web
  # updates run as that account and then only download what changed.
  PIP_CACHE_DIR="$DATA_DIR/.cache/pip" "$RELEASE/venv/bin/pip" install -q --disable-pip-version-check \
    "${PIP_ARGS[@]}" "$WHEEL"
  chown -R "$SVC_USER:$SVC_USER" "$DATA_DIR/.cache"
  "$RELEASE/venv/bin/python" -c "import caelum.main"
  chown -R "$SVC_USER:$SVC_USER" "$RELEASE"

  if [[ -L "$PREFIX/current" ]]; then
    ln -sfn "$(readlink "$PREFIX/current")" "$PREFIX/previous.tmp"
    mv -T "$PREFIX/previous.tmp" "$PREFIX/previous"
  fi
  ln -sfn "releases/$VERSION" "$PREFIX/current.tmp"
  mv -T "$PREFIX/current.tmp" "$PREFIX/current"
  chown -h "$SVC_USER:$SVC_USER" "$PREFIX/current" "$PREFIX/previous" 2>/dev/null || true
  # Installed by hand, with someone watching — no boot-guard probation.
  rm -f "$PREFIX/update-pending"
fi

DEPLOY="$("$PREFIX/current/venv/bin/python" -c 'import caelum, pathlib; print(pathlib.Path(caelum.__file__).parent / "deploy")')"
install -m 0755 "$DEPLOY/caelum-launch" "$PREFIX/bin/caelum-launch"

echo "==> Configuration in $CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
  "$PREFIX/current/venv/bin/python" - "$CONFIG_DIR/config.json" "$CAMERA" <<'EOF'
import sys
from caelum.config.schema import AppConfig
path, camera = sys.argv[1], sys.argv[2]
cfg = AppConfig()
cfg.camera.backend = camera
if camera == "opencv":
    cfg.camera.sensor_id = "0"
open(path, "w").write(cfg.model_dump_json(indent=2) + "\n")
EOF
  chown "$SVC_USER:$SVC_USER" "$CONFIG_DIR/config.json"
  chmod 0600 "$CONFIG_DIR/config.json"
  echo "    seeded config.json (camera.backend=$CAMERA) — set the location in the web UI"
fi

if [[ ! -f "$CONFIG_DIR/caelum.env" ]]; then
  cat > "$CONFIG_DIR/caelum.env" <<EOF
# Bootstrap settings for the caelum service — see .env.example in the repo.
CAELUM_CONFIG_DIR=$CONFIG_DIR
CAELUM_DATA_DIR=$DATA_DIR
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
    "$DEPLOY/caelum.service.in" > /etc/systemd/system/caelum.service

if [[ $START -eq 1 ]]; then
  systemctl daemon-reload
  systemctl enable --now redis-server
  systemctl enable caelum
  systemctl restart caelum
fi

PORT="$(sed -n 's/^CAELUM_HTTP_PORT=//p' "$CONFIG_DIR/caelum.env")"
echo
echo "caelum $VERSION installed (camera=$CAMERA)."
echo "Open http://$(hostname -I 2>/dev/null | awk '{print $1}'):${PORT:-8000}/"
echo "First admin password (created on first start): $CONFIG_DIR/initial-admin-password.txt"
echo "Logs: journalctl -u caelum -f"
}

main "$@"
