#!/usr/bin/env sh
# One-time bootstrap for a fresh Debian/Ubuntu VPS.
#
#   sudo REPO_URL=git@github.com:you/asaan.git \
#        SITE_HOST=asaan.in \
#        EMAIL=you@example.com \
#        deploy/bootstrap.sh
#
# Only REPO_URL is required when the checkout does not exist yet. Everything
# else has a sensible default:
#
#   SITE_HOST      public hostname; defaults to <public-ip>.sslip.io
#   EMAIL          ACME contact address (optional, recommended)
#   EXTRA_HOSTS    extra hostnames to serve, comma separated (e.g. a sslip.io
#                  name for testing before DNS, or www.asaan.in)
#   PROXY          caddy (default, needs ports 80/443) or nginx (existing server)
#   DB             sqlite (default) or postgres
#   APP_DIR        /opt/asaan
#   APP_USER       asaan
#   DATA_DIR       /var/lib/asaan
#   GUNICORN_PORT  8123
#   SKIP_FRONTEND  1 when dist/ was already built and shipped from the dev machine
#
# Without a git remote, ship the code first and the bootstrap will use it:
#   SKIP_DEPLOY=1 deploy/ship.sh <user@host>
#   ssh <user@host> "sudo SITE_HOST=asaan.in EMAIL=you@asan.in SKIP_FRONTEND=1 sh /opt/asaan/deploy/bootstrap.sh"
#
# It is safe to re-run: packages, user, directories and the env file are only
# created when missing, and the last step is an ordinary deploy.
set -eu

APP_DIR="${APP_DIR:-/opt/asaan}"
APP_USER="${APP_USER:-asaan}"
APP_GROUP="${APP_GROUP:-$APP_USER}"
DATA_DIR="${DATA_DIR:-/var/lib/asaan}"
ENV_DIR="${ENV_DIR:-/etc/asaan}"
ENV_FILE="$ENV_DIR/asaan.env"
GUNICORN_PORT="${GUNICORN_PORT:-8123}"
DB="${DB:-sqlite}"
PROXY="${PROXY:-caddy}"
SITE_HOST="${SITE_HOST:-}"
# Extra hostnames to serve (comma separated), e.g. a sslip.io name for testing
# before DNS is pointed, or www.asaan.in.
EXTRA_HOSTS="${EXTRA_HOSTS:-}"
EMAIL="${EMAIL:-}"
REPO_URL="${REPO_URL:-}"
SKIP_FIREWALL="${SKIP_FIREWALL:-0}"

say() { printf '\n==> %s\n' "$1"; }
die() { echo "error: $1" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "run this with sudo"
[ -f /etc/debian_version ] || die "this script targets Debian or Ubuntu"
[ "$DB" = "sqlite" ] || [ "$DB" = "postgres" ] || die "DB must be sqlite or postgres"
[ "$PROXY" = "caddy" ] || [ "$PROXY" = "nginx" ] || die "PROXY must be caddy or nginx"

say "hostname"
if [ -z "$SITE_HOST" ]; then
  ip="$(curl -fsS --max-time 10 https://api.ipify.org || true)"
  [ -n "$ip" ] || die "could not detect the public IP; pass SITE_HOST=..."
  SITE_HOST="$(printf '%s' "$ip" | tr '.' '-').sslip.io"
  echo "no SITE_HOST given; using $SITE_HOST (sslip.io resolves to this server)"
fi

# Hosts the app answers for: the primary name, any extras, and loopback.
ALL_HOSTS="$SITE_HOST"
CSRF_ORIGINS="https://$SITE_HOST"
if [ -n "$EXTRA_HOSTS" ]; then
  ALL_HOSTS="$SITE_HOST,$EXTRA_HOSTS"
  for host in $(printf '%s' "$EXTRA_HOSTS" | tr ',' ' '); do
    CSRF_ORIGINS="$CSRF_ORIGINS,https://$host"
  done
fi

say "ports"
# Fail only when something other than our own Caddy holds the port; a re-run
# finds Caddy already listening with the config from last time.
busy_by_other() {
  owner="$(ss -ltnp 2>/dev/null | awk -v p=":$1\$" '$4 ~ p { print $NF; exit }')"
  [ -n "$owner" ] || return 1
  case "$owner" in *'"caddy"'*) return 1 ;; esac
  return 0
}
if [ "$PROXY" = "caddy" ]; then
  if busy_by_other 80 || busy_by_other 443; then
    die "ports 80 or 443 are already in use by another service. For a box that already runs nginx use PROXY=nginx."
  fi
else
  echo "using the existing nginx; Asaan becomes another virtual host on 80/443"
fi

say "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates gnupg sqlite3 python3-venv python3-pip ufw

# A reverse proxy: Caddy on a fresh box, or the nginx that is already running.
if [ "$PROXY" = "caddy" ]; then
  if ! command -v caddy >/dev/null 2>&1; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
      | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
      > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
    apt-get install -y -qq caddy
  fi
