## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | A/S 관리 시스템 전면 재설계 |
| 작성일 | 2026-03-21 |
| 예상 기간 | 3~4일 |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 1,253건 계약/1,206건 보증 대비 A/S 케이스 0건, 기존 A/S는 카카오워크 게시판(140건)으로 관리, 제품 생산이력 미연동, 보증기간 자동추적 미흡 |
| **Solution** | 계약→납품→대금→보증→A/S 전 주기 통합, 보증 자동 생성/만료 추적, 제품 이력카드, 대시보드, 카카오워크 A/S 이력 마이그레이션 |
| **Function UX Effect** | 보증 진행중 258건 실시간 모니터링, 만료 임박 알림, A/S 접수→완료 전 과정 추적, 제품별 BOM+생산+A/S 통합 이력 |
| **Core Value** | 1,000건+ 계약의 A/S 리스크 사전 관리, 유상/무상 판별 자동화, 반복 불량 패턴 분석 |

---

# Plan: A/S 관리 시스템 전면 재설계

## 1. 현황 분석

### 1.1 데이터 규모

| 항목 | 건수 | 비고 |
|------|------|------|
| 현장(Project) | 1,269 | 설계+계약 포함 |
| 계약(Contract) | 1,253 | 대부분 1품목, 최대 5품목 |
| 계약품목(ContractItem) | 1,504 | LED투광등 382, 가로등주 212, 가로등 142 등 |
| 납품(Delivery) | 1,253 | 계약과 1:1 |
| 세금계산서(TaxInvoice) | 2,360 | 2013~2026, 연 평균 180건 |
| 보증(Warranty) | 1,206 | 일반 887, 우수제품 319, 혁신 0 |
| 보증 진행중 | 258 | 만료일 > 오늘 |
| 보증 만료 | 948 | |
| A/S 케이스 | **0** | 시스템 미사용 |
| BOM 완성품 | 220 | 부품 3,752 |
| 생산공정 | 0 | 미사용 |
| G2B 조달 | 1,594 | 우수/혁신 판별 기준 |
| 카카오워크 A/S | 140 | as.db (워크보드 게시판) |

### 1.2 핵심 문제점

1. **A/S 케이스 0건** — 시스템이 만들어져 있지만 아무도 사용하지 않음
2. **카카오워크로 A/S 관리** — as.db에 140건의 실제 A/S 이력이 워크보드 게시판으로 관리됨
3. **보증기간 시작 기준 불명확** — 대금청구(세금계산서 발행일) 기준이어야 하는데 로직 검증 필요
4. **혁신제품 미분류** — warranty_type에 '혁신제품' 0건, G2B에서 혁신 판별 로직 누락 가능
5. **제품 이력 단절** — BOM→생산→납품→A/S가 연결되지 않음
6. **보증 만료 임박 알림 없음** — 258건 진행중 보증의 만료 추적 안됨
7. **유상/무상 판별 없음** — 보증기간 내 무상, 외 유상 구분 로직 미구현
8. **반복 불량 분석 없음** — 동일 모델/부품 반복 하자 패턴 파악 불가

### 1.3 기존 프로세스 (카카오워크)

as.db 분석 결과, 실제 A/S 관리 흐름:
```
고객 연락 → 카카오워크 A/S 게시판 글 작성
  → 담당자 @멘션 → 부품 택배 발송 → 완료 댓글
```

게시판 내용에서 파악되는 A/S 필수 정보:
- **현장명/계약명** (어디서 접수됐는지)
- **요청 품목** (SMPS, LED모듈 등 + 모델명 + 수량)
- **증상/원인** (불량 사유)
- **발송 방법** (택배/방문)
- **담당자** (처리 기술자)
- **처리 결과** (교체/수리/반품)
- **유상/무상** 여부
- **고객 연락처** (공사업체, 담당자, 전화번호)

## 2. 재설계 전략

### 2.1 핵심 원칙

> **계약 → 납품 → 대금청구 → 보증 시작 → A/S → 보증 만료** 전 주기 자동 추적
> - 대금청구 완료(세금계산서 발행일) = 보증 시작일
> - 우수제품/혁신제품 = 3년, 일반 = 1년
> - A/S 접수 시 보증기간 자동 판별 → 유상/무상 자동 표시
> - 제품별 이력카드: BOM + 생산 + 납품 + A/S 통합

