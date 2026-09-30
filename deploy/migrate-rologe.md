# Migrating the Lightsail apps to OVHcloud

Inventory taken read-only from `ubuntu@13.233.243.133`, updated 30 Sep 2026 after
the scope was cut down: **only `orders.rologe.com` moves.** `qr.rologe.com` and
`dashboard.rologe.com` stay on Lightsail, and the ProBooks data migration has its
own procedure (see below). The Lightsail box stays running.

## What is running today

| Domain | App | How it runs | Decision |
|---|---|---|---|
| `orders.rologe.com` | prorder-admin (Node/Express) | **Docker** `prorder-admin:latest`, `restart=unless-stopped`, publishes `3100 -> 3000`, mounts `/var/lib/prorder:/data`, SQLite | **migrate** |
| `qr.rologe.com` | rserver (Node) + static files | bare process, no service manager | **stays on Lightsail** |
| `dashboard.rologe.com` | rserver (`/`, `/*`), xltron (`/api`), exart (`/gql`) | bare processes; `/dash` upstream (5005) already dead | **stays on Lightsail** |
| ProBooks/xltron data | PostgreSQL database `postgres` on Lightsail | — | **its own doc**: `project/probooks/xltron/deploy/DEPLOY.md` |
| keymint | CRA app, not running, not served | — | ignore |

Other facts:

- **PostgreSQL 10** on Lightsail is now **loopback-only** (a persistent firewall rule
  blocks external 5432; it was publicly reachable before).
- DNS for rologe.com is at **GoDaddy** (`ns05/ns06.domaincontrol.com`); the apex points
  at Vercel, the subdomains at the Lightsail IP.
- The names `orders.asaan.in`, `karm.asaan.in` and `probook.asaan.in` are already
  configured on the OVH box (Caddy), alongside Asaan, Karmos and ProBooks.

## Target on the OVH box (51.79.144.234)

```
Caddy
├── orders.asaan.in   -> 127.0.0.1:8123  Asaan        (live)
├── karm.asaan.in     -> 127.0.0.1:8124  Karmos       (live)
├── probook.asaan.in  -> 127.0.0.1:8130  ProBooks     (live)
└── orders.rologe.com -> 127.0.0.1:3100  prorder-admin (this migration)
PostgreSQL 16 on loopback (asaan, karmos, probooks databases)
```

`qr` and `dashboard` keep their nginx + certbot setup on Lightsail, untouched.

## Migrating prorder-admin

1. **Freeze writes**: tell users, then stop the container on Lightsail
   (`sudo docker stop prorder-admin`) so the SQLite file is stable.
2. **Copy the data**: `/var/lib/prorder/prorder.db` (and anything else in that
   directory) plus `/home/ubuntu/backup-db.sh` and the nightly cron entry.
3. **Copy the image** so the running code is preserved exactly:
   `sudo docker save prorder-admin:latest | gzip | ssh ovh 'gunzip | sudo docker load'`
   (the source directory `/var/www/prorder-admin` holds only its `.env`; the code
   lives inside the image).
4. **Run it on OVH** with the same volume layout — `/var/lib/prorder/prorder.db` on
   the host, published on `127.0.0.1:3100` only. Wrap it in a systemd unit so it
   starts on boot (`docker run --restart` is enough if Docker is enabled).
5. **Caddy block** for `orders.rologe.com` → `reverse_proxy 127.0.0.1:3100`
   (copy the shape of the ProBooks block: log, encode, HSTS, reverse_proxy).
6. **Verify with a hosts-file override** before touching DNS: point
   `orders.rologe.com` at the OVH IP locally and exercise the app.
7. **Cut over**: lower the TTL at GoDaddy first, then change the A record to
   `51.79.144.234`. Rollback is flipping it back.
8. **Keep Lightsail running** for a week or two; only then decommission.

## Verification checklist

- [ ] Page loads over HTTPS with a valid certificate on the new box.
- [ ] Sign in, raise a test order/bill, check a report.
- [ ] `journalctl -u docker` / container logs clean.
- [ ] `prorder.db` size and row counts match the old copy.
- [ ] Nightly backup cron runs on the new box.
- [ ] Old site still answers until DNS moves, then returns 404 or stays idle.

## Open questions

- [ ] Does prorder-admin have any other files next to `prorder.db` in `/var/lib/prorder`
      that matter (uploads, exports)?
- [ ] Keep the Docker-based deploy, or unpack the image into a normal app directory
      with a systemd unit while we are here?
- [ ] `orders.rologe.com` keeps its name (recommended) or moves to an `asaan.in` name?
