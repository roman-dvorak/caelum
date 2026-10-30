---
description: 'Uploading caelum frames to a permanent remote archive with rsync, SCP or S3, and the JSON manifests the remote viewer reads.'
---

# Upload and the remote archive

The camera's local disk rotates. The remote host is the permanent archive, and
it is also what serves the public read-only viewer. The remote needs no backend
whatsoever — the uploader writes a static tree of JPEGs, FITS files and JSON
manifests that Apache (or any other static server) hands out directly.

## Configuration

```json
{
  "upload": {
    "enabled": true,
    "remote_host": "archive.example.org",
    "remote_user": "caelum",
    "remote_base_path": "/var/www/allsky-data",
    "ssh_key_path": "/etc/caelum/upload_key",
    "thumbnail_interval_s": 60.0,
    "reconcile_interval_s": 1800.0
  }
}
```

The `upload` block holds only what the transfer needs — the target and its
credentials. Who the camera is lives in `camera.identity`:

```json
{
  "camera": {
    "identity": {
      "name": "Brno North Allsky",
      "slug": "brno-north",
      "observatory_name": "Brno Observatory",
      "camera_type": "Allsky, RPi HQ + fisheye",
      "owner": "Example Astronomical Society",
      "publish_location": false
    }
  }
}
```

`slug` is the directory name this camera owns on the remote
(`<remote_base_path>/<slug>/`) and the key it is indexed under; `name` is the
human-readable label the viewer shows. `observatory_name`, `camera_type` and
`owner` are optional catalog metadata published with the camera (see
`cameras.json` below), and also usable in overlay labels as `{camera_name}`,
`{observatory_name}`, `{camera_type}` and `{owner}`. The exact `lat`/`lon` go
into the published manifests only with `publish_location: true`; the sky
overlay does not need them (see "Sky layers" below). Older configs with these
fields under `upload` are converted when they are loaded. Upload is
disabled by default. Pushes start when a frame's derivatives, overlay and
sidecar are all written, not when the frame is merely captured, so a push
never misses the outputs of the frame that triggered it.

::: tip A local or mounted archive
If `remote_host` is empty, every target is treated as a plain local filesystem
path instead of an SSH target and no SSH options are passed at all. That makes
an NFS or USB-mounted archive a first-class configuration, and it is also what
makes the transport testable with no network involved.
:::

## Two triggers

A single `UploadWorker` thread runs both.

**Incremental push**, at most every `thumbnail_interval_s` (default 60 s). The
worker subscribes to `frame_captured` and sets a flag; the loop waits on that
flag with a timeout of `thumbnail_interval_s`. When a frame has arrived, it
pushes only *today's* date directories:

```
<data_dir>/thumbnails/<today>/  ->  <remote_base>/<slug>/thumbnails/<today>/
<data_dir>/raw/<today>/         ->  <remote_base>/<slug>/raw/<today>/
<data_dir>/derivatives/<today>/ ->  <remote_base>/<slug>/derivatives/<today>/
```

then regenerates and pushes the manifests. This is the fast path: new
thumbnails appear on the public site within about a minute of capture, and the
amount of tree rsync has to stat stays small.

**Reconciliation**, every `reconcile_interval_s` (default 1800 s). The worker
pushes the *entire* local data directory to `<remote_base>/<slug>`, then the
manifests, and — only if rsync reported success — advances the
confirmed-upload watermark to now.

Only the reconciliation pass moves that watermark. The incremental pass proves
that today is covered; it says nothing about the week you were offline. Since
[retention](/guide/storage) only deletes files newer than the watermark when
the free-space floor forces it, an incremental-only history would never free a
byte by age.

## Why this is self-healing

There is no retry queue, no pending-upload ledger, no per-file state to get out
of sync with reality. That is not an omission — it is the point of using rsync.

rsync compares source against destination itself, transfers only what differs,
and is idempotent: running it twice on an unchanged tree does nothing the
second time. So the reconciliation pass *is* the retry mechanism. A reboot
halfway through a transfer, a network blip, an uplink that was down for two
days, a file the incremental push missed because it landed a second after the
push started — all of them are simply differences between the two trees, and
the next reconciliation pass finds and fixes them. There is no state that can
disagree with the filesystem, because the filesystem is the state.

The transport is deliberately one-way and archival:

```python
cmd = ["rsync", "-az", "--mkpath", *ssh_option, f"{local_dir}/", target]
```

There is no `--delete`. Removing a file locally — which retention does
routinely — never removes it from the archive. A missing local directory is not
an error either; there is simply nothing to push yet.

rsync was chosen over scp (no delta transfer, no resume) and over
sftp/paramiko (a slower pure-Python SSH stack, and this workload is thousands
of small files).

## SSH key setup

The uploader invokes rsync with a fixed, non-interactive SSH command:

```
ssh -i <ssh_key_path> -o StrictHostKeyChecking=accept-new -o BatchMode=yes
```

`BatchMode=yes` means it will never prompt — a passphrase-protected key, a
missing key or an unknown host all fail immediately rather than hanging the
upload thread forever. `accept-new` records the host key on first contact but
refuses a *changed* one.

