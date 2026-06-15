# Deployment Runbook — agent-gtd

Cookbook-style instructions for setting up agent-gtd in a production-style
configuration: nginx terminates TLS and serves the built React frontend as
static files; uvicorn runs the FastAPI backend; Vite is **not** present in
production.

```
client (HTTPS)
   │
   ▼
nginx
   ├── /              → static files from frontend/dist/  (SPA fallback to index.html)
   ├── /api/events    → http://127.0.0.1:<API_PORT>       (SSE, proxy_buffering off)
   └── /api/*         → http://127.0.0.1:<API_PORT>       (uvicorn / FastAPI)
```

This runbook is environment-agnostic. Substitute the variables below for
your machine before applying. It works equally well for a remote server
reached over SSH or for a local prod-style deployment on a workstation —
where SSH-wrapped commands appear, drop the `ssh <HOST>` prefix and run
locally.

---

## Variables to substitute

Read these from your machine before starting.

| Variable          | What it is                                           | How to find it                                                                  |
|-------------------|------------------------------------------------------|---------------------------------------------------------------------------------|
| `<APP_DIR>`       | Absolute path to the cloned agent-gtd repo on host   | `pwd` inside the checkout                                                       |
| `<API_PORT>`      | Port uvicorn listens on (default `8000`)             | Check `serve.sh` or your systemd unit                                           |
| `<SYSTEMD_UNIT>`  | User-level systemd service name                      | e.g. `agent-gtd.service` — pick a name if creating new                          |
| `<NGINX_SITE>`    | Base name for the nginx config file                  | e.g. `agent-gtd` (Debian/Ubuntu: `sites-enabled/agent-gtd`; AL2023/RHEL: `conf.d/agent-gtd.conf`) |
| `<SERVER_NAMES>`  | `server_name` values for nginx                       | Hostname(s) and/or IP(s) the host answers on                                    |
| `<SSL_CERT>`      | Path to TLS certificate                              | Existing nginx config, or generate self-signed (see "TLS" below)                |
| `<SSL_KEY>`       | Path to TLS private key                              | Same as above                                                                   |
| `<HOME_USER>`     | Linux user running the systemd unit                  | `whoami` on the host                                                            |
| `<HOST>`          | SSH alias / hostname for remote deploys              | The name in `~/.ssh/config`. Omit `ssh <HOST>` for local-only deploys           |
| `<DISPATCH_REPO_URL>` | Git URL of the `agent-gtd-dispatch` repo         | The `[tool.uv.sources]` entry in `pyproject.toml` — adapt to your git host (see Step 3) |

**TLS:** If the host doesn't already have certs, the simplest local-LAN
option is a self-signed cert (`openssl req -x509 -nodes -days 3650
-newkey rsa:2048 -keyout key.pem -out cert.pem -subj "/CN=<hostname>"`).
For a public host use Let's Encrypt / certbot. The runbook below assumes
TLS is in use; for HTTP-only LAN deploys, skip the redirect server block
and remove the `ssl_*` directives + `listen 443 ssl` → `listen 80`.

---

## Step 0 — One-time bootstrap (first deploy only)

### 0a. Build the frontend

Before applying the new nginx config, ensure `frontend/dist/` exists.
Otherwise nginx will serve 404s — and on SPA fallback paths it can
redirect-loop trying to `stat` a missing `index.html`.

```bash
cd <APP_DIR>
git pull
npm --prefix frontend install
npm --prefix frontend run build
ls frontend/dist/index.html
```

Expected: `frontend/dist/index.html` exists, with hashed asset references
under `frontend/dist/assets/`.

If `npm --prefix frontend run build` fails with a Rollup error about
`react-transition-group` (or another CJS-only transitive dep) failing
ESM resolution, the fix is already committed in `frontend/vite.config.ts`
under `build.commonjsOptions.include`. If a fresh failure appears for a
different package, widen that regex to include the failing package's
node_modules path. Do **not** try to upgrade `react-transition-group`
beyond v4 — v5 does not exist on npm.

