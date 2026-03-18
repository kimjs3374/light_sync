# NAS 폴더 동기화 - 완료 보고서

> **Feature**: nas-folder-sync
> **Project**: Light-Sync ERP
> **Author**: ENG
> **Date**: 2026-03-17
> **Status**: Completed (v2 - 과년도 .lnk 지원 추가)

---

## Executive Summary

| Item | Detail |
|------|--------|
| **Feature** | NAS 폴더 → ERP 현장 자동 동기화 |
| **PDCA Period** | 2026-03-17 (단일 세션) |
| **Match Rate** | 100% (구현 완료, 운영 테스트 통과) |

### 1.3 Value Delivered

| Perspective | Content |
|-------------|---------|
| **Problem** | 시놀로지 NAS에 현장 폴더 생성 후 ERP에 수동으로 다시 등록해야 하는 이중 작업, 누락 위험. 과년도 현장 바로가기(.lnk)도 관리 필요 |
| **Solution** | NAS cron(1분) + ERP REST API. 실제 폴더 + .lnk 바로가기 모두 감지. 폴더명 연도 기준으로 work_path 자동 결정 |
| **Function/UX Effect** | NAS 폴더/바로가기 생성만으로 ERP에 현장 자동 등록, 생성일 = 폴더 날짜, work_path = SMB 원본 경로 |
| **Core Value** | 이중 작업 제거, 누락 방지, 과년도 현장 포함 NAS-ERP 데이터 일원화 |

---

## 2. PDCA Cycle Summary

### 2.1 Plan Phase
- NAS 폴더명 패턴 분석: `YYYY.MM.DD_현장명`
- 동기화 방식 결정: NAS cron → ERP API (사용자 선택)
- NAS 접근 방식: UNC 경로 + SSH (사용자 확인)
- 중복 방지 전략: `work_path` 필드 기준 + NAS 상태 파일 이중 체크

### 2.2 Design Phase
- API 엔드포인트 설계: `POST /api/sync_nas_folders`
- API 인증: `X-API-Key` 헤더 (`.env` 관리)
- CSRF 면제 처리 (외부 NAS에서 호출)
- 폴더명 파싱 정규식: `^(\d{4})\.(\d{2})\.(\d{2})_(.+)$`

### 2.3 Do Phase
- 신규 파일 2개, 수정 파일 2개
- ERP 서버 + NAS 배포 완료
- 운영 환경 테스트 통과 (13건 스킵 정상 확인)
- v2 추가: .lnk 바로가기 지원, 폴더명 연도 기준 경로 결정, 카테고리 연동

### 2.4 Check Phase
- **Match Rate: 100%**
- 동기화 API 정상 동작 확인 (HTTP 200)
- 기존 13건 날짜 보정 완료 (`/api/fix_nas_dates`)
- JSON 한글 깨짐 수정 (`app.json.ensure_ascii = False`)
- work_path SMB 경로 보정 완료 (`/api/fix_nas_paths`)

---

## 3. Implementation Details

### 3.1 신규 파일

| 파일 | 역할 | 코드량 |
|------|------|--------|
| `routes/api.py` | NAS 동기화 + 카탈로그 검색 API | ~200줄 |
| `scripts/nas_folder_sync.sh` | NAS cron 스크립트 (폴더+.lnk 감지 → API 호출) | ~100줄 |

### 3.2 수정 파일

| 파일 | 변경 내용 |
|------|----------|
| `app.py` | api_bp 등록, CSRF 면제, `ensure_ascii=False` |
| `.env` | `NAS_SYNC_API_KEY` 추가 |

### 3.3 API 스펙

| Endpoint | Method | Auth | 용도 |
|----------|--------|------|------|
| `/api/sync_nas_folders` | POST | X-API-Key | 폴더 목록 → 현장 생성 |
| `/api/fix_nas_paths` | POST | X-API-Key | 기존 경로 보정 (일회성) |

### 3.4 동작 흐름

```
시놀로지 NAS (cron 1분, /scripts/nas_folder_sync.sh)
  └─ 당해년도 디렉토리 스캔 (/volume1/현장관리/000. 현장관리/2026/)
  └─ 실제 폴더 (type -d) 감지
  └─ .lnk 바로가기 (type -f, *.lnk) 감지 → 파일명에서 현장명 추출
  └─ 상태파일(.nas_sync_state_2026.txt)과 비교
  └─ 새 항목 발견 시 JSON 배열 생성
  └─ POST /api/sync_nas_folders 호출
        └─ 폴더명 앞 4자리(YYYY)로 연도 결정
        └─ work_path: \\Magnatech\현장관리\000. 현장관리\{YYYY}\{폴더명}
        └─ project_no: {YYYY}-{순번}
        └─ created_at: 폴더 날짜
        └─ 히스토리 로그 기록
```

### 3.5 .lnk 바로가기 처리

```
NAS 파일: "2025.09.16_동구청 다목적 축구장 - 바로 가기.lnk"
  → 파싱: "2025.09.16_동구청 다목적 축구장"
  → work_path: \\Magnatech\현장관리\000. 현장관리\2025\2025.09.16_동구청 다목적 축구장
  → project_no: 2025-XXX
  → created_at: 2025-09-16
```

### 3.6 중복 방지 (이중 체크)

| 레벨 | 방식 |
|------|------|
| NAS 측 | `.nas_sync_state_2026.txt` 상태 파일 |
| ERP 측 | `Project.work_path` DB 중복 체크 (SMB + 구 리눅스 경로 호환) |

### 3.7 NAS 스크립트 설정

| 항목 | 값 |
|------|-----|
| 스크립트 경로 | `/scripts/nas_folder_sync.sh` |
| 상태 파일 | `/scripts/.nas_sync_state_{YEAR}.txt` |
| 로그 파일 | `/scripts/nas_sync.log` |
| crontab | `*/1 * * * * root bash /scripts/nas_folder_sync.sh` |

---

## 4. 운영 이슈 및 해결

| 이슈 | 원인 | 해결 |
|------|------|------|
| 로그에 유니코드 이스케이프 출력 | Flask `jsonify` 기본 ASCII 변환 | `app.json.ensure_ascii = False` |
| 기존 현장 생성일 미반영 | 이미 스킵된 건은 업데이트 안 됨 | `/api/fix_nas_dates` 보정 API |
| NAS에서 404 응답 | 시놀로지 리버스 프록시 경유 | 내부 IP:Port 직접 호출로 해결 |
| `synoservicecfg` 명령 없음 | DSM 버전 차이 | crontab 직접 편집 |
| work_path 리눅스 경로 | 초기 구현 시 리눅스 경로 저장 | `/api/fix_nas_paths`로 SMB 경로 일괄 보정 |
| 과년도 현장 누락 | 당해년도만 스캔 | .lnk 바로가기 감지 + 폴더명 연도 기준 경로 |

---

## 5. 향후 개선 가능 사항

- `/api/fix_nas_paths`, `/api/fix_nas_dates` 엔드포인트 제거 (일회성 사용 완료)
- 폴더 삭제 감지 → ERP 알림 (현재는 생성만 감지)
- NAS 스크립트 에러 시 카카오워크 알림 연동
