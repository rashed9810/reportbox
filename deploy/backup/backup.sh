#!/bin/sh
# Nightly encrypted backups of the database and the (already encrypted) report files.
# Files land in deploy/backups/ on the server. Copy them to a second location in Bangladesh.
set -eu

: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE is required}"
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p /backups

backup_once() {
  ts=$(date -u +%Y%m%d-%H%M)
  pg_dump --no-owner | gzip | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE \
    -out "/backups/db-$ts.sql.gz.enc"
  tar -C /data -czf - storage | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE \
    -out "/backups/reports-$ts.tar.gz.enc"
  find /backups -name '*.enc' -mtime "+$KEEP_DAYS" -delete
  echo "$(date -u) backup done: db-$ts, reports-$ts"
}

# First backup when the container starts, then about every 24 hours.
while true; do
  backup_once || echo "$(date -u) BACKUP FAILED" >&2
  sleep 86400
done
