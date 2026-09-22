#!/usr/bin/env sh
# Nightly backup of the Ordex database and uploaded photos.
# Install as /etc/cron.daily/ordex-backup (chmod +x) or a systemd timer.
#
# Offsite copy: set BACKUP_REMOTE to keep a second copy off the server.
#   rclone:ordex-backups         -> rclone copy (remote configured with rclone config)
#   backup@host:/srv/ordex       -> rsync over ssh
set -eu

DATABASE_PATH="${DATABASE_PATH:-/var/lib/ordex/ordex.db}"
MEDIA_ROOT="${MEDIA_ROOT:-/var/lib/ordex/media}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/ordex}"
KEEP_DAYS="${KEEP_DAYS:-14}"
BACKUP_REMOTE="${BACKUP_REMOTE:-}"
mkdir -p "$BACKUP_DIR"

STAMP="$(date +%F)"
sqlite3 "$DATABASE_PATH" ".backup '$BACKUP_DIR/ordex-$STAMP.db'"

if [ -d "$MEDIA_ROOT" ]; then
  tar -czf "$BACKUP_DIR/ordex-media-$STAMP.tar.gz" \
    -C "$(dirname "$MEDIA_ROOT")" "$(basename "$MEDIA_ROOT")"
fi

if [ -n "$BACKUP_REMOTE" ]; then
  case "$BACKUP_REMOTE" in
    rclone:*)
      rclone copy "$BACKUP_DIR" "${BACKUP_REMOTE#rclone:}" --include 'ordex-*' --quiet
      ;;
    *)
      rsync -az --quiet "$BACKUP_DIR"/ordex-* "$BACKUP_REMOTE/"
      ;;
  esac
fi

find "$BACKUP_DIR" -type f \( -name 'ordex-*.db' -o -name 'ordex-media-*.tar.gz' \) -mtime "+$KEEP_DAYS" -delete
