# Light-Sync 우분투 서버 Crontab 설정

## 사전 준비

```bash
# Flask CLI가 app.py를 찾을 수 있도록 환경변수 설정
# /web/light_sync/.env 에 아래 추가 (없으면)
FLASK_APP=app.py
```

## Crontab 등록

```bash
crontab -e
```

아래 내용 추가:

```cron
# ======================================================
# Light-Sync ERP 자동화 작업
# ======================================================

# 1) 나라장터 조달내역 일일 동기화 + 자동 계약생성 (매일 새벽 1시)
#    - 전일 계약/납품요구건 수집
#    - 매그나텍 물품 + 스포츠조명기구 포함
#    - 신규 수집건은 자동으로 계약관리에 등록 (status='G2B자동')
#    - 자동계약 미사용 시: --no-auto-contract 추가
0 1 * * * cd /web/light_sync && venv/bin/flask sync-g2b --mode daily >> logs/g2b_cron.log 2>&1

# 2) NAS 폴더 동기화 (매 30분)
#    - 시놀로지 NAS에서 curl로 호출하는 방식 유지
#    (NAS 작업 스케줄러에서 설정)

# 3) 조달내역 벌크 동기화 (수동 실행용, cron 등록 불필요)
#    cd /web/light_sync && venv/bin/flask sync-g2b --mode bulk --start-year 2012
```

## Flask CLI 명령어

```bash
# 프로젝트 디렉토리에서 실행
cd /web/light_sync

# 일일 동기화 (전일 데이터)
venv/bin/flask sync-g2b

# 벌크 동기화 (전체)
venv/bin/flask sync-g2b --mode bulk

# 특정 연도부터 벌크
venv/bin/flask sync-g2b --mode bulk --start-year 2020
```

## 로그 확인

```bash
# 동기화 로그
tail -f /web/light_sync/logs/g2b_cron.log

# Flask 앱 로그
tail -f /web/light_sync/logs/light_sync.log
```

## 로그 로테이션 (선택)

```bash
# /etc/logrotate.d/light-sync
/web/light_sync/logs/g2b_cron.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}
```