### 0b. Allow nginx to traverse the home directory

nginx runs as **`www-data`** (Debian/Ubuntu) or **`nginx`** (AL2023/RHEL/CentOS).
Ubuntu 24.04 sets `/home/<user>` to mode `750` by default, which blocks the nginx
process user from traversing into `<APP_DIR>` → `[crit] stat() ... Permission denied`
→ HTTP 500. Grant traverse-only access:

```bash
chmod o+x /home/<HOME_USER>
namei -lx <APP_DIR>/frontend/dist/index.html
```

The `namei` output should show `drwxr-x--x` (or wider) on every path
component up to `dist/`. `o+x` grants traverse without listing — nginx
can `stat` files inside but cannot `ls` the directory. If you want a
listable home directory, `chmod 755` works too, but `o+x` is the
tighter posture.

**Symlinked home directories:** if `/home/<HOME_USER>` is a symlink to a real
path (e.g. `/home/<HOME_USER>` → `/local/home/<HOME_USER>`), `chmod o+x`
updates the permissions of the symlink _target_ — but every directory _component_
of the real path must also be traversable. Run
`namei -lx <APP_DIR>/frontend/dist/index.html` and scan each component; the first
entry showing `drwx------` (mode `700`) or `drwxr-x---` (mode `750`) is the
blocking one. Apply `chmod o+x` to that real path, e.g.:

```bash
chmod o+x /local/home/<HOME_USER>
```

This step is not needed if `<APP_DIR>` is outside `/home/` (e.g.
`/srv/agent-gtd`).

---

## Step 1 — Install the nginx site config

> **Distro note — config path and nginx user:**
>
> | Distro | Config drop-in directory | nginx process user |
> |---|---|---|
> | Debian / Ubuntu | `/etc/nginx/sites-enabled/` | `www-data` |
> | AL2023 / RHEL / CentOS | `/etc/nginx/conf.d/` (files must end in `.conf`) | `nginx` |
>
> The commands below use the Debian/Ubuntu paths. On AL2023/RHEL, replace
> `/etc/nginx/sites-enabled/<NGINX_SITE>` with `/etc/nginx/conf.d/<NGINX_SITE>.conf`
> throughout this step, and remember Step 0b uses `nginx` (not `www-data`) as the
> nginx process user.

Back up the current site config (if present) **outside** the config drop-in
directory. nginx loads every file in `sites-enabled/` (or `conf.d/`) regardless
of extension — saving an `agent-gtd.bak` next to the active config produces
"conflicting server name" warnings and may serve stale config.

```bash
sudo mkdir -p /etc/nginx/backups
[ -f /etc/nginx/sites-enabled/<NGINX_SITE> ] && \
  sudo cp /etc/nginx/sites-enabled/<NGINX_SITE> \
          /etc/nginx/backups/<NGINX_SITE>.$(date +%Y%m%d-%H%M%S).bak
```

Then write the new config. Substitute every `<...>` placeholder before
applying:

```bash
sudo tee /etc/nginx/sites-enabled/<NGINX_SITE> > /dev/null << 'NGINX_CONF'
# Redirect HTTP → HTTPS  (omit this server block for HTTP-only deploys)
server {
    listen 80;
    server_name <SERVER_NAMES>;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name <SERVER_NAMES>;

    ssl_certificate     <SSL_CERT>;
    ssl_certificate_key <SSL_KEY>;

    # Serve built React app as static files
    root <APP_DIR>/frontend/dist;
    index index.html;

    # Long-lived cache for hashed assets (Vite appends content hash to filenames)
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }

    # SSE — must have buffering off or events are held until buffer flushes
    location /api/events {
        proxy_pass         http://127.0.0.1:<API_PORT>;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 86400s;
    }

    # API — proxy to uvicorn
    location /api/ {
        proxy_pass         http://127.0.0.1:<API_PORT>;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    # SPA fallback — all other paths serve index.html so react-router handles routing
    location / {
        try_files $uri $uri/ /index.html;
    }
}
NGINX_CONF

sudo nginx -t
sudo systemctl reload nginx
```

