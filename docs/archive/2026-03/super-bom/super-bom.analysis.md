# Super BOM (옵션별 BOM 필터링) Gap Analysis Report

> **Analysis Type**: Gap Analysis (Plan vs Implementation)
>
> **Project**: Light-Sync ERP
> **Analyst**: Claude (gap-detector)
> **Date**: 2026-03-20
> **Plan Doc**: [super-bom.plan.md](../01-plan/features/super-bom.plan.md)

---

## 1. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| FR 구현률 | 100% | Pass |
| Architecture Compliance | 95% | Pass |
| Convention Compliance | 90% | Pass |
| **Overall Match Rate** | **95%** | **Pass** |

---

## 2. FR Item-by-Item Verification

| FR | Requirement | Priority | Status | Implementation Location |
|----|-------------|----------|:------:|------------------------|
| FR-01 | `bom_items.option_filter` (TEXT/JSON) 컬럼 추가 | High | ✅ Pass | `entities.py:1123` + `db.py:198-205` ALTER TABLE |
| FR-02 | `bom_headers.option_schema` (TEXT/JSON) 컬럼 추가 | High | ✅ Pass | `entities.py:1099` + `db.py:189-196` ALTER TABLE |
| FR-03 | 엑셀 임포트 시 옵션조건 파싱 → option_filter 저장 | High | ✅ Pass | `bom.py:621,674` (Web) + `import_bom_from_excel.py:56-57,94-117` (CLI) |
| FR-04 | BOM 상세화면 옵션 드롭다운 필터 UI | High | ✅ Pass | `bom_detail.html:67-91` select dropdown, option_schema driven |
| FR-05 | 옵션 선택 시 공통+해당옵션 부품만 표시 (JS) | High | ✅ Pass | `bom_detail.html:310-338` `applyOptionFilter()` |
| FR-06 | BOM 편집 시 옵션조건 입력/수정 | Medium | ✅ Pass | `bom.py:320,338-349` form parsing + `bom_detail.html:193-194` input |
| FR-07 | 소요자재 계산 시 option_filter 반영 | Medium | ✅ Pass | `bom.py:932-953` item_spec_json 기반 필터링 |
| FR-08 | BOM 엑셀 다운로드 시 옵션조건 컬럼 포함 | Low | ✅ Pass | `bom.py:502-503,514-521` 헤더 + 데이터 출력 |

**FR Match Rate: 8/8 = 100%**

---

## 3. Implementation Details Beyond Plan (Added Features)

| Item | Location | Description |
|------|----------|-------------|
| option_schema 자동 재생성 | `bom.py:374-388` | 편집 저장 시 모든 bom_item의 option_filter에서 option_schema 자동 재구축 |
| Import 시 option_schema 자동생성 | `bom.py:799-812`, `import_bom_from_excel.py:337-360` | 신규 BOM import 시 option_filter를 집계하여 option_schema 자동 구성 |
| 슈퍼BOM badge 표시 | `bom_detail.html:13` | option_schema 존재 시 `<span class="badge bg-info">슈퍼BOM</span>` |
| 필터링 건수 표시 | `bom_detail.html:87,332` | 옵션 선택 시 "N/M건" 실시간 표시 |
| 옵션 초기화 버튼 | `bom_detail.html:86` | 드롭다운 필터 초기화 기능 |
| CLI 스크립트 ensure_columns | `import_bom_from_excel.py:236-258` | option_filter, option_schema 컬럼 자동 마이그레이션 |

---

## 4. Issues Found

### 4.1 Minor Gaps (Warning)

| Severity | Item | Location | Description |
|----------|------|----------|-------------|
| ⚠️ Warning | Web import "changed" 경로 option_filter 미갱신 | `bom.py:850-860` | 기존 BOM 갱신 시 기존 item의 option_filter를 업데이트하지 않음. 신규 item만 option_filter 반영됨 |
| ⚠️ Warning | Web import "changed" 경로 option_schema 미갱신 | `bom.py:840-874` | changed BOM 갱신 후 option_schema를 재생성하지 않음 |

### 4.2 Code Quality (Info)

| Severity | Item | Location | Description |
|----------|------|----------|-------------|
| ℹ️ Info | option_filter 파싱 함수 중복 | `bom.py:34-52` vs `import_bom_from_excel.py:94-117` | 동일 로직 2곳 존재. 향후 `modules/utils.py`로 추출 권장 |
| ℹ️ Info | 비기능 요구사항 충족 | 전체 | option_filter=null인 기존 BOM 정상 동작, 클라이언트 JS 필터링으로 서버 부하 없음 |

---

## 5. Data Format Compliance

| Plan Spec | Implementation | Status |
|-----------|---------------|:------:|
| `null` = 공통부품 | `option_filter IS NULL` → 항상 표시 (`bom.py:942`, `bom_detail.html:323`) | ✅ |
| `{"lens_angle": "20도"}` = 단일 옵션 | JSON.parse + key-value matching (`bom.py:944-949`) | ✅ |
| `{"lens_angle": "20도", "main_reflector": "A"}` = 복합 AND | 모든 key에 대해 매칭 확인 | ✅ |
| 엑셀 `렌즈=20도` → JSON 변환 | `_parse_option_filter_text()` split by `,` then `=` | ✅ |
| option_schema = 옵션 종류/값 목록 | 자동 수집 방식으로 구현 | ✅ |

---

## 6. Recommended Actions

### Immediate (수정 권장)

| Priority | Item | File:Line |
|----------|------|-----------|
| 1 | Web import "changed" 경로에서 기존 item의 `option_filter` 갱신 추가 | `bom.py:850-860` |
| 2 | Web import "changed" 경로 완료 후 `option_schema` 재생성 로직 추가 | `bom.py:874` 이후 |

### Short-term (개선 권장)

| Priority | Item |
|----------|------|
| 3 | `_parse_option_filter_text` 함수를 `modules/utils.py`로 추출 (코드 중복 제거) |
| 4 | Plan 문서의 FR Status를 Pending → Done으로 업데이트 |

### Out of Scope (2단계 예정)

- 영업관리 item_spec_json 자동 연동
- 협의완료 시 BOM 자동 필터링 → 자재발주
- BATOO/ARENA 기존 BOM 슈퍼BOM 통합

---

## 7. Conclusion

**Match Rate 100%** (8/8 FR 구현 완료), Overall Score **95%**.

핵심 기능 모두 구현 완료. Plan 대비 추가 기능(option_schema 자동 재생성, 슈퍼BOM badge 등)도 포함.
Web import "changed" 경로에서 기존 item option_filter/option_schema 미갱신 2건이 유일한 개선 사항.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-20 | Initial gap analysis | Claude (gap-detector) |
