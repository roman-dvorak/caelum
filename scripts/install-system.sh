#!/usr/bin/env bash
#
# Installs (or upgrades) caelum as a systemd service on Debian / Raspberry Pi
# OS from a release wheel — no source checkout, no build on the device.
#
#   curl -fsSL https://github.com/roman-dvorak/caelum/releases/latest/download/install.sh | sudo bash
#   curl -fsSL .../install.sh | sudo bash -s -- --camera opencv
#
# Options: see usage() below, or run it with --help.
#
# Re-running it with a newer wheel upgrades; config, accounts and data are
# kept. Day-to-day upgrades are meant to happen from the web UI instead
# (System -> Software update), into the same layout:
#
#   /opt/caelum/releases/<version>/venv   one venv per release
#   /opt/caelum/current, previous         symlinks: running / rollback target
#   /opt/caelum/bin/caelum-launch         boot guard, systemd's ExecStart
#   /etc/caelum/                          caelum.env, config.json, auth.json,
#                                         upload_key(.pub) — the SSH key for uploads
#                                         and the tunnel, tunnel.env
#   /var/lib/caelum/                      captured data
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install.sh [options]      (as root)

Installs or upgrades caelum as a systemd service from a release wheel.
Re-running it upgrades; configuration, accounts and data are kept.

Installation:
  --wheel FILE|URL      install this wheel instead of the newest in the manifest
  --manifest URL        release manifest to read (default: latest GitHub release)
  --camera BACKEND      picamera2 | opencv | mock — only used to seed a new
                        config.json (default: picamera2 on a Raspberry Pi,
                        mock elsewhere); picamera2 also selects the apt camera
                        stack and the numpy pins that go with it
  --user NAME           service account (default: caelum)
  --proxy               serve the web UI on ports 80 and 443 through nginx with
                        a self-signed certificate; caelum itself then listens on
                        127.0.0.1:8000 only
  --no-start            install everything but don't enable/start the services
  --report              only print the report on the installed camera (version,
                        addresses, camera, upload, admin password, SSH key,
                        tunnel, services) — the same one every run ends with

This camera (written into an existing config.json too):
  --name TEXT           camera name (upload.camera_name), shown on images
  --slug ID             camera's directory on the upload target
                        (upload.camera_slug) — unique per camera
  --lat DEG             latitude, north positive
  --lon DEG             longitude, east positive
  --elevation M         elevation in metres
  --hostname NAME       set the system's host name (and NAME.local)
  --new-identity        for a card cloned from another camera: a new upload/
                        tunnel SSH key, a new admin password (printed at the
                        end; signs everyone out), a new session key and a new
                        TLS certificate

Reverse SSH tunnel (remote shell access through a server you control):
  --tunnel USER@HOST    keep `ssh -R PORT:localhost:22 USER@HOST` running, logged
                        in with the upload key
  --tunnel-port PORT    port on HOST that leads to this camera's sshd —
                        unique per camera
  --tunnel-ssh-port N   HOST's own sshd port (default 22)
  --no-tunnel           remove the tunnel
  Given once, the tunnel settings are kept in /etc/caelum/tunnel.env; a later
  run changes only what it names (e.g. just --tunnel-port).

  -h, --help            show this help

Example — a card cloned from camera 1 turned into camera 2:
  sudo bash install.sh --new-identity --hostname caelum-lhota-2 --name "Lhota 2" \
    --slug lhota-2 --lat 50.00 --lon 15.00 --elevation 300 --tunnel-port 20002
EOF
}