`nginx -t` should print:
```
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

**Long FQDN?** If `<SERVER_NAMES>` contains a hostname longer than roughly
56 characters, `nginx -t` may report:

```
nginx: [emerg] could not build server_names_hash, you should increase
server_names_hash_bucket_size: 64
```

Fix: add `server_names_hash_bucket_size 128;` inside the `http {}` block of
`/etc/nginx/nginx.conf` (not in the site config):

```nginx
http {
    server_names_hash_bucket_size 128;
    # ... rest of http block
}
```

The default is `64` bytes. Increasing to `128` comfortably covers FQDNs up to
~120 characters. After editing, re-run `sudo nginx -t && sudo systemctl reload nginx`.

---

## Step 1.5 — Environment (`.env`)

Nothing in the app loads `.env` automatically — there is no `load_dotenv`
in the backend, and `serve.sh` just execs `uv run uvicorn`. In production
the environment must come from systemd: Step 2 adds
`EnvironmentFile=<APP_DIR>/.env` to the unit, and this step creates that
file.

**Pick your mode first:**

- **Single-engineer machine (single-user mode):** if `AGENT_GTD_DATABASE_URL`
  is unset, the app runs in SQLite single-user local mode — data lives in
  `~/.local/share/agent_gtd/gtd.db` (or `$XDG_DATA_HOME/agent_gtd/gtd.db`),
  no PostgreSQL required. This is the intended path for one person on one
  box: skip the PostgreSQL setup below, but still set a real `JWT_SECRET`.
- **Shared / production instance:** PostgreSQL is mandatory — set
  `AGENT_GTD_DATABASE_URL` explicitly and verify the mode after deploy
  (verification check #7 below).

Create `.env` from the template and generate a real JWT secret:

```bash
cd <APP_DIR>
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # → JWT_SECRET value
```

Then edit `.env` and set:

```
JWT_SECRET=<the generated value>
AGENT_GTD_DATABASE_URL=postgresql://<DB_USER>:<DB_PASSWORD>@localhost:5432/agent_gtd
```

(`auth.py` falls back to `dev-secret-change-me` when `JWT_SECRET` is
unset — never ship that default.)

If PostgreSQL isn't installed yet (shared-instance mode only):

```bash
sudo apt install -y postgresql
sudo -u postgres createuser --pwprompt <DB_USER>
sudo -u postgres createdb -O <DB_USER> agent_gtd
```

**Port 5432 contention:** On a development machine, port 5432 may already be in
use — for example, by an RDS/Aurora SSM tunnel that _must_ bind 5432 for IAM
token port matching. Before installing or starting PostgreSQL, check:

```bash
ss -tlnp | grep :5432
```

If another process holds 5432, configure the local PostgreSQL instance to use a
different port. Edit `postgresql.conf` (find it with
`pg_lsclusters` on Debian/Ubuntu, or look in
`/var/lib/pgsql/data/postgresql.conf` on AL2023/RHEL):

```
port = 5433    # or any other free port
```

Restart PostgreSQL after changing the port, then update `.env` to match:

```
AGENT_GTD_DATABASE_URL=postgresql://<DB_USER>:<DB_PASSWORD>@localhost:5433/agent_gtd
```

The app reads the full DSN from `AGENT_GTD_DATABASE_URL`, so any port is valid —
5432 is the default but is not hard-coded anywhere in the application.

The schema auto-creates on app startup — there is no migration step.

**The silent-SQLite trap:** if `AGENT_GTD_DATABASE_URL` is unset (typo'd
var name, missing `EnvironmentFile=` line, `.env` not created), the app
does **not** fail — it silently falls back to SQLite local mode. The
service shows `active (running)`, `/api/health` returns ok, and a shared
instance is quietly serving the wrong (empty) database, possibly with the
insecure default JWT secret. Verification check #7 below distinguishes
the two modes — run it on every shared-instance deploy.

---

## Step 2 — Install / update the systemd user unit

`serve.sh` is the production entry point — it's checked into the repo
and runs uvicorn only (no Vite). If you already have a systemd unit
running `start.sh`, change `ExecStart` to point at `serve.sh`. If
you're creating the unit fresh, the minimal definition is:

```ini
# ~/.config/systemd/user/<SYSTEMD_UNIT>
[Unit]
Description=agent-gtd — uvicorn (frontend served by nginx)
After=network.target