else
  command -v nginx >/dev/null 2>&1 || die "PROXY=nginx but nginx is not installed"
  command -v certbot >/dev/null 2>&1 || apt-get install -y -qq certbot python3-certbot-nginx
fi

if [ "${SKIP_FRONTEND:-0}" != "1" ]; then
  if ! command -v node >/dev/null 2>&1 || [ "$(node -v | sed 's/^v\([0-9]*\).*/\1/')" -lt 18 ]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y -qq nodejs
  fi
else
  echo "PWA is shipped prebuilt; skipping Node on the server"
fi
if [ "$DB" = "postgres" ]; then apt-get install -y -qq postgresql postgresql-client; fi

say "service account and directories"
id -u "$APP_USER" >/dev/null 2>&1 || adduser --system --group --home "$APP_DIR" "$APP_USER"
# Caddy (or any other proxy user) must be able to traverse into dist/ and media.
chmod 755 "$APP_DIR"
install -d -o "$APP_USER" -g "$APP_GROUP" "$DATA_DIR" "$DATA_DIR/media"
install -d -o root -g "$APP_GROUP" -m 750 "$ENV_DIR"
install -d /var/backups/asaan

say "code"
if [ -d "$APP_DIR/.git" ]; then
  if [ -n "$(runuser -u "$APP_USER" -- git -C "$APP_DIR" remote 2>/dev/null || true)" ]; then
    runuser -u "$APP_USER" -- git -C "$APP_DIR" pull --ff-only || true
  else
    echo "checkout has no git remote (shipped with deploy/ship.sh); using it as it is"
  fi
elif [ -f "$APP_DIR/django_api/manage.py" ]; then
  echo "code is present without git history; using it as it is"
else
  [ -n "$REPO_URL" ] || die "$APP_DIR has no checkout; pass REPO_URL=... or ship it with deploy/ship.sh SKIP_DEPLOY=1"
  runuser -u "$APP_USER" -- git clone "$REPO_URL" "$APP_DIR"
fi

say "python environment"
command -v python3 >/dev/null 2>&1 || die "python3 missing"
[ -d "$APP_DIR/django_api/.venv" ] || runuser -u "$APP_USER" -- python3 -m venv "$APP_DIR/django_api/.venv"
runuser -u "$APP_USER" -- "$APP_DIR/django_api/.venv/bin/pip" install -q --upgrade pip
runuser -u "$APP_USER" -- "$APP_DIR/django_api/.venv/bin/pip" install -q -r "$APP_DIR/django_api/requirements.txt"

say "database"
if [ "$DB" = "postgres" ]; then
  systemctl enable --now postgresql
  password="$(openssl rand -hex 24)"
  if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='asaan'" | grep -q 1; then
    runuser -u postgres -- psql -qc "CREATE ROLE asaan LOGIN PASSWORD '$password';"
  else
    password="$(sed -n 's/^POSTGRES_PASSWORD=//p' "$ENV_FILE" 2>/dev/null | tail -1)"
  fi
  runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='asaan'" | grep -q 1 \
    || runuser -u postgres -- psql -qc "CREATE DATABASE asaan OWNER asaan;"
  DB_BLOCK="POSTGRES_DB=asaan
POSTGRES_USER=asaan
POSTGRES_PASSWORD=$password
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432"
else
  DB_BLOCK="DATABASE_PATH=$DATA_DIR/asaan.db"
fi

say "configuration"
if [ -f "$ENV_FILE" ]; then
  echo "$ENV_FILE already exists; refreshing the host list"
  sed -i \
    -e "s|^DJANGO_ALLOWED_HOSTS=.*|DJANGO_ALLOWED_HOSTS=$ALL_HOSTS,127.0.0.1|" \
    -e "s|^DJANGO_CSRF_TRUSTED_ORIGINS=.*|DJANGO_CSRF_TRUSTED_ORIGINS=$CSRF_ORIGINS|" "$ENV_FILE"
  grep -q '^DJANGO_ALLOWED_HOSTS=' "$ENV_FILE" || printf 'DJANGO_ALLOWED_HOSTS=%s\n' "$ALL_HOSTS,127.0.0.1" >> "$ENV_FILE"
  grep -q '^DJANGO_CSRF_TRUSTED_ORIGINS=' "$ENV_FILE" || printf 'DJANGO_CSRF_TRUSTED_ORIGINS=%s\n' "$CSRF_ORIGINS" >> "$ENV_FILE"
else
  cat > "$ENV_FILE" <<EOF
DJANGO_SECRET_KEY=$(openssl rand -hex 48)
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=$ALL_HOSTS,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=$CSRF_ORIGINS
# Flipped to true automatically once HTTPS is working.
DJANGO_SECURE_COOKIES=false
GUNICORN_PORT=$GUNICORN_PORT
MEDIA_ROOT=$DATA_DIR/media
$DB_BLOCK
EOF
fi
chown root:"$APP_GROUP" "$ENV_FILE"
chmod 640 "$ENV_FILE"

