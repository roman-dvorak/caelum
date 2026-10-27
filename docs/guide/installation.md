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

The installer also generates an SSH key for [uploads](/guide/upload#ssh-key-setup),
`/etc/caelum/upload_key`, and ends its output with the public half — the line
to put in the archive host's `authorized_keys`.

Then continue with [Getting started](/getting-started) — the observing site
comes next.

## Where things live

```
/etc/caelum/                          caelum.env, config.json, auth.json, tls/
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
