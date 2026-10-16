# Deployment

A production caelum installation is three pieces on (usually) two machines:

1. The capture engine plus its local web UI, on a Raspberry Pi at the camera.
2. The static archive plus the read-only `remote-web` viewer, on a web host.
3. These docs, on the same web host or another one.

## The Raspberry Pi

### Install

Install from a release with the one-line installer — no source checkout, no
build on the Pi:

```bash
curl -fsSL https://github.com/roman-dvorak/caelum/releases/latest/download/install.sh | sudo bash
```

It installs `redis-server` and (on a Pi) `python3-picamera2` from apt,
creates a `caelum` system user, and lays the install out as:

```
/opt/caelum/releases/<version>/venv   one virtualenv per release
/opt/caelum/current -> releases/...   the release systemd runs
/opt/caelum/previous -> releases/...  the rollback target
/opt/caelum/bin/caelum-launch         boot guard, systemd's ExecStart
/etc/caelum/                          caelum.env, config.json, auth.json
/var/lib/caelum/                      captured data
```

The release wheel carries the backend *and* the built local web UI, so there is
nothing else to deploy. Options: `--camera picamera2|opencv|mock` (seeds a new
`config.json`; default `picamera2` on a Pi), `--wheel FILE|URL`,
`--manifest URL`, `--no-start`.

On a Pi the release venv is created with `--system-site-packages`, so it sees
apt's picamera2/libcamera (which have no PyPI wheels), and pip installs with
the numpy/astropy/opencv pins shipped inside the wheel
(`caelum/constraints-rpi.txt`) to match the system numpy's ABI.

Leave `CAELUM_CAMERA_BACKEND` unset on real hardware and set
`camera.backend` in the config instead — the environment variable is an
explicit dev override, not a configuration mechanism, and leaving it set is
how you end up quietly recording synthetic frames.

The installer binds the HTTP server to `0.0.0.0` in `/etc/caelum/caelum.env`.
Change it to `127.0.0.1` if you put a reverse proxy in front.

Updates then happen from the web UI — see [Updates](/guide/updates).

### The systemd unit

The installer renders the unit from the release
(`caelum/deploy/caelum.service.in`). The parts that matter:

```ini
[Service]
User=caelum
WorkingDirectory=/var/lib/caelum
EnvironmentFile=/etc/caelum/caelum.env
Environment=CAELUM_RELEASES_DIR=/opt/caelum
ExecStart=/opt/caelum/bin/caelum-launch
Restart=always
RestartSec=5
```

`Restart=always`, not `on-failure`: after a web update caelum exits cleanly so
that systemd starts the newly linked release. `After=redis-server.service`
orders startup but does not require it — caelum starts fine without Redis,
logging a warning and running off the disk config alone.

Things worth adding for an unattended box (a drop-in via
`systemctl edit caelum`):

```ini
[Service]
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true
ReadWritePaths=/var/lib/caelum /etc/caelum /opt/caelum
```

`ReadWritePaths` must cover the data directory, the config directory — the
config manager rewrites `config.json` atomically via a temporary file in the
same directory — and `/opt/caelum`, where web updates install new releases.
The installer already puts the service user in the `video` group for camera
access.

A healthy startup logs:

```
caelum 0.2.0 starting: camera=picamera2 http=0.0.0.0:8000 local-web=/opt/caelum/releases/0.2.0/venv/.../caelum/webui
```

### Serving the local web UI from FastAPI

There is no nginx on the Pi and no second process. caelum looks for the built
frontend in this order: `CAELUM_WEB_DIR`, then `caelum/webui` inside the
installed package (where a release wheel carries it), then
`web/apps/local-web/dist` in a source checkout. Whichever exists is mounted:

```python
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="local-web")
```

The mount is a bare `StaticFiles` with `html=True` — it serves `index.html` for
directory requests but performs no SPA fallback rewrite for arbitrary paths,
which is why `local-web` uses a hash router. API routes are registered before
the mount, so `/api/*` and `/ws/*` are matched first and are never shadowed.

### Reverse proxy and TLS

uvicorn serves plain HTTP. If the UI is reachable beyond localhost, put a proxy
in front of it, and make sure the proxy forwards WebSocket upgrades — without
that, `/ws/stream` fails and the live view never receives a frame.

Apache:

```apache
<VirtualHost *:443>
    ServerName camera.example.org

    SSLEngine on
    SSLCertificateFile    /etc/letsencrypt/live/camera.example.org/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/camera.example.org/privkey.pem

    ProxyPreserveHost On
    ProxyPass        /ws/ ws://127.0.0.1:8000/ws/
    ProxyPassReverse /ws/ ws://127.0.0.1:8000/ws/
    ProxyPass        /    http://127.0.0.1:8000/
    ProxyPassReverse /    http://127.0.0.1:8000/
</VirtualHost>
```

Enable `proxy`, `proxy_http`, `proxy_wstunnel` and `ssl`. The `/ws/` rules must
come first — Apache matches `ProxyPass` in order.

Certificates from Let's Encrypt via certbot. A Pi behind a domestic connection
without a public port 80 will need the DNS-01 challenge.

::: danger
If you are exposing the local UI to the internet at all, read
[Security](/guide/security) first. In particular set
`auth.terminal_enabled: false` — the web terminal is a full shell as the
caelum user, and a TLS-terminating proxy does nothing to change that.
:::

## The archive and remote viewer

The remote host serves a static tree and nothing else. No PHP, no application
server, no database. Apache's job is to hand out files.

### Directory layout

Both the uploaded data tree and the built viewer sit under one document root:

