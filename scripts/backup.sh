#!/usr/bin/env bash
# =============================================================================
# Joplin Server — Daily Backup Script
# Backs up: PostgreSQL DB dump + config files
# Uploads to: Google Drive via rclone
# =============================================================================

set -euo pipefail

# --- Config ------------------------------------------------------------------
JOPLIN_DIR="/home/kalp/git/joplin"
BACKUP_DIR="${JOPLIN_DIR}/backups"
RCLONE_REMOTE="gdrive"                        # rclone remote name (set during rclone config)
RCLONE_PATH="joplin backups"                  # folder in your Google Drive
KEEP_LOCAL_DAYS=7                             # how many days of local backups to keep
DB_CONTAINER="joplin-joplin-db-1"
DB_NAME="joplin"
DB_USER="joplin"
# -----------------------------------------------------------------------------

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
ARCHIVE_NAME="joplin-backup-${TIMESTAMP}.tar.gz"
TMP_DIR=$(mktemp -d)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

cleanup() { rm -rf "${TMP_DIR}"; }
trap cleanup EXIT

log "Starting Joplin backup: ${ARCHIVE_NAME}"

# 1. Dump PostgreSQL database from inside the container
log "Dumping PostgreSQL database..."
docker exec "${DB_CONTAINER}" \
    pg_dump -U "${DB_USER}" "${DB_NAME}" \
    > "${TMP_DIR}/joplin.sql"
log "Database dump complete ($(du -sh "${TMP_DIR}/joplin.sql" | cut -f1))"

# 2. Copy config files
log "Copying config files..."
cp "${JOPLIN_DIR}/docker-compose.yml" "${TMP_DIR}/"
cp "${JOPLIN_DIR}/.env"               "${TMP_DIR}/"

# 3. Create compressed archive
log "Creating archive..."
mkdir -p "${BACKUP_DIR}"
tar -czf "${BACKUP_DIR}/${ARCHIVE_NAME}" -C "${TMP_DIR}" .
log "Archive created: ${BACKUP_DIR}/${ARCHIVE_NAME} ($(du -sh "${BACKUP_DIR}/${ARCHIVE_NAME}" | cut -f1))"

# 4. Upload to Google Drive
log "Uploading to Google Drive (${RCLONE_REMOTE}:${RCLONE_PATH})..."
rclone copy "${BACKUP_DIR}/${ARCHIVE_NAME}" "${RCLONE_REMOTE}:${RCLONE_PATH}" \
    --progress \
    --stats-one-line
log "Upload complete."

# 5. Prune local backups older than KEEP_LOCAL_DAYS
log "Pruning local backups older than ${KEEP_LOCAL_DAYS} days..."
find "${BACKUP_DIR}" -name "joplin-backup-*.tar.gz" \
    -mtime "+${KEEP_LOCAL_DAYS}" -delete
log "Local cleanup done. Current backups:"
ls -lh "${BACKUP_DIR}/" | tail -10

log "Backup finished successfully: ${ARCHIVE_NAME}"
