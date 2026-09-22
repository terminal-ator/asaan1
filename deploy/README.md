# Deploying Asaan

One small server runs everything: Caddy terminates TLS and serves the built PWA, gunicorn runs Django, SQLite and uploaded photos live on local disk. That is comfortably enough for a distributor taking tens to a few hundred orders a day, and it keeps the moving parts to three.

```
                    ┌──────────────────────── VPS (Ubuntu LTS) ───────────────────────┐
  phone / laptop    │                                                                  │
      │             │  Caddy :443 ──┬── /                → /opt/asaan/dist  (PWA)      │
      └── HTTPS ────┼───────────────┼── /assets/         → hashed build files          │
                    │               ├── /static/         → django_api/staticfiles       │
                    │               ├── /media/          → /var/lib/asaan/media         │
                    │               └── /api /console /admin /healthz                   │
                    │                       │                                          │
                    │               gunicorn :8123 (2 workers) ── Django              │
                    │                       │                                          │
                    │              /var/lib/asaan/asaan.db (SQLite, WAL)                │
                    └──────────────────────────────────────────────────────────────────┘
                                   nightly → /var/backups/asaan → offsite copy
```

| Piece | Where | Notes |
|---|---|---|
| Code | `/opt/asaan` (git checkout) | owned by the `asaan` user |
| Python env | `/opt/asaan/django_api/.venv` | gunicorn + Django from `requirements.txt` |
| Database | `/var/lib/asaan/asaan.db` or PostgreSQL | SQLite by default; see *Database* below |
| Photos | `/var/lib/asaan/media` | `MEDIA_ROOT`; phone uploads |
| Secrets | `/etc/asaan/asaan.env` | `root:asaan`, mode `640` |
| Backups | `/var/backups/asaan` | plus offsite copy |

### Ports

| Port | Use | Exposed publicly? |
|---|---|---|
| `8123` | gunicorn (internal) | no — bound to `127.0.0.1` |
| `443` | Caddy, TLS, when you have a hostname | yes |
| `80` | Caddy, ACME challenge and redirect | yes (needed for certificates) |
| `9123` | optional public HTTPS port if `443` is already taken by another service | yes, via the firewall |

Keep `GUNICORN_PORT` in `/etc/asaan/asaan.env` and the upstream address in the `Caddyfile` identical; nothing else needs the internal port.

## Assumptions and sizing

- **Server**: 1–2 vCPU, 1–2 GB RAM, 20 GB SSD. Ubuntu 22.04/24.04 LTS.
- **Traffic**: a handful of concurrent users; the PWA is served as static files, so Django only handles the catalogue, orders and the console.
- **SQLite** is fine at this scale and is the simplest thing to back up. Move to Postgres only when you hit the triggers in *Scale path* below.
- **One server, no staging** is the deliberate default. If you later want a staging box, run the same kit with a different `server_name`, `DATABASE_PATH` and a copy of the production database.

## 1. One-time server setup

```sh
# as root
adduser --system --group --home /opt/asaan asaan
apt update && apt install -y sqlite3 git curl ca-certificates gnupg unzip
# a recent Node LTS for building the PWA (or build it in CI and skip this)
curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt install -y nodejs
# Caddy, from its official repository
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  > /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy
# firewall
apt install -y ufw fail2ban unattended-upgrades
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable

# directories
install -d -o asaan -g asaan /var/lib/asaan /var/lib/asaan/media
install -d -o root -g asaan -m 750 /etc/asaan
install -d /var/backups/asaan

# code
runuser -u asaan -- git clone <your-repo-url> /opt/asaan
runuser -u asaan -- python3 -m venv /opt/asaan/django_api/.venv
runuser -u asaan -- /opt/asaan/django_api/.venv/bin/pip install -r /opt/asaan/django_api/requirements.txt
```

The checkout needs read access to the repository from the server — an SSH deploy key or a read-only token in the remote URL. The deploy script fetches as the `asaan` user, so that credential lives with the service account, not with you.

Install the unit and site, then create the admin account:

```sh
cp /opt/asaan/deploy/asaan.service /etc/systemd/system/asaan.service
cp /opt/asaan/deploy/asaan.env.example /etc/asaan/asaan.env   # then edit it
chown root:asaan /etc/asaan/asaan.env && chmod 640 /etc/asaan/asaan.env
sed 's/asaan\.in/<your-hostname>/' /opt/asaan/deploy/Caddyfile > /etc/caddy/Caddyfile
systemctl daemon-reload && systemctl enable --now asaan caddy
runuser -u asaan -- sh -c 'cd /opt/asaan/django_api && .venv/bin/python manage.py createsuperuser'
```

Caddy fetches and renews the certificate for that hostname by itself; once `https://<your-hostname>/healthz` answers, set `DJANGO_SECURE_COOKIES=true` and restart the service. On a box that already serves websites on 80/443, use the nginx vhost in `deploy/nginx.conf` instead — see *Shared server* below.

The env file must contain at least:

