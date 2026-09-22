# Deploying Ordex

One small server runs everything: nginx terminates TLS and serves the built PWA, gunicorn runs Django, SQLite and uploaded photos live on local disk. That is comfortably enough for a distributor taking tens to a few hundred orders a day, and it keeps the moving parts to three.

```
                    ┌──────────────────────── VPS (Ubuntu LTS) ───────────────────────┐
  phone / laptop    │                                                                  │
      │             │  nginx :443 ──┬── /                → /opt/ordex/dist  (PWA)      │
      └── HTTPS ────┼───────────────┼── /assets/         → hashed build files          │
                    │               ├── /static/         → django_api/staticfiles       │
                    │               ├── /media/          → /var/lib/ordex/media         │
                    │               └── /api /console /admin /healthz                   │
                    │                       │                                          │
                    │               gunicorn :8123 (2 workers) ── Django              │
                    │                       │                                          │
                    │              /var/lib/ordex/ordex.db (SQLite, WAL)                │
                    └──────────────────────────────────────────────────────────────────┘
                                   nightly → /var/backups/ordex → offsite copy
```

| Piece | Where | Notes |
|---|---|---|
| Code | `/opt/ordex` (git checkout) | owned by the `ordex` user |
| Python env | `/opt/ordex/django_api/.venv` | gunicorn + Django from `requirements.txt` |
| Database | `/var/lib/ordex/ordex.db` | SQLite; `DATABASE_PATH` in the env file |
| Photos | `/var/lib/ordex/media` | `MEDIA_ROOT`; phone uploads |
| Secrets | `/etc/ordex/ordex.env` | `root:ordex`, mode `640` |
| Backups | `/var/backups/ordex` | plus offsite copy |

### Ports

