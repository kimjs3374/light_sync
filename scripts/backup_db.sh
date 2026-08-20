#!/bin/bash
# Light-Sync ERP 데이터베이스 백업 (매일 02:00)
# 7일치 보관, 오래된 백업 자동 삭제
#
# 2026-08-06 수정 — 그전까지 백업이 전부 0바이트였음:
#   1) 호스트엔 pg_dump 래퍼만 있고 postgresql-client 실체가 없어 매번 실패
#   2) `pg_dump | gzip` 파이프라인 종료코드가 gzip 것이라 set -e가 실패를 못 잡음
#   3) stderr를 /dev/null로 버려 로그엔 계속 "성공"으로 기록
# → supabase-db 컨테이너의 pg_dump(15.8) 사용 + 실패/빈파일 검증 추가.
#   임시파일에 받고 검증을 통과한 것만 정식 파일명으로 승격하므로,
#   실패 시 깨진 백업이 남거나 기존 백업이 삭제되는 일이 없음.

set -euo pipefail

BACKUP_DIR="/web/light_sync/backups"
DATE=$(date +%Y%m%d_%H%M%S)
FILENAME="light_sync_${DATE}.sql.gz"
KEEP_DAYS=7
SCHEMA="light_sync"

DB_CONTAINER="${DB_CONTAINER:-supabase-db}"
DB_USER="${DB_USER:-postgres}"
DB_NAME="${DB_NAME:-postgres}"

TMPFILE="${BACKUP_DIR}/.${FILENAME}.part"
DUMP_ERR="${BACKUP_DIR}/.dump_err.$$"

# 어떤 경로로 실패하든 원인을 반드시 로그에 남기고 나간다.
# (set -e 로 중도 중단되는 경우에도 pg_dump stderr가 유실되지 않도록)
cleanup() {
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        [ -s "$DUMP_ERR" ] && sed 's/^/[backup]   pg_dump: /' "$DUMP_ERR" >&2
        echo "[backup] 실패 종료 (exit ${rc}) — 이번 백업 없음, 기존 백업은 유지됨" >&2
    fi
    rm -f "$TMPFILE" "$DUMP_ERR"
}
trap cleanup EXIT

fail() {
    echo "[backup] ERROR: $*" >&2
    exit 1
}

mkdir -p "$BACKUP_DIR"

# --- 덤프 (컨테이너 우선, 없으면 호스트 pg_dump) ---------------------------
if docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null | grep -q true; then
    SOURCE="container:${DB_CONTAINER}"
    docker exec "$DB_CONTAINER" \
        pg_dump -U "$DB_USER" -d "$DB_NAME" \
        --schema="$SCHEMA" --no-owner --no-privileges \
        2>"$DUMP_ERR" | gzip > "$TMPFILE"
else
    # 폴백: DB가 컨테이너 밖으로 옮겨진 경우
    source /web/light_sync/.env 2>/dev/null || true
    DB_URL="${DATABASE_URL:-${SUPABASE_DB_DSN:-}}"
    [ -n "$DB_URL" ] || fail "${DB_CONTAINER} 컨테이너도 없고 DATABASE_URL도 없음"
    command -v pg_dump >/dev/null || fail "${DB_CONTAINER} 컨테이너 미기동 + 호스트에 pg_dump 없음"
    SOURCE="host:pg_dump"
    pg_dump "$DB_URL" --schema="$SCHEMA" --no-owner --no-privileges \
        2>"$DUMP_ERR" | gzip > "$TMPFILE"
fi
# set -o pipefail 이 걸려 있어 pg_dump 실패 시 여기서 즉시 중단됨

# --- 검증 ------------------------------------------------------------------
gzip -t "$TMPFILE" 2>/dev/null || fail "gzip 무결성 검사 실패 — $(head -3 "$DUMP_ERR" 2>/dev/null)"

RAW_BYTES=$(gzip -dc "$TMPFILE" | wc -c)
[ "$RAW_BYTES" -gt 0 ] || fail "덤프가 비어 있음 — $(head -3 "$DUMP_ERR" 2>/dev/null)"

TABLES=$(gzip -dc "$TMPFILE" | grep -c '^CREATE TABLE' || true)
[ "$TABLES" -gt 0 ] || fail "덤프에 테이블이 0개 (${RAW_BYTES} bytes)"

# 실DB 테이블 수와 대조 (조회 실패 시 대조는 건너뜀)
LIVE_TABLES=$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tAc \
    "select count(*) from information_schema.tables where table_schema='${SCHEMA}' and table_type='BASE TABLE'" \
    2>/dev/null | tr -d '[:space:]' || true)
if [[ "$LIVE_TABLES" =~ ^[0-9]+$ ]] && [ "$TABLES" -ne "$LIVE_TABLES" ]; then
    echo "[backup] WARN: 테이블 수 불일치 — 덤프 ${TABLES}개 / 실DB ${LIVE_TABLES}개"
fi

# --- 승격 ------------------------------------------------------------------
mv "$TMPFILE" "${BACKUP_DIR}/${FILENAME}"
SIZE=$(du -h "${BACKUP_DIR}/${FILENAME}" | cut -f1)
echo "[backup] ${DATE} — ${FILENAME} (${SIZE}, 테이블 ${TABLES}개, ${SOURCE})"

# --- 오래된 백업 삭제 (성공했을 때만) --------------------------------------
find "$BACKUP_DIR" -name "light_sync_*.sql.gz" -mtime +${KEEP_DAYS} -delete
REMAINING=$(find "$BACKUP_DIR" -name "light_sync_*.sql.gz" | wc -l)
echo "[backup] 보관 중: ${REMAINING}개 (${KEEP_DAYS}일치)"
