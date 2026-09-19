# Deployment

A production caelum installation is three pieces on (usually) two machines:

1. The capture engine plus its local web UI, on a Raspberry Pi at the camera.
2. The static archive plus the read-only `remote-web` viewer, on a web host.
3. These docs, on the same web host or another one.

## The Raspberry Pi

### Install

Install as a dedicated system user with no login shell, into `/opt/caelum`:

```bash
sudo useradd --system --home /opt/caelum --shell /usr/sbin/nologin caelum
sudo mkdir -p /opt/caelum /etc/caelum /var/lib/caelum
sudo chown caelum:caelum /opt/caelum /etc/caelum /var/lib/caelum

sudo -u caelum git clone <your-remote>/caelum.git /opt/caelum
cd /opt/caelum
sudo -u caelum uv sync --extra picamera2
```

The `picamera2` extra carries an `aarch64`/`armv7l` marker, so it installs on
the Pi and is skipped everywhere else.

Redis:

```bash
sudo apt install redis-server
sudo systemctl enable --now redis-server
```

Environment file at `/opt/caelum/.env`:

```ini
CAELUM_CONFIG_DIR=/etc/caelum
CAELUM_DATA_DIR=/var/lib/caelum

CAELUM_HTTP_HOST=127.0.0.1
CAELUM_HTTP_PORT=8000

CAELUM_REDIS_URL=redis://127.0.0.1:6379/0
CAELUM_LOG_LEVEL=INFO
```

Leave `CAELUM_CAMERA_BACKEND` unset on real hardware and set
`camera.backend` to `"picamera2"` in `config.json` instead — the environment
variable is an explicit dev override, not a configuration mechanism, and
leaving it set is how you end up quietly recording synthetic frames.

`CAELUM_HTTP_HOST=127.0.0.1` assumes a reverse proxy in front. Use `0.0.0.0`
only if you are deliberately serving uvicorn directly on a trusted LAN.

### The systemd unit

The repository ships `systemd/caelum.service.template`. Copy it, adjust the
paths and the user, install it:

```ini
[Unit]
Description=caelum — allsky/astro camera capture engine
After=network-online.target redis-server.service
Wants=network-online.target

[Service]
Type=simple
User=caelum
WorkingDirectory=/opt/caelum
EnvironmentFile=/opt/caelum/.env
ExecStart=/opt/caelum/.venv/bin/caelum
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo cp /opt/caelum/systemd/caelum.service.template /etc/systemd/system/caelum.service
sudo systemctl daemon-reload
sudo systemctl enable --now caelum
journalctl -u caelum -f
```

`ExecStart` points at the console script inside the uv-created virtualenv, so
systemd starts the interpreter directly with no shell and no `uv run` wrapper
in the process tree. `After=redis-server.service` orders startup but does not
require it — caelum starts fine without Redis, logging a warning and running
off the disk config alone.

Things worth adding for an unattended box:

```ini
# under [Service]
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true
ReadWritePaths=/var/lib/caelum /etc/caelum
SupplementaryGroups=video
```

`SupplementaryGroups=video` is what lets the service user reach `/dev/video*`
and the camera devices. `ReadWritePaths` must cover both the data directory and
the config directory — the config manager rewrites `config.json` atomically via
a temporary file in the same directory, so that directory must be writable, not
just the file.

A healthy startup logs:

```
caelum starting: camera=picamera2 http=127.0.0.1:8000 local-web=bundled
```

If it says `local-web=not built`, the frontend has not been built where the
backend expects it.

### Serving the local web UI from FastAPI

There is no nginx on the Pi and no second process. `main.py` computes the
path to the built frontend relative to the installed package:

```
<repo parent>/caelum-web/apps/local-web/dist
```

so `caelum` and `caelum-web` must be checked out as siblings. If that directory
exists at startup, `create_app()` mounts it:

```python
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="local-web")
```

The mount is a bare `StaticFiles` with `html=True` — it serves `index.html` for
directory requests but performs no SPA fallback rewrite for arbitrary paths,
which is why `local-web` uses a hash router. API routes are registered before
the mount, so `/api/*` and `/ws/*` are matched first and are never shadowed.

Building on the Pi is slow and wants a lot of RAM. Build on a workstation and
copy the result:

```bash
# on the workstation
cd caelum-web
pnpm install
pnpm --filter local-web build

rsync -az apps/local-web/dist/ pi:/opt/caelum-web/apps/local-web/dist/
```

Then restart caelum — the static mount is decided once, at startup.

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
cd caelum-web
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

The docs are a VitePress site in `caelum-web/apps/docs`, and they build to
static HTML like everything else.

```bash
cd caelum-web
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

To serve the docs from a subpath rather than their own hostname, set `base` in
the VitePress config to match (`'/docs/'`) and rebuild; the generated asset
URLs are absolute and will 404 otherwise.

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
`local-web=not built` line after a frontend deploy means the `dist/` directory
is not where the backend looks for it.
