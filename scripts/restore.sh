#!/usr/bin/env bash
# =============================================================================
# Joplin Server — Restore from Backup
#
# Usage:
#   ./restore.sh                  → interactive: list Drive backups, pick one
#   ./restore.sh <archive.tar.gz> → restore a specific local file directly
#
# What it restores:
#   - PostgreSQL database (required)
#   - .env and docker-compose.yml (optional, prompted)
# =============================================================================

set -euo pipefail

# --- Config (must match backup.sh) -------------------------------------------
JOPLIN_DIR="/home/kalp/git/joplin"
BACKUP_DIR="${JOPLIN_DIR}/backups"
RCLONE_REMOTE="gdrive"
RCLONE_PATH="joplin backups"
DB_CONTAINER="joplin-joplin-db-1"
DB_NAME="joplin"
DB_USER="joplin"
# -----------------------------------------------------------------------------

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️  $*"; }
die()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ $*" >&2; exit 1; }

TMP_DIR=$(mktemp -d)
cleanup() { rm -rf "${TMP_DIR}"; }
trap cleanup EXIT

# =============================================================================
# Step 1 — Determine which archive to restore
# =============================================================================
ARCHIVE_PATH=""

if [[ $# -ge 1 ]]; then
    # --- Direct file argument
    ARCHIVE_PATH="$1"
    [[ -f "${ARCHIVE_PATH}" ]] || die "File not found: ${ARCHIVE_PATH}"
    log "Using local archive: ${ARCHIVE_PATH}"
else
    # --- Interactive: list backups from Google Drive
    log "Fetching available backups from Google Drive (${RCLONE_REMOTE}:${RCLONE_PATH})..."
    mapfile -t REMOTE_FILES < <(
        rclone ls "${RCLONE_REMOTE}:${RCLONE_PATH}" 2>/dev/null \
        | grep 'joplin-backup-.*\.tar\.gz' \
        | awk '{print $2}' \
        | sort -r
    )

    if [[ ${#REMOTE_FILES[@]} -eq 0 ]]; then
        die "No backups found in ${RCLONE_REMOTE}:${RCLONE_PATH}"
    fi

    echo ""
    echo "Available backups (newest first):"
    echo "-----------------------------------"
    for i in "${!REMOTE_FILES[@]}"; do
        printf "  [%d] %s\n" "$((i+1))" "${REMOTE_FILES[$i]}"
    done
    echo ""

    read -rp "Select backup to restore [1-${#REMOTE_FILES[@]}]: " SELECTION
    [[ "${SELECTION}" =~ ^[0-9]+$ ]] || die "Invalid selection."
    IDX=$((SELECTION - 1))
    [[ ${IDX} -ge 0 && ${IDX} -lt ${#REMOTE_FILES[@]} ]] || die "Selection out of range."

    CHOSEN="${REMOTE_FILES[$IDX]}"
    LOCAL_CACHED="${BACKUP_DIR}/${CHOSEN}"

    if [[ -f "${LOCAL_CACHED}" ]]; then
        log "Found cached locally, skipping download: ${LOCAL_CACHED}"
        ARCHIVE_PATH="${LOCAL_CACHED}"
    else
        log "Downloading ${CHOSEN} from Google Drive..."
        mkdir -p "${BACKUP_DIR}"
        rclone copy "${RCLONE_REMOTE}:${RCLONE_PATH}/${CHOSEN}" "${BACKUP_DIR}" --progress
        ARCHIVE_PATH="${BACKUP_DIR}/${CHOSEN}"
    fi
fi

log "Archive to restore: ${ARCHIVE_PATH} ($(du -sh "${ARCHIVE_PATH}" | cut -f1))"

# =============================================================================
# Step 2 — Safety confirmation
# =============================================================================
echo ""
warn "This will DROP and recreate the '${DB_NAME}' database, replacing all current data."
read -rp "Are you sure you want to proceed? Type YES to confirm: " CONFIRM
[[ "${CONFIRM}" == "YES" ]] || die "Aborted by user."

# =============================================================================
# Step 3 — Extract archive
# =============================================================================
log "Extracting archive..."
tar -xzf "${ARCHIVE_PATH}" -C "${TMP_DIR}"
log "Contents: $(ls "${TMP_DIR}")"

[[ -f "${TMP_DIR}/joplin.sql" ]] || die "Archive does not contain joplin.sql — invalid backup."

# =============================================================================
# Step 4 — Stop Joplin (keep DB running for restore)
# =============================================================================
log "Stopping Joplin app container (keeping database up)..."
cd "${JOPLIN_DIR}"
docker compose stop joplin
log "Joplin app stopped."

# =============================================================================
# Step 5 — Restore PostgreSQL database
# =============================================================================
log "Dropping existing database '${DB_NAME}'..."
docker exec "${DB_CONTAINER}" \
    psql -U "${DB_USER}" -d postgres \
    -c "DROP DATABASE IF EXISTS ${DB_NAME};"

log "Recreating database '${DB_NAME}'..."
docker exec "${DB_CONTAINER}" \
    psql -U "${DB_USER}" -d postgres \
    -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

log "Restoring database from dump (this may take a moment)..."
docker exec -i "${DB_CONTAINER}" \
    psql -U "${DB_USER}" -d "${DB_NAME}" \
    < "${TMP_DIR}/joplin.sql"
log "✅ Database restored."

# =============================================================================
# Step 6 — Optionally restore config files
# =============================================================================
echo ""
read -rp "Restore .env and docker-compose.yml from backup? [y/N]: " RESTORE_CONFIG
if [[ "${RESTORE_CONFIG}" =~ ^[Yy]$ ]]; then
    if [[ -f "${TMP_DIR}/.env" ]]; then
        cp "${JOPLIN_DIR}/.env" "${JOPLIN_DIR}/.env.pre-restore.bak"
        cp "${TMP_DIR}/.env" "${JOPLIN_DIR}/.env"
        log "Restored .env (old version saved as .env.pre-restore.bak)"
    else
        warn ".env not found in archive, skipping."
    fi

    if [[ -f "${TMP_DIR}/docker-compose.yml" ]]; then
        cp "${JOPLIN_DIR}/docker-compose.yml" "${JOPLIN_DIR}/docker-compose.yml.pre-restore.bak"
        cp "${TMP_DIR}/docker-compose.yml" "${JOPLIN_DIR}/docker-compose.yml"
        log "Restored docker-compose.yml (old version saved as .pre-restore.bak)"
    else
        warn "docker-compose.yml not found in archive, skipping."
    fi
else
    log "Skipping config file restore."
fi

# =============================================================================
# Step 7 — Restart Joplin
# =============================================================================
log "Starting Joplin app container..."
docker compose start joplin
log "✅ Joplin started."

echo ""
log "🎉 Restore complete! Joplin is back up at https://joplin.kalp.dev"
log "   Restored from: $(basename "${ARCHIVE_PATH}")"
