---
description: 'Installing caelum on a Raspberry Pi: what you need, the one-line installer and its options, https, the first login and where everything lives.'
---

# Installation

caelum installs from a release with one command — no source checkout and
nothing to build on the camera. The same command later upgrades an existing
install, keeping its configuration, accounts and data.

## What you need

- **A Raspberry Pi** with **Raspberry Pi OS Bookworm** or another
  Debian Bookworm system, and a camera module — or an
  [AMASC01](/cameras/amasc01), which has both. Any Debian machine works with
  a USB webcam.
- **A network connection** during installation; afterwards the camera works
  offline.
- **An SSH session or a terminal** on the Pi, with `sudo`.

## Install

```bash
curl -fsSL https://github.com/roman-dvorak/caelum/releases/latest/download/install.sh | sudo bash
```

The installer:

1. installs the system packages caelum needs (Redis, and on a Pi the
   libcamera camera stack),
2. creates a `caelum` service account,
3. installs the newest release, backend and web interface together,
4. writes a starting configuration, and
5. starts caelum as a systemd service that comes back after every reboot.

### Options

Add options after `sudo bash -s --`:

```bash
curl -fsSL https://github.com/roman-dvorak/caelum/releases/latest/download/install.sh | sudo bash -s -- --proxy
```

| Option | What it does |
|---|---|
| `--proxy` | Serves the web interface over **https** on ports 80 and 443 through nginx — recommended. See below. |
| `--camera picamera2\|opencv\|mock` | Camera backend for a new configuration. Default: `picamera2` on a Raspberry Pi, `mock` elsewhere. `opencv` is a USB webcam. |
| `--wheel FILE\|URL` | Install this release file instead of the newest one — for offline machines. |
| `--manifest URL` | Read releases from another [update channel](/guide/updates#update-channels-and-self-hosting). |
| `--no-start` | Install everything, but don't start the service. |
| `--report` | Install nothing, only print the report on the installed camera — see below. |
| `-h`, `--help` | List all options. |

### Setting up one camera of several

These options set the values that differ from camera to camera. They are
written into the configuration even when it already exists, so the same
command also re-labels a camera that is already installed:

| Option | What it does |
|---|---|
| `--name TEXT` | Camera name, shown on images (`upload.camera_name`). |
| `--slug ID` | The camera's directory on the upload target (`upload.camera_slug`). Two cameras with the same slug overwrite each other's uploads. |
| `--lat DEG`, `--lon DEG`, `--elevation M` | Observing site; north and east positive. |
| `--hostname NAME` | The system's host name, so the camera is `NAME.local` on the network. |
| `--new-identity` | For an SD card cloned from another camera: a new SSH key, a new admin password, a new session key (everyone is signed out) and a new TLS certificate. The new password is printed at the end. |

A card cloned from camera 1, turned into camera 2:

```bash
sudo bash install.sh --new-identity --hostname caelum-lhota-2 --name "Lhota 2" \
  --slug lhota-2 --lat 50.00 --lon 15.00 --elevation 300 --tunnel-port 20002
```

### Reverse SSH tunnel

A camera behind NAT or a mobile connection can't be reached from outside. With
a tunnel it keeps an SSH connection to a server you control open and forwards a
port there back to its own SSH daemon:

| Option | What it does |
|---|---|
| `--tunnel USER@HOST` | The server, and the account the camera logs in as. |
| `--tunnel-port PORT` | Port on the server that leads to this camera — a different one for every camera. |
| `--tunnel-ssh-port N` | The server's SSH port, if not 22. |
| `--no-tunnel` | Remove the tunnel. |

The settings are kept in `/etc/caelum/tunnel.env`; a later run changes only
the ones it names, so `--tunnel-port 20002` alone re-numbers a cloned camera.
The tunnel runs as the `caelum-tunnel` service, logs in with the same key as
uploads and reconnects on its own. The installer also installs and enables the
camera's SSH server.

On the server, add the key the installer prints to the tunnel account's
`~/.ssh/authorized_keys`, limited to opening that one port:

```
restrict,port-forwarding,permitlisten="20002" ssh-ed25519 AAAA... caelum@caelum-lhota-2
```

Then, on the server, `ssh -p 20002 pi@localhost` is a shell on the camera.

### https with `--proxy`

`--proxy` puts nginx in front of caelum on ports 80 and 443 and binds caelum
itself to `127.0.0.1:8000`, so nothing else on the network can reach it
directly. The web interface is then at `https://<camera>/`.

The installer creates a self-signed certificate for the camera's host name in
`/etc/caelum/tls/` (`caelum.crt`, `caelum.key`). Browsers warn about it until
you accept it once; replace the two files with a real certificate to lose the
warning. https is also what [Caelum Viewer](/viewer#straight-from-a-camera)
needs to read a camera directly.

Without `--proxy`, caelum answers plain http on port 8000 on every network
interface.

## First login

On its first start caelum creates an `admin` account with a random password:

```bash
sudo cat /etc/caelum/initial-admin-password.txt
```

Open `https://<camera>/` (or `http://<camera>:8000/` without `--proxy`), log
in as `admin`, change the password under **Accounts** and delete the file.
Lost the password later? See
[Resetting a forgotten admin password](/guide/security#resetting-a-forgotten-admin-password).

With `--new-identity` the installer sets a new admin password itself and
prints it at the end of its output instead.

The installer also generates an SSH key for [uploads](/guide/upload#ssh-key-setup)
and the tunnel, `/etc/caelum/upload_key`, and ends its output with the public
half — the line to put in the archive host's `authorized_keys`.

### The report

Every run of the installer ends with a report on the camera: installed and
rollback version, host name and addresses, web address, state of the services,
camera name and slug, location, upload target, the admin password while
`initial-admin-password.txt` still exists, the tunnel and the SSH public key —
for the tunnel also the ready-made `authorized_keys` line. To print it again
without installing anything:

```bash
curl -fsSL https://github.com/roman-dvorak/caelum/releases/latest/download/install.sh | sudo bash -s -- --report
```

Then continue with [Getting started](/getting-started) — the observing site
comes next.

## Where things live

```
/etc/caelum/                          caelum.env, config.json, auth.json, tls/,
                                      upload_key, tunnel.env
/var/lib/caelum/                      captured data
/opt/caelum/releases/<version>/       one installed release each
/opt/caelum/current, previous         the running release and the rollback target
```

Configuration and data are kept apart from the releases, so an update or a
rollback never touches them.

## Updating

Later releases install from the web interface — **System → Software update** —
with an automatic rollback if the new release fails to start. See
[Updates](/guide/updates). Re-running the installer upgrades too.

## Checking the service

```bash
systemctl status caelum          # running, or restarting in a loop?
journalctl -u caelum -f          # its log, live
```

The same log is in the web interface under **Logs**.
