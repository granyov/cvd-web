#!/usr/bin/env sh
set -eu

DB_PATH="${CVD_DB_PATH:-data/cvd.sqlite3}"
BACKUP_DIR="${CVD_BACKUP_DIR:-backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$BACKUP_DIR"
sqlite3 "$DB_PATH" ".backup '$BACKUP_DIR/cvd-$STAMP.sqlite3'"
find "$BACKUP_DIR" -type f -name 'cvd-*.sqlite3' -mtime +14 -delete
