# BOM Excel Import Planning Document

> **Summary**: BOM LIST 엑셀 파일을 DB로 마이그레이션하고 품목관리(items)와 연동
>
> **Project**: Light-Sync ERP
> **Author**: CTO Lead
> **Date**: 2026-03-18
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | BOM 데이터가 엑셀(16개 시트, 수백 완성품)에만 존재하여 ERP의 BOM 관리/자재소요 계산 기능이 작동하지 않음 |
| **Solution** | 엑셀 파싱 스크립트로 16개 시트를 순회하며 BomHeader/BomItem 생성, items 테이블과 품번(icube_item_cd) 매칭 |
| **Function/UX Effect** | BOM 목록에 실제 제품 데이터 표시, 제품군별 필터링, 자재소요 자동계산 정상 동작 |
| **Core Value** | 엑셀 수동관리에서 DB 기반 자동관리로 전환, 발주/입고/원가관리의 기초 데이터 확보 |

---

## 1. Overview

### 1.1 Purpose

`reference/제품 및 자재LIST(BOM+인건비).xlsx` 엑셀의 16개 시트에 있는 BOM 데이터를
DB의 `bom_headers`/`bom_items` 테이블로 마이그레이션하고, `items` 테이블과 연동한다.

### 1.2 Background

- 현재 `bom_headers`, `bom_items` 테이블은 0건 (빈 상태)
- `items` 테이블에 iCUBE SITEM 1,835건 존재 (icube_item_cd = 품번)
- BOM 목록 페이지, 자재소요 계산 기능이 데이터 없이 빈 화면
- 수동 BOM 입력은 비현실적 (수백 개 완성품 x 평균 5~15개 부품)

### 1.3 Related Documents

- 엑셀: `reference/제품 및 자재LIST(BOM+인건비).xlsx`
- 기존 모델: `modules/models/entities.py` (BomHeader, BomItem, Item)
- 기존 라우트: `routes/bom.py`

---

## 2. Scope

### 2.1 In Scope

- [x] 엑셀 파싱 스크립트 작성 (`scripts/import_bom_from_excel.py`)
- [x] BomHeader 모델에 `product_category`, `certification_no` 필드 추가
- [x] BomItem 모델에 `item_code`, `unit_price`, `amount`, `supplier` 필드 추가
- [x] items 테이블 매칭 (BomItem.item_code -> items.icube_item_cd)
- [x] items.manufacturer 업데이트 (BOM의 납품업체 정보)
- [x] BOM 목록 페이지에 제품군 필터 추가

### 2.2 Out of Scope

- 인건비 시트 처리 (BOM 자재만 대상)
- 엑셀 역방향 동기화 (DB -> 엑셀)
- BOM 버전 관리 (V1만 임포트)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 16개 시트 파싱, 시트별 헤더행 자동 감지 | High | Pending |
| FR-02 | 완성품코드별 BomHeader 생성 (중복 스킵) | High | Pending |
| FR-03 | BomItem 생성 (소요량, 단가, 금액, 납품업체) | High | Pending |
| FR-04 | BomItem.item_code -> items.icube_item_cd 매칭 | High | Pending |
| FR-05 | items.manufacturer 자동 업데이트 | Medium | Pending |
| FR-06 | BomHeader.product_category 시트명 기반 분류 | Medium | Pending |
| FR-07 | BOM 목록 페이지 제품군 필터 | Medium | Pending |
| FR-08 | 중복 실행 안전 (idempotent) | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 안정성 | 중복 실행시 데이터 무결성 유지 | product_code unique constraint |
| 성능 | 전체 임포트 30초 이내 | 스크립트 실행 시간 |

---

## 4. Data Analysis

### 4.1 엑셀 시트 구조

| Sheet Index | 시트명 | 제품군 | 헤더행 | 컬럼 구조 | 예상 완성품수 |
|:-----------:|--------|--------|:------:|-----------|:------------:|
| 0 | 실내등SLA | 실내등(SLA) | 13 | 표준 11열 | ~12 |
| 1 | 실내등SLC | 실내등(SLC) | 13 | 표준 11열 | ~12 |
| 2 | 실외등ML | 실외등(ML) | 14 | 표준 11열 | ~8 |
| 3 | 터널등TL | 터널등(TL) | 16 | 표준 11열 | ~10 |
| 4 | 투광등BATOO | 투광등(BATOO) | 26 | 표준 11열 | ~40+ |
| 5 | 투광등MT-FL | 투광등(MT-FL) | 21 | 표준 11열 | ~30 |
| 6 | 투광등ARENA | 투광등(ARENA) | 27 | 표준 11열 | ~100+ |
| 7 | 투광등 표준가 | (스킵) | N/A | 참고 데이터 | - |
| 8 | 투광등STA | 투광등(STA) | 9 | 표준 11열 | ~3 |
| 9 | 투광등STA-S | 투광등(STA-S) | 10 | 표준 11열 | ~4 |
| 10 | 보안타워 | 보안타워 | 15 | 변형(품번없음) | ~9 |
| 11 | 등대폴대 | 등대폴대 | N/A | 비표준(스킵) | - |
| 12 | 알루미늄폴대 | 알루미늄폴대 | 41 | 변형(규격포함) | ~35 |
| 13 | 철재폴대 | 철재폴대 | 19 | 변형(규격포함) | ~12 |
| 14 | 태양광보안등 | 태양광보안등 | 7 | 변형(10열) | ~1 |
| 15 | 태양광보안등(분전반) | 태양광보안등(분전반) | 41 | 변형(규격포함) | ~35 |

