# Migrating the Lightsail apps to OVHcloud

Inventory taken read-only from `ubuntu@13.233.243.133` on 2026-09-24, and the plan
for moving each piece to the new OVH VPS. The Lightsail box stays running until the
new one has been verified for at least a week.

## What is running today

| Domain | App | How it runs now | Code | Data |
|---|---|---|---|---|
| `orders.rologe.com` | prorder-admin (Node/Express) | **Docker** `prorder-admin:latest`, `restart=unless-stopped`, publishes `3100 -> 3000`, mounts `/var/lib/prorder:/data` | `/var/www/prorder-admin` (only `.env` left; code lives in the image) | SQLite `/var/lib/prorder/prorder.db`; nightly cron `backup-db.sh` → `/home/ubuntu/prorder-backups` |
| `qr.rologe.com` | rserver (Node, `node index.js`) | **bare process**, no service manager | `/home/ubuntu/probooks/rserver` (11 MB), second copy under `documents/probooks/` | static files in `/var/www/qr.rologe.com` |
| `dashboard.rologe.com` | xltron (Go) | **bare process started with `go run`** — the running binary is `/tmp/go-build.../xltron` | `/home/ubuntu/probooks/xltron` (git: terminal-ator/xltron) and a second copy in `documents/probooks/` (94 MB) | Postgres |
| `dashboard.rologe.com` `/gql` | exart (Node + `@babel/node`, runs `src/index.js` as a dev-mode process) | **bare process** | `/home/ubuntu/probooks/exart` (151 MB, git: terminal-ator/exart) | Postgres |
| `dashboard.rologe.com` `/dash` | *nothing* — `proxy_pass http://localhost:5005`, no listener | dead upstream | — | — |
| — | keymint (CRA app) | not running, not referenced by nginx | `/home/ubuntu/documents/probooks/keymint` (749 MB) | — |

Other facts:

- **nginx 1.14** serves the three vhosts; certbot certificates exist for all three domains (expiring Oct–Dec 2026).
- **PostgreSQL 10.23** on `0.0.0.0:5432`. Databases with real data: `postgres` (70 tables — `posting`, `statement`, `journal`, i.e. an accounting schema), `crash_course` (10), `wholeshop` (8), `new_log` (6). Roles: `adminone`, `administrator`, `postgres`.
- **DNS for rologe.com is at GoDaddy** (`ns05/ns06.domaincontrol.com`); the apex points at Vercel, the three subdomains at the Lightsail IP.
- Node is installed via nvm under `/home/ubuntu` (v12.4.0 in use by exart).
- Junk in `/home/ubuntu` that does not need migrating: `bkp.sql` (16 MB), `bkp_now.sql` (90 MB), `f_bkp_0401.sql` (90 MB), `go.tar.gz` (116 MB), `go/` (136 MB), `documents/` (1 GB).

### 🔴 Do this immediately

`13.233.243.133:5432` is **reachable from the internet**. Open PostgreSQL is scanned
constantly and is a common ransomware target. Remove the `5432` rule in the Lightsail
console (*Networking → IPv4 Firewall*) now; if anything connects from outside the box,
tell me first and I will restrict it to that address instead.

## Target layout on the OVH VPS (4 GB / 40 GB)

```
nginx (host)
├── orders.asaan.in        -> 127.0.0.1:8123  gunicorn   (Asaan, new)
├── orders.rologe.com      -> 127.0.0.1:3100  prorder-admin
├── qr.rologe.com          -> 127.0.0.1:3000  rserver      + /var/www/qr.rologe.com
└── dashboard.rologe.com   -> /     127.0.0.1:3000  rserver
                             /api  127.0.0.1:8080  xltron
                             /gql  127.0.0.1:4000  exart
PostgreSQL 16 on 127.0.0.1 only
```

Everything that runs as a bare process today becomes a **systemd unit** — that alone
fixes the biggest fragility on the old box (xltron currently runs from a `/tmp` build
that disappears on reboot).

## Migration order

1. **Asaan first** — fresh deploy, proves the box, the proxy and TLS before touching
   anything that is already serving customers.
2. **qr.rologe.com** — simplest: static root plus one Node process.
3. **orders.rologe.com** — Docker image + SQLite volume + backup cron.
4. **dashboard.rologe.com** — three upstreams; do it last and with a maintenance note.

## Per-service procedure (repeat for each)

1. **Freeze**: tell users (or accept a quiet window), stop writes.
2. **Copy code**: `rsync -az` the app directory (excluding `node_modules`) to
   `/opt/rologe/<app>` on the new box; clone from GitHub where a repo exists
   (`terminal-ator/xltron`, `terminal-ator/exart`).
3. **Copy data**: SQLite files, uploads, and — for Postgres — `pg_dump -Fc` then
   `pg_restore` into the new PG 16 instance, followed by row-count comparison.
4. **Start under systemd** on an internal port; verify with
   `curl -H "Host: <domain>" http://127.0.0.1:<port>/`.
5. **Add the nginx vhost** on the new box and verify end to end with a hosts-file
   override on your laptop before touching DNS.
6. **Cut over DNS** in the GoDaddy panel: one A record at a time, with TTL lowered
   in advance. Verify, then move to the next app.
7. **Keep the old service running** for a week; rollback is flipping the A record back.

## Questions to resolve before starting

- [ ] Does anything **outside** the Lightsail box connect to Postgres, or can it stay
      loopback-only? (Determines the 5432 fix.)
- [ ] Which app uses which database? (`postgres`/accounting looks like xltron or
      exart; `crash_course`, `wholeshop`, `new_log` belong to something else — the
      running processes' environments will tell us.)
- [ ] Are `/home/ubuntu/documents/probooks/{rserver,xltron,exart}` older copies or
      newer than `/home/ubuntu/probooks/...`?
- [ ] Is **keymint** still needed? (749 MB, not running, not served.)
- [ ] Keep `dashboard.rologe.com/dash`? Its upstream (5005) is already dead.

## Verification checklist after each cutover

- [ ] Page loads over HTTPS with a valid certificate on the new box.
- [ ] The app's own functions work (login, main screens, a write).
- [ ] `journalctl -u <unit>` shows no errors.
- [ ] Row counts / SQLite file sizes match the old box.
- [ ] Backup cron runs on the new box.
