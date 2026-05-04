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
| `<NGINX_SITE>`    | Filename under `/etc/nginx/sites-enabled/`           | e.g. `agent-gtd`                                                                |
| `<SERVER_NAMES>`  | `server_name` values for nginx                       | Hostname(s) and/or IP(s) the host answers on                                    |
| `<SSL_CERT>`      | Path to TLS certificate                              | Existing nginx config, or generate self-signed (see "TLS" below)                |
| `<SSL_KEY>`       | Path to TLS private key                              | Same as above                                                                   |
| `<HOME_USER>`     | Linux user running the systemd unit                  | `whoami` on the host                                                            |
| `<HOST>`          | SSH alias / hostname for remote deploys              | The name in `~/.ssh/config`. Omit `ssh <HOST>` for local-only deploys           |

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

nginx runs as `www-data`. Ubuntu 24.04 sets `/home/<user>` to mode `750`
by default, which blocks `www-data` from traversing into `<APP_DIR>` →
`[crit] stat() ... Permission denied` → HTTP 500. Grant traverse-only
access:

```bash
chmod o+x /home/<HOME_USER>
namei -lx <APP_DIR>/frontend/dist/index.html
```

The `namei` output should show `drwxr-x--x` (or wider) on every path
component up to `dist/`. `o+x` grants traverse without listing — nginx
can `stat` files inside but cannot `ls` the directory. If you want a
listable home directory, `chmod 755` works too, but `o+x` is the
tighter posture.

This step is not needed if `<APP_DIR>` is outside `/home/` (e.g.
`/srv/agent-gtd`).

---

## Step 1 — Install the nginx site config

Back up the current site config (if present) **outside** `sites-enabled/`.
nginx loads every file in `sites-enabled/` regardless of extension —
saving an `agent-gtd.bak` next to the active config produces "conflicting
server name" warnings and may serve stale config.

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

If the unit isn't running on login, enable lingering so it survives
logout: `sudo loginctl enable-linger <HOME_USER>`.

---

## Step 3 — Set up `deploy.sh`

`deploy.sh` is operator-local (gitignored). It pulls, rebuilds the
frontend, and restarts the service. The build step is the important
one — without it, frontend changes from a `git pull` won't show up.

**Remote deploy (over SSH):**

```bash
#!/usr/bin/env bash
set -euo pipefail
ssh <HOST> 'cd <APP_DIR> && git pull && npm --prefix frontend install && npm --prefix frontend run build && systemctl --user restart <SYSTEMD_UNIT>'
sleep 2
ssh <HOST> 'systemctl --user is-active <SYSTEMD_UNIT>'
```

**Local deploy (same machine):**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd <APP_DIR>
git pull
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

- **`*.bak` files in `sites-enabled/` are loaded by nginx.** Always store
  backups outside `sites-enabled/` (e.g. `/etc/nginx/backups/`).
- **`/home/<user>` is mode `750` on Ubuntu 24.04.** `chmod o+x /home/<user>`
  for nginx traversal without exposing directory listings.
- **`react-transition-group` v5 does not exist on npm** (verified May 2026).
  If you hit a build error there, the fix is the `commonjsOptions.include`
  entry in `frontend/vite.config.ts`, not a version bump.
- **Vite-in-prod has no flag to disable HMR-reconnect-reload.** The only
  fix is to stop running the dev server in production — which is what
  this runbook is for.
- **`frontend/dist/` must exist before nginx reload.** Otherwise nginx
  serves 404 and may redirect-loop on the SPA fallback. Always build
  before swapping the systemd unit.
- **Headless dispatch agents installing new npm deps don't propagate to
  local/prod automatically.** That's why `deploy.sh` runs `npm install`
  on every deploy — a freshly-added package from a `git pull` would
  otherwise be missing on the server.