### 2.2 변경 범위

| 영역 | 현재 | 변경 |
|------|------|------|
| **Warranty 모델** | 기본 구조 있음 | 만료 알림, 혁신제품 판별 강화 |
| **WarrantyCase 모델** | 기본 구조 있음 | 유상/무상 자동판별, 교체부품 상세, 비용, 고객 연락처 |
| **보증 자동생성** | warranty_auto 존재 | 혁신제품 판별 보강, 대금청구 기준 정확화 |
| **A/S 대시보드** | 없음 | 신규 (보증 현황 + 만료 임박 + A/S 통계) |
| **A/S 접수 UX** | 현재 사용 안 됨 | 계약 검색 → 자동 채움 → 1클릭 접수 |
| **제품 이력카드** | 없음 | 계약품목별 BOM+생산+납품+A/S 통합 뷰 |
| **카카오워크 마이그레이션** | as.db 140건 | WarrantyCase로 이관 (선택) |

## 3. 데이터 모델 재설계

### 3.1 Warranty 모델 — 보강

```python
class Warranty(Base):
    # 기존 유지
    id, contract_id, project_id, warranty_start, warranty_end,
    warranty_amount, warranty_type, auto_generated,
    insurance_no, insurance_returned, note, created_at, updated_at

    # 신규 추가
    contract_name = Column(String(200))    # 비정규화: 빠른 목록 조회용
    project_name = Column(String(200))     # 비정규화: 빠른 목록 조회용
    item_group = Column(String(50))        # 품목유형 (LED투광등기구 등)
    model_name = Column(String(200))       # 주요 모델명
    quantity = Column(Integer)             # 납품 수량
    site_address = Column(String(500))     # 현장 주소
    customer_contact = Column(String(200)) # 고객 연락처 (발주처 담당자)
    customer_phone = Column(String(50))    # 고객 전화번호
```

> **비정규화 이유**: 1,206건 보증을 목록으로 빠르게 조회할 때, 매번 Contract→Project JOIN 하면 느림.
> 보증 생성 시 한 번 복사해두고 목록 조회는 Warranty 테이블만으로 해결.

### 3.2 WarrantyCase 모델 — 대폭 보강

```python
class WarrantyCase(Base):
    # 기존 유지
    id, warranty_id, project_id, case_no, defect_type, symptom,
    status, reported_by, reported_date, site_visit_date,
    completed_date, cause_analysis, action_taken, replaced_parts,
    assigned_to, created_by, created_at, updated_at,
    manual_site_name, manual_contract_name, manual_model_name,
    manual_delivery_date

    # 신규 추가
    is_chargeable = Column(Boolean, default=False)    # 유상 여부 (보증 만료 시 True)
    charge_amount = Column(Integer, default=0)        # 유상 금액
    charge_status = Column(String(20))                # 청구상태: 미청구/청구완료/입금완료

    # A/S 요청 상세
    request_channel = Column(String(30))   # 접수경로: 전화/카톡/이메일/방문
    customer_name = Column(String(100))    # 고객 담당자명
    customer_phone = Column(String(50))    # 고객 전화번호
    customer_address = Column(String(500)) # 고객/현장 주소

    # 교체 부품 상세
    parts_json = Column(Text)  # JSON: [{"name":"SMPS 150W","model":"MT-SLC-150","qty":1,"unit_price":0}]

    # 물류
    shipping_method = Column(String(30))   # 발송방법: 택배/방문/직접수령
    shipping_tracking = Column(String(100)) # 송장번호
    shipping_date = Column(Date)           # 발송일

    # 제품 정보 (비정규화)
    contract_name = Column(String(200))    # 계약명
    item_group = Column(String(50))        # 품목유형
    model_name = Column(String(200))       # 모델명
```

### 3.3 하자유형 확장

```python
DEFECT_TYPES = [
    ('LED_MODULE', 'LED 모듈 불량'),
    ('SMPS', 'SMPS 고장'),
    ('HEAT', '방열 이상'),
    ('LENS', '렌즈/리플렉터 손상'),
    ('MOISTURE', '결로/침수'),
    ('CONTROL', '제어 불량'),
    ('WIRING', '배선/커넥터 불량'),
    ('BODY', '등기구 외함 손상'),
    ('POLE', '등주/타워 손상'),
    ('PAINT', '도장 박리/부식'),
    ('ANCHOR', '앵커/기초 문제'),
    ('SENSOR', '센서 오동작'),
    ('OTHER', '기타'),
]
```

