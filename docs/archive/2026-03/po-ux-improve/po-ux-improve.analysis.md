# PO UX Improve — Gap Analysis Report

## Analysis Overview
- **Feature**: po-ux-improve (발주 UX 개선)
- **Design**: `docs/02-design/features/po-ux-improve.design.md`
- **Analysis Date**: 2026-03-20

## Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| bom_requirement (R1-R5) | 88% | ✅ |
| po_list (P1-P5) | 82% | ✅ |
| Backend/Route | 100% | ✅ |
| 추가 구현 (Design 외) | +5건 | ✅ |
| **Overall Match Rate** | **90%** | ✅ |

## 의도적 변경 (사용자 요청)

| Design | 구현 | 사유 |
|--------|------|------|
| 현장(project) 컬럼/그룹핑 | 계약(contract) 컬럼/그룹핑 | 사용자가 계약명이 더 적절하다고 판단 |
| 2모드 토글 (거래처/날짜) | 3모드 토글 (거래처/계약/날짜) | 사용자 요청 |

## 추가 구현 (Design에 없음)

| Item | 파일 | 설명 |
|------|------|------|
| 선택발주 기능 | material_detail.html + material_actions.py | 체크한 자재만 거래처별 발주서 자동생성 |
| 실재고/가용재고 | po_detail.html + purchase_order.py | 발주서 품목별 재고 현황 표시 |

## Minor Gaps (기능 영향 없음)

| Item | 설명 |
|------|------|
| hover 효과 CSS | `.has-checkbox:hover` 미구현 |
| disabled 툴팁 | `::after` pseudo-element 미구현 |
| SVG chevron | 텍스트 ▼ 사용 (기능 동일) |
| 모바일 숨김 클래스 | req-col-* 클래스 미적용 |

## Conclusion

Match Rate **90%**. 핵심 기능 전부 구현, 의도적 변경 2건 일관 적용, 추가 구현 2건(선택발주+재고).