```
/var/www/allsky-data/
  index.html          <- remote-web build
  assets/             <- remote-web build
  favicon.svg
  cameras.json        <- written by the uploader
  brno-north/
    manifest.json
    thumbnails/...
    raw/...
    derivatives/...
```

`VITE_REMOTE_BASE_URL` defaults to `/`, which is exactly right for this
same-origin arrangement. Point it elsewhere only if the data tree lives on a
different host.

### Build and deploy the viewer

```bash
cd caelum/web
pnpm install
pnpm --filter remote-web build
rsync -az apps/remote-web/dist/ archive.example.org:/var/www/allsky-data/
```

Note the lack of `--delete`: the uploader's data files live in the same tree
and must not be swept away by a viewer deploy.

### The upload user

`remote_base_path` must be writable by the SSH user in `upload.remote_user`,
and readable by Apache:

```bash
sudo mkdir -p /var/www/allsky-data
sudo chown caelum:www-data /var/www/allsky-data
sudo chmod 2775 /var/www/allsky-data
```

The setgid bit keeps the group on directories rsync creates later. Key setup
and the `authorized_keys` restrictions are in [Upload](/guide/upload).

### Apache vhost

```apache
<VirtualHost *:443>
    ServerName allsky.example.org
    DocumentRoot /var/www/allsky-data

    SSLEngine on
    SSLCertificateFile    /etc/letsencrypt/live/allsky.example.org/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/allsky.example.org/privkey.pem

    <Directory /var/www/allsky-data>
        Require all granted
        Options -Indexes +FollowSymLinks
        AllowOverride None
    </Directory>

    # Thumbnails and manifests change; hashed build assets never do.
    <FilesMatch "\.(json|jpg)$">
        Header set Cache-Control "public, max-age=60"
    </FilesMatch>
    <LocationMatch "^/assets/">
        Header set Cache-Control "public, max-age=31536000, immutable"
    </LocationMatch>

    AddOutputFilterByType DEFLATE application/json
</VirtualHost>
```

`remote-web` is a single-page app. If it uses path-based routes rather than a
hash router, add a fallback so a deep link does not 404 — while making sure the
data tree is not swallowed by it:

```apache
<Directory /var/www/allsky-data>
    RewriteEngine On
    RewriteCond %{REQUEST_FILENAME} !-f
    RewriteCond %{REQUEST_FILENAME} !-d
    RewriteRule . /index.html [L]
</Directory>
```

The `!-f` / `!-d` conditions mean any real file — every JSON manifest, every
JPEG — is served as itself and only genuinely missing paths reach the app.

::: warning
Everything under this document root is public: thumbnails, FITS files,
per-frame metadata and the `location` coordinates in each `manifest.json`. If
your camera's exact position is not something you want published, set
`location` to a rounded coordinate — the sky-state calculation does not care
about a few hundred metres.
:::

::: tip Disk on the archive
The archive is never rotated by caelum. `retention` applies exclusively to the
camera's local disk. Whatever reaches the archive stays there until you remove
it, which is the entire point — but it does mean the archive host needs a
capacity plan of its own.
:::

## These docs

The pages are Markdown in the repository's `docs/`; the VitePress tooling that
builds them is `web/apps/docs`. They build to static HTML like everything else.

The public copy at <https://caelum.astrometers.eu> is published to GitHub Pages
by `.github/workflows/docs.yml` on every push to `master` that touches the
docs. The web UI always links to that public copy (`DOCS_URL` in
`web/packages/ui/src/brand.ts`). To host another copy anyway — e.g. a
LAN-only mirror — build and rsync it:

```bash
cd caelum/web
pnpm --filter docs build
rsync -az --delete apps/docs/.vitepress/dist/ archive.example.org:/var/www/caelum-docs/
```

`--delete` is safe here, unlike the viewer deploy, because nothing else writes
into this directory.

```apache
<VirtualHost *:443>
    ServerName docs.example.org
    DocumentRoot /var/www/caelum-docs

    SSLEngine on
    SSLCertificateFile    /etc/letsencrypt/live/docs.example.org/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/docs.example.org/privkey.pem

    <Directory /var/www/caelum-docs>
        Require all granted
        Options -Indexes +FollowSymLinks
        AllowOverride None
    </Directory>

    ErrorDocument 404 /404.html
</VirtualHost>
```

VitePress emits fully resolved static HTML per route, so no rewrite rule is
needed — every documented URL is a real file on disk. It does generate its own
`404.html`, which is what the `ErrorDocument` line points at.

To serve the docs from a subpath rather than their own hostname, build with
`DOCS_BASE=/docs/` (leading and trailing slash); the generated asset URLs are
absolute and will 404 otherwise.

## Operational checks

```bash
# the service, and whether it is restarting in a loop
systemctl status caelum
journalctl -u caelum --since '1 hour ago'

# is it capturing, and at what exposure
curl -s localhost:8000/api/status

# did uploads actually run
journalctl -u caelum | grep -E 'reconciliation|rsync failed'

# is retention keeping up
df -h /var/lib/caelum
journalctl -u caelum | grep 'Retention sweep'

# is fresh data landing on the archive
curl -s https://allsky.example.org/cameras.json | head
```

Two failure modes are worth watching for specifically. Repeated `rsync failed`
warnings with no successful `Running full upload reconciliation pass` mean
nothing is being archived *and* nothing is being rotated, because retention
refuses to delete files it cannot confirm were uploaded. And a
`local-web=not built` line means the installed package carries no UI — a
wheel built without `scripts/build-release.sh`.