### 3.4 상태 프로세스 개선

```python
CASE_STATUS_STEPS = ['접수', '현장확인', '부품준비', '수리/교체', '완료', '보류']
```

## 4. 성능 최적화 (1,000건+ 대응)

### 4.1 비정규화 전략

| 비정규화 필드 | 원본 | 목적 |
|-------------|------|------|
| Warranty.contract_name | Contract.contract_name | 목록 조회 시 JOIN 제거 |
| Warranty.project_name | Project.temp_name | 목록 조회 시 JOIN 제거 |
| Warranty.item_group | Contract.item_group | 필터링 |
| Warranty.model_name | ContractItem.model_name | 검색 |
| Warranty.site_address | Project.site_address | 표시 |
| WarrantyCase.contract_name | Contract.contract_name | 목록 조회 |
| WarrantyCase.item_group | Contract.item_group | 필터링 |
| WarrantyCase.model_name | ContractItem.model_name | 검색 |

### 4.2 인덱스 전략

```sql
-- 보증 만료 추적 (만료 임박 조회)
CREATE INDEX idx_warranty_end ON warranties(warranty_end);
-- 보증 유형별 필터
CREATE INDEX idx_warranty_type ON warranties(warranty_type);
-- A/S 케이스 상태별 조회
CREATE INDEX idx_case_status ON warranty_cases(status);
-- A/S 케이스 접수일 정렬
CREATE INDEX idx_case_reported ON warranty_cases(reported_date DESC);
```

### 4.3 쿼리 최적화

```python
# 목록 조회: Warranty 테이블만 (JOIN 없음)
warranties = db.query(Warranty).filter(...).order_by(Warranty.warranty_end.asc()).limit(50).all()

# 상세 조회: 필요 시에만 JOIN
warranty = db.query(Warranty).options(
    joinedload(Warranty.contract).joinedload(Contract.items),
    joinedload(Warranty.cases)
).get(warranty_id)
```

## 5. 기능 설계

### 5.1 A/S 대시보드 (/warranty)

```
┌─── 보증 현황 요약 ──────────────────────────────────┐
│  전체 1,206  │  진행중 258  │  만료 948  │  A/S 접수 0  │
└─────────────────────────────────────────────────────┘

┌─── 만료 임박 (30일 이내) ───────────────────────────┐
│  현장명 | 품목 | 모델 | 만료일 | D-day | [A/S접수]  │
│  ...                                                │
└─────────────────────────────────────────────────────┘

┌─── 진행중 A/S 케이스 ───────────────────────────────┐
│  AS-2026-001 | 현장 | 증상 | 상태 | 담당자 | 경과일  │
│  ...                                                │
└─────────────────────────────────────────────────────┘

┌─── 품목별 불량 통계 ────────────────────────────────┐
│  LED투광등 | SMPS 12건 | LED모듈 8건 | ...          │
│  LED가로등 | SMPS 5건 | 결로 3건 | ...              │
└─────────────────────────────────────────────────────┘
```

### 5.2 보증 목록 (/warranty/list)

- **필터**: 상태(진행중/만료/전체), 품목유형, 보증유형(일반/우수/혁신), 연도
- **검색**: 현장명, 계약명, 모델명 통합검색
- **정렬**: 만료일순(기본), 시작일순, 현장명순
- **페이지네이션**: 50건/페이지
- **일괄 처리**: 선택 보증 → 만료 체크, 보증서 출력

### 5.3 A/S 접수 (/warranty/case/create)

```
Step 1: 계약 검색 (현장명/관리번호/모델명)
  → 계약 선택 시 자동 채움: 현장, 품목, 모델, 보증기간, 유상/무상
Step 2: A/S 정보 입력
  - 하자유형, 증상, 접수경로, 고객 연락처
  - 교체 부품 (동적 행)
  - 발송 방법, 담당자 배정
Step 3: 확인 및 저장
```

### 5.4 제품 이력카드 (/warranty/<id>/product-history)

