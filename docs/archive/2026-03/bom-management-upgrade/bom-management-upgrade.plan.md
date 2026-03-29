# BOM 관리 업그레이드 Planning Document

> **Summary**: BOM 목록 일괄 삭제 + 엑셀 임포트(갱신/추가/변경) + 엑셀 다운로드
>
> **Project**: Light-Sync ERP
> **Date**: 2026-03-19
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | BOM 목록에서 불필요한 항목 삭제가 불편(상세 진입 후 개별 삭제만 가능), 엑셀 기반 BOM 갱신/추가 불가 |
| **Solution** | 목록 체크박스 일괄 삭제 + 엑셀 업로드 비교/적용(신규/변경/동일) + 엑셀 다운로드 |
| **Function/UX Effect** | BOM 관리 시간 90% 단축, 엑셀 양식 그대로 업로드하여 BOM 일괄 갱신 |
| **Core Value** | 현장에서 사용하는 엑셀 양식과 ERP BOM의 동기화 자동화 |

---

## 1. Overview

### 1.1 Purpose
BOM 목록에서 불필요한 BOM을 일괄 삭제하고, 기존 엑셀 양식("제품 및 자재LIST")으로 BOM을 업로드하여 기존 데이터와 비교 후 갱신/추가/변경 처리

### 1.2 Background
- 현재 BOM 삭제는 상세 페이지 진입 후 개별 삭제만 가능
- BOM 데이터가 엑셀로 관리되고 있으며, 변경 시 ERP에 수동 반영 필요
- 엑셀 양식: 시트별 제품군, Row 16+에 No/식별번호/완제품코드/품목코드/품목명/원수/부품업체/소요량/단가/재료비/비고

---

## 2. Scope

### 2.1 In Scope
- [x] FR-01: BOM 목록 체크박스 일괄 삭제
- [x] FR-02: BOM 엑셀 업로드 → 기존 비교 → 선택 적용 (신규/변경/동일)
- [x] FR-03: BOM 품목 변경 감지 (소요량/단가/부품업체 변경 시 하이라이트)
- [x] FR-04: 현재 BOM 전체 엑셀 다운로드

### 2.2 Out of Scope
- BOM 버전 이력 관리 (별도 기능)
- 엑셀 양식 자동 생성

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | BOM 목록에서 체크박스 선택 → 일괄 삭제 (confirm 필수) | High | Pending |
| FR-02 | 엑셀 업로드 시 시트별 파싱 → BomHeader(product_code) 기준 매칭 → 신규/변경/동일 구분 | High | Pending |
| FR-03 | 변경된 BOM 품목(소요량/단가/부품업체) 시각적 하이라이트 | Medium | Pending |
| FR-04 | 현재 BOM 전체 엑셀 다운로드 (BomHeader + BomItem) | Medium | Pending |

### 3.2 엑셀 양식 구조 (reference/제품 및 자재LIST)

```
시트별 구조:
- 시트명 = 제품군 (가로등기구, 보안등기구, 터널등기구, 투광등기구 등)
- Row 1~15: 완제품 모델 목록 (MT-TL-050 등)
- Row 16 (헤더): No | 식별번호 | 완제품코드 | 품목코드 | 품목명 | 원수 | 부품업체 | 소요량 | 단가 | 재료비 | 비고
- Row 17+: BOM 품목 데이터
- 완제품코드로 BomHeader.product_code 매칭
```

---

## 4. Implementation Plan

### 4.1 Backend (routes/bom.py)
1. `POST /bom/bulk-delete` — 선택된 BOM ID 일괄 삭제
2. `GET /bom/export` — 전체 BOM 엑셀 다운로드
3. `GET/POST /bom/import` — 엑셀 업로드/비교/적용

### 4.2 Frontend
1. `bom_list.html` — 체크박스 + 삭제 버튼 + 다운로드/가져오기 버튼
2. `bom_import.html` — 업로드 폼 + 비교 결과 테이블 + 적용

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 2026-03-19 | Initial draft |
