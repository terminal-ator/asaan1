#!/usr/bin/env sh
# Deploy Ordex in place: pull, install, migrate, collect, build, reload, verify.
#
#   deploy/deploy.sh                    # deploy the configured branch
#   TARGET=v1.2.0 deploy/deploy.sh      # deploy a tag (or an old commit) by hand
#   SKIP_FRONTEND=1 deploy/deploy.sh    # when dist/ is shipped separately
#
# Run as root on the server, or as the ordex user if it owns the checkout.
set -eu

APP_DIR="${APP_DIR:-/opt/ordex}"
APP_USER="${APP_USER:-ordex}"
ENV_FILE="${ENV_FILE:-/etc/ordex/ordex.env}"
BRANCH="${BRANCH:-main}"
TARGET="${TARGET:-$BRANCH}"
SERVICE="${SERVICE:-ordex}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/ordex}"
PYTHON="$APP_DIR/django_api/.venv/bin/python"
PIP="$APP_DIR/django_api/.venv/bin/pip"
GUNICORN_PORT="$(sed -n 's/^GUNICORN_PORT=//p' "$ENV_FILE" | tail -1)"
[ -n "${GUNICORN_PORT:-}" ] || GUNICORN_PORT=8123
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${GUNICORN_PORT}/healthz}"

say() { printf '\n==> %s\n' "$1"; }
as_user() {
  if [ "$(id -u)" = "0" ]; then runuser -u "$APP_USER" -- sh -c "$1"; else sh -c "$1"; fi
}

cd "$APP_DIR"
PREVIOUS_REV="$(git rev-parse --short HEAD)"
say "current revision $PREVIOUS_REV, deploying $TARGET"

say "backing up the database before touching anything"
DATABASE_PATH="$(sed -n 's/^DATABASE_PATH=//p' "$ENV_FILE" | tail -1)"
[ -n "${DATABASE_PATH:-}" ] || DATABASE_PATH=/var/lib/ordex/ordex.db
if [ -f "$DATABASE_PATH" ]; then
  mkdir -p "$BACKUP_DIR"
  sqlite3 "$DATABASE_PATH" ".backup '$BACKUP_DIR/pre-deploy-$(date +%F-%H%M).db'"
fi

say "fetching $TARGET"
as_user "git -C '$APP_DIR' fetch --all --tags --prune"
as_user "git -C '$APP_DIR' checkout --force '$TARGET'"

say "installing python dependencies"
as_user "'$PIP' install --quiet --upgrade pip"
as_user "'$PIP' install --quiet -r '$APP_DIR/django_api/requirements.txt'"

say "applying migrations"
as_user "cd '$APP_DIR/django_api' && '$PYTHON' manage.py migrate --noinput"

say "collecting static files"
as_user "cd '$APP_DIR/django_api' && '$PYTHON' manage.py collectstatic --noinput --clear"

if [ "${SKIP_FRONTEND:-0}" != "1" ]; then
  say "building the PWA"
  as_user "cd '$APP_DIR' && npm ci --silent && npm run build"
fi

say "reloading $SERVICE"
systemctl reload "$SERVICE" || systemctl restart "$SERVICE"

say "checking health at $HEALTH_URL"
attempt=1
while [ "$attempt" -le 10 ]; do
  if curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null; then
    say "deployed $TARGET successfully"
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 2
done

say "HEALTH CHECK FAILED, rolling back to $PREVIOUS_REV"
as_user "git -C '$APP_DIR' checkout --force '$PREVIOUS_REV'"
as_user "'$PIP' install --quiet -r '$APP_DIR/django_api/requirements.txt'"
as_user "cd '$APP_DIR/django_api' && '$PYTHON' manage.py collectstatic --noinput --clear"
if [ "${SKIP_FRONTEND:-0}" != "1" ]; then
  as_user "cd '$APP_DIR' && npm ci --silent && npm run build"
fi
systemctl reload "$SERVICE" || systemctl restart "$SERVICE"

cat >&2 <<'EOF'
Code rolled back, but migrations are forward-only. If the failure was caused by
a schema change, restore the pre-deploy database backup:

  systemctl stop ordex
  cp /var/backups/ordex/pre-deploy-YYYY-MM-DD-HHMM.db /var/lib/ordex/ordex.db
  systemctl start ordex

Then fix forward and deploy again.
EOF
exit 1
