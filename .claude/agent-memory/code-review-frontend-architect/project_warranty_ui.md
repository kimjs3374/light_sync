---
name: project_warranty_ui
description: A/S 관리 UI 4개 페이지 목업 설계 — MAGNATECH 디자인 시스템 적용 (2026-03-21)
type: project
---

A/S 관리 기능 4개 페이지 HTML 목업 설계 완료.

**Why:** 보증관리·A/S 접수·케이스 추적 기능 신규 추가, 기존 warranty_list.html 존재 확인 후 업그레이드.

**How to apply:** 향후 라우트(warranty.py) 및 모델 구현 시 아래 파일 구조 참조.

## 생성/수정 파일
- `templates/warranty.html` — A/S 대시보드 (신규): KPI 4칸 + 만료임박 테이블 + 케이스 카드 + 상태/불량 바차트
- `templates/warranty_list.html` — 보증·케이스 목록 (업그레이드): page-hero + 통계 4칸 + 필터바 + 테이블
- `templates/warranty_case_create.html` — A/S 접수 폼 (신규): 4단계 표시기 + AJAX 계약검색 + 부품 동적 행
- `templates/warranty_case_detail.html` — 케이스 상세 (신규): 6단계 프로그레스 + 2컬럼 + 타임라인 로그

## 주요 컴포넌트 패턴
- `dday-badge` 클래스: dday-critical / dday-warn / dday-ok / dday-expired 4단계
- `badge-{상태}` 클래스: 접수/현장확인/부품준비/수리교체/완료/보류 인라인 소프트 배지
- `as-case-card` 클래스: 좌측 border inset hover 패턴
- `paid-hero-badge` 클래스: free(파랑)/paid(빨강) 유무상 대형 배지
- `timeline` + `tl-item` + `tl-dot`: 처리이력 타임라인
- AJAX 자동완성: `/warranty/api/contract-search?q=` 엔드포인트 필요
- 상태변경: POST `/warranty/case/<id>/update-status` 엔드포인트 필요
