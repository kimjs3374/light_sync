# PO UX Improve Plan

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| Problem | 자재관리에서 부족자재 전체가 아닌 특정 자재만 골라서 발주하고 싶은데 UX가 불명확. 발주관리 목록에 현장명이 없어서 어느 현장 발주인지 모름, 거래처별로 묶어서 보고 싶음 |
| Solution | 자재관리 선택발주 UX 강화 (체크박스 + 부족분만 선택 가능 + 건수 표시) + 발주관리 목록에 현장 컬럼 추가 + 거래처별 그룹핑 뷰 |
| Function UX Effect | 원하는 자재만 체크해서 거래처별 발주서 자동생성. 발주 목록에서 현장·거래처 한눈에 파악 |
| Core Value | 발주 실수 방지 (불필요 자재 발주 차단) + 발주 현황 가독성 향상 |

## 1. Background

### 현재 구조

**자재관리 (bom_requirement.html)**
- 이미 체크박스 존재: `shortage > 0`인 행만 체크 가능
- 전체선택 `#checkAll` 있음
- "선택 자재 발주서 생성" 버튼 → 모달에서 거래처별 프리뷰 → 발주서 생성
- **문제**: 체크박스 UX가 미흡 — 선택 안 하면 버튼 숨김인데 직관적이지 않음

**발주관리 (po_list.html)**
- 컬럼: 발주번호|발주일|거래처|상태|공급가액|합계|발송|액션
- **현장 컬럼 없음** — `po.project` 관계는 모델에 존재하지만 미표시
- 거래처별 그룹핑 없음 — 단순 날짜 DESC 정렬

## 2. Requirements

### 2.1 자재관리 선택발주 UX 개선

| # | 요구사항 | 우선순위 |
|---|----------|---------|
| R1 | 부족량 > 0인 행만 체크박스 표시 (현재 동일 — 유지) | 필수 |
| R2 | 전체선택/해제 체크박스 동작 명확화 | 필수 |
| R3 | 선택 건수 실시간 표시 + 0건이면 버튼 비활성(disabled) | 필수 |
| R4 | 선택된 행 배경색 하이라이트 | 필수 |
| R5 | 발주서 생성 모달에서 거래처별 소계 금액 표시 | 필수 |

### 2.2 발주관리 목록 개선

| # | 요구사항 | 우선순위 |
|---|----------|---------|
| P1 | 컬럼 순서: 발주번호 \| 발주일 \| 현장 \| 거래처 \| 상태 \| 합계 \| 발송 \| 액션 | 필수 |
| P2 | 현장명 표시 (`po.project.name` 또는 `po.contract.project.name`) | 필수 |
| P3 | 거래처별 그룹핑 — 같은 거래처 연속 배치, 거래처명 헤더행 삽입 | 필수 |
| P4 | 그룹핑 토글 (거래처별 / 날짜순) — 기본: 거래처별 | 필수 |
| P5 | 공급가액 컬럼 제거 (합계만 표시) | 필수 |

## 3. Scope

### In Scope
- `templates/bom_requirement.html` — 체크박스 UX, 선택 하이라이트, 모달 소계
- `templates/po_list.html` — 현장 컬럼 추가, 거래처 그룹핑, 컬럼 재배치
- `routes/purchase_order.py` — 목록 조회 시 거래처별 정렬 옵션

### Out of Scope
- 발주서 생성 API 변경 없음 (bom.py create_po_from_requirement 그대로)
- PurchaseOrder 모델 변경 없음
- 발주 상세 페이지 변경 없음

## 4. Implementation Order

| # | 작업 | 파일 | 예상 범위 |
|---|------|------|-----------|
| 1 | bom_requirement.html 체크박스 UX 개선 (하이라이트 + 건수 + disabled) | bom_requirement.html | JS 20줄 + CSS 5줄 |
| 2 | bom_requirement.html 모달에 거래처별 소계 금액 추가 | bom_requirement.html | JS 10줄 |
| 3 | po_list.html 현장 컬럼 추가 + 공급가액 제거 | po_list.html | HTML 10줄 |
| 4 | purchase_order.py 목록 정렬 옵션 (vendor_id 기준) | purchase_order.py | 10줄 |
| 5 | po_list.html 거래처별 그룹핑 + 토글 버튼 | po_list.html | JS 30줄 + HTML 15줄 |

## 5. Risks

| 리스크 | 대응 |
|--------|------|
| po.project가 null인 발주서 (수동 생성 시) | 현장 컬럼에 '-' 표시 |
| 거래처 그룹핑 시 페이지네이션 깨짐 | 서버사이드 정렬만, 그룹 헤더는 클라이언트 JS로 삽입 |
| 기존 iCUBE 발주이력과 혼동 | 기존 이력 섹션은 변경 없음 |
