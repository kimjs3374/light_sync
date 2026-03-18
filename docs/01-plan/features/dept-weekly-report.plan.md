# Plan: 부서별 주간보고서

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | dept-weekly-report (부서별 주간보고서) |
| 작성일 | 2026-03-18 |
| 예상 규모 | Medium (라우트 1파일 수정 + 템플릿 2개 신규) |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 주간보고서가 영업부 전용이라 생산부/관리부는 수동으로 보고서 작성 |
| **Solution** | 부서별 자동 집계 주간보고서 + 접근 제한 |
| **Function UX Effect** | 부서 선택 없이 로그인 사용자 기준 자동으로 해당 부서 보고서 표시 |
| **Core Value** | 3개 부서 주간보고 자동화로 보고서 작성 시간 절감 |

---

## 1. 기능 개요

현재 영업부 전용 주간보고서(`/report/weekly`)를 부서별(영업부/생산부/관리부) 보고서 시스템으로 확장.
- 로그인 사용자의 `user_group` 기준 자동 부서 판별
- 타 부서 보고서 접근 차단 (admin은 전체 접근 가능)
- 부서별 다른 템플릿/데이터 렌더링

## 2. 구현 범위

### 2.1 라우트 수정 (`routes/report.py`)

**URL 구조 변경:**
- `/report/weekly` → 로그인 사용자의 user_group 기준 자동 라우팅
- `?dept=영업부` 파라미터로 직접 지정 가능 (admin 전용)
- 타 부서 접근 시 403 반환

**부서 판별 로직:**
```python
user_group = session.get('user_group', '')
# user_group → dept 매핑
dept_map = {
    '영업부': 'sales',
    '생산부': 'production',
    '관리부': 'admin_mgmt',
    '경영관리부': 'admin_mgmt',
}
```

**admin 권한:**
- `session.get('role') == 'admin'` → 모든 부서 보고서 접근 가능
- 부서 선택 드롭다운 표시

### 2.2 영업부 보고서 (기존 유지)
- 템플릿: `templates/report_weekly.html` (현행 유지)
- 데이터: Project + Material + Contract + ContractItem + Catalog

### 2.3 생산부 보고서 (신규)
- 템플릿: `templates/report_weekly_production.html`

| 섹션 | 데이터 | 쿼리 |
|------|--------|------|
| 1. 주간 요약 | 생산중/납품준비/납품완료/AS접수 건수 | ContractItem(status_prod) + Delivery + WarrantyCase |
| 2. 생산 공정 현황 | 현장명, 계약명, 품목, 공정명, 진행률%, 상태 | ProductionProcess (status in 대기/진행중) |
| 3. 납품 진행 현황 | 현장명, 회차, 수량, 예정일, 상태 | Delivery + DeliverySplit (status != 완료) |
| 4. AS/하자보증 현황 | 케이스번호, 현장명, 불량유형, 상태, 접수일 | WarrantyCase (status != 완료) |

### 2.4 관리부 보고서 (신규)
- 템플릿: `templates/report_weekly_management.html`

| 섹션 | 데이터 | 쿼리 |
|------|--------|------|
| 1. 주간 요약 | 발주건수/입고건수/검수대기/발주총액 | MaterialOrder + Receiving + PurchaseOrder |
| 2. 자재 발주 현황 | 현장명, 품목, 모델, 발주상태, 발주일, 예상입고일 | MaterialOrder (order_status != 입고완료) |
| 3. 발주서 현황 | PO번호, 거래처, 금액, 발송여부 + 합계 | PurchaseOrder (status != 취소) |
| 4. 입고 검수 현황 | 입고번호, 거래처, 품목, 수량, 상태 | Receiving (기간 내) |

### 2.5 접근 제어

| 사용자 그룹 | 접근 가능 보고서 |
|-------------|-----------------|
| 영업부 | 영업부 보고서만 |
| 생산부 | 생산부 보고서만 |
| 관리부/경영관리부 | 관리부 보고서만 |
| admin (role) | 전체 부서 + 부서 선택 드롭다운 |

## 3. 구현 순서

1. `routes/report.py` - 부서 판별 + 접근 제어 + 생산부/관리부 쿼리 함수 추가
2. `templates/report_weekly_production.html` - 생산부 템플릿 (영업부 스타일 동일)
3. `templates/report_weekly_management.html` - 관리부 템플릿 (영업부 스타일 동일)
4. `templates/report_weekly.html` - admin용 부서 선택 드롭다운 추가

## 4. 영향 범위

- **수정 파일**: `routes/report.py`, `templates/report_weekly.html`
- **신규 파일**: `templates/report_weekly_production.html`, `templates/report_weekly_management.html`
- **DB 변경**: 없음 (기존 모델 활용)
