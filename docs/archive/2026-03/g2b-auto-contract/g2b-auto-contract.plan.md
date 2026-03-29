# G2B 자동 계약생성 + 설계관리 매칭 Planning Document

> **Summary**: G2B 조달동기화 시 자동 계약/프로젝트 생성 + 계약현장-설계현장 병합 기능
>
> **Project**: Light-Sync ERP
> **Author**: CTO Lead
> **Date**: 2026-03-18
> **Status**: Approved

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | G2B 조달내역 동기화 후 수작업으로 프로젝트/계약 생성 필요, 기존 설계현장과 계약현장 간 데이터 분리 |
| **Solution** | sync-g2b CLI에서 자동 Project+Contract+ContractItem 생성, 계약상세에서 설계현장 매칭/병합 |
| **Function/UX Effect** | 동기화만 돌리면 자동으로 계약관리 목록에 등장, 한 번의 클릭으로 설계 데이터 이관 |
| **Core Value** | 반복 수작업 제거로 업무 효율화, 설계-계약 데이터 일원화 |

---

## 1. Overview

### 1.1 Purpose
1. G2B 동기화 시 신규 계약건 자동으로 ERP 프로젝트/계약 생성
2. 계약 현장에서 기존 설계 프로젝트의 데이터를 병합하여 일원화

### 1.2 Background
- 현재 flask sync-g2b로 G2B 조달내역(G2bProcurement)을 DB에 저장하지만, Project/Contract는 수동 생성
- 설계 단계에서 등록한 프로젝트와 G2B 계약 체결 후 등록되는 프로젝트가 별도로 존재하여 이중관리 발생

---

## 2. Scope

### 2.1 In Scope
- [x] G2B 동기화 후 미연동 건 자동 Project+Contract+ContractItem 생성
- [x] 자동생성 Project status = 'G2B자동', project_no = YYYY-NNN 채번
- [x] 취소건(금액/수량 0) 자동 제외
- [x] 계약 상세에서 "설계현장 연결" 버튼 + 모달(검색)
- [x] 설계 프로젝트 -> 계약 프로젝트 데이터 병합(materials, contacts, drawings, history_logs, deliveries)
- [x] 병합 후 설계 프로젝트 비활성(soft delete) 처리

### 2.2 Out of Scope
- G2B API 자체 변경
- 자동생성된 계약의 자동 수정/삭제

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | sync-g2b 후 미연동 G2B 계약번호 자동 Project+Contract 생성 | High | Pending |
| FR-02 | 자동생성 Project: status='G2B자동', is_contracted=True | High | Pending |
| FR-03 | 동일 g2b_contract_no 중복 생성 방지 | High | Pending |
| FR-04 | 취소건(prdct_amt=0 AND prdct_qty=0) 제외 | Medium | Pending |
| FR-05 | 계약상세 "설계현장 연결" 버튼 + 미계약 설계프로젝트 검색 모달 | High | Pending |
| FR-06 | 설계프로젝트 자식 엔티티 project_id 일괄 변경(병합) | High | Pending |
| FR-07 | 병합 후 설계 프로젝트 비활성화 (status='병합완료') | Medium | Pending |

---

## 4. Success Criteria

### 4.1 Definition of Done
- [x] flask sync-g2b 실행 시 자동 계약 생성 동작
- [x] 이미 연동된 계약번호는 skip
- [x] 설계현장 연결/병합 기능 동작
- [x] 기존 코드 정상 동작 유지

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| G2B 계약번호 중복 매칭 | High | Low | cntrct_dlvr_req_no 기준 유니크 체크 |
| 병합 시 데이터 손실 | High | Low | 트랜잭션 처리 + 히스토리 로그 기록 |
| 자동생성 프로젝트 번호 충돌 | Medium | Low | 기존 채번 로직(YYYY-NNN) 재사용 |
