# Authentication and access control

caelum's local web UI can control the camera, rewrite the entire runtime
config, delete recorded frames, browse the data directory and — if you leave it
on — hand out a shell. Treat it as an administrative interface, because that is
what it is.

## Roles

Two roles, and the distinction is simply write access:

- **`admin`** — everything. Change config, edit plugins, override exposure,
  delete recordings, browse files, use the terminal.
- **`viewer`** — read-only. See the live preview, the status readout and the
  sky state. No config writes, no deletions, no terminal.

## Where accounts live

Accounts are stored in:

```
<config_dir>/auth.json
```

**not** in `config.json`. That separation is deliberate. The settings page in
the web UI renders the entire `AppConfig` as an editable JSON tree, and
`GET /api/config` returns it in full — so anything in the config document is
visible to anyone who can reach that page or that endpoint. Password hashes do
not belong there. Keeping users in their own file also means exporting,
diffing, version-controlling or copying a config between cameras never carries
credentials along with it.

`auth.json` should be owned by the user caelum runs as and readable by nobody
else:

```bash
sudo chown caelum:caelum /etc/caelum/auth.json
sudo chmod 600 /etc/caelum/auth.json
```

## First start

If no user database exists, caelum creates an `admin` account with a randomly
generated password and writes the plaintext to:

```
<config_dir>/initial-admin-password.txt
```

```bash
cat /etc/caelum/initial-admin-password.txt
```

Log in with it, change the password immediately, then delete the file:

```bash
sudo rm /etc/caelum/initial-admin-password.txt
```

Nothing rotates or expires that file on its own. A camera that has been running
for six months with a world-readable initial password sitting in its config
directory is a real and entirely avoidable problem.

## The `auth` config section

```json
{
  "auth": {
    "enabled": true,
    "preview_access": "viewer",
    "session_ttl_hours": 24,
    "terminal_enabled": false
  }
}
```

| Key | Type | Meaning |
| --- | --- | --- |
| `enabled` | bool | Master switch for authentication. With it off, everyone reaching the port is effectively an admin. |
| `preview_access` | `"public"` \| `"viewer"` \| `"admin"` | Who may see the live preview, the status readout and the stream. |
| `session_ttl_hours` | number | How long a login session stays valid before re-authentication is required. |
| `terminal_enabled` | bool | Whether the `/terminal` page and its PTY backend exist at all. |

Like everything else in the config, these are patched through
`PUT /api/config` or edited in the settings tree, and they take effect without
a restart.

### `preview_access`

This is the one axis where "public" is often the right answer, so it is its own
setting rather than being folded into the role system.

- **`"public"`** — anyone who can reach the port sees the live view, the status
  readout and the stream, with no login. Everything else still requires the
  appropriate role. This is what you want if the camera is the interesting part
  and you would like to show it to people.
- **`"viewer"`** — a login is required, but the `viewer` role is enough.
- **`"admin"`** — only admins see the preview. The right setting if the camera
  points somewhere you would rather not broadcast.

::: warning
`preview_access: "public"` exposes an unauthenticated, continuously updating
image feed and the endpoints that drive it. That is a bandwidth surface as well
as a privacy one — the stream pushes a JPEG per capture to every connected
client. If the camera is reachable from the open internet, put it behind the
[reverse proxy](/guide/deployment) with rate limiting rather than exposing
uvicorn directly.
:::

## Resetting a forgotten admin password

There is no email recovery flow and no secret question. You need shell access
to the machine, which is the correct bar for an administrative reset.

Stop the service, remove the user database, and start it again — caelum sees no
user database and repeats its first-start behaviour, writing a fresh random
admin password:

```bash
sudo systemctl stop caelum
sudo mv /etc/caelum/auth.json /etc/caelum/auth.json.bak
sudo systemctl start caelum
sudo cat /etc/caelum/initial-admin-password.txt
```

Log in, set a password you will keep, then delete both the password file and
the backup:

```bash
sudo rm /etc/caelum/initial-admin-password.txt /etc/caelum/auth.json.bak
```

This resets *every* account, not just the admin one — any `viewer` accounts go
with it. If you only need to recover the admin and want to keep the others,
edit `auth.json` to remove the admin entry, restart, and let caelum recreate
just that account.

The main `config.json` is untouched by any of this. Exposure presets, upload
settings, plugin configuration and everything else survive a credential reset.

## The web terminal

::: danger The terminal is a full shell
`/terminal` is not a restricted command runner, a sandbox, or a set of approved
maintenance actions. It is a real PTY running a real shell with the full
privileges of the user the caelum process runs as.

Anyone who reaches that page as an admin can read every file that user can
read — including `auth.json`, the rsync SSH private key at `upload.ssh_key_path`,
and `.env` — install software, add cron jobs, connect outward to your archive
host, or make the camera persist a backdoor across reboots. If that user has
sudo rights, they have the machine.

It exists because a camera on a roof is genuinely inconvenient to reach, and
because being able to check `dmesg` or restart a service without climbing a
ladder is worth a lot. That convenience is real. So is the exposure.
:::

Turn it off on any host reachable from a network you do not fully control:

```json
{
  "auth": { "terminal_enabled": false }
}
```

Reasonable positions, in descending order of comfort:

1. **`terminal_enabled: false`, always.** Use SSH. This costs you nothing you
   did not already have, and SSH has key auth, a decades-long security record
   and audit logging.
2. **Enabled, but bound to localhost and reached over an SSH tunnel or a
   WireGuard/Tailscale interface.** Set `CAELUM_HTTP_HOST=127.0.0.1` and reach
   the UI through the tunnel. The terminal is then no more exposed than the SSH
   you used to get there.
3. **Enabled on a trusted LAN with a strong admin password.** Acceptable on a
   home network you administer. Be honest with yourself about what else is on
   that network.

Never enable it on a host with a public IP and a port-forward, with
`auth.enabled` false, or with the initial generated admin password still in
use.

## General hardening

- **Bind to localhost when you can.** `CAELUM_HTTP_HOST=127.0.0.1` and reach
  the UI over an SSH tunnel or a VPN interface. Nothing in caelum needs to be
  publicly reachable — the *public* site is the static remote archive, which is
  a completely separate host with no write path.
- **Put TLS in front of it** if it is reachable beyond localhost. uvicorn is
  served plain HTTP; see [Deployment](/guide/deployment) for the reverse proxy
  and certificate setup.
- **Note the CORS policy.** The FastAPI app is created with
  `allow_origins=["*"]` and `allow_credentials=True`. That is convenient for
  development against a Vite dev server on another port, and it is permissive
  for a production deployment. If the instance is exposed, tighten it.
- **Restrict the upload key.** `upload.ssh_key_path` points at a private key
  with write access to your archive. Force-command it in the remote's
  `authorized_keys`; see [Upload](/guide/upload).
- **Do not reuse passwords across cameras.** A fleet sharing one admin password
  is one compromised camera away from being a fleet of compromised cameras.
