# G2B 자동 계약생성 + 설계관리 매칭 Design Document

> **Summary**: G2B 동기화 자동 계약생성 + 설계현장 병합 기술 설계
>
> **Project**: Light-Sync ERP
> **Author**: CTO Lead
> **Date**: 2026-03-18
> **Status**: Approved
> **Planning Doc**: [g2b-auto-contract.plan.md](../01-plan/features/g2b-auto-contract.plan.md)

---

## 1. Overview

### 1.1 Design Goals
- G2B 동기화 후 자동 계약 생성 로직을 기존 sync 함수에 최소한으로 추가
- 설계현장 병합 기능을 기존 contract_detail 페이지에 자연스럽게 통합
- 기존 코드 변경 최소화

### 1.2 Design Principles
- 기존 sync_daily/sync_bulk 함수는 건드리지 않고 별도 auto_create_contracts 함수 추가
- 병합 로직은 DB 트랜잭션 단위로 안전하게 처리
- 중복 방지를 위한 g2b_contract_no 기반 체크

---

## 2. Architecture

### 2.1 Component Diagram

```
flask sync-g2b CLI
    |
    v
sync_daily(db) / sync_bulk(db)   -- 기존 그대로
    |
    v
auto_create_contracts(db)         -- 신규 함수
    |
    +--> G2bProcurement 조회 (미연동건)
    +--> Project 생성 (status='G2B자동')
    +--> Contract 생성 (g2b_contract_no 연결)
    +--> ContractItem 생성 (품목별)

계약 상세 페이지
    |
    +--> "설계현장 연결" 버튼
    +--> GET /api/design-projects/search?q=... (미계약 프로젝트 검색)
    +--> POST /api/project/<id>/merge-design/<design_id> (병합 실행)
```

### 2.2 Data Flow

**자동 계약 생성:**
```
G2bProcurement (cntrct_dlvr_req_no 기준 그룹핑)
  --> 이미 Contract.g2b_contract_no로 연결된 건 제외
  --> 취소건(prdct_amt=0 AND prdct_qty=0) 제외
  --> Project 생성 (project_no=YYYY-NNN, status='G2B자동', is_contracted=True)
  --> Contract 생성 (contract_name=계약명, g2b_contract_no=계약번호)
  --> ContractItem 생성 (품목별 category, model_name, quantity)
```

**설계현장 병합:**
```
계약 Project (target) <-- 설계 Project (source)
  --> source.materials -> target.id로 project_id 변경
  --> source.contacts -> target.id로 project_id 변경
  --> source.drawings -> target.id로 project_id 변경
  --> source.history_logs -> target.id로 project_id 변경
  --> source.deliveries -> target.id로 project_id 변경
  --> source.sports_modules -> target.id로 project_id 변경
  --> source.status = '병합완료'
  --> source.is_contracted = False (유지)
```

---

## 3. API Specification

### 3.1 Endpoint List

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | /api/design-projects/search | 미계약 설계프로젝트 검색 | Required |
| POST | /api/project/{id}/merge-design/{design_id} | 설계프로젝트 병합 | Required |

### 3.2 GET /api/design-projects/search

**Request:**
```
GET /api/design-projects/search?q=검색어
```

**Response (200):**
```json
{
  "results": [
    {
      "id": 123,
      "project_no": "2026-001",
      "temp_name": "현장명",
      "status": "설계/영업",
      "material_count": 3,
      "contact_count": 2,
      "drawing_count": 1,
      "created_at": "2026-01-15"
    }
  ]
}
```

### 3.3 POST /api/project/{id}/merge-design/{design_id}

**Response (200):**
```json
{
  "ok": true,
  "merged": {
    "materials": 3,
    "contacts": 2,
    "drawings": 1,
    "history_logs": 5,
    "deliveries": 0
  },
  "design_project_no": "2026-001"
}
```

---

## 4. Implementation Guide

### 4.1 File Structure

```
modules/services/g2b_procurement_sync.py  -- auto_create_contracts() 추가
app.py                                     -- sync-g2b CLI에서 호출 추가
routes/project.py                          -- 검색 API + 병합 API 추가
templates/contract_detail.html             -- 버튼 + 모달 추가
```

### 4.2 Implementation Order

1. [x] g2b_procurement_sync.py에 auto_create_contracts(db) 함수 구현
2. [x] app.py sync-g2b CLI에서 auto_create_contracts 호출 추가
3. [x] routes/project.py에 설계프로젝트 검색 API 구현
4. [x] routes/project.py에 병합 API 구현
5. [x] contract_detail.html에 "설계현장 연결" 버튼 + 모달 UI 구현

### 4.3 Key Implementation Details

**auto_create_contracts 그룹핑 로직:**
- G2bProcurement를 cntrct_dlvr_req_no 기준으로 그룹핑
- 동일 계약번호의 여러 품목은 하나의 Contract에 여러 ContractItem으로
- 대표 정보(계약명, 계약일, 납품기한)는 그룹 첫 레코드에서 취득

**병합 시 주의사항:**
- 설계 프로젝트의 모든 자식 엔티티 FK를 일괄 UPDATE
- 병합 히스토리 로그 기록
- 설계 프로젝트 status를 '병합완료'로 변경 (삭제하지 않음)