say "systemd unit"
sed -e "s|/opt/asaan|$APP_DIR|g" -e "s|/var/lib/asaan|$DATA_DIR|g" \
  "$APP_DIR/deploy/asaan.service" > /etc/systemd/system/asaan.service

if [ "$PROXY" = "caddy" ]; then
  say "caddy site"
  install -d /etc/caddy
  # Caddy separates site addresses with ", " and nginx with spaces.
  CADDY_HOSTS="$(printf '%s' "$ALL_HOSTS" | sed 's/,/, /g')"
  SITE_PATTERN="$(printf '%s' "$SITE_HOST" | sed 's/\./\\./g')"
  sed -e "s/asaan\.in/$SITE_HOST/g" \
      -e "s/^$SITE_PATTERN {/$CADDY_HOSTS {/" \
      -e "s|/opt/asaan|$APP_DIR|g" \
      -e "s|/var/lib/asaan|$DATA_DIR|g" \
      "$APP_DIR/deploy/Caddyfile" > /etc/caddy/Caddyfile
  if [ -n "$EMAIL" ]; then
    printf '{\n\temail %s\n}\n\n' "$EMAIL" > /etc/caddy/Caddyfile.tmp
    cat /etc/caddy/Caddyfile >> /etc/caddy/Caddyfile.tmp
    mv /etc/caddy/Caddyfile.tmp /etc/caddy/Caddyfile
  fi
  caddy validate --config /etc/caddy/Caddyfile
else
  say "nginx site"
  NGINX_HOSTS="$(printf '%s' "$ALL_HOSTS" | tr ',' ' ')"
  sed -e "s/server_name asaan\.in;/server_name $NGINX_HOSTS;/" \
      -e "s/asaan\.in/$SITE_HOST/g" \
      -e "s|/opt/asaan|$APP_DIR|g" \
      -e "s|/var/lib/asaan|$DATA_DIR|g" \
      "$APP_DIR/deploy/nginx.conf" > /etc/nginx/sites-available/asaan
  ln -sf /etc/nginx/sites-available/asaan /etc/nginx/sites-enabled/asaan
  nginx -t
fi

if [ "$SKIP_FIREWALL" != "1" ]; then
  say "firewall"
  ufw allow 22/tcp >/dev/null 2>&1 || true
  ufw allow 80/tcp >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
  ufw --force enable >/dev/null 2>&1 || true
  echo "ufw allows 22, 80 and 443. Open the same in your cloud firewall (Lightsail: Networking -> IPv4 Firewall)."
fi

say "first deploy"
systemctl daemon-reload
systemctl enable asaan >/dev/null
APP_DIR="$APP_DIR" APP_USER="$APP_USER" ENV_FILE="$ENV_FILE" \
  SKIP_FRONTEND="${SKIP_FRONTEND:-0}" sh "$APP_DIR/deploy/deploy.sh"

say "https"
if [ "$PROXY" = "caddy" ]; then
  systemctl enable caddy >/dev/null 2>&1 || true
  systemctl restart caddy
else
  systemctl reload nginx 2>/dev/null || systemctl restart nginx
  if [ -n "$EMAIL" ]; then
    certbot --nginx -d "$SITE_HOST" --non-interactive --agree-tos -m "$EMAIL" --redirect || true
  fi
fi

# Ask for the certificate locally, so this works before public DNS has settled.
https_ok() {
  curl -fsS --max-time 5 --resolve "$SITE_HOST:443:127.0.0.1" \
    "https://$SITE_HOST/healthz" >/dev/null 2>&1
}

URL="https://$SITE_HOST"
if https_ok; then
  sed -i 's/^DJANGO_SECURE_COOKIES=.*/DJANGO_SECURE_COOKIES=true/' "$ENV_FILE"
  systemctl restart asaan
  echo "HTTPS is live for $SITE_HOST; secure cookies enabled"
else
  echo "HTTPS is not answering yet for $SITE_HOST. That is expected until DNS"
  echo "points here; the certificate is issued on the next attempt. Then run:"
  if [ "$PROXY" = "nginx" ]; then
    echo "  certbot --nginx -d $SITE_HOST        # only when no certificate exists yet"
  fi
  echo "  curl -fsS $URL/healthz"
  echo "  sed -i 's/^DJANGO_SECURE_COOKIES=.*/DJANGO_SECURE_COOKIES=true/' $ENV_FILE"
  echo "  systemctl restart asaan"
fi

say "done"
install -m 755 "$APP_DIR/deploy/backup-asaan.sh" /etc/cron.daily/asaan-backup
cat <<EOF
Asaan is running at $URL

Remaining steps:
  1. Cloud firewall: allow 80 and 443 (OVH VPS are open by default; other clouds
     need a rule).
  2. Admin user:
       sudo -u $APP_USER sh -c 'cd $APP_DIR/django_api && .venv/bin/python manage.py createsuperuser'
  3. Nightly backups are installed at /etc/cron.daily/asaan-backup.
  4. Health checks: point an uptime monitor at $URL/healthz
EOF
