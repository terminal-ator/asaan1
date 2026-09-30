# QR Shops app

A static Create React App build (title "QR Shops") served at `qr.asaan.in`. There is
no server process: Caddy serves the files and proxies `/gql` (and `/api`) to the
ProBooks API on `127.0.0.1:8130`, which is where shop sign-in and data live.

| What | Where |
|---|---|
| The build (source of truth until it has a repo) | Lightsail `ubuntu@13.233.243.133:/var/www/qr.rologe.com` |
| Live files on OVH | `/var/www/qr.asaan.in` |
| Caddy block | end of `/etc/caddy/Caddyfile`, marked `# >>> qr … # <<< qr` |
| API | ProBooks (`probook.asaan.in`), same `probooks` PostgreSQL database |
| DNS | A record `qr` → `51.79.144.234` (plus the `qr.<ip>.sslip.io` fallback) |

## Deploy

```sh
deploy/qr-app/deploy.sh          # pull the build from Lightsail, copy, reload Caddy
```

The script replaces only the marked qr section of the Caddyfile, validates it and
restores the previous file if validation fails, so the other apps on the box are
never disturbed.

## Notes

- Shop accounts and data come from the ProBooks database; if a shop cannot sign in,
  check the API first (`curl https://probook.asaan.in/api/ping`).
- `shop-upload-template.xlsx` is served from the site root and is linked by the app.
- The old `qr.rologe.com` vhost on Lightsail still answers; it can be retired once
  nobody uses it.
