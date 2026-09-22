#!/usr/bin/env sh
set -eu

DATABASE_PATH="${DATABASE_PATH:-/var/lib/ordex/ordex.db}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/ordex}"
mkdir -p "$BACKUP_DIR"
sqlite3 "$DATABASE_PATH" ".backup '$BACKUP_DIR/ordex-$(date +%F).db'"
find "$BACKUP_DIR" -type f -name 'ordex-*.db' -mtime +14 -delete