| Port | Use | Exposed publicly? |
|---|---|---|
| `8123` | gunicorn (internal) | no — bound to `127.0.0.1` |
| `443` | nginx, TLS, when you have a hostname | yes |
| `80` | nginx, ACME challenge and redirect | yes (needed for Let's Encrypt) |
| `9123` | optional public HTTPS port if `443` is already taken by another service | yes, via the firewall |

Keep `GUNICORN_PORT` in `/etc/ordex/ordex.env` and the `proxy_pass` values in `nginx.conf` identical; nothing else needs the internal port.

## Assumptions and sizing

- **Server**: 1–2 vCPU, 1–2 GB RAM, 20 GB SSD. Ubuntu 22.04/24.04 LTS.
- **Traffic**: a handful of concurrent users; the PWA is served as static files, so Django only handles the catalogue, orders and the console.
- **SQLite** is fine at this scale and is the simplest thing to back up. Move to Postgres only when you hit the triggers in *Scale path* below.
- **One server, no staging** is the deliberate default. If you later want a staging box, run the same kit with a different `server_name`, `DATABASE_PATH` and a copy of the production database.

## 1. One-time server setup

```sh
# as root
adduser --system --group --home /opt/ordex ordex
apt update && apt install -y nginx sqlite3 git curl ca-certificates unzip
# a recent Node LTS for building the PWA (or build it in CI and skip this)
curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt install -y nodejs
# TLS (after DNS points at the server) and a firewall
apt install -y certbot python3-certbot-nginx ufw fail2ban unattended-upgrades
ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw --force enable

# directories
install -d -o ordex -g ordex /var/lib/ordex /var/lib/ordex/media
install -d -o root -g ordex -m 750 /etc/ordex
install -d /var/backups/ordex

# code
runuser -u ordex -- git clone <your-repo-url> /opt/ordex
runuser -u ordex -- python3 -m venv /opt/ordex/django_api/.venv
runuser -u ordex -- /opt/ordex/django_api/.venv/bin/pip install -r /opt/ordex/django_api/requirements.txt
```

The checkout needs read access to the repository from the server — an SSH deploy key or a read-only token in the remote URL. The deploy script fetches as the `ordex` user, so that credential lives with the service account, not with you.

Install the unit and site, then create the admin account:

```sh
cp /opt/ordex/deploy/ordex.service /etc/systemd/system/ordex.service
cp /opt/ordex/deploy/ordex.env.example /etc/ordex/ordex.env   # then edit it
chown root:ordex /etc/ordex/ordex.env && chmod 640 /etc/ordex/ordex.env
cp /opt/ordex/deploy/nginx.conf /etc/nginx/sites-available/ordex
ln -s /etc/nginx/sites-available/ordex /etc/nginx/sites-enabled/ordex
systemctl daemon-reload && nginx -t && systemctl enable --now ordex nginx
runuser -u ordex -- sh -c 'cd /opt/ordex/django_api && .venv/bin/python manage.py createsuperuser'
certbot --nginx -d orders.example.com
```

The env file must contain at least:

```
DJANGO_SECRET_KEY=<long random value>
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=orders.example.com,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://orders.example.com
DJANGO_SECURE_COOKIES=true
DATABASE_PATH=/var/lib/ordex/ordex.db
MEDIA_ROOT=/var/lib/ordex/media
```

`127.0.0.1` in `ALLOWED_HOSTS` is what lets the deploy script health-check Django directly.

`protect-system` keeps `/usr`, `/boot` and `/etc` read-only for the service; only `/var/lib/ordex` is writable, which is where the database and photos belong.

## 2. First deploy

```sh
chmod +x /opt/ordex/deploy/*.sh
/opt/ordex/deploy/deploy.sh
```

It backs up the database, pulls the target revision, installs requirements, migrates, collects static, builds the PWA, reloads gunicorn (graceful HUP, so in-flight requests finish) and then polls `/healthz`. Anything short of 200 rolls the code back automatically.

## 3. Routine deploys and rollback

Tag releases so a rollback target always exists:

```sh
git tag -a v1.1.0 -m "scheme percentages, bulk sheets" && git push --tags
```

Then, on the server:

```sh
/opt/ordex/deploy/deploy.sh                 # deploy main
TARGET=v1.1.0 /opt/ordex/deploy/deploy.sh   # deploy a specific release
SKIP_FRONTEND=1 /opt/ordex/deploy/deploy.sh # when dist/ is shipped another way
```

- Deploys are **in place** from a git checkout, with `--force` so the server tree never blocks a pull. Never edit files on the server.
- **Graceful**: gunicorn reloads workers instead of dropping connections.
- **Migrations are forward-only.** The script takes a database backup before running them, and says so if a rollback is needed. Schema changes should always be additive (add a column, backfill, drop later) so the previous code keeps working.
- **Rollback**: redeploy the previous tag. The script also does this automatically when the health check fails.

## 4. Backups and restore

```sh
cp /opt/ordex/deploy/backup-ordex.sh /etc/cron.daily/ordex-backup
chmod +x /etc/cron.daily/ordex-backup
```

Nightly it takes a consistent SQLite `.backup` snapshot, tars the media folder and keeps `KEEP_DAYS` (default 14). Set `BACKUP_REMOTE` in the cron environment to also copy off the server:

```sh
BACKUP_REMOTE=rclone:ordex-backups          # object storage via rclone
BACKUP_REMOTE=backup@host:/srv/ordex        # another machine via rsync
```

Restore drill — do this once, before you need it:

```sh
systemctl stop ordex
cp /var/backups/ordex/ordex-2026-09-20.db /var/lib/ordex/ordex.db
tar -xzf /var/backups/ordex/ordex-media-2026-09-20.tar.gz -C /var/lib
systemctl start ordex
curl -fsS https://orders.example.com/healthz
```

A backup you have never restored is not a backup. Also copy the env file somewhere safe — losing `DJANGO_SECRET_KEY` only invalidates sessions, but losing the admin password means a reset.

## 5. Monitoring and logs

- `curl -fsS https://orders.example.com/healthz` → `{"status":"ok"}`; it returns 503 when the database is unreachable. Point an uptime checker (UptimeRobot, healthchecks.io, or a cron `curl`) at it and alert to email/WhatsApp.
- `journalctl -u ordex -f` for gunicorn access and error logs; `journalctl -u nginx`, `/var/log/nginx/`.
- Watch disk space (`df -h`): SQLite plus photos grows slowly, but `/var/backups/ordex` can creep. `journalctl --vacuum-time=30d` trims old logs.
- `certbot renew` runs from its own timer; confirm with `systemctl list-timers | grep certbot`.
- `unattended-upgrades` should be enabled for security patches; reboot when the kernel asks.

## 6. Security checklist

- [ ] `DJANGO_DEBUG=false`, and the env file is `640 root:ordex`.
- [ ] `DJANGO_SECURE_COOKIES=true` once TLS is on, `DJANGO_CSRF_TRUSTED_ORIGINS` set to the real origin.
- [ ] SSH key-only, root login disabled, `ufw` on, `fail2ban` running.
- [ ] Strong admin password; the console logs out through `/logout/`.
- [ ] Photos are public by URL under `/media/` — that is fine for catalogue images, but do not upload anything sensitive.
- [ ] Optional: restrict `/admin/` to the office IP in nginx (`allow 203.0.113.4; deny all;` inside the location).
- [ ] Django admin and console accounts: one per person, so a departure is a deactivation, not a shared-password change.

## 7. Shared server (Lightsail and friends)

Ordex is happy to share a box with other services as long as ports and the reverse proxy do not collide.

**Recon first:**

```sh
ss -ltnp                        # what is listening, and on which ports
systemctl is-active nginx apache2 caddy
df -h && free -h                # room for SQLite, photos and a node build
```

Then choose the shape:

- **nginx already owns 80/443** (the usual case): add Ordex as another `server_name` vhost. Nothing new is exposed, other services are untouched, and `certbot --nginx` issues the certificate. Preferred.
- **separate public port**: after getting a certificate, change `listen 80;` to `listen 9123 ssl;` in the Ordex server block. Open 9123 in the Lightsail console and in `ufw` if enabled.
- **no hostname yet**: `https://203-0-113-10.sslip.io` resolves to your IP automatically, so `certbot --nginx -d 203-0-113-10.sslip.io` can issue a real certificate. The PWA can then install and work offline.
- **no TLS at all yet**: treat plain HTTP as a temporary test — the PWA's install and offline features require HTTPS. For the console, do not expose it; tunnel instead: `ssh -L 8123:127.0.0.1:8123 ubuntu@<ip>` then browse `http://localhost:8123/console/`.

**Lightsail firewall** (separate from `ufw`): Console → instance → *Networking* → *IPv4 Firewall* → *Add rule*. Allow `HTTPS 443` and `HTTP 80` for Let's Encrypt, or your custom TCP port `9123`. Your SSH rule is already there. Attach a **static IP** so the address survives a reboot, and turn on automatic **instance snapshots** as a second line of defence behind the nightly backups.

**Coexistence notes:**

- Only one process can bind a port — check `ss -ltnp | grep 8123` before starting.
- nginx routes virtual hosts by `server_name`, so adding one does not disturb the others.
- Memory: two gunicorn workers plus SQLite sit around 150–250 MB. On a 512 MB instance add 1 GB of swap, or set `--workers 1`.
- If another web server (Apache, Caddy) owns 80/443, either put Ordex behind it as a plain HTTP upstream on 8123, or use the custom-port route.

## 8. Scale path

Move when you see it, not before:

| Signal | Change |
|---|---|
| Concurrent console users, or "database is locked" during billing hour | switch `DATABASE_ENGINE` to Postgres (compose or managed), migrate with `dumpdata`/`loaddata` |
| Catalogue traffic grows | the PWA is already static; add a CDN in front of `/assets` and `/media` |
| Photos fill the disk | move `MEDIA_ROOT` to object storage and serve via CDN |
| Deploys feel risky | add CI that runs `manage.py test` + `npm run build` and only tags on green; add a staging box |
| Console Tailwind/Alpine CDNs blocked | self-host both and drop the CDN `<script>` tags |

## 9. Release checklist

Before tagging:

- [ ] `cd django_api && .venv/bin/python manage.py test` — all green.
- [ ] `npm run build` — the PWA compiles.
- [ ] `manage.py makemigrations --check --dry-run` — no missing migrations.
- [ ] Any new setting is in the env example and the deploy README.

After deploying:

- [ ] `/healthz` returns `{"status":"ok"}`.
- [ ] Open the console, place a test order from the PWA, print a slip.
- [ ] Check `journalctl -u ordex -n 50` for errors.
- [ ] Confirm the nightly backup file appears in `/var/backups/ordex`.

## 10. Troubleshooting

| Symptom | Check |
|---|---|
| 502 from nginx | `systemctl status ordex`, `journalctl -u ordex -n 50` — usually a bad env value or a failed migration |
| 400 Bad Request on every request | `DJANGO_ALLOWED_HOSTS` does not include the hostname you used |
| Login works but the console immediately logs out | `DJANGO_SECURE_COOKIES=true` while still on plain HTTP, or a wrong `DJANGO_CSRF_TRUSTED_ORIGINS` |
| PWA serves an old build | it should not: index.html and sw.js are `no-cache`, assets are hashed. If a device is stuck, use the app menu → *Clear cache & reload* |
| Photos upload but do not display | permissions on `/var/lib/ordex/media` (must be readable by nginx) and the `/media/` alias in nginx |
| Static files missing after deploy | `manage.py collectstatic` ran as the wrong user, or `/static/` alias points elsewhere |
| "database is locked" | a long report at the same time as writes; retry, and plan the Postgres move |
