# item-management Planning Document

> **Summary**: iCUBE SITEM에서 마이그레이션된 품목 데이터에 분류 체계를 추가하고, 품목 CRUD 관리 페이지 구현
>
> **Project**: Light-Sync ERP
> **Version**: 1.0
> **Author**: Claude (PDCA)
> **Date**: 2026-03-18
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | iCUBE에서 마이그레이션된 품목 데이터(SITEM)가 품번·품명·규격으로 분리되어 있으나, 분류 체계(카테고리)가 없어 품목 검색·관리가 어렵고, 전용 관리 화면이 없어 발주서 작성 시 품목 검색으로만 활용되고 있음. |
| **Solution** | Item 모델에 category(분류), manufacturer(제조사), note(비고) 필드를 추가하고, 품목 목록/상세/수정/신규등록 CRUD 페이지를 구현. BOM 엑셀의 분류 체계(드라이버, 하우징, LED모듈, PCB 등)를 반영. |
| **기능/UX 효과** | 카테고리별 품목 필터링, 품번·품명·규격 통합 검색, 품목 신규 등록/수정, 기존 자동완성 기반 카테고리 입력으로 일관성 유지. |
| **핵심 가치** | 품목 마스터 데이터를 체계적으로 관리하여 발주서 작성·BOM 매칭·입고 확인의 정확도 향상. 제조사/분류별 품목 파악으로 구매 의사결정 지원. |

---

## 1. Overview

### 1.1 Purpose

iCUBE SITEM 테이블에서 마이그레이션된 품목 마스터 데이터를 분류 체계와 함께 관리할 수 있는 전용 페이지를 구현한다.

### 1.2 Background

- 현재 Item 모델: `icube_item_cd`(품번), `item_name`(품명), `item_spec`(규격), `unit`(단위)
- BOM 엑셀 기준 제품군: SLA, SLC, ML, TL, BATOO, MT-FL, ARENA, STA, 보안타워, 폴대 등
- BOM 내 부품 분류: 배선, 드라이버, 하우징, LED모듈, PCB, SPD, 커넥터, 유리, 방열판 등
- 품목은 발주서 작성 시 검색용으로만 사용되고 있어 전용 관리 화면이 필요

### 1.3 Scope

| 항목 | 포함 여부 |
|------|-----------|
| Item 모델 확장 (category, manufacturer, note) | O |
| 품목 CRUD 페이지 (목록/상세/수정/등록) | O |
| 카테고리별 필터링 | O |
| 통합 검색 (품번/품명/규격/제조사) | O |
| 기존 발주서/BOM 품목 검색과 연동 | O |
| 거래처별 단가 이력 연동 | X (추후) |
| 재고 수량 관리 | X (추후) |

---

## 2. Requirements

### 2.1 Functional Requirements

| ID | 요구사항 | 우선순위 |
|----|---------|---------|
| FR-01 | Item 모델에 category, manufacturer, note 필드 추가 | P0 |
| FR-02 | 품목 목록 페이지 (페이지네이션, 검색, 카테고리 필터) | P0 |
| FR-03 | 품목 상세/수정 페이지 | P0 |
| FR-04 | 품목 신규 등록 페이지 | P0 |
| FR-05 | 품목 비활성화 (삭제 대신) | P1 |
| FR-06 | 카테고리 자동완성 (기존 값 기반) | P1 |

### 2.2 Non-Functional Requirements

- 기존 프로젝트 패턴(Flask Blueprint, Jinja2, Bootstrap 5) 준수
- 사이드바 관리부 메뉴에 "품목관리" 추가
- 모바일 반응형 지원 (기존 base.html 패턴)

---

## 3. Implementation Items

| # | 작업 | 파일 |
|---|------|------|
| 1 | Item 모델 확장 | `modules/models/entities.py` |
| 2 | 품목관리 라우트 | `routes/item.py` |
| 3 | 품목 목록 템플릿 | `templates/item_list.html` |
| 4 | 품목 상세 템플릿 | `templates/item_detail.html` |
| 5 | 품목 등록 템플릿 | `templates/item_create.html` |
| 6 | Blueprint 등록 + 네비 추가 | `app.py`, `templates/base.html` |
| 7 | DB 마이그레이션 (ALTER TABLE) | `alembic` 또는 수동 |

---

## 4. Risks

| 리스크 | 대응 |
|--------|------|
| 기존 품목 데이터에 category 없음 | nullable로 추가, 점진적 분류 |
| 발주서/BOM 검색 API 변경 영향 | 기존 API는 그대로 유지, 별도 라우트 |