[Service]
Type=simple
WorkingDirectory=<APP_DIR>
# .env created in Step 1.5 — JWT_SECRET and (for shared instances)
# AGENT_GTD_DATABASE_URL. Without this line the app silently falls back
# to SQLite local mode with the insecure default JWT secret.
EnvironmentFile=<APP_DIR>/.env
# serve.sh execs `uv run uvicorn`. The standard uv installer puts uv in
# ~/.local/bin, which is NOT on the systemd user manager's default PATH
# on stock Ubuntu — without this line the unit crash-loops with exit 127.
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=<APP_DIR>/serve.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Reload and apply:

```bash
systemctl --user daemon-reload
systemctl --user enable --now <SYSTEMD_UNIT>      # first install
systemctl --user restart <SYSTEMD_UNIT>           # subsequent updates
systemctl --user status <SYSTEMD_UNIT>
```

Expected: `active (running)`, with `serve.sh` as the main process and
the cgroup listing showing only the uvicorn process — **no `node`,
`npm`, or `vite` processes**. If Vite still appears, `daemon-reload`
didn't take — re-run it and restart.

If `status` instead shows the unit flapping with `status=127`
(`uv: command not found`), `uv` isn't on the unit's PATH — check the
`Environment=PATH=` line above, or hardcode the absolute path from
`which uv` into `serve.sh`. If it fails with
`Failed to load environment files`, you skipped Step 1.5 — create
`<APP_DIR>/.env` first.

If the unit isn't running on login, enable lingering so it survives
logout: `sudo loginctl enable-linger <HOME_USER>`.

---

## Step 3 — Set up `deploy.sh`

`deploy.sh` is operator-local (gitignored). It pulls, rebuilds the
frontend, and restarts the service. The build step is the important
one — without it, frontend changes from a `git pull` won't show up.

### Protocol package lock refresh

`agent-gtd-dispatch-protocol` is declared as a git dependency with
`rev = "main"` in `pyproject.toml` (`[tool.uv.sources]`), but `uv.lock`
pins to a specific commit SHA at lock time.

> **Adapt this to your environment.** In this checkout the source URL is
> `ssh://git@ubuntu-vm01/~/repos/agent-gtd-dispatch` — Jason's homelab
> git server. Both `uv lock` **and** `uv sync` fetch from that URL, so on
> any machine without SSH reachability to the configured git host they
> fail outright with an unreachable-host fetch error — the deploy scripts
> below will not get past `uv lock`/`uv sync`. For an internal port:
> repoint the `[tool.uv.sources]` entry for `agent-gtd-dispatch-protocol`
> in `pyproject.toml` to your own mirror of the `agent-gtd-dispatch` repo
> (or vendor/publish the protocol package), then run
> `uv lock --upgrade-package agent-gtd-dispatch-protocol` to re-pin and
> commit the updated `uv.lock`.

