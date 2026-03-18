# Gap Analysis: dept-weekly-report

## Match Rate: 100%

## Plan vs Implementation Comparison

| Plan 항목 | Design 항목 | 구현 상태 | Gap |
|-----------|-------------|----------|-----|
| 영업부 보고서 기존 유지 | _weekly_sales() 추출 | OK | - |
| 생산부 보고서 신규 | report_weekly_production.html | OK | - |
| 관리부 보고서 신규 | report_weekly_management.html | OK | - |
| 접근 제어 (user_group 기준) | _resolve_dept() | OK | - |
| admin 전체 접근 + 드롭다운 | is_admin + dept select | OK | - |
| URL /report/weekly 하나 유지 | weekly_report() 분기 | OK | - |
| 생산부 - 주간 요약 (4카드) | stats dict | OK | - |
| 생산부 - 생산 공정 현황 | process_rows | OK | - |
| 생산부 - 납품 진행 현황 | delivery_rows | OK | - |
| 생산부 - AS/하자보증 현황 | warranty_rows | OK | - |
| 관리부 - 주간 요약 (4카드) | stats dict | OK | - |
| 관리부 - 자재 발주 현황 | material_rows | OK | - |
| 관리부 - 발주서 현황 + 합계 | po_rows + po_sum | OK | - |
| 관리부 - 입고 검수 현황 | receiving_rows | OK | - |
| 인쇄 page-break | page-break class | OK | - |
| 테이블 white-space:nowrap | CSS 적용 | OK | - |
| 금액 합계행 | 발주서 tfoot | OK | - |
| DB 변경 없음 | 기존 모델만 사용 | OK | - |

## Gap Count: 0 Critical, 0 Minor

## Implementation Summary

### 수정 파일
- `routes/report.py` - 전체 재작성 (부서 판별 + 3개 부서 쿼리 함수)
- `templates/report_weekly.html` - admin 부서 선택 드롭다운 추가

### 신규 파일
- `templates/report_weekly_production.html` - 생산부 보고서
- `templates/report_weekly_management.html` - 관리부 보고서
- `docs/02-design/features/dept-weekly-report.design.md` - Design 문서
