# 가공발주 Plan

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| Problem | 외주 가공발주를 구두/카톡으로 관리하여 도면 버전, 납기일, 가공비용 추적이 불가능하고, 생산관리와 연동되지 않아 가공품 입고 현황을 별도로 확인해야 함 |
| Solution | 독립 '가공발주' 메뉴를 만들어 DWG 도면 첨부 발주 + 사급/외주 구분 + 납품 추적 + 생산공정 연동 + 업체별 단가 관리를 일원화 |
| Function UX Effect | 가공발주 등록 시 DWG 파일 첨부 1회로 도면+발주 동시 관리. 가공 상태(발주→가공중→입고)가 목록에서 즉시 확인. 생산관리 공정 진행률에 자동 반영 |
| Core Value | 외주가공 전 과정을 ERP에서 추적하여 납기 지연 사전 감지 + 가공비용 분석 + 생산일정 정확도 향상 |

---

## 1. Background

### 현재 상황
- 외주 가공발주는 **구두/카톡/이메일**로 진행 — ERP에 기록 없음
- 자재관리의 `is_outsourcing` 필드로 외주 여부만 표시, 실제 가공 발주 관리는 안 됨
- 기존 발주관리(PO)는 **자재 구매** 전용 — 가공발주와 성격이 다름
  - PO: 품목+수량+단가 → PDF 발주서 → 이메일 발송
  - 가공: **DWG 도면** 보내서 가공 요청 → 납품 대기 → 입고
- 가공 완료된 부품이 입고되어야 조립 공정 시작 가능 → 생산 일정에 직결

### 기존 외주가공 상태 관리 (MaterialOrder)
```
outsourcing_status: 외주입고대기 → 외주입고 → 가공중 → 본사입고완료
```
- 자재관리 화면에서 수동 상태변경만 가능
- 언제 누구에게 발주했는지, 어떤 도면으로 발주했는지 기록 없음
- 업체별 가공 단가 이력 없음

### 가공 품목 예시
- 폴(등주) 가공 — 등주 전문업체
- PCB/LED 모듈 — SMT 업체
- 등기구(하우징) — 판금/금형 업체
- RP(반사판) — 외주 가공
- 렌즈, 브라켓 등 기타 부품

## 2. Goal
- **외주 가공발주** 전용 메뉴를 만들어 발주→납품 전 과정을 ERP에서 관리
- **DWG 도면 첨부** 기반 발주 (가공발주의 핵심)
- **사급가공 / 외주가공** 구분 관리
- **납기 추적** — 가공업체별 납기일 관리 + 지연 알림
- **생산 연동** — 입고 완료 시 생산관리 공정에 자동 반영
- **단가/비용 관리** — 업체별 가공 단가 이력 축적

## 3. Scope

### In Scope

#### A. 가공발주서 (ProcessingOrder)
- **발주번호 채번**: `FO{YYYY}-{NNN}` (Fabrication Order)
- **기본 정보**: 발주일, 가공업체(Vendor), 담당자
- **가공 유형**: 사급가공 / 외주가공 선택
- **계약/현장 연결**: 선택적 (계약 없이 재고용 가공도 가능)
- **DWG 파일 첨부**: 복수 파일 업로드 (Supabase Storage)
- **상태 관리**: 작성중 → 발주완료 → 가공중 → 입고완료 → 취소

#### B. 가공발주 품목 (ProcessingOrderItem)
- 품명, 규격, 수량, 가공단가, 금액
- 품목별 납기일 + 입고 확인
- BOM 품목 연결 (선택적)
- 가공 사양 메모 (품목별 특이사항)

#### C. 목록 화면 (/processing-orders)
- 통계 카드: 전체 / 가공중 / 입고대기 / 완료
- 필터: 상태, 업체, 가공유형(사급/외주), 기간
- 검색: 발주번호, 업체명, 품목명
- 납기 임박/지연 하이라이트 (D-3 노랑, 지연 빨강)

#### D. 상세/등록 화면
- 가공업체 선택 (기존 Vendor 활용 + 자동완성)
- DWG 파일 다중 업로드 + 미리보기(파일명 목록) + 삭제
- 품목 테이블: 동적 행 추가/삭제
- 합계금액 자동 계산
- 히스토리 로그 (append_history_log)

#### E. 생산관리 연동
- 가공발주 품목 → MaterialOrder 자동 연결 (`is_outsourcing=True`)
- 입고 확인 시 → MaterialOrder.outsourcing_status = '본사입고완료' 자동 갱신
- 생산관리 화면에서 외주가공 상태 확인 가능 (기존 기능 활용)

#### F. 단가/비용 관리
- 업체별 품목별 최근 단가 자동 기록 (VendorItem 활용)
- 가공발주 목록에서 업체별 누적 발주금액 집계
- 동일 품목 과거 단가 이력 조회 (발주서 기록 기반)

### Out of Scope (향후)
- PDF 가공발주서 출력 (1차에선 불필요, 추후 필요 시 추가)
- 이메일 자동 발송 (DWG는 직접 전달이 일반적)
- 가공업체 평가 (납기 준수율, 불량률 등)
- 모바일 최적화 (1차에선 PC 기준)

