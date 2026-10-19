---
description: 'Updating caelum from the web UI: release manifests, offline wheel upload and automatic rollback after a bad release.'
---

# Updates

An install made by the [installer](/guide/deployment#install) updates itself
from the web UI: **System → Software update**. Admin only.

## What happens

1. **Check for updates** fetches the release manifest at
   `update.manifest_url` and offers the newest release newer than the running
   one, with its release notes.
2. **Update** downloads that release's wheel (verifying its SHA-256 from the
   manifest) and installs it into a fresh virtualenv,
   `/opt/caelum/releases/<version>`, next to the running release. The camera
   keeps capturing meanwhile; the install log streams into the page.
3. The new release is smoke-tested (`import caelum.main` in its own venv),
   then `current` is switched to it, `previous` to the release that was
   running, and caelum exits. systemd starts the new release — capture pauses
   for a few seconds.
4. Once the new release has run for a minute, it confirms itself healthy and
   removes releases other than `current` and `previous`.

If anything before the switch fails — download, checksum, pip, smoke test —
the running release is never touched; the page shows the error.

## Automatic rollback

If the new release does not stay up, systemd keeps restarting it, and the boot
guard (`/opt/caelum/bin/caelum-launch`, a small shell script outside every
release) counts those starts. On the fourth one it switches `current` back to
`previous` and starts that instead. The System page then reports that the
update was rolled back. No SSH needed.

## Offline cameras

A camera without internet access can be updated by uploading the wheel file
(`caelum-<version>-py3-none-any.whl` from a release) under **Install a wheel
file**. The rest is identical. pip still needs to reach PyPI for any
dependency that changed since the running release; dependencies already
installed once come from the service account's pip cache.

## Update channels and self-hosting

The manifest is a static JSON file:

```json
{
  "releases": [
    {
      "version": "0.3.0",
      "wheel": "caelum-0.3.0-py3-none-any.whl",
      "sha256": "…",
      "notes": "…"
    }
  ]
}
```

`wheel` is resolved relative to the manifest's own URL. Hosting releases
somewhere other than GitHub therefore means copying `manifest.json` and the
wheel from a release onto any static web server, and setting:

```json
{ "update": { "manifest_url": "https://example.org/caelum/stable/manifest.json" } }
```

Channels are just different URLs — `…/stable/` for most cameras, `…/beta/`
for a test camera.

## From the command line

Re-running the installer with a newer wheel upgrades into the same layout —
useful over SSH, or if the web UI itself is unreachable:

```bash
curl -fsSL https://github.com/roman-dvorak/caelum/releases/latest/download/install.sh | sudo bash
# or a specific file
sudo bash install.sh --wheel caelum-0.3.0-py3-none-any.whl
```

To go back by hand:

```bash
cd /opt/caelum
sudo -u caelum ln -sfn "$(readlink previous)" current
sudo systemctl restart caelum
```

## What is not updated

The apt packages underneath — Python itself, `python3-picamera2`, Redis —
belong to the operating system and are updated with `apt`, not from here.
