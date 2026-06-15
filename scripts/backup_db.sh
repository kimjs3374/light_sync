#!/bin/bash
# Light-Sync ERP 데이터베이스 백업 (매일 02:00)
# 7일치 보관, 오래된 백업 자동 삭제

set -e

BACKUP_DIR="/web/light_sync/backups"
DATE=$(date +%Y%m%d_%H%M%S)
FILENAME="light_sync_${DATE}.sql.gz"
KEEP_DAYS=7

# .env에서 DATABASE_URL 읽기
source /web/light_sync/.env 2>/dev/null || true
DB_URL="${DATABASE_URL:-${SUPABASE_DB_DSN}}"

if [ -z "$DB_URL" ]; then
    echo "[backup] ERROR: DATABASE_URL not set"
    exit 1
fi

# pg_dump + gzip
pg_dump "$DB_URL" --schema=light_sync --no-owner --no-privileges 2>/dev/null | gzip > "${BACKUP_DIR}/${FILENAME}"

SIZE=$(du -h "${BACKUP_DIR}/${FILENAME}" | cut -f1)
echo "[backup] ${DATE} — ${FILENAME} (${SIZE})"

# 오래된 백업 삭제
find "${BACKUP_DIR}" -name "light_sync_*.sql.gz" -mtime +${KEEP_DAYS} -delete
REMAINING=$(ls -1 "${BACKUP_DIR}"/light_sync_*.sql.gz 2>/dev/null | wc -l)
echo "[backup] 보관 중: ${REMAINING}개 (${KEEP_DAYS}일치)"