The git server only advertises branch HEADs — it does not serve
arbitrary SHA fetches — so if the pinned SHA has drifted behind dispatch
main, `uv sync` fails with a fetch error. The lock refresh is needed
**when the protocol package (or any Python dep) has changed** — not
literally on every deploy. The templates below include it because it's
the safe default for a copy-paste script; a minimal deploy that skips
the `uv lock`/`uv sync` lines (pull + frontend build + restart, which is
what the operator's actual `deploy.sh` does when Python deps are stable)
also works, **but then you must run
`uv lock --upgrade-package agent-gtd-dispatch-protocol && uv sync`
manually after any pull that changes `pyproject.toml` or `uv.lock`** —
otherwise Python dependency changes never land on the host.

To refresh: run `uv lock --upgrade-package agent-gtd-dispatch-protocol`
after `git pull` to advance the pin to the current HEAD of dispatch
main, then commit the updated `uv.lock` if it changed.

**Remote deploy (over SSH):**

```bash
#!/usr/bin/env bash
set -euo pipefail
ssh <HOST> bash <<'REMOTE'
set -euo pipefail
cd <APP_DIR>
git pull
uv lock --upgrade-package agent-gtd-dispatch-protocol
if ! git diff --quiet uv.lock; then
    git add uv.lock
    git commit -m 'chore: refresh protocol pkg lock'
fi
uv sync
npm --prefix frontend install
npm --prefix frontend run build
systemctl --user restart <SYSTEMD_UNIT>
REMOTE
sleep 2
ssh <HOST> 'systemctl --user is-active <SYSTEMD_UNIT>'
```

**Local deploy (same machine):**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd <APP_DIR>
git pull
uv lock --upgrade-package agent-gtd-dispatch-protocol
if ! git diff --quiet uv.lock; then
    git add uv.lock
    git commit -F - <<'EOF'
chore: refresh protocol pkg lock
EOF
fi
uv sync
npm --prefix frontend install
npm --prefix frontend run build
systemctl --user restart <SYSTEMD_UNIT>
sleep 2
systemctl --user is-active <SYSTEMD_UNIT>
```

`npm install` is fast as a no-op when deps haven't changed; it's there
so a freshly-added package lands on the server after a pull.

---

## Verification checklist

### Programmatic checks

```bash
# 1. API up
curl -sk https://<HOSTNAME>/api/health    # → {"status":"ok"}

# 2. Index served from build (look for hashed asset references)
curl -sk https://<HOSTNAME>/ | head -10
# Expected: <link rel="stylesheet" ... href="/assets/index-<hash>.css">
#           <script type="module" ... src="/assets/index-<hash>.js">

# 3. No Vite client referenced — would mean dev server is still running somewhere
curl -sk https://<HOSTNAME>/ | grep -E '@vite|HMR|hot' \
  && echo "FAIL: Vite client still present" \
  || echo "OK: no vite refs"

# 4. SPA fallback works on a deep route
curl -sk -o /dev/null -w "%{http_code}\n" https://<HOSTNAME>/projects    # → 200

# 5. Process tree shows uvicorn only, no node/vite
systemctl --user status <SYSTEMD_UNIT> --no-pager | grep -E 'CGroup:|node|vite|uvicorn'

# 6. Protocol package reflects current dispatch main
#    uv.lock embeds the pinned SHA as a URL fragment on the package's
#    `source = { git = "...#<sha>" }` line (there is no `rev = ` line)
ssh <HOST> "cd <APP_DIR> && grep -A3 '^name = \"agent-gtd-dispatch-protocol\"' uv.lock | grep -o '#[0-9a-f]\{40\}'"
git ls-remote <DISPATCH_REPO_URL> main
# The fragment SHA (minus the leading '#') should match the ls-remote SHA.
# <DISPATCH_REPO_URL> is the [tool.uv.sources] URL from pyproject.toml —
# ls-remote works against any reachable remote, no host-side clone needed.
# Alternatively, inspect the installed package version:
ssh <HOST> 'cd <APP_DIR> && uv run python -c "import agent_gtd_dispatch_protocol; print(agent_gtd_dispatch_protocol.__file__)"'

# 7. Confirm database mode (PostgreSQL vs silent SQLite fallback)
#    Reads the env of the running service's main process.
ssh <HOST> 'MAINPID=$(systemctl --user show <SYSTEMD_UNIT> -p MainPID --value) && \
  tr "\0" "\n" < /proc/$MAINPID/environ | grep "^AGENT_GTD_DATABASE_URL=" \
  || echo "SQLite local mode (no AGENT_GTD_DATABASE_URL)"'
# Shared instance: must print the postgresql:// DSN.
# Single-user machine: "SQLite local mode" is the expected output.
```

### Browser checks

1. Visit `https://<HOSTNAME>/` — page loads, served as static HTML.
2. Devtools → Network on refresh: `index.html` + hashed JS/CSS load.
   No `/@vite/client` request. No HMR WebSocket in the WS tab.
3. **Background the tab for 2–3 minutes, switch back: no page reload.**
   This is the regression we're fixing.
4. Hard-refresh on a deep client route (e.g. `/projects/<id>`): page
   renders correctly (SPA fallback works, no 404).
5. Trigger a dispatch: SSE events stream live (run-progress comments
   appear in real time).
6. Copy a task ID via the copy-to-clipboard button: clipboard receives
   the value (HTTPS context preserved via 443).

---

## Rollback

If anything goes wrong:

```bash
# Restore previous systemd unit (change ExecStart back to start.sh, if that's what was there)
$EDITOR ~/.config/systemd/user/<SYSTEMD_UNIT>
systemctl --user daemon-reload && systemctl --user restart <SYSTEMD_UNIT>

# Restore previous nginx config from the backup taken in Step 1
sudo cp /etc/nginx/backups/<NGINX_SITE>.<TIMESTAMP>.bak \
        /etc/nginx/sites-enabled/<NGINX_SITE>
sudo nginx -t && sudo systemctl reload nginx
```

---

## Known gotchas

- **`*.bak` files in `sites-enabled/` (or `conf.d/`) are loaded by nginx.**
  Always store backups outside those directories (e.g. `/etc/nginx/backups/`).
- **AL2023 / RHEL use `/etc/nginx/conf.d/*.conf`, not `sites-enabled/`.**
  The nginx process user on those distros is `nginx`, not `www-data`. Adjust
  the Step 0b `chmod` target and the Step 1 config paths accordingly.
- **`/home/<user>` is mode `750` on Ubuntu 24.04** (and on many AL2023/RHEL
  setups). `chmod o+x /home/<user>` grants nginx traversal without exposing
  directory listings.
- **Symlinked home dirs: chmod the real path, not just the symlink entry.**
  If `/home/<user>` is a symlink to `/local/home/<user>`, run
  `namei -lx <APP_DIR>/frontend/dist/index.html` to find the first directory
  component with `700`/`750` permissions and apply `chmod o+x` to that real
  path.
- **Long FQDNs exceed nginx's default `server_names_hash_bucket_size 64`.**
  If `nginx -t` reports "could not build server_names_hash", add
  `server_names_hash_bucket_size 128;` inside the `http {}` block of
  `/etc/nginx/nginx.conf`.
- **Port 5432 may be occupied (e.g., an SSM tunnel to RDS/Aurora).** Check
  with `ss -tlnp | grep :5432` before deploying. If contended, set a
  different `port =` in `postgresql.conf` and update the DSN in `.env`
  to match (see Step 1.5).
- **`react-transition-group` v5 does not exist on npm** (verified May 2026).
  If you hit a build error there, the fix is the `commonjsOptions.include`
  entry in `frontend/vite.config.ts`, not a version bump.
- **Vite-in-prod has no flag to disable HMR-reconnect-reload.** The only
  fix is to stop running the dev server in production — which is what
  this runbook is for.
- **`frontend/dist/` must exist before nginx reload.** Otherwise nginx
  serves 404 and may redirect-loop on the SPA fallback. Always build
  before swapping the systemd unit.
- **Unset `AGENT_GTD_DATABASE_URL` does not fail — it silently switches
  to SQLite local mode.** The service runs, `/api/health` passes, and a
  shared instance serves the wrong database. See Step 1.5 and
  verification check #7.
- **Headless dispatch agents installing new npm deps don't propagate to
  local/prod automatically.** That's why `deploy.sh` runs `npm install`
  on every deploy — a freshly-added package from a `git pull` would
  otherwise be missing on the server.