```
DJANGO_SECRET_KEY=<long random value>
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=asaan.in,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://asaan.in
DJANGO_SECURE_COOKIES=true
DATABASE_PATH=/var/lib/asaan/asaan.db
MEDIA_ROOT=/var/lib/asaan/media
```

`127.0.0.1` in `ALLOWED_HOSTS` is what lets the deploy script health-check Django directly.

`protect-system` keeps `/usr`, `/boot` and `/etc` read-only for the service; only `/var/lib/asaan` is writable, which is where the database and photos belong.

### Database: SQLite or PostgreSQL

SQLite is the default and is genuinely fine at this scale — one file, backed up with `.backup`, nothing else to run. If the server already runs PostgreSQL (many shared boxes do), use it instead: it removes the single-writer limit and needs no file permissions to reason about.

Create a dedicated role and database, then point the env file at it:

```sh
sudo -u postgres psql <<'SQL'
CREATE ROLE asaan LOGIN PASSWORD 'a-long-random-password';
CREATE DATABASE asaan OWNER asaan;
SQL
```

In `/etc/asaan/asaan.env`, comment out `DATABASE_PATH` and add:

```
POSTGRES_DB=asaan
POSTGRES_USER=asaan
POSTGRES_PASSWORD=a-long-random-password
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
```

`manage.py migrate` creates the schema on the first deploy. If the role cannot connect over `127.0.0.1`, check `pg_hba.conf` on the database server (`scram-sha-256` for host connections). Switching later is a copy job (`dumpdata`/`loaddata`), not a rewrite — but it is easiest before you have production orders.

## 2. First deploy

```sh
chmod +x /opt/asaan/deploy/*.sh
/opt/asaan/deploy/deploy.sh
```

It backs up the database, pulls the target revision, installs requirements, migrates, collects static, builds the PWA, reloads gunicorn (graceful HUP, so in-flight requests finish) and then polls `/healthz`. Anything short of 200 rolls the code back automatically.

## 3. Routine deploys and rollback

Tag releases so a rollback target always exists:

```sh
git tag -a v1.1.0 -m "scheme percentages, bulk sheets" && git push --tags
```

Then, on the server:

```sh
/opt/asaan/deploy/deploy.sh                 # deploy main
TARGET=v1.1.0 /opt/asaan/deploy/deploy.sh   # deploy a specific release
SKIP_FRONTEND=1 /opt/asaan/deploy/deploy.sh # when dist/ is shipped another way
```

- Deploys are **in place** from a git checkout, with `--force` so the server tree never blocks a pull. Never edit files on the server.
- **Graceful**: gunicorn reloads workers instead of dropping connections.
- **Migrations are forward-only.** The script takes a database backup before running them, and says so if a rollback is needed. Schema changes should always be additive (add a column, backfill, drop later) so the previous code keeps working.
- **Rollback**: redeploy the previous tag. The script also does this automatically when the health check fails.

## 4. Backups and restore

```sh
cp /opt/asaan/deploy/backup-asaan.sh /etc/cron.daily/asaan-backup
chmod +x /etc/cron.daily/asaan-backup
```

Nightly it takes a consistent database snapshot (`.backup` for SQLite, `pg_dump -Fc` for PostgreSQL), tars the media folder and keeps `KEEP_DAYS` (default 14). Set `BACKUP_REMOTE` in the cron environment to also copy off the server:

```sh
BACKUP_REMOTE=rclone:asaan-backups          # object storage via rclone
BACKUP_REMOTE=backup@host:/srv/asaan        # another machine via rsync
```

Restore drill — do this once, before you need it:

```sh
systemctl stop asaan
cp /var/backups/asaan/asaan-2026-09-20.db /var/lib/asaan/asaan.db
tar -xzf /var/backups/asaan/asaan-media-2026-09-20.tar.gz -C /var/lib
systemctl start asaan
curl -fsS https://asaan.in/healthz
```

With PostgreSQL the equivalent is:

```sh
systemctl stop asaan
sudo -u postgres dropdb asaan && sudo -u postgres createdb -O asaan asaan
PGPASSWORD=... pg_restore -h 127.0.0.1 -U asaan -d asaan --clean --if-exists \
  /var/backups/asaan/asaan-2026-09-20.dump
systemctl start asaan
```

A backup you have never restored is not a backup. Also copy the env file somewhere safe — losing `DJANGO_SECRET_KEY` only invalidates sessions, but losing the admin password means a reset.

## 5. Monitoring and logs

- `curl -fsS https://asaan.in/healthz` → `{"status":"ok"}`; it returns 503 when the database is unreachable. Point an uptime checker (UptimeRobot, healthchecks.io, or a cron `curl`) at it and alert to email/WhatsApp.
- `journalctl -u asaan -f` for gunicorn logs; `journalctl -u caddy -f` for the proxy, certificate and access logs.
- Watch disk space (`df -h`): SQLite plus photos grows slowly, but `/var/backups/asaan` can creep. `journalctl --vacuum-time=30d` trims old logs.
- Caddy renews certificates automatically, about a month before expiry; `journalctl -u caddy | grep -i certificate` shows the renewals.
- `unattended-upgrades` should be enabled for security patches; reboot when the kernel asks.