계약품목 기준으로:
- **계약 정보**: 현장명, 계약일, 납품일, 대금청구일
- **제품 사양**: 모델명, 수량, BOM (있으면)
- **생산 이력**: 공정 진행 상황 (있으면)
- **A/S 이력**: 해당 계약의 전체 A/S 케이스 타임라인
- **보증 상태**: 보증기간, 남은일수, 유상/무상

### 5.5 보증 자동생성 강화

```python
def auto_create_warranty(db, contract):
    """대금청구 완료 시 보증 자동생성"""
    if not contract.invoice_date:
        return  # 세금계산서 미발행
    if contract.warranty:
        return  # 이미 보증 존재

    # 보증유형 판별
    warranty_type = '일반'
    if contract.g2b_contract_no:
        g2b = db.query(G2bProcurement).filter_by(cntrct_no=contract.g2b_contract_no).first()
        if g2b:
            if g2b.exclc_prodct_yn == 'Y':
                warranty_type = '우수제품'
            elif '혁신' in (g2b.cntrct_mthd_nm or ''):
                warranty_type = '혁신제품'

    # 보증기간 (우수/혁신: 3년, 일반: 1년)
    years = 3 if warranty_type in ('우수제품', '혁신제품') else 1
    start = contract.invoice_date
    end = start.replace(year=start.year + years)

    # 비정규화 데이터 수집
    project = contract.project
    first_item = contract.items[0] if contract.items else None

    warranty = Warranty(
        contract_id=contract.id,
        project_id=contract.project_id,
        warranty_start=start,
        warranty_end=end,
        warranty_type=warranty_type,
        auto_generated=True,
        # 비정규화
        contract_name=contract.contract_name,
        project_name=project.temp_name if project else None,
        item_group=contract.item_group,
        model_name=first_item.model_name if first_item else None,
        quantity=sum(i.quantity or 0 for i in contract.items),
        site_address=project.site_address if project else None,
    )
    db.add(warranty)
```

## 6. 구현 순서

```
Phase 1 (Day 1): 모델 + 보증 강화
  ├─ Warranty/WarrantyCase 모델 필드 추가
  ├─ DB 마이그레이션 (ALTER TABLE)
  ├─ 기존 1,206건 보증에 비정규화 데이터 백필
  ├─ 혁신제품 판별 보강
  └─ 인덱스 추가

Phase 2 (Day 2): A/S 대시보드 + 목록
  ├─ /warranty → 대시보드 (요약 + 만료임박 + 진행중 케이스 + 통계)
  ├─ /warranty/list → 보증 목록 (필터/검색/정렬/페이지네이션)
  └─ 보증 상세 페이지 개선

Phase 3 (Day 3): A/S 접수 UX + 제품 이력
  ├─ A/S 접수 → 계약검색→자동채움→유상/무상 판별
  ├─ A/S 상세 → 상태변경+부품+물류+비용
  ├─ 제품 이력카드 (BOM+생산+납품+A/S)
  └─ 카카오워크 A/S 이력 마이그레이션 (선택)

Phase 4 (Day 4): MCP + 알림 + 검증
  ├─ MCP 도구 업데이트
  ├─ 만료 임박 알림 (대시보드 + 전사현황판)
  └─ 전체 검증
```

## 7. 예상 결과

| 지표 | Before | After |
|------|--------|-------|
| A/S 케이스 등록 | 0건 (카톡 관리) | ERP 통합 |
| 보증 추적 | 수동 | 자동 (만료 알림 포함) |
| 유상/무상 판별 | 수동 | 자동 (보증기간 기준) |
| 목록 조회 성능 | JOIN 3개 | JOIN 0개 (비정규화) |
| 반복 불량 분석 | 불가 | 품목/모델별 통계 |
| 제품 이력 | 분산 | 통합 이력카드 |

## 8. 리스크

| 리스크 | 확률 | 대응 |
|--------|------|------|
| 비정규화 데이터 불일치 | 중 | 보증 생성 시 1회 복사, 원본 변경 시 동기화 불필요 (보증 데이터는 과거 시점 snapshot) |
| 카카오워크 마이그레이션 품질 | 높 | 140건 수동 검수 필요, 자동 파싱은 참고용 |
| 기존 1,206건 백필 시간 | 낮 | 1회성 스크립트, 수 초 내 완료 예상 |
| 혁신제품 판별 누락 | 중 | G2B 데이터 기준 + 수동 보정 UI 제공 |
