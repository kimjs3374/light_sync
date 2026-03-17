#!/bin/bash
# =============================================================
# NAS 폴더 → ERP 현장 자동 동기화 스크립트
# 시놀로지 NAS 작업 스케줄러(cron)에 등록하여 사용
#
# 설치 방법:
#   1. 이 파일을 NAS에 복사: /volume1/scripts/nas_folder_sync.sh
#   2. 실행 권한 부여: chmod +x /volume1/scripts/nas_folder_sync.sh
#   3. 시놀로지 DSM → 제어판 → 작업 스케줄러 → 생성 → 예약된 작업
#      - 실행 명령: bash /volume1/scripts/nas_folder_sync.sh
#      - 반복: 매 10분 (또는 원하는 간격)
# =============================================================

# ── 설정 ──
ERP_URL="https://work.mgnt.kr/api/sync_nas_folders"
API_KEY="change-me-to-your-api-key"   # .env의 NAS_SYNC_API_KEY와 동일하게 설정

BASE_DIR="/volume1/현장관리/000. 현장관리"
YEAR=$(date +%Y)
SCAN_DIR="${BASE_DIR}/${YEAR}"

# 동기화 상태 파일 (이미 전송한 폴더 목록)
STATE_FILE="/volume1/scripts/.nas_sync_state_${YEAR}.txt"
LOG_FILE="/volume1/scripts/nas_sync.log"

# ── 초기화 ──
touch "$STATE_FILE"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# ── 스캔 디렉토리 확인 ──
if [ ! -d "$SCAN_DIR" ]; then
    log "ERROR: 스캔 디렉토리 없음: $SCAN_DIR"
    exit 1
fi

# ── 새 폴더 감지 ──
NEW_FOLDERS=()

while IFS= read -r -d '' dir; do
    folder_name=$(basename "$dir")

    # 패턴 매칭: YYYY.MM.DD_현장명
    if [[ ! "$folder_name" =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{2}_.+ ]]; then
        continue
    fi

    # 이미 동기화된 폴더인지 확인
    if grep -qxF "$folder_name" "$STATE_FILE" 2>/dev/null; then
        continue
    fi

    NEW_FOLDERS+=("$folder_name")
done < <(find "$SCAN_DIR" -maxdepth 1 -mindepth 1 -type d -print0 | sort -z)

# ── 새 폴더가 없으면 종료 ──
if [ ${#NEW_FOLDERS[@]} -eq 0 ]; then
    exit 0
fi

log "새 폴더 ${#NEW_FOLDERS[@]}건 감지"

# ── JSON 배열 생성 ──
JSON_ARRAY="["
FIRST=true
for f in "${NEW_FOLDERS[@]}"; do
    if [ "$FIRST" = true ]; then
        FIRST=false
    else
        JSON_ARRAY+=","
    fi
    # JSON 이스케이프 (큰따옴표, 백슬래시)
    escaped=$(echo "$f" | sed 's/\\/\\\\/g; s/"/\\"/g')
    JSON_ARRAY+="\"${escaped}\""
done
JSON_ARRAY+="]"

PAYLOAD="{\"folders\": ${JSON_ARRAY}, \"year\": \"${YEAR}\"}"

# ── API 호출 ──
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST "$ERP_URL" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d "$PAYLOAD" \
    --max-time 30 \
    2>/dev/null)

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "200" ]; then
    # 성공 시 동기화된 폴더를 상태 파일에 기록
    for f in "${NEW_FOLDERS[@]}"; do
        echo "$f" >> "$STATE_FILE"
    done
    log "동기화 성공 (HTTP ${HTTP_CODE}): ${BODY}"
else
    log "동기화 실패 (HTTP ${HTTP_CODE}): ${BODY}"
    exit 1
fi
