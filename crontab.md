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

# 1-2) 변경계약 감지 (매일 새벽 1시 30분)
#    - 활성 계약(미청구/부분입금)의 최소 계약일 ~ 오늘 범위 재조회
#    - 변경차수 증가 감지 시 계약 금액/품목 자동 업데이트
30 1 * * * cd /web/light_sync && venv/bin/flask sync-g2b-changes >> logs/g2b_sync.log 2>&1

# 1-3) 홈택스 매입/매출 세금계산서 수집 (매일 새벽 6시 — 백업 02시/G2B 07시와 분리)
#    - 공동인증서 무인 로그인 → 최근 10일 매입/매출 전자세금계산서 수집
#    - 매출은 G2B 계약 매칭 + 하자보증 파이프라인 연결, 매입은 저장만
#    - 중복(approval_no)은 자동 skip, 관리자설정▸홈택스 연동에서 상태 확인
0 6 * * * cd /web/light_sync && FLASK_APP=app /web/light_sync/venv/bin/flask sync-hometax-invoices >> /web/light_sync/logs/hometax.log 2>&1

# 1-4) 연차사용촉진 점검 (평일 09:10 — 알림 09:00과 분리)
#    - 입사일 기준 연차연도 시작일 기준: 1회차=시작+6개월, 2회차=시작+9개월(미지정자)
#    - 직원에게 noreply@ → username@mgnt.kr 메일 발송(사용시기 지정 요청)
#    - 인사관리 권한자 전체에게 촉진 대상자 명단 알림(ERP+Mattermost)
#    - leave_promotions UNIQUE(user,leave_year,stage)로 중복 발송 차단
#    - 미리보기(기록/발송 없음): venv/bin/flask check-leave-promotions --dry
10 9 * * 1-5 cd /web/light_sync && FLASK_APP=app /web/light_sync/venv/bin/flask check-leave-promotions >> /web/light_sync/logs/leave_promotion.log 2>&1

# 1-5) 미결재 결재문서 독촉 알림 (평일 09:00)
#    - status='pending' + 현재 차례(step status='current')인 결재자별로 묶어 알림
#    - ERP 인앱 + Mattermost DM + 카카오워크 DM (대기일수 오래된 순, 문서 링크 포함)
#    - 하루 1회 dedupe(approval.reminder:{user}:{날짜})
0 9 * * 1-5 cd /web/light_sync && FLASK_APP=app /web/light_sync/venv/bin/flask remind-pending-approvals >> /web/light_sync/logs/approval_reminder.log 2>&1

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

# 변경계약 감지 (활성 계약 대상)
venv/bin/flask sync-g2b-changes
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
