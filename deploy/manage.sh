#!/usr/bin/env sh
# Run manage.py on the server with the service environment loaded, so management
# commands see the same database, secret key and settings as the running app.
#
#   sudo -u asaan /opt/asaan/deploy/manage.sh check --deploy
#   sudo -u asaan /opt/asaan/deploy/manage.sh createsuperuser
#   sudo -u asaan /opt/asaan/deploy/manage.sh migrate
set -eu

APP_DIR="${APP_DIR:-/opt/asaan}"
ENV_FILE="${ENV_FILE:-/etc/asaan/asaan.env}"

if [ -f "$ENV_FILE" ]; then
  while IFS='=' read -r key value; do
    case "$key" in ''|\#*) continue ;; esac
    export "$key=$value"
  done < "$ENV_FILE"
fi

cd "$APP_DIR/django_api"
exec "$APP_DIR/django_api/.venv/bin/python" manage.py "$@"