## 6. Security checklist

- [ ] `DJANGO_DEBUG=false`, and the env file is `640 root:asaan`.
- [ ] `DJANGO_SECURE_COOKIES=true` once TLS is on, `DJANGO_CSRF_TRUSTED_ORIGINS` set to the real origin.
- [ ] SSH key-only, root login disabled, `ufw` on, `fail2ban` running.
- [ ] Strong admin password; the console logs out through `/logout/`.
- [ ] Photos are public by URL under `/media/` — that is fine for catalogue images, but do not upload anything sensitive.
- [ ] Optional: restrict `/admin/*` to the office IP (`@admin remote_ip` style matcher in the Caddyfile, or nginx `allow`/`deny` if you are on that path).
- [ ] Django admin and console accounts: one per person, so a departure is a deactivation, not a shared-password change.

## 7. Shared server (Lightsail and friends)

Asaan is happy to share a box with other services as long as ports and the reverse proxy do not collide.

**Recon first:**

```sh
ss -ltnp                        # what is listening, and on which ports
systemctl is-active caddy nginx apache2
df -h && free -h                # room for SQLite, photos and a node build
```

Then choose the shape:

- **a web server already owns 80/443** (the usual case on a shared box): Caddy cannot bind those ports, so add Asaan as another nginx vhost using `deploy/nginx.conf`, and run `certbot --nginx -d <hostname>` for the certificate. Nothing new is exposed and other sites are untouched.
- **separate public port**: after getting a certificate, change `listen 80;` to `listen 9123 ssl;` in the Asaan server block. Open 9123 in the Lightsail console and in `ufw` if enabled.
- **no hostname yet**: `https://203-0-113-10.sslip.io` resolves to your IP automatically. Point Caddy (or the nginx vhost plus `certbot --nginx -d 203-0-113-10.sslip.io`) at it and you get a real certificate, so the PWA can install and work offline.
- **no TLS at all yet**: treat plain HTTP as a temporary test — the PWA's install and offline features require HTTPS. For the console, do not expose it; tunnel instead: `ssh -L 8123:127.0.0.1:8123 ubuntu@<ip>` then browse `http://localhost:8123/console/`.

**Lightsail firewall** (separate from `ufw`): Console → instance → *Networking* → *IPv4 Firewall* → *Add rule*. Allow `HTTPS 443` and `HTTP 80` for Let's Encrypt, or your custom TCP port `9123`. Your SSH rule is already there. Attach a **static IP** so the address survives a reboot, and turn on automatic **instance snapshots** as a second line of defence behind the nightly backups.

**Coexistence notes:**

- Only one process can bind a port — check `ss -ltnp | grep 8123` before starting.
- nginx routes virtual hosts by `server_name` and Caddy by site address, so adding one does not disturb the others.
- Memory: two gunicorn workers plus SQLite sit around 150–250 MB. On a 512 MB instance add 1 GB of swap, or set `--workers 1`.
- If another web server (Apache, Caddy) owns 80/443, either put Asaan behind it as a plain HTTP upstream on 8123, or use the custom-port route.

## 8. Scale path

Move when you see it, not before:

| Signal | Change |
|---|---|
| Console feels slow on big reports | already covered: set `POSTGRES_DB` and move to the PostgreSQL you run |
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
- [ ] Check `journalctl -u asaan -n 50` for errors.
- [ ] Confirm the nightly backup file appears in `/var/backups/asaan`.

## 10. Troubleshooting

| Symptom | Check |
|---|---|
| 502 from Caddy | `systemctl status asaan`, `journalctl -u asaan -n 50` — usually a bad env value or a failed migration |
| Caddy serves HTTP but no certificate | DNS for the hostname does not point here yet, or port 80 is blocked; `journalctl -u caddy -n 50` shows the ACME error, and Caddy keeps retrying |
| 400 Bad Request on every request | `DJANGO_ALLOWED_HOSTS` does not include the hostname you used |
| Login works but the console immediately logs out | `DJANGO_SECURE_COOKIES=true` while still on plain HTTP, or a wrong `DJANGO_CSRF_TRUSTED_ORIGINS` |
| PWA serves an old build | it should not: index.html and sw.js are `no-cache`, assets are hashed. If a device is stuck, use the app menu → *Clear cache & reload* |
| Photos upload but do not display | permissions on `/var/lib/asaan/media` (must be readable by the `caddy` user) and the `/media/*` block in the Caddyfile |
| Static files missing after deploy | `manage.py collectstatic` ran as the wrong user, or `/static/` alias points elsewhere |
| "database is locked" | a long report at the same time as writes; retry, or set `POSTGRES_DB` and move to the PostgreSQL you already run |
| `connection to server at "127.0.0.1" failed` | PostgreSQL role password or `pg_hba.conf`; test with `psql -h 127.0.0.1 -U asaan -d asaan` |
