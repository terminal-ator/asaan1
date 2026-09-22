#!/usr/bin/env sh
set -eu

DATABASE_PATH="${DATABASE_PATH:-/var/lib/ordex/ordex.db}"
MEDIA_ROOT="${MEDIA_ROOT:-/var/lib/ordex/media}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/ordex}"
mkdir -p "$BACKUP_DIR"

sqlite3 "$DATABASE_PATH" ".backup '$BACKUP_DIR/ordex-$(date +%F).db'"

if [ -d "$MEDIA_ROOT" ]; then
  tar -czf "$BACKUP_DIR/ordex-media-$(date +%F).tar.gz" \
    -C "$(dirname "$MEDIA_ROOT")" "$(basename "$MEDIA_ROOT")"
fi

find "$BACKUP_DIR" -type f \( -name 'ordex-*.db' -o -name 'ordex-media-*.tar.gz' \) -mtime +14 -delete
