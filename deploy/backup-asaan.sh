#!/usr/bin/env sh
# Nightly backup of the Asaan database and uploaded photos.
# Install as /etc/cron.daily/asaan-backup (chmod +x) or a systemd timer.
#
# Works with either database: it follows POSTGRES_DB in the env file, and
# otherwise snapshots the SQLite file.
#
# Offsite copy: set BACKUP_REMOTE to keep a second copy off the server.
#   rclone:asaan-backups         -> rclone copy (remote configured with rclone config)
#   backup@host:/srv/asaan       -> rsync over ssh
set -eu

ENV_FILE="${ENV_FILE:-/etc/asaan/asaan.env}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/asaan}"
MEDIA_ROOT="${MEDIA_ROOT:-/var/lib/asaan/media}"
KEEP_DAYS="${KEEP_DAYS:-14}"
BACKUP_REMOTE="${BACKUP_REMOTE:-}"
mkdir -p "$BACKUP_DIR"

env_value() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -1 || true; }

STAMP="$(date +%F)"
POSTGRES_DB="${POSTGRES_DB:-$(env_value POSTGRES_DB)}"

if [ -n "$POSTGRES_DB" ]; then
  POSTGRES_HOST="${POSTGRES_HOST:-$(env_value POSTGRES_HOST)}"
  POSTGRES_USER="${POSTGRES_USER:-$(env_value POSTGRES_USER)}"
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(env_value POSTGRES_PASSWORD)}"
  export PGPASSWORD="${POSTGRES_PASSWORD:-}"
  pg_dump \
    -h "${POSTGRES_HOST:-127.0.0.1}" \
    -p "${POSTGRES_PORT:-$(env_value POSTGRES_PORT)}" \
    -U "${POSTGRES_USER:-asaan}" \
    -Fc -f "$BACKUP_DIR/asaan-$STAMP.dump" \
    "$POSTGRES_DB"
  unset PGPASSWORD
else
  DATABASE_PATH="${DATABASE_PATH:-$(env_value DATABASE_PATH)}"
  sqlite3 "${DATABASE_PATH:-/var/lib/asaan/asaan.db}" \
    ".backup '$BACKUP_DIR/asaan-$STAMP.db'"
fi

if [ -d "$MEDIA_ROOT" ]; then
  tar -czf "$BACKUP_DIR/asaan-media-$STAMP.tar.gz" \
    -C "$(dirname "$MEDIA_ROOT")" "$(basename "$MEDIA_ROOT")"
fi

if [ -n "$BACKUP_REMOTE" ]; then
  case "$BACKUP_REMOTE" in
    rclone:*)
      rclone copy "$BACKUP_DIR" "${BACKUP_REMOTE#rclone:}" --include 'asaan-*' --quiet
      ;;
    *)
      rsync -az --quiet "$BACKUP_DIR"/asaan-* "$BACKUP_REMOTE/"
      ;;
  esac
fi

find "$BACKUP_DIR" -type f \( -name 'asaan-*.db' -o -name 'asaan-*.dump' -o -name 'asaan-media-*.tar.gz' \) -mtime "+$KEEP_DAYS" -delete
