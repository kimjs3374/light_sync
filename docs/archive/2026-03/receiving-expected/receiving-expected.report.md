# 입고예정 관리 v2 — Completion Report

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| Problem | 입고예정이 MaterialOrder(자재관리) 기반이라 계약 연결 없는 발주서는 아예 안 보임. 검수 프로세스가 구현 없이 상태값만 존재 |
| Solution | PurchaseOrderItem 직접 조회로 전환하여 모든 발주서 품목 표시. 불필요한 검수 상태 전면 제거. 디자인 po_list 기준 통일 |
| Function UX Effect | 발주서 발송하면 즉시 입고예정에 표시, 예정일 인라인 편집, D-Day/납기위험 한눈에 파악 |
| Core Value | 데이터 소스를 발주서 품목으로 일원화 → 계약 유무 관계없이 전체 입고 추적 가능 |

---

## 1. Overview

| 항목 | 내용 |
|------|------|
| Feature | receiving-expected (입고예정 관리 v2) |
| Duration | 2026-03-20 (1 session) |
| Match Rate | N/A (설계 대비 구현 방식 자체를 변경) |
| Iterations | 3 (MaterialOrder→PurchaseOrderItem 전환, NULL 처리, 미지정 표시) |

---

## 2. Design vs Implementation Deviation

설계 문서는 `MaterialOrder` 기반이었으나, 실제 구현 시 **근본적 아키텍처 변경** 결정:

| 항목 | Design (v2) | 실제 구현 |
|------|-------------|-----------|
| 데이터 소스 | MaterialOrder | **PurchaseOrderItem** (직접 조회) |
| 표시 범위 | 계약 연결 발주만 | **모든 발주서** (계약 무관) |
| 새 컬럼 | 없음 | PurchaseOrderItem에 `expected_in_date`, `in_confirmed`, `in_confirmed_at` 추가 |
| 검수 프로세스 | 유지 | **전면 제거** (검수대기/완료/반품 상태, 상태변경 라우트, 통계) |
| 디자인 스타일 | 기존 유지 | **po_list.html 기준 통일** (stat-card, rcv-table, filter-bar, badge-status) |

**변경 사유**: MaterialOrder는 계약 연결된 발주서만 생성되므로, 계약 없는 발주서(실제 업무 대부분)가 입고예정에 아예 안 나타남.

---

## 3. Changes Summary

### 3.1 Model (entities.py)

| 변경 | 내용 |
|------|------|
| PurchaseOrderItem | `expected_in_date DATE`, `in_confirmed BOOLEAN`, `in_confirmed_at DATETIME` 3개 컬럼 추가 |

### 3.2 Routes

| 파일 | 변경 |
|------|------|
| routes/receiving.py | 입고예정 쿼리 MaterialOrder→PurchaseOrderItem 전환. AJAX 엔드포인트 2개 PurchaseOrderItem 기준으로 변경. 검수 상태변경 라우트 삭제. 검수 통계/필터 제거 |
| routes/dashboard.py | dash_expected 통계를 PurchaseOrderItem 기반으로 변경 |
| modules/production_display_utils.py | build_material_ticker를 PurchaseOrderItem 기반으로 변경. 현장명 계약 경유 fallback 추가 |

### 3.3 Templates

| 파일 | 변경 |
|------|------|
| receiving_list.html | 전면 재작성 — po_list.html 디자인 통일 (stat-card-rcv, rcv-table, filter-bar, badge-status, expected-badge). 검수 뱃지/상태 드롭다운 제거. 통계 카드를 전체입고/입고예정/지연/예정일미정으로 변경 |
| receiving_detail.html | 검수 상태 뱃지 제거, 상태변경 버튼 제거, 삭제 제한 제거 |
| production_display.html | 티커 현장명 없으면 거래처만 표시 (빈 화살표 방지) |

### 3.4 Migration

| 파일 | 변경 |
|------|------|
| modules/models/db.py | SQLite purchase_order_items 3컬럼 자동 마이그레이션 추가 |
| sql_editer.sql | PostgreSQL ALTER TABLE 3줄 추가 |

---

## 4. Key Decisions

1. **MaterialOrder → PurchaseOrderItem 전환**: 계약 없는 발주서도 입고예정에 표시하기 위한 필수 변경. MaterialOrder 동기화는 유지 (기존 자재관리 기능 호환)
2. **검수 프로세스 제거**: 상태값만 있고 실제 검수 로직이 없었으므로 의미 없는 코드 정리
3. **in_confirmed NULL 처리**: 기존 행은 새 컬럼이 NULL이므로 `== False OR IS NULL` 조건 필수
4. **현장명 계약 경유 fallback**: PO에 project_id 없어도 contract→project 경로로 현장명 표시

---

## 5. Remaining Items

- 서버 PostgreSQL에 ALTER TABLE 실행 필요
- 입고예정 탭에 현장/거래처 필터 추가 가능 (현재 D-Day 상태 필터만)
