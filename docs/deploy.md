# Deployment Runbook — agent-gtd on r7-research

Cookbook-style instructions for Jason to apply on r7-research after merging a branch that
introduces the production static-file architecture.

**Context:** nginx (443, TLS) serves the built React frontend as static files and proxies
`/api/*` directly to uvicorn on port 8000. Vite only runs in local dev — it is not present
in production.

```
client (HTTPS 443)
   │
   ▼
nginx (r7-research)
   ├── /              → static files from frontend/dist/  (SPA fallback to index.html)
   ├── /api/events    → http://127.0.0.1:8000  (SSE, proxy_buffering off)
   └── /api/*         → http://127.0.0.1:8000  (uvicorn / FastAPI)
```

---

## Step 0 — One-time bootstrap (first deploy only)

Before applying the new nginx config, ensure `frontend/dist/` exists on the server.
Otherwise nginx will serve 404s when it tries to find static files.

```bash
ssh r7-research
cd ~/hosting_root/agent_gtd
git pull
npm --prefix frontend install
npm --prefix frontend run build
# Verify:
ls frontend/dist/index.html
```

Expected output: `frontend/dist/index.html`

---

## Step 1 — Update nginx config

Replace the nginx site config for agent-gtd with the block below.

**On r7-research:**

```bash
# Back up the current config first — used by the rollback section below
sudo cp /etc/nginx/sites-enabled/agent-gtd /etc/nginx/sites-enabled/agent-gtd.bak

# Write the new config
sudo tee /etc/nginx/sites-enabled/agent-gtd > /dev/null << 'NGINX_CONF'
# Redirect HTTP → HTTPS
server {
    listen 80;
    server_name r7-research 192.168.1.51;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name r7-research 192.168.1.51;

    ssl_certificate     /etc/ssl/apertura/selfsigned.crt;
    ssl_certificate_key /etc/ssl/apertura/selfsigned.key;

    # Serve built React app as static files
    root /home/jason/hosting_root/agent_gtd/frontend/dist;
    index index.html;

    # Long-lived cache for hashed assets (Vite appends content hash to filenames)
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }

    # SSE — must have buffering off or events are held until buffer flushes
    location /api/events {
        proxy_pass         http://127.0.0.1:8000;
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
        proxy_pass         http://127.0.0.1:8000;
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

# Test config is valid
sudo nginx -t

# Apply
sudo systemctl reload nginx
```

Expected output from `nginx -t`:
```
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

---

## Step 2 — Update systemd unit to use serve.sh

The systemd user service currently runs `start.sh` (uvicorn + vite). Switch it to `serve.sh`
(uvicorn only).

**On r7-research:**

```bash
# Edit the ExecStart line
nano ~/.config/systemd/user/agent-gtd.service
```

Change:
```
ExecStart=/home/jason/hosting_root/agent_gtd/start.sh
```

To:
```
ExecStart=/home/jason/hosting_root/agent_gtd/serve.sh
```

Then apply and verify:

```bash
systemctl --user daemon-reload
systemctl --user restart agent-gtd
systemctl --user status agent-gtd
```

Expected: `active (running)` with `serve.sh` as the main process. No node/vite processes
should appear.

---

## Step 3 — Update your local deploy.sh

`deploy.sh` is gitignored (operator-local). Update it to pull, build the frontend, and
restart the service:

```bash
#!/usr/bin/env bash
set -e
ssh r7-research 'cd ~/hosting_root/agent_gtd && git pull && npm --prefix frontend install && npm --prefix frontend run build && systemctl --user restart agent-gtd'
sleep 2
ssh r7-research 'systemctl --user is-active agent-gtd'
```

Replace your existing `deploy.sh` with the above. The `npm install` step is fast (no-op when
dependencies haven't changed) and ensures newly added packages are present after a pull.

---

## Verification checklist (post-deploy, in browser)

1. Visit `https://r7-research/` — page loads, served as static HTML.
2. Devtools → Network: refresh, confirm `index.html` + hashed JS/CSS assets load. No
   `/@vite/client` requests. No HMR WebSocket in the WS tab.
3. Background the tab for 2–3 minutes, switch back: **no page reload** (the regression we're
   fixing).
4. Hard-refresh a deep route (`/projects/<id>`): page renders correctly (SPA fallback works,
   no 404).
5. Trigger a dispatch: SSE events stream in live (run-progress comments appear).
6. Copy a task ID: clipboard receives the value (HTTPS context preserved via 443).
7. Confirm `systemctl --user status agent-gtd` shows `active (running)` with `serve.sh`; no
   node/vite processes in the cgroup listing.

---

## Rollback

If anything goes wrong:

```bash
# Restore old systemd unit (change ExecStart back to start.sh)
nano ~/.config/systemd/user/agent-gtd.service
systemctl --user daemon-reload && systemctl --user restart agent-gtd

# Restore old nginx config from the backup taken in Step 1
sudo cp /etc/nginx/sites-enabled/agent-gtd.bak /etc/nginx/sites-enabled/agent-gtd
sudo nginx -t && sudo systemctl reload nginx
```