## 4. Technical Approach

### 4.1 DB 모델

#### ProcessingOrder (신규 테이블)
```
processing_orders
├── id (PK)
├── fo_no (UNIQUE)          -- FO2026-001
├── fo_date (DATE)          -- 발주일
├── vendor_id (FK→vendors)  -- 가공업체
├── processing_type         -- 사급가공 / 외주가공
├── project_id (FK, nullable) -- 현장 연결 (선택)
├── contract_id (FK, nullable) -- 계약 연결 (선택)
├── assigned_to (FK→users)  -- 담당자
├── status                  -- 작성중/발주완료/가공중/입고완료/취소
├── total_amount (FLOAT)    -- 합계금액
├── tax_amount (FLOAT)      -- 세액
├── note (TEXT)
├── created_by (FK→users)
├── created_at, updated_at
└── history_log (TEXT)      -- 히스토리 JSON
```

#### ProcessingOrderItem (신규 테이블)
```
processing_order_items
├── id (PK)
├── fo_id (FK→processing_orders)
├── item_id (FK→items, nullable)
├── item_name, item_spec
├── quantity, unit_price, amount, unit
├── delivery_date (DATE)    -- 납기일
├── in_confirmed (BOOL)     -- 입고 확인
├── in_confirmed_at (DATETIME)
├── bom_item_id (FK, nullable)
├── processing_note (TEXT)  -- 가공 사양 메모
└── material_order_id (FK→material_orders, nullable)
```

#### ProcessingOrderFile (신규 테이블)
```
processing_order_files
├── id (PK)
├── fo_id (FK→processing_orders)
├── file_name              -- 원본 파일명
├── file_path              -- Supabase Storage 경로
├── file_size (INT)
├── file_type              -- dwg/pdf/etc
├── uploaded_by (FK→users)
└── uploaded_at (DATETIME)
```

### 4.2 라우트 구조

```
routes/processing_order.py
├── GET  /processing-orders              -- 목록
├── GET  /processing-order/create        -- 등록 폼
├── POST /processing-order/create        -- 등록 처리
├── GET  /processing-order/<fo_id>       -- 상세
├── POST /processing-order/<fo_id>/edit  -- 수정
├── POST /processing-order/<fo_id>/delete -- 삭제
├── POST /processing-order/<fo_id>/status -- 상태변경
├── POST /processing-order/<fo_id>/upload -- DWG 파일 업로드
├── POST /processing-order/<fo_id>/file/<fid>/delete -- 파일 삭제
└── GET  /processing-order/<fo_id>/file/<fid>/download -- 파일 다운로드
```

### 4.3 템플릿

```
templates/
├── fo_list.html            -- 가공발주 목록
├── fo_create.html          -- 등록/수정 폼
└── fo_detail.html          -- 상세 조회
```

### 4.4 메뉴 등록

```python
# config.py MENU_REGISTRY - 관리부 섹션, 발주관리 바로 뒤
("processing_order", {"label": "가공발주", "group": "관리부", "endpoint": "processing_order.fo_list"}),
```

### 4.5 파일 저장 방식
- Supabase Storage `processing-orders/` 버킷
- 경로: `processing-orders/{fo_no}/{filename}`
- 허용 확장자: `.dwg`, `.dxf`, `.pdf`, `.jpg`, `.png`, `.zip`
- 파일 크기 제한: 50MB

## 5. Implementation Order

| # | 작업 | 예상 |
|---|------|------|
| 1 | DB 모델 + 마이그레이션 SQL | 테이블 3개 생성 |
| 2 | 라우트 기본 (목록 + 등록 + 상세) | CRUD 핵심 |
| 3 | 템플릿 (목록 + 등록폼 + 상세) | UI |
| 4 | DWG 파일 업로드/다운로드 | Supabase Storage |
| 5 | 상태 관리 + 히스토리 로그 | 상태 변경 추적 |
| 6 | 생산 연동 (MaterialOrder 연결) | 입고→생산 반영 |
| 7 | 메뉴 등록 + 권한 설정 | config.py |
| 8 | 단가 이력 + 통계 카드 | 비용 관리 |

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| DWG 파일 크기가 큰 경우 업로드 시간 | UX 저하 | 프로그레스 바 + 50MB 제한 |
| 기존 MaterialOrder와 이중 관리 | 데이터 불일치 | 가공발주 입고 시 MaterialOrder 자동 동기화 |
| Vendor 테이블에 가공업체/자재업체 혼재 | 검색 혼란 | vendor_type 필드 추가 또는 가공발주 화면에서 필터 |

## 7. Success Criteria
- [ ] 가공발주 등록 + DWG 파일 첨부 정상 동작
- [ ] 상태 변경 흐름 (작성중→발주완료→가공중→입고완료) 정상
- [ ] 입고 확인 시 MaterialOrder 자동 갱신
- [ ] 업체별 단가 이력 조회 가능
- [ ] 납기 지연 건 하이라이트 표시