# What is installed and how to reach it — printed at the end of every run,
# and on its own with --report. Reads everything from disk, so it describes
# the installation as it is, not what this run was asked to do.
report() {
  local current previous port url line
  current="$(readlink "$PREFIX/current" 2>/dev/null)"
  previous="$(readlink "$PREFIX/previous" 2>/dev/null)"
  port="$(sed -n 's/^CAELUM_HTTP_PORT=//p' "$CONFIG_DIR/caelum.env" 2>/dev/null)"
  if [[ -e /etc/nginx/sites-enabled/caelum ]]; then
    url="https://$(hostname).local/  (self-signed certificate; http on port 80 too)"
  else
    url="http://$(hostname).local:${port:-8000}/"
  fi
  echo
  echo "======================== caelum report ========================"
  printf '%-14s%s\n' "Generated" "$(date '+%Y-%m-%d %H:%M %Z')"
  printf '%-14s%s\n' "Version" "${current#releases/}${previous:+  (rollback: ${previous#releases/})}"
  printf '%-14s%s\n' "Host name" "$(hostname)"
  printf '%-14s%s\n' "Addresses" "$(hostname -I 2>/dev/null | xargs)"
  printf '%-14s%s\n' "Web UI" "$url"
  line=""
  for unit in caelum caelum-tunnel redis-server nginx ssh; do
    if [[ $unit == caelum || -e "/etc/systemd/system/$unit.service" || -n "$(systemctl list-unit-files --no-legend "$unit.service" 2>/dev/null)" ]]; then
      line+="$unit $(systemctl is-active "$unit" 2>/dev/null), "
    fi
  done
  printf '%-14s%s\n' "Services" "${line%, }"
  if [[ -f "$CONFIG_DIR/config.json" ]]; then
    "$PREFIX/current/venv/bin/python" - "$CONFIG_DIR/config.json" <<'EOF'
import sys
from pathlib import Path
from caelum.config import store_disk
cfg = store_disk.read(Path(sys.argv[1]))
u, loc = cfg.upload, cfg.location
row = lambda key, value: print(f"{key:<14}{value}")
row("Camera", f'"{u.camera_name}", slug {u.camera_slug}, backend {cfg.camera.backend}')
row("Location", f"lat {loc.lat}, lon {loc.lon}, {loc.elevation_m:g} m, {loc.timezone}")
if u.transport == "s3":
    target = f"s3://{u.s3_bucket}/{u.s3_prefix}" + (f" at {u.s3_endpoint_url}" if u.s3_endpoint_url else "")
elif u.remote_host:
    target = f"{u.remote_user + '@' if u.remote_user else ''}{u.remote_host}:{u.remote_base_path}/{u.camera_slug}"
    target += f" (port {u.ssh_port}, key {u.ssh_key_path})"
else:
    target = f"{u.remote_base_path}/{u.camera_slug}"
row("Upload", f"{'on' if u.enabled else 'off'}, {u.transport} -> {target}")
EOF
  fi
  if [[ -f "$CONFIG_DIR/initial-admin-password.txt" ]]; then
    printf '%-14s%s\n' "Admin login" "admin / $(<"$CONFIG_DIR/initial-admin-password.txt")"
    printf '%-14s%s\n' "" "change it under Accounts, then delete $CONFIG_DIR/initial-admin-password.txt"
  else
    printf '%-14s%s\n' "Admin login" "password set by an admin, not stored (--new-identity sets a new one)"
  fi
  if [[ -f "$CONFIG_DIR/tunnel.env" ]]; then
    local t_host t_port t_ssh
    t_host="$(sed -n 's/^TUNNEL_HOST=//p' "$CONFIG_DIR/tunnel.env")"
    t_port="$(sed -n 's/^TUNNEL_PORT=//p' "$CONFIG_DIR/tunnel.env")"
    t_ssh="$(sed -n 's/^TUNNEL_SSH_PORT=//p' "$CONFIG_DIR/tunnel.env")"
    printf '%-14s%s\n' "Tunnel" "$t_host (sshd port ${t_ssh:-22}), port $t_port -> this camera's sshd"
    printf '%-14s%s\n' "" "from ${t_host#*@}: ssh -p $t_port <user>@localhost"
  else
    printf '%-14s%s\n' "Tunnel" "none"
  fi
  printf '%-14s%s\n' "Logs" "journalctl -u caelum -f"
  if [[ -f "$CONFIG_DIR/upload_key.pub" ]]; then
    echo
    echo "SSH public key ($CONFIG_DIR/upload_key.pub), for the upload user's ~/.ssh/"
    echo "authorized_keys on the archive host:"
    echo
    cat "$CONFIG_DIR/upload_key.pub"
    if [[ -f "$CONFIG_DIR/tunnel.env" ]]; then
      echo
      echo "and for ${t_host%@*}'s ~/.ssh/authorized_keys on ${t_host#*@}, limited to its port:"
      echo
      echo "restrict,port-forwarding,permitlisten=\"$t_port\" $(<"$CONFIG_DIR/upload_key.pub")"
    fi
  fi
  echo "==============================================================="
}

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
PROXY=0
NEW_IDENTITY=0
HOSTNAME_CHANGED=0
REPORT_ONLY=0
NAME="" SLUG="" LAT="" LON="" ELEVATION="" NEW_HOSTNAME=""
TUNNEL_ARG="" TUNNEL_PORT_ARG="" TUNNEL_SSH_PORT_ARG="" NO_TUNNEL=0