### 4.2 컬럼 매핑 (표준 시트)

| 엑셀 컬럼 | DB 필드 | 비고 |
|-----------|---------|------|
| No | (그룹 구분) | 새 No = 새 완성품 시작 |
| 인증번호 | BomHeader.certification_no | |
| 완성품코드 | BomHeader.product_code | unique |
| 품목코드(품번) | BomItem.item_code | -> items.icube_item_cd 매칭 |
| 품명 | BomItem.item_name | |
| 수량 | (무시, 항상 1) | 완성품 수량 |
| 납품업체 | BomItem.supplier | -> items.manufacturer |
| 소요량 | BomItem.quantity | |
| 단가 | BomItem.unit_price | |
| 금액 | BomItem.amount | |
| 비고 | BomItem.note | -> BomItem.item_spec |

### 4.3 변형 시트 처리

**보안타워(Sheet 10)**: 품목코드(품번) 컬럼 없음, 품명+규격으로 구성
- 헤더: No, 인증번호, 완성품코드, 품명, 규격, 수량, 납품업체, 소요량, 단가, 금액, 비고
- item_code = 빈 값, item_name = 품명, item_spec = 규격

**폴대류(Sheet 12, 13, 15)**: 동일 변형
- 헤더: No, 인증번호, 완성품코드, 품명, 규격, 수량, 납품업체, 소요량, 단가, 금액, 비고

**태양광보안등(Sheet 14)**: 10열 변형 (인증번호 없음)

**등대폴대(Sheet 11)**: 비표준 구조 (높이별 자재 나열), BOM 형식 아님 -> 스킵

---

## 5. Model Changes

### 5.1 BomHeader 추가 필드

```python
product_category = Column(String(50), nullable=True)   # 제품군 (실내등, 투광등 등)
certification_no = Column(String(50), nullable=True)    # 인증번호
```

### 5.2 BomItem 추가 필드

```python
item_code = Column(String(100), nullable=True)     # 품번 (items.icube_item_cd 매칭용)
item_id = Column(Integer, ForeignKey('items.id'), nullable=True)  # items FK
unit_price = Column(Float, nullable=True)           # 단가
amount = Column(Float, nullable=True)               # 금액
supplier = Column(String(200), nullable=True)        # 납품업체
```

---

## 6. Implementation Plan

### 6.1 Step 1: 모델 확장

1. BomHeader에 product_category, certification_no 추가
2. BomItem에 item_code, item_id(FK), unit_price, amount, supplier 추가
3. Alembic 마이그레이션 또는 직접 ALTER TABLE

### 6.2 Step 2: 임포트 스크립트

1. `scripts/import_bom_from_excel.py` 작성
2. 시트별 카테고리 매핑 딕셔너리
3. 헤더행 자동 감지 (첫 번째 셀 = 'No')
4. 완성품 그룹핑: No 컬럼에 숫자가 있으면 새 완성품 시작
5. items 매칭 및 manufacturer 업데이트
6. dry-run 모드 지원

### 6.3 Step 3: BOM 목록 개선

1. 제품군 필터 추가 (product_category)
2. 부품수, 총 금액 표시
3. 인증번호 표시

---

## 7. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 엑셀 인코딩 깨짐 | Low | Low | openpyxl은 UTF-8 정상 처리 |
| 헤더행 위치 다름 | Medium | High | 'No' 셀 자동 감지 |
| 품번 미매칭 | Medium | Medium | item_id nullable, 매칭률 리포트 |
| 중복 실행 데이터 오류 | High | Medium | product_code unique + upsert |
| 비표준 시트 파싱 실패 | Medium | Medium | 시트별 파싱 전략 분기 |

---

## 8. Success Criteria

### 8.1 Definition of Done

- [x] 모든 표준 시트 (14개 중 13개, 등대폴대 제외) 파싱 성공
- [x] BomHeader 생성 수 >= 100개
- [x] BomItem 생성 수 >= 500개
- [x] items 매칭률 >= 50%
- [x] BOM 목록 페이지에 데이터 정상 표시
- [x] 중복 실행시 에러 없음

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-18 | Initial draft | CTO Lead |
