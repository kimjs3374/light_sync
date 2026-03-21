# G2B 업무플로우 통합 완료 보고서

> **Summary**: G2B 조달내역을 기준으로 ERP 전체 업무 흐름(계약→납품→수금→하자보증)을 통합 구축
>
> **Author**: 사용자
> **Created**: 2026-03-21
> **Status**: Completed
> **Match Rate**: N/A (PDCA 없이 직접 구현)

---

## Executive Summary

### 1.1 개요

- **Feature**: G2B 업무플로우 통합 (g2b-workflow-integration)
- **Duration**: 2026-03-21 (1일)
- **Scope**: G2B 조달내역 기반 계약 자동 생성, 세금계산서 매칭, 하자보증 자동화, 아카이브 이관, 리팩토링

### 1.2 Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | ERP에 계약 이후 흐름(수금/하자보증)이 없고, G2B 조달내역 1,326건과 세금계산서 2,360건이 연결되지 않아 수금 추적 불가 |
| **Solution** | G2B 조달내역 자동 동기화 → 계약 생성 → 세금계산서 DB 대조 매칭 → 입금완료 시 하자보증 자동 생성 → 과거 워크보드 이력 연결 |
| **Function/UX Effect** | 미청구/잔금미청구 탭에서 수금 추적, 승인번호 직접 매칭, 예외처리, 년도별 매출 추이 대시보드 |
| **Core Value** | `contract.payment_status` 단일 기준으로 6개 관리 화면 완료건 자동 필터링, 과거 10년 조달 이력 ERP 통합 |

---

## 2. 구현 내역

### 2.1 G2B → 계약 자동 동기화

| 항목 | 수량 |
|------|------|
| G2B 조달내역 → 프로젝트+계약 생성 | 1,253건 |
| 상세품목 자동 매칭 (조달 기준 11종) | 100% |
| 취소 계약 자동 제외 (합산 0원) | 73건 |
| 변경계약 처리 | 3건 |

**파일**: `modules/services/g2b_contract_sync.py`

### 2.2 세금계산서 매칭

| 항목 | 수량 |
|------|------|
| 자동매칭 (G2B 번호) | 1,321건 |
| 수동매칭 | 27건 |
| 미매칭 (민수 거래) | 1,012건 |

**핵심 로직**: `find_g2b_no_from_remark()` — 비고 텍스트의 모든 토큰을 G2B DB와 대조 (정규식 파싱 → DB 대조로 전환)

**매칭 UI**:
- 미청구 계약 탭: 계약 기준으로 세금계산서 후보 추천 (상위 5건)
- 조달 세금계산서 검색: 미매칭 전체에서 키워드 검색
- 승인번호 직접 매칭: 조회 + 매칭 상태 확인 + 강제 매칭
- 모달 내 매칭 시 페이지 새로고침 없이 계속 작업 가능

**파일**: `routes/financial.py`, `modules/services/tax_invoice_import.py`

### 2.3 수금 관리

**payment_status 단계**:
1. `미청구` — 납품 전/세금계산서 미발행
2. `부분입금` — 세금계산서 일부 매칭 (선금)
3. `입금완료` — 전액 매칭 → 완료 + 하자보증 생성
4. `변경완료` — 변경계약으로 대체
5. `취소` — 계약 취소

**세금계산서 목록 탭**: 매칭완료 / 미청구 / 잔금미청구 / 전체

### 2.4 하자보증 자동화

| 항목 | 수량 |
|------|------|
| 자동 생성 | 1,208건 |
| 우수제품 (3년) | G2B exclc_prodct_yn='Y' |
| 혁신제품 (3년) | cntrct_mthd_nm에 '혁신' 포함 |
| 일반 (1년) | 나머지 |

**시작일**: 세금계산서 발행일 (입금완료일)

### 2.5 아카이브 이관

| 항목 | 수량 |
|------|------|
| 워크보드 현장관리 게시글 | 417건 |
| A/S 게시글 | 140건 |
| 댓글 | 845건 |
| 계약 매칭률 | 96.9% (404/417) |

**MCP Tool**: `search_archive`, `get_archive_post_detail`

### 2.6 리팩토링

**Before**: `project.status = '납품완료'`를 수동 설정 → 6개 화면에서 필터
**After**: `contract.payment_status` 기반 `active_contract_filter()` 공통 함수

**적용 화면**: 계약관리, 영업관리, 납품관리, 자재관리, 생산관리, 전사현황판

**파일**: `modules/contract_filters.py`

### 2.7 매출 대시보드

- 년도별 조달매출 추이 그래프 (막대+꺾은선)
- 탭 분리: 매출 추이 / 상세 분석

### 2.8 기타

- 인증서 만료 관리 (`certifications`)
- iCal 연차 동기화 DTEND exclusive 버그 수정
- 상세품목 조달 기준 명칭 통일 (11종)

---

## 3. 파일 변경 목록

### 신규 파일
| 파일 | 용도 |
|------|------|
| `modules/contract_filters.py` | 완료건 필터 공통 함수 |
| `modules/services/g2b_contract_sync.py` | G2B → 계약 동기화 |
| `modules/services/warranty_auto.py` | 하자보증 자동 생성 |
| `routes/certification.py` | 인증서 관리 라우트 |
| `templates/certification_list.html` | 인증서 목록 |
| `templates/certification_form.html` | 인증서 등록/수정 |
| `light_sync_mcp/tools/archive.py` | MCP 아카이브 검색 |
| `.claude/magnatech_workflow.md` | 업무 워크플로우 |
| `.claude/chatbot_mcp_design.md` | 챗봇 MCP 설계 |

### 주요 수정 파일
| 파일 | 변경 내용 |
|------|----------|
| `routes/financial.py` | 세금계산서 매칭 UI, 수금 관리, 매출 대시보드 |
| `routes/project.py` | 계약관리 필터, 설계관리 G2B 제외 |
| `routes/sales.py` | 영업관리 필터 |
| `routes/delivery.py` | 납품관리 필터 |
| `routes/material.py` | 자재관리 필터 |
| `routes/production.py` | 생산관리 필터 |
| `routes/api.py` | G2B 동기화 API, 재매칭 API |
| `modules/models/constants.py` | 상세품목 조달 기준 통일 |
| `modules/models/contract_entities.py` | project_id nullable |
| `modules/models/misc_entities.py` | Certification, warranty_type |
| `modules/services/tax_invoice_import.py` | DB 대조 파싱 |
| `config.py` | 메뉴 등록, 상세품목 |
| `app.py` | Blueprint 등록 |
| `templates/tax_invoice_list.html` | 매칭 UI 전면 개편 |
| `templates/financial_dashboard.html` | 매출 추이 그래프 + 탭 |
| `templates/admin_settings.html` | G2B 동기화 탭 |

---

## 4. 업무 흐름 (최종)

```
[G2B 조달내역] ← 뿌리
      │
      ▼ 동기화
[계약관리] → [영업관리] → [자재관리] → [생산관리] → [납품관리]
                                                        │
                                                  납품 완료
                                                        │
                                                        ▼
                                            영업부: 대금청구완료
                                                        │
                                                        ▼
                                            관리부: 세금계산서 매칭
                                                        │
                                                ┌───────┴───────┐
                                                │               │
                                          입금완료          부분입금
                                                │               │
                                          각 화면 완료     잔금 추적
                                          하자보증 시작
                                                │
                                                ▼
                                            [A/S 관리]
```

**상태 기준**: `contract.payment_status` 단일 변수
**완료 판정**: `active_contract_filter()` — 모든 계약이 입금완료/변경완료/취소면 완료
