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
#   EMAIL          Let's Encrypt account; when set, HTTPS is configured
#   DB             sqlite (default) or postgres
#   APP_DIR        /opt/asaan
#   APP_USER       asaan
#   DATA_DIR       /var/lib/asaan
#   GUNICORN_PORT  8123
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
SITE_HOST="${SITE_HOST:-}"
EMAIL="${EMAIL:-}"
REPO_URL="${REPO_URL:-}"
SKIP_FIREWALL="${SKIP_FIREWALL:-0}"

say() { printf '\n==> %s\n' "$1"; }
die() { echo "error: $1" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "run this with sudo"
[ -f /etc/debian_version ] || die "this script targets Debian or Ubuntu"
[ "$DB" = "sqlite" ] || [ "$DB" = "postgres" ] || die "DB must be sqlite or postgres"

say "hostname"
if [ -z "$SITE_HOST" ]; then
  ip="$(curl -fsS --max-time 10 https://api.ipify.org || true)"
  [ -n "$ip" ] || die "could not detect the public IP; pass SITE_HOST=..."
  SITE_HOST="$(printf '%s' "$ip" | tr '.' '-').sslip.io"
  echo "no SITE_HOST given; using $SITE_HOST (sslip.io resolves to this server)"
fi

say "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates sqlite3 nginx python3-venv python3-pip ufw
command -v certbot >/dev/null 2>&1 || apt-get install -y -qq certbot python3-certbot-nginx
if ! command -v node >/dev/null 2>&1 || [ "$(node -v | sed 's/^v\([0-9]*\).*/\1/')" -lt 18 ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y -qq nodejs
fi
if [ "$DB" = "postgres" ]; then apt-get install -y -qq postgresql postgresql-client; fi

say "service account and directories"
id -u "$APP_USER" >/dev/null 2>&1 || adduser --system --group --home "$APP_DIR" "$APP_USER"
install -d -o "$APP_USER" -g "$APP_GROUP" "$DATA_DIR" "$DATA_DIR/media"
install -d -o root -g "$APP_GROUP" -m 750 "$ENV_DIR"
install -d /var/backups/asaan

say "code"
if [ -d "$APP_DIR/.git" ]; then
  runuser -u "$APP_USER" -- git -C "$APP_DIR" pull --ff-only || true
else
  [ -n "$REPO_URL" ] || die "$APP_DIR has no checkout; pass REPO_URL=..."
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
  echo "$ENV_FILE already exists; leaving it alone"
else
  cat > "$ENV_FILE" <<EOF
DJANGO_SECRET_KEY=$(openssl rand -hex 48)
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=$SITE_HOST,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://$SITE_HOST
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

say "nginx site"
sed -e "s/asaan\.in/$SITE_HOST/g" \
    -e "s|/opt/asaan|$APP_DIR|g" \
    -e "s|/var/lib/asaan|$DATA_DIR|g" \
    "$APP_DIR/deploy/nginx.conf" > /etc/nginx/sites-available/asaan
ln -sf /etc/nginx/sites-available/asaan /etc/nginx/sites-enabled/asaan
rm -f /etc/nginx/sites-enabled/default
nginx -t

if [ "$SKIP_FIREWALL" != "1" ]; then
  say "firewall"
  ufw allow 22/tcp >/dev/null 2>&1 || true
  ufw allow 'Nginx Full' >/dev/null 2>&1 || true
  ufw --force enable >/dev/null 2>&1 || true
  echo "ufw allows 22, 80 and 443. Open the same in your cloud firewall (Lightsail: Networking -> IPv4 Firewall)."
fi

say "first deploy"
systemctl daemon-reload
systemctl enable asaan >/dev/null
APP_DIR="$APP_DIR" APP_USER="$APP_USER" ENV_FILE="$ENV_FILE" sh "$APP_DIR/deploy/deploy.sh"

if [ -n "$EMAIL" ]; then
  say "https"
  if certbot --nginx -d "$SITE_HOST" --non-interactive --agree-tos -m "$EMAIL" --redirect; then
    sed -i 's/^DJANGO_SECURE_COOKIES=.*/DJANGO_SECURE_COOKIES=true/' "$ENV_FILE"
    systemctl restart asaan
    URL="https://$SITE_HOST"
  else
    echo "certbot failed (DNS not pointing here yet?). Re-run: certbot --nginx -d $SITE_HOST"
    URL="http://$SITE_HOST"
  fi
else
  say "https"
  echo "No EMAIL set, so HTTPS was skipped. Once DNS points at this server run:"
  echo "  certbot --nginx -d $SITE_HOST"
  echo "  sed -i 's/^DJANGO_SECURE_COOKIES=.*/DJANGO_SECURE_COOKIES=true/' $ENV_FILE"
  echo "  systemctl restart asaan"
  URL="http://$SITE_HOST"
fi

say "done"
cat <<EOF
Asaan is running at $URL

Remaining steps:
  1. Cloud firewall: allow 80 and 443 (Lightsail -> Networking -> IPv4 Firewall).
  2. Admin user:
       sudo -u $APP_USER sh -c 'cd $APP_DIR/django_api && .venv/bin/python manage.py createsuperuser'
  3. Nightly backups:
       sudo cp $APP_DIR/deploy/backup-asaan.sh /etc/cron.daily/asaan-backup
  4. Attach a static IP and enable automatic snapshots in the cloud console.
  5. Health checks: point an uptime monitor at $URL/healthz
EOF
