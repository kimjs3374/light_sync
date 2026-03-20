# Super BOM (옵션별 BOM 필터링) Planning Document

> **Summary**: 하나의 BOM에 모든 옵션 부품을 포함하고, 옵션 선택 시 해당 부품만 필터링하는 슈퍼BOM 시스템
>
> **Project**: Light-Sync ERP
> **Author**: ENG
> **Date**: 2026-03-19
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | STA 모델처럼 옵션 조합(렌즈3종 x 반사판3종 = 9가지)이 많은 제품은 BOM을 조합별로 만들면 관리 불가 |
| **Solution** | 하나의 BOM에 모든 부품을 넣고, 각 부품에 옵션조건(option_filter) 태그를 달아 필터링 |
| **Function/UX Effect** | BOM 상세화면에서 옵션 선택 → 해당 부품만 표시, 엑셀 임포트 시 옵션조건 컬럼 자동 파싱 |
| **Core Value** | BOM 1개로 N개 옵션조합 커버 → 담당자 관리부담 대폭 감소, 영업협의 연동 기반 마련 |

---

## 1. Overview

### 1.1 Purpose

제품 옵션(렌즈각도, 반사판 종류 등)에 따라 BOM 구성이 달라지는 경우,
하나의 슈퍼BOM으로 모든 옵션 부품을 관리하고 옵션 선택 시 필터링하는 시스템 구축.

### 1.2 Background

- STA 모델: 렌즈각도 3종(20도/30도/60도) x 메인반사판 3종(A/B/C) = 9가지 조합
- 현재 STA-400 BOM에 이미 20도/30도 렌즈가 같이 들어있음 (담당자가 이미 슈퍼BOM 개념으로 작성중)
- BATOO/ARENA는 옵션별 별도 BOM (BATOO-400-020, BATOO-400-030 ...) → 향후 통합 가능
- 담당자가 엑셀로 BOM 재작성 중 → 완성 후 --reset --commit으로 갈아엎기 예정
- 2단계로 영업관리(item_spec_json) 연동 예정

### 1.3 Related Documents

- BOM 엑셀: `reference/제품 및 자재LIST(BOM+인건비).xlsx`
- 임포트 스크립트: `scripts/import_bom_from_excel.py`

---

## 2. Scope

### 2.1 In Scope (1단계 - 현재)

- [x] DB 컬럼 추가: `bom_items.option_filter`, `bom_headers.option_schema`
- [x] Entity 모델 업데이트
- [x] 엑셀 임포트 스크립트에 옵션조건 컬럼 파싱 추가
- [x] 웹 BOM 임포트(/bom/import)에 옵션조건 파싱 추가
- [x] BOM 상세화면에 옵션 필터 드롭다운 UI
- [x] BOM 편집 시 옵션조건 입력/수정 지원
- [x] 소요자재 계산 시 옵션 필터 적용

### 2.2 Out of Scope (2단계 - 나중)

- 영업관리 item_spec_json과 자동 연동
- 협의완료 시 BOM 자동 필터링 → 자재발주
- BATOO/ARENA 기존 BOM을 슈퍼BOM으로 통합

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | bom_items에 option_filter(TEXT/JSON) 컬럼 추가 | High | Pending |
| FR-02 | bom_headers에 option_schema(TEXT/JSON) 컬럼 추가 | High | Pending |
| FR-03 | 엑셀 임포트 시 "옵션조건" 컬럼 파싱 → option_filter 저장 | High | Pending |
| FR-04 | BOM 상세화면에 옵션 드롭다운 필터 UI | High | Pending |
| FR-05 | 옵션 선택 시 공통부품 + 해당옵션 부품만 표시 (JS 필터) | High | Pending |
| FR-06 | BOM 편집 시 각 부품의 옵션조건 입력/수정 | Medium | Pending |
| FR-07 | 소요자재 계산 시 option_filter 반영 | Medium | Pending |
| FR-08 | BOM 엑셀 다운로드 시 옵션조건 컬럼 포함 | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria |
|----------|----------|
| 호환성 | 옵션 없는 기존 BOM은 그대로 동작 (option_filter=null → 공통) |
| 성능 | 옵션 필터링은 클라이언트 JS로 처리 (서버 부하 없음) |

---

## 4. Data Design

### 4.1 option_filter 형식

```json
// null → 공통부품 (모든 옵션에 포함)
null

// 단일 옵션 조건
{"lens_angle": "20도"}

// 복합 옵션 조건 (AND)
{"lens_angle": "20도", "main_reflector": "A"}
```

### 4.2 option_schema 형식 (bom_headers)

```json
// 이 BOM이 지원하는 옵션 종류와 값 목록
{
  "lens_angle": ["20도", "30도", "60도"],
  "main_reflector": ["A", "B", "C"]
}
// null이면 옵션 없는 일반 BOM
```

### 4.3 엑셀 옵션조건 컬럼 형식

```
빈칸          → null (공통)
렌즈=20도     → {"lens_angle": "20도"}
반사판=A      → {"main_reflector": "A"}
렌즈=20도,반사판=A → {"lens_angle": "20도", "main_reflector": "A"}
```

---

## 5. Implementation Order

1. **DB**: ALTER TABLE + Entity 모델 (entities.py, db.py)
2. **Import**: import_bom_from_excel.py 수정
3. **Web Import**: routes/bom.py bom_import() 수정
4. **Detail UI**: bom_detail.html 옵션 필터 UI
5. **Edit**: bom_edit() 옵션조건 저장
6. **Requirement**: material_requirement() 옵션 필터 적용
7. **Export**: bom_export() 옵션조건 컬럼 추가

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-19 | Initial draft | ENG |
