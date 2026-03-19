# Production Display - Gap Analysis

> **Design Doc**: `docs/02-design/features/production-display.design.md`
> **분석일**: 2026-03-19
> **상태**: Check 완료

## Match Rate: 100%

설계 문서의 25개 항목 모두 구현 완료. 사용자 피드백 반영으로 8건의 기능 추가(scope expansion) 존재.

---

## 1. 설계 항목별 구현 대조표

| # | 설계 항목 | 구현 | 구현 위치 | 비고 |
|---|----------|:---:|----------|------|
| 1 | `production_display_utils.py` 신규 | ✅ | `modules/production_display_utils.py` | 437줄 |
| 2 | `routes/production.py` 수정 | ✅ | `routes/production.py:44-197` | display + weather 엔드포인트 |
| 3 | `production_display.html` 신규 | ✅ | `templates/production_display.html` | 1183줄 |
| 4 | `build_display_cards()` 함수 | ✅ | `utils.py:111` | 시그니처 확장: deliveries 추가 |
| 5 | 카드 데이터 구조 (20+ 필드) | ✅ | `utils.py:85-108` | status_sales, status_admin 추가 |
| 6 | 정렬 규칙 (priority→urgent→dday→id) | ✅ | `utils.py:33-39` | 설계와 동일 |
| 7 | 자재 0개 → percent=100 처리 | ✅ | `utils.py:46` | |
| 8 | 공정 미생성 시 처리 | ✅ | `utils.py:59-63` | |
| 9 | 납기일 미지정 → dday=None | ✅ | `utils.py:28-30` | |
| 10 | `build_material_ticker()` 함수 | ✅ | `utils.py:158-201` | 설계와 동일 |
| 11 | 티커 쿼리 (7일, READY 제외) | ✅ | `utils.py:160-176` | |
| 12 | 티커 데이터 구조 (6필드) | ✅ | `utils.py:192-199` | |
| 13 | `GET /production/display` 라우트 | ✅ | `routes/production.py:51` | |
| 14 | `@login_required` 데코레이터 | ✅ | `routes/production.py:52` | |
| 15 | 계약 프로젝트 joinedload 쿼리 | ✅ | `routes/production.py:60-73` | |
| 16 | base.html 미사용 (전체화면) | ✅ | `production_display.html:1` | |
| 17 | 칸반 보드 레이아웃 | ✅ | `production_display.html:695` | |
| 18 | column_meta (key/label/icon/tone) | ✅ | `routes/production.py:173-180` | |
| 19 | 자재대기 카드 (D-Day + 자재바 + 미입고) | ✅ | `production_display.html:763-785` | |
| 20 | 생산대기 카드 (자재OK + 우선순위) | ✅ | `production_display.html:787-789` | |
| 21 | 생산중 카드 (공정바 + 다음공정) | ✅ | `production_display.html:791-801` | |
| 22 | 자재 티커 footer + 스크롤 애니메이션 | ✅ | `production_display.html:845-869` | |
| 23 | 다크 테마 (#0f172a, 100vh) | ✅ | `production_display.html:12-21` | |
| 24 | D-Day 뱃지 (red≤3 / yellow≤7 / blue) | ✅ | `production_display.html:753-755` | |
| 25 | 30초 자동 갱신 | ✅ | `production_display.html:876,1179` | meta→AJAX 진화 |

---

## 2. 설계 대비 추가된 기능 (Scope Expansion) — 8건

| # | 추가 기능 | 구현 위치 | 설명 |
|---|----------|----------|------|
| A1 | 6컬럼 구조 (4→6) | utils + routes | negotiation, delivery, schedule 추가 |
| A2 | 전광판 (Billboard) | utils + html | fade 전환, 대시보드 공지 연동 |
| A3 | 날씨 API | utils + routes | `/api/weather` — wttr.in 광주, 10분 캐시, 3일 예보 |
| A4 | 카드 클릭 모달 | html | 자재/공정/납품 상세 모달 |
| A5 | 일정 컬럼 (캘린더) | utils + html | 미니 캘린더 + 다가오는 납품 리스트 |
| A6 | AJAX 부분 갱신 | routes + html | `?partial=1`, 전광판 끊김 방지 |
| A7 | 회사 브랜딩 | html | "MAGNATECH \| 전사 현황판" + LIVE |
| A8 | 테스트 모드 | routes | `?test=1` 더미 데이터 주입 |

---

## 3. 전체 점수

```
설계 항목:     25개
구현 완료:     25개 (100%)
추가 기능:      8건 (의도적 scope expansion)
미구현:         0건

Match Rate:   100%
```