need_value() {
  [[ $# -ge 2 && "$2" != --* ]] || { echo "$1 needs a value (see --help)" >&2; exit 64; }
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --wheel|--manifest|--camera|--user|--name|--slug|--lat|--lon|--elevation|--hostname|--tunnel|--tunnel-port|--tunnel-ssh-port)
      need_value "$@" ;;&
    --wheel) WHEEL="$2"; shift 2 ;;
    --manifest) MANIFEST_URL="$2"; shift 2 ;;
    --camera) CAMERA="$2"; shift 2 ;;
    --user) SVC_USER="$2"; shift 2 ;;
    --no-start) START=0; shift ;;
    --proxy) PROXY=1; shift ;;
    --name) NAME="$2"; shift 2 ;;
    --slug) SLUG="$2"; shift 2 ;;
    --lat) LAT="$2"; shift 2 ;;
    --lon) LON="$2"; shift 2 ;;
    --elevation) ELEVATION="$2"; shift 2 ;;
    --hostname) NEW_HOSTNAME="$2"; shift 2 ;;
    --new-identity) NEW_IDENTITY=1; shift ;;
    --tunnel) TUNNEL_ARG="$2"; shift 2 ;;
    --tunnel-port) TUNNEL_PORT_ARG="$2"; shift 2 ;;
    --tunnel-ssh-port) TUNNEL_SSH_PORT_ARG="$2"; shift 2 ;;
    --no-tunnel) NO_TUNNEL=1; shift ;;
    --report) REPORT_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 64 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "run as root (sudo)" >&2
  exit 1
fi
if [[ $REPORT_ONLY -eq 1 ]]; then
  [[ -x "$PREFIX/current/venv/bin/python" ]] || { echo "caelum is not installed in $PREFIX" >&2; exit 1; }
  report
  exit 0
fi
if [[ -d "$PREFIX/.git" ]]; then
  echo "$PREFIX is a git checkout from an older install method — move it aside first" >&2
  exit 1
fi

if [[ -z "$CAMERA" ]]; then
  if grep -qs "Raspberry Pi" /proc/device-tree/model; then CAMERA=picamera2; else CAMERA=mock; fi
fi
case "$CAMERA" in picamera2|opencv|mock) ;; *) echo "bad --camera: $CAMERA" >&2; exit 64 ;; esac
is_num() { [[ "$1" =~ ^-?[0-9]+(\.[0-9]+)?$ ]]; }
is_port() { [[ "$1" =~ ^[0-9]+$ ]] && (( $1 >= 1 && $1 <= 65535 )); }
for v in LAT LON ELEVATION; do
  [[ -z "${!v}" ]] || is_num "${!v}" || { echo "bad --${v,,}: ${!v}" >&2; exit 64; }