The installer generates this key (ed25519, no passphrase) as
`/etc/caelum/upload_key`, owned by the service account, prints its public half
at the end of its output, and points `ssh_key_path` at it in a newly seeded
`config.json`. It replaces an existing key only with `--new-identity`. To print the public key
again later:

```bash
sudo cat /etc/caelum/upload_key.pub
```

On a hand-made install, create it as the user caelum runs as:

```bash
sudo -u caelum ssh-keygen -t ed25519 -N '' -f /etc/caelum/upload_key
```

On the archive host, append `/etc/caelum/upload_key.pub` to the upload user's
`~/.ssh/authorized_keys` and make sure that user can write
`remote_base_path`.

::: tip Restrict the key
This key exists to run rsync into one directory. Pin it with a forced command
and the usual restrictions in `authorized_keys`:

```
command="rrsync -wo /var/www/allsky-data",no-agent-forwarding,no-port-forwarding,no-pty,no-X11-forwarding ssh-ed25519 AAAA... caelum@camera
```

`rrsync` ships with rsync; `-wo` makes it write-only into that subtree. Note
that the uploader also *reads* `cameras.json` back (see below), so use `-w`
without `-o` if you need read access for the index merge — or accept that the
index merge will start from empty each time and let each camera re-assert its
own entry.
:::

Verify before enabling upload:

```bash
sudo -u caelum ssh -i /etc/caelum/upload_key \
     -o BatchMode=yes caelum@archive.example.org true && echo ok
```

## Remote directory layout

```
<remote_base_path>/
  cameras.json
  <camera_slug>/
    manifest.json
    thumbnails/
      2026-09-19/
        index.json
        210431.jpg
        210431.json
        ...
    raw/
      2026-09-19/
        210431.fits
        210431.json
    derivatives/
      2026-09-19/
        235959_keogram_keogram.png
  <another_camera_slug>/
    ...
```

Drop the built `remote-web` app at the same document root and it reads exactly
this tree with no server-side code at all.

### `cameras.json`

The shared top-level index across every camera writing to this host:

```json
{
  "version": 1,
  "updated_at": "2026-09-19T21:30:00+00:00",
  "cameras": [
    {
      "slug": "brno-north",
      "name": "Brno North Allsky",
      "observatory_name": "Brno Observatory",
      "camera_type": "Allsky, RPi HQ + fisheye",
      "owner": "Example Astronomical Society",
      "manifest": "brno-north/manifest.json"
    }
  ]
}
```

Because this one file is shared, it cannot simply be overwritten. Each upload
cycle does a fetch-merge-push: pull the current `cameras.json` into a temporary
directory, replace *only* this camera's own entry, sort by slug and push it
back. Cameras uploading concurrently therefore do not clobber each other's
entries, and if one does lose a race it self-heals on the next cycle, since
every camera re-asserts its own entry every time. A missing `cameras.json` —
first camera, first boot — is routine and logged at debug level, not as a
warning.

### Per-camera `manifest.json`

Regenerated locally from the data directory before every push, so it rides
along with the next rsync like any other file:

```json
{
  "version": 1,
  "slug": "brno-north",
  "name": "Brno North Allsky",
  "location": { "lat": 50.0755, "lon": 14.4378 },
  "dates": [
    {
      "date": "2026-09-19",
      "thumbnail_count": 842,
      "has_raw": true,
      "raw_count": 611,
      "latest_thumbnail": "thumbnails/2026-09-19/210501.jpg"
    }
  ]
}
```

`location` is taken from the live `location` config — latitude and longitude
only. Paths inside a camera manifest are relative to that camera's own
directory; paths inside `cameras.json` are relative to the archive root.

### Per-date `index.json`

One per thumbnail date directory, listing that night's frames:

```json
{
  "date": "2026-09-19",
  "images": [
    {
      "time": "210431",
      "thumbnail": "thumbnails/2026-09-19/210431.jpg",
      "metadata": "thumbnails/2026-09-19/210431.json"
    }
  ]
}
```

A date appears in the manifest only if it has at least one thumbnail. Raw
counts are reported per date but raw files are not individually indexed — the
viewer works from thumbnails and their sidecars.

## Sky layers

With the `sky_overlay` plugin on and `storage_policy.overlay_mode = "file"`,
each layer of the sky overlay — grid, constellations, stars, planets, compass —
is rendered by the camera into its own transparent PNG,
`overlays/YYYY/MM/DD/<stem>.<layer>.png`, and uploaded like the rest of
`overlays/`. A date's `index.json` lists them per image:

```json
{ "time": "20261030-210000", "overlay": "overlays/2026/10/30/20261030-210000.png",
  "layers": { "stars": "overlays/2026/10/30/20261030-210000.stars.png",
              "constellations": "overlays/2026/10/30/20261030-210000.constellations.png" } }
```

and the camera's `manifest.json` gets a `sky` block with the lens and the
layer names, which is what the viewer needs to offer an on/off switch for each.
The coordinates are not part of it: the positions are already in the pixels.
