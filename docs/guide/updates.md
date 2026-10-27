---
description: 'Updating caelum from the web UI step by step: preparing, what each message means, your settings across updates, offline wheel upload, automatic rollback and release channels.'
---

# Updates

A camera installed with the [installer](/guide/installation) updates itself
from the web interface, in a few clicks and without SSH: **System → Software
update**. You need an administrator account.

An update never puts the camera at risk: the new release is installed *next
to* the running one, and if it does not start properly the camera goes back
to the release that worked — by itself.

## In short

1. **Settings → Export** — keep a copy of the configuration.
2. **System → Software update → Check for updates.**
3. Read the release notes, press **Update to x.y.z**, confirm.
4. Wait for *Updated from … to …*. Capture pauses for a few seconds only.

The rest of this page explains each step, what you see on the way, and what
to do when something does not go to plan.

## Before you update

- **Export the configuration.** **Settings → Export** downloads it as a JSON
  file. Updates keep your settings (see [below](#your-settings-across-updates)),
  but a copy costs nothing and lets you restore any value in one step — see
  [Configuration files](/guide/config-files).
- **Pick a convenient time.** Capture pauses for a few seconds while caelum
  restarts, plus the time until the first new frame — at night that is one
  long exposure. Daytime is the natural moment; nothing is lost either way.
- **Check the free space** on **System**. An update needs a few hundred MB;
  caelum makes room by itself where it safely can (see
  [Disk space](#disk-space)).
- **Make sure the camera reaches the internet** — or prepare the wheel file
  for an [offline update](#offline-cameras).

## Step by step

### 1. Check for updates

**System → Software update → Check for updates.** caelum fetches the
release list (the *manifest*, from `update.manifest_url`) and shows:

![System page with the Software update panel at the bottom](/images/screenshots/system.webp)


- **Running version** — what the camera runs now,
- **Available** — the newest release newer than that, or *Up to date*.

When a newer release exists, its release notes appear below with a button
**Update to x.y.z**. Read the notes: they say what changed, and whether
anything needs your attention after the update (a new setting worth
reviewing, for example).

The bottom line of the panel shows where releases come from —
*Releases from https://… (Settings → update.manifest_url)*.

### 2. Start the update

Press **Update to x.y.z** and confirm *caelum will restart*. From here on the
panel shows the progress, and **Show install log** opens the full log of the
installation as it happens.

| Message | What happens | How long |
|---|---|---|
| *Installing x.y.z… the camera keeps running until the switch.* | The wheel is downloaded and its checksum verified, then installed with all its dependencies into a new, separate directory. The camera keeps capturing as usual. | Tens of seconds to several minutes on a Raspberry Pi, depending on how many dependencies changed. |
| *Restarting into x.y.z…* | The new release passed its start test; caelum switches to it and exits. | A moment. |
| *Waiting for caelum to come back…* | systemd starts the new release. The page reconnects by itself. | Usually under a minute. |
| *Running x.y.z; confirming it stays up before removing old releases…* | The new release is running. It is on probation for a minute. | One minute. |
| *Updated from a.b.c to x.y.z* | Done. The new release has confirmed itself healthy, and releases older than the previous one were removed. | — |

You can leave the page during an update; the job runs on the camera, not in
the browser. Coming back to **System** shows where it got to.

### 3. After the update

- **Running version** shows the new version.
- Glance at the **Dashboard**: a fresh frame within a minute or two (one
  long exposure at night).
- If the release notes mentioned new settings, look them up under
  **Settings** — they are already there, with their default values.

## Your settings across updates

The configuration (`/etc/caelum/config.json`), user accounts, the upload key
and all captured data live outside the software releases. An update replaces
the program only; your settings, passwords and frames stay as they are.

When a release brings **new settings**, they appear in the configuration with
their default values on the first start of the new release — no action
needed unless you want a different value.

To set several values after an update in one go — for example the new
options the release notes recommend — use a small partial JSON file and
**Settings → Import…**: you see every change before it is applied. See
[Configuration files](/guide/config-files).

::: info Going back to an older release
After a rollback — automatic or by hand — the older release finds settings
in `config.json` that only the newer release knows. It ignores them, logs
*Ignoring config settings this release does not know: …* and starts
normally; every other setting is kept. The ignored values are gone, though:
updating again brings those settings back with their defaults. If you changed
any of them, the export made before the update has the values.

Releases up to 0.5.4 do not do this yet and refuse such a file. Going back
to one of them, restore the export made before the update as
`/etc/caelum/config.json` if it does not start.
:::

## When something goes wrong

**Nothing is changed until the new release is fully installed and tested.**
If the download, the checksum, the installation or the start test fails, the
panel says *Update to x.y.z failed: … The running version was not touched.*
and the camera simply carries on.

| Message | Meaning | What to do |
|---|---|---|
| *Update check failed: Cannot fetch …* | The camera cannot reach the manifest URL. | Check the network and `update.manifest_url`; or update [offline](#offline-cameras). |
| *Update check failed: … is not valid JSON* / *Malformed release entry* | The URL does not point at a release manifest. | Check `update.manifest_url`. |
| *Not enough disk space: … MB free, the install needs about … MB* | See [Disk space](#disk-space). | Free some space and try again. |
| *Checksum mismatch for … — refusing to install it* | The downloaded file is not the one the manifest describes (a broken download or a wrong file on the server). | Try again later; if it persists, the release server needs fixing. |
| *pip exited with status 1* | A dependency could not be installed — most often no access to PyPI. | **Show install log** has pip's own message. |
| *python exited with status 1* | The start test failed: the release does not work on this system. | Report it with the install log; stay on the current release. |
| *x.y.z is already the running version* | — | Nothing to do. |
| *x.y.z did not start properly and was rolled back to a.b.c* | The new release installed, but kept crashing after the restart. | See [Automatic rollback](#automatic-rollback). The camera runs the old release again. |

The install log is also in **Logs** (every line of the update is logged
there), so it survives closing the page.

## Disk space

A new release needs about as much disk as the running one (every Python
dependency is installed afresh) plus a couple hundred MB for pip — typically
a few hundred MB. Before downloading anything the update checks for that much
free space. If it is short, retention deletes frames that are **already
uploaded** ahead of their age limit, keeping the usual
`retention.min_free_space_mb` free on top; frames not yet uploaded are never
deleted for an update. If that is still not enough, the update stops with
"Not enough disk space" and nothing is changed — free some space (files
outside caelum's data directory are not caelum's to delete) and try again.

After a successful update only two releases stay on disk: the running one
and the previous one, as a rollback target.

## Automatic rollback

If the new release does not stay up, systemd keeps restarting it, and the boot
guard (`/opt/caelum/bin/caelum-launch`, a small shell script outside every
release) counts those starts. On the fourth one it switches `current` back to
`previous` and starts that instead. The System page then reports that the
update was rolled back. No SSH needed.

After a rollback the camera runs exactly what it ran before. **Check for
updates** will still offer the failed release, as it is still the newest one —
do not install it again until a fixed release is out. **Logs** from around
the restart show why it failed; they are worth including when reporting the
problem.

## Offline cameras

A camera without internet access can be updated by uploading the wheel file
(`caelum-<version>-py3-none-any.whl` from a
[release](https://github.com/roman-dvorak/caelum/releases)) under **Install a
wheel file**: download it on any computer, open the camera's web interface,
pick the file and confirm *Install … ? caelum will restart.* The rest —
progress, start test, switch and rollback — is identical.

pip still needs to reach PyPI for any dependency that changed since the
running release; dependencies already installed once come from the service
account's pip cache. The release notes say when a release changes
dependencies.

## How it works

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

The same actions are available to scripts, as an admin:
`GET /api/update/status`, `POST /api/update/check`,
`POST /api/update/start` with `{"version": "x.y.z"}`, and
`POST /api/update/upload` with the wheel as a multipart `file`.

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
for a test camera. Switching a camera between channels is a one-line partial
file for **Settings → Import…** (exactly the snippet above), so it is easy to
apply to several cameras — see [Configuration files](/guide/config-files).

## From the command line

Re-running the installer with a newer wheel upgrades into the same layout —
useful over SSH, or if the web UI itself is unreachable:

```bash
curl -fsSL https://github.com/roman-dvorak/caelum/releases/latest/download/install.sh | sudo bash
# or a specific file
sudo bash install.sh --wheel caelum-0.3.0-py3-none-any.whl
```

The installer leaves an existing `/etc/caelum/config.json` alone.

To go back by hand:

```bash
cd /opt/caelum
sudo -u caelum ln -sfn "$(readlink previous)" current
sudo systemctl restart caelum
```

## What is not updated

The apt packages underneath — Python itself, `python3-picamera2`, Redis —
belong to the operating system and are updated with `apt`, not from here.