done
[[ -z "$SLUG" || "$SLUG" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "bad --slug: $SLUG (letters, digits, . _ -)" >&2; exit 64; }
[[ -z "$NEW_HOSTNAME" || "$NEW_HOSTNAME" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$ ]] \
  || { echo "bad --hostname: $NEW_HOSTNAME" >&2; exit 64; }

# Tunnel: what tunnel.env already says, overridden by whatever was given now.
TUNNEL_ENV="$CONFIG_DIR/tunnel.env"
TUNNEL_HOST="" TUNNEL_PORT="" TUNNEL_SSH_PORT=22
if [[ -f "$TUNNEL_ENV" ]]; then
  TUNNEL_HOST="$(sed -n 's/^TUNNEL_HOST=//p' "$TUNNEL_ENV")"
  TUNNEL_PORT="$(sed -n 's/^TUNNEL_PORT=//p' "$TUNNEL_ENV")"
  TUNNEL_SSH_PORT="$(sed -n 's/^TUNNEL_SSH_PORT=//p' "$TUNNEL_ENV")"
fi
TUNNEL_HOST="${TUNNEL_ARG:-$TUNNEL_HOST}"
TUNNEL_PORT="${TUNNEL_PORT_ARG:-$TUNNEL_PORT}"
TUNNEL_SSH_PORT="${TUNNEL_SSH_PORT_ARG:-${TUNNEL_SSH_PORT:-22}}"
TUNNEL=0
if [[ $NO_TUNNEL -eq 1 ]]; then
  [[ -z "$TUNNEL_ARG$TUNNEL_PORT_ARG$TUNNEL_SSH_PORT_ARG" ]] || { echo "--no-tunnel with other --tunnel options" >&2; exit 64; }
elif [[ -n "$TUNNEL_HOST$TUNNEL_PORT" ]]; then
  [[ "$TUNNEL_HOST" =~ ^[^@[:space:]]+@[^@[:space:]]+$ ]] || { echo "the tunnel needs --tunnel USER@HOST" >&2; exit 64; }
  is_port "$TUNNEL_PORT" || { echo "the tunnel needs --tunnel-port 1-65535" >&2; exit 64; }
  is_port "$TUNNEL_SSH_PORT" || { echo "bad --tunnel-ssh-port: $TUNNEL_SSH_PORT" >&2; exit 64; }
  TUNNEL=1
fi

if [[ -n "$NEW_HOSTNAME" && "$NEW_HOSTNAME" != "$(hostname)" ]]; then
  echo "==> Host name $(hostname) -> $NEW_HOSTNAME"
  HOSTNAME_CHANGED=1
  hostnamectl set-hostname "$NEW_HOSTNAME"
  # Debian's 127.0.1.1 line; without it sudo complains it can't resolve the name.
  sed -i -E "s/^(127\.0\.1\.1[[:space:]]+).*$/\1$NEW_HOSTNAME/" /etc/hosts
  grep -qE "^127\.0\.1\.1[[:space:]]" /etc/hosts || echo "127.0.1.1	$NEW_HOSTNAME" >> /etc/hosts
  # The avahi daemon announces NAME.local; it caches the old name.
  systemctl try-restart avahi-daemon 2>/dev/null || true
fi

echo "==> System packages"
PKGS=(python3 python3-venv redis-server curl unzip openssh-client)
# libcamera has no PyPI wheel — apt's picamera2 is the only way to get it.
if [[ "$CAMERA" == picamera2 ]]; then PKGS+=(python3-picamera2); fi
# The tunnel leads to this machine's own sshd.
if [[ $TUNNEL -eq 1 ]]; then PKGS+=(openssh-server); fi
if [[ $PROXY -eq 1 ]]; then
  # Checked before installing nginx, whose default site wants port 80 too.
  if ss -ltnpH 'sport = :80 or sport = :443' | grep -qv nginx; then
    echo "ports 80/443 are taken by something other than nginx — stop it first:" >&2
    ss -ltnpH 'sport = :80 or sport = :443' >&2
    exit 1
  fi
  PKGS+=(nginx openssl)
fi
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
  # Built as the service account, exactly like a web update does it: the
  # release ends up owned by it, and pip fills the account's own cache
  # (~/.cache/pip, its home being $DATA_DIR), so later web updates only
  # download what changed.
  install -d -o "$SVC_USER" -g "$SVC_USER" "$RELEASE"
  install -m 0644 "$WHEEL" "$RELEASE/$(basename "$WHEEL")"
  WHEEL="$RELEASE/$(basename "$WHEEL")"
  VENV_ARGS=()
  PIP_ARGS=()
  if [[ "$CAMERA" == picamera2 ]]; then
    # apt's picamera2 is built against the system numpy; the wheel carries
    # the matching pins (caelum/constraints-rpi.txt).
    VENV_ARGS+=(--system-site-packages)
    unzip -p "$WHEEL" caelum/constraints-rpi.txt > "$RELEASE/constraints.txt"
    PIP_ARGS+=(-c "$RELEASE/constraints.txt")
  fi
  as_svc() { runuser -u "$SVC_USER" -- env HOME="$DATA_DIR" "$@"; }
  as_svc python3 -m venv "${VENV_ARGS[@]}" "$RELEASE/venv"
  as_svc "$RELEASE/venv/bin/pip" install -q --disable-pip-version-check "${PIP_ARGS[@]}" "$WHEEL"
  as_svc "$RELEASE/venv/bin/python" -c "import caelum.main"
  rm -f "$WHEEL"

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
# Nothing below may race the running service rewriting its own config; the
# end of the script starts it again (unless --no-start).
systemctl stop caelum 2>/dev/null || true

# The SSH key the rsync/scp upload transports and the tunnel log in with:
# generated once and kept — its public half may already be in a remote
# authorized_keys — unless this card is becoming another camera.
UPLOAD_KEY="$CONFIG_DIR/upload_key"
if [[ $NEW_IDENTITY -eq 1 ]]; then rm -f "$UPLOAD_KEY" "$UPLOAD_KEY.pub"; fi
if [[ ! -f "$UPLOAD_KEY" ]]; then
  runuser -u "$SVC_USER" -- ssh-keygen -q -t ed25519 -N '' \
    -C "caelum@$(hostname)" -f "$UPLOAD_KEY"
  echo "    generated the upload SSH key $UPLOAD_KEY"
fi
if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
  "$PREFIX/current/venv/bin/python" - "$CONFIG_DIR/config.json" "$CAMERA" "$UPLOAD_KEY" <<'EOF'
import sys
from caelum.config.schema import AppConfig
path, camera, upload_key = sys.argv[1], sys.argv[2], sys.argv[3]
cfg = AppConfig()
cfg.camera.backend = camera
cfg.upload.ssh_key_path = upload_key
if camera == "opencv":
    cfg.camera.sensor_id = "0"
open(path, "w").write(cfg.model_dump_json(indent=2) + "\n")
EOF
  chown "$SVC_USER:$SVC_USER" "$CONFIG_DIR/config.json"
  chmod 0600 "$CONFIG_DIR/config.json"
  echo "    seeded config.json (camera.backend=$CAMERA)"
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

if [[ -n "$NAME$SLUG$LAT$LON$ELEVATION" ]]; then
  "$PREFIX/current/venv/bin/python" - "$CONFIG_DIR/config.json" "$NAME" "$SLUG" "$LAT" "$LON" "$ELEVATION" <<'EOF'
import sys
from pathlib import Path
from caelum.config import store_disk
from caelum.config.schema import AppConfig
path, name, slug, lat, lon, elevation = Path(sys.argv[1]), *sys.argv[2:]
data = store_disk.read(path).model_dump()
for section, key, value in [("upload", "camera_name", name), ("upload", "camera_slug", slug),
                            ("location", "lat", lat), ("location", "lon", lon),
                            ("location", "elevation_m", elevation)]:
    if value:
        data[section][key] = value
        print(f"    {section}.{key} = {value}")
store_disk.write(path, AppConfig.model_validate(data))
EOF
  chown "$SVC_USER:$SVC_USER" "$CONFIG_DIR/config.json"
  chmod 0600 "$CONFIG_DIR/config.json"
  # Redis holds the running config too, and wins at start when its version is
  # newer; dropping it makes caelum take config.json as it is now.
  REDIS_URL="$(sed -n 's/^CAELUM_REDIS_URL=//p' "$CONFIG_DIR/caelum.env")"
  redis-cli -u "${REDIS_URL:-redis://127.0.0.1:6379/0}" DEL caelum:config caelum:config:version >/dev/null \
    || echo "    warning: could not clear the config cached in Redis — check the values in the web UI" >&2
fi

if [[ $NEW_IDENTITY -eq 1 ]]; then
  # A new admin password and session key: the cloned card's would otherwise
  # let the other camera's admin (and its open sessions) in here. Other
  # accounts are kept.
  # The report at the end prints it from initial-admin-password.txt.
  "$PREFIX/current/venv/bin/python" - "$CONFIG_DIR" <<'EOF'
import json, os, secrets, sys
from datetime import UTC, datetime
from pathlib import Path
from caelum.auth.passwords import hash_password
from caelum.auth.store import BOOTSTRAP_PASSWORD_FILE, BOOTSTRAP_USERNAME
config_dir = Path(sys.argv[1])
path = config_dir / "auth.json"
document = json.loads(path.read_text()) if path.exists() else {"version": 1, "users": {}}
password = secrets.token_urlsafe(18)
document["session_secret"] = secrets.token_bytes(32).hex()
document["users"][BOOTSTRAP_USERNAME] = {
    "role": "admin",
    "password_hash": hash_password(password),
    "token_version": 1,
    "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    "last_login_at": None,
}
for name, text in [("auth.json", json.dumps(document, indent=2)), (BOOTSTRAP_PASSWORD_FILE, password + "\n")]:
    fd = os.open(config_dir / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
EOF
  chown "$SVC_USER:$SVC_USER" "$CONFIG_DIR/auth.json" "$CONFIG_DIR/initial-admin-password.txt"
  echo "    new admin password and session key"
fi

TLS_DIR="$CONFIG_DIR/tls"
make_cert() {
  # A camera on a LAN has no public name a CA could vouch for: self-signed,
  # for the host's name only — its address may change (DHCP), its name not.
  # Replace the two files with a real certificate to lose the browser warning.
  install -d -m 0750 "$TLS_DIR"
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=$(hostname)" \
    -addext "subjectAltName=DNS:$(hostname),DNS:$(hostname).local,DNS:localhost" \
    -keyout "$TLS_DIR/caelum.key" -out "$TLS_DIR/caelum.crt" 2>/dev/null
  chmod 0600 "$TLS_DIR/caelum.key"
}
# A certificate for the old name (or the other camera's key) is no use now.
if [[ -f "$TLS_DIR/caelum.crt" && $PROXY -eq 0 ]] && (( NEW_IDENTITY || HOSTNAME_CHANGED )); then
  echo "==> New TLS certificate for $(hostname)"
  make_cert
  systemctl try-reload-or-restart nginx 2>/dev/null || true
fi

if [[ $PROXY -eq 1 ]]; then
  echo "==> nginx on ports 80 and 443"
  # Nothing but nginx should reach caelum once it is in front.
  sed -i 's/^CAELUM_HTTP_HOST=.*/CAELUM_HTTP_HOST=127.0.0.1/' "$CONFIG_DIR/caelum.env"
  PORT="$(sed -n 's/^CAELUM_HTTP_PORT=//p' "$CONFIG_DIR/caelum.env")"
  if [[ ! -f "$TLS_DIR/caelum.crt" ]] || (( NEW_IDENTITY || HOSTNAME_CHANGED )); then make_cert; fi
  rm -f /etc/nginx/sites-enabled/default
  sed -e "s|@TLS_DIR@|$TLS_DIR|g" -e "s|@PORT@|${PORT:-8000}|g" > /etc/nginx/sites-available/caelum <<'NGINX'
# Written by caelum's install-system.sh --proxy.
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;

    ssl_certificate     @TLS_DIR@/caelum.crt;
    ssl_certificate_key @TLS_DIR@/caelum.key;

    # Room for a software-update wheel uploaded from the browser.
    client_max_body_size 128m;

    location / {
        proxy_pass http://127.0.0.1:@PORT@;
        proxy_http_version 1.1;
        # /ws/stream, /ws/logs, /ws/terminal, /ws/update
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 1h;
    }
}
NGINX
  ln -sfn /etc/nginx/sites-available/caelum /etc/nginx/sites-enabled/caelum
  nginx -t -q
  if [[ $START -eq 1 ]]; then systemctl enable --now nginx && systemctl reload nginx; fi
fi

echo "==> systemd unit"
sed -e "s|@PREFIX@|$PREFIX|g" -e "s|@USER@|$SVC_USER|g" \
    -e "s|@CONFIG_DIR@|$CONFIG_DIR|g" -e "s|@DATA_DIR@|$DATA_DIR|g" \
    "$DEPLOY/caelum.service.in" > /etc/systemd/system/caelum.service

TUNNEL_UNIT=/etc/systemd/system/caelum-tunnel.service
if [[ $TUNNEL -eq 1 ]]; then
  echo "==> Reverse SSH tunnel: $TUNNEL_HOST port $TUNNEL_PORT -> this camera's sshd"
  cat > "$TUNNEL_ENV" <<EOF
# Reverse SSH tunnel — written by install-system.sh; re-run it to change.
TUNNEL_HOST=$TUNNEL_HOST
TUNNEL_PORT=$TUNNEL_PORT
TUNNEL_SSH_PORT=$TUNNEL_SSH_PORT
EOF
  chmod 0644 "$TUNNEL_ENV"
  # Plain ssh restarted by systemd does what autossh would. ExitOnForwardFailure:
  # a port still held on the server (stale session, another camera) is retried
  # rather than leaving a tunnel-less connection up.
  cat > "$TUNNEL_UNIT" <<EOF
[Unit]
Description=caelum reverse SSH tunnel
Wants=network-online.target
After=network-online.target

[Service]
User=$SVC_USER
EnvironmentFile=$TUNNEL_ENV
ExecStart=/usr/bin/ssh -N -i $UPLOAD_KEY -p \${TUNNEL_SSH_PORT} \\
  -o BatchMode=yes -o StrictHostKeyChecking=accept-new \\
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \\
  -R \${TUNNEL_PORT}:localhost:22 \${TUNNEL_HOST}
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
elif [[ $NO_TUNNEL -eq 1 && -f "$TUNNEL_UNIT" ]]; then
  echo "==> Removing the reverse SSH tunnel"
  systemctl disable --now caelum-tunnel 2>/dev/null || true
  rm -f "$TUNNEL_UNIT" "$TUNNEL_ENV"
fi

AUTH_EXISTED=0
[[ -f "$CONFIG_DIR/auth.json" ]] && AUTH_EXISTED=1
systemctl daemon-reload
if [[ $START -eq 1 ]]; then
  systemctl enable --now redis-server
  systemctl enable caelum
  systemctl restart caelum
  if [[ $TUNNEL -eq 1 ]]; then
    systemctl enable --now ssh
    systemctl enable caelum-tunnel
    systemctl restart caelum-tunnel
  fi
fi

if [[ $START -eq 1 && $AUTH_EXISTED -eq 0 ]]; then
  # The first start creates the admin account and writes its password.
  for _ in $(seq 60); do
    [[ -f "$CONFIG_DIR/initial-admin-password.txt" ]] && break
    sleep 1
  done
fi

echo
echo "caelum $VERSION installed (camera=$CAMERA)."
report
}

main "$@"
