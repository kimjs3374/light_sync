# Light-Sync ERP 챗봇 MCP 응답 설계서

> AI 챗봇이 ERP 데이터 + 과거 워크보드 데이터를 조합하여
> 사용자의 자연어 질문에 실무 맥락을 포함한 답변을 제공하는 설계

---

## 1. 질문 유형 분류 & MCP 호출 전략

### 유형 A: 현장 진행상황 질의

**트리거**: 현장명/계약명/발주처 언급 + "어떻게", "진행", "상황", "확인"

**MCP 호출 체인**:
```
search_projects("{키워드}")
  → 현장 ID 확보
    → get_contracts(project_id)
    → get_deliveries(project_id)
    → get_tax_invoices() + 계약 매칭 확인
    → search_archive("{키워드}")
      → get_archive_post_detail(post_id) (댓글 있으면)
```

**응답 템플릿**:
```markdown
## {현장명}

**기본 정보**
| 항목 | 내용 |
|------|------|
| 발주처 | {발주처} |
| 계약일 | {계약일} |
| 납기 | {납기일} (D{+/-N}) |
| 품목 | {모델} x{수량} |
| 계약금액 | {금액}원 |
| 수금 | {미청구/부분입금/입금완료} |

**진행 이력**
- {날짜} {작성자}: {내용}
- {날짜} {작성자}: {내용}
...

**현재 상태 & 필요 조치**
→ {상태 판단 + 다음 액션 제안}
```

---

### 유형 B: 목록/통계 질의

**트리거**: "몇 건", "목록", "알려줘", "얼마", "리스트"

| 질문 예시 | MCP 호출 |
|-----------|---------|
| "미청구 현장 몇 개야?" | `get_contracts(payment_status="미청구")` |
| "이번 달 매출 얼마야?" | `get_revenue_summary(year, month)` |
| "재고 부족한 거 있어?" | `get_low_stock()` |
| "하자보증 만료 임박 건?" | `get_warranty_cases()` + 보증 필터 |
| "납품 예정 건?" | `get_deliveries(status="예정")` |

**응답 원칙**: 숫자 먼저 → 상세 목록 → 주의 항목 강조

---

### 유형 C: A/S 관련 질의

**트리거**: "AS", "A/S", "하자", "고장", "미점등", "불량", 모델명

**MCP 호출 체인**:
```
get_warranty_cases(search="{키워드}")
  → 현재 ERP AS 케이스
search_archive("{키워드}", board_type="as")
  → 과거 A/S 이력
search_archive("{모델명}", board_type="as")
  → 동일 모델 A/S 사례
```

**응답 템플릿**:
```markdown
## A/S: {현장명}

**접수 정보**
- 모델: {모델명}
- 증상: {증상}
- 담당자: {이름} {연락처}

**처리 이력**
- {날짜}: {처리 내용}

**유사 사례** ({모델명} 기준)
- {다른 현장}: {증상} → {처리 방법}
```

---

### 유형 D: 수금/재무 질의

**트리거**: "대금", "수금", "잔금", "세금계산서", "입금", "미수금"

**MCP 호출 체인**:
```
get_contracts(payment_status="미청구")  → 미청구 목록
get_contracts(payment_status="부분입금") → 잔금 미수
get_tax_invoices() → 매칭 현황
get_financial_overview() → 전체 재무 요약
```

**응답 시 주의**:
- 납기 경과 + 미청구 → "세금계산서 발행 확인 필요" 강조
- 부분입금 → 잔금 금액 명시
- 변경계약 → 원계약과 구분하여 안내

---

### 유형 E: 업무 지시/작성 요청

**트리거**: "작성해줘", "만들어줘", "보내줘", "공지"

| 요청 | 생성 양식 |
|------|----------|
| 납품 공지 | `<납품공지>` 표준 양식 |
| A/S 접수 | `**A/S 요청` 표준 양식 |
| 일일업무보고 | 자동 수집 데이터 기반 |

**납품 공지 자동 생성**:
```
사용자: "강진군 납품 공지 써줘"
AI: search_projects("강진") → 계약 정보 조회

<납품공지>
건명 : 강진군 가로(보안)등 관급자재
납품일시 : 2026/03/21 금요일 오전 10시 하차
납품장소 : {주소}
모델명 : MT-SLA(D)-050, 50W
수량 : {N}EA
인수자 : {확인 필요}
```

---

## 2. 상태 자동 판단 로직

챗봇이 현장 정보를 조회한 후 자동으로 상태를 판단하고 액션을 제안:

```python
def judge_site_status(contract, invoices, archive_comments):
    """현장 상태 판단 + 액션 제안"""

    actions = []

    # 1. 납품 상태 판단
    delivery_done = any('납품완료' in c.content for c in archive_comments)

    # 2. 수금 상태
    if contract.payment_status == '미청구':
        if delivery_done:
            actions.append("납품은 완료됐으나 세금계산서가 미발행입니다. 청구가 필요합니다.")
        elif contract.delivery_due_date < today:
            days = (today - contract.delivery_due_date).days
            actions.append(f"납기가 {days}일 경과했습니다. 발주처에 일정 확인이 필요합니다.")
        else:
            actions.append("납품 진행 중입니다.")

    elif contract.payment_status == '부분입금':
        remaining = contract.g2b_amount - invoiced_total
        actions.append(f"잔금 {remaining:,}원 청구가 필요합니다.")

    elif contract.payment_status == '입금완료':
        if not warranty:
            actions.append("하자보증 등록이 필요합니다.")
        elif warranty.warranty_end < today + timedelta(days=30):
            actions.append("하자보증이 곧 만료됩니다.")

    # 3. 변경계약 확인
    if '변경' in any_comment or '연기' in any_comment:
        actions.append("변경계약/납기연장 이력이 있습니다. 최신 납기를 확인해주세요.")

    return actions
```

---

## 3. 응답 품질 기준

### 3.1 필수 포함 정보

| 질문 유형 | 필수 정보 |
|-----------|----------|
| 현장 조회 | 발주처, 모델/수량, 계약금액, 납기, 수금상태, 진행이력 |
| 미청구 조회 | D-Day, 금액, 납품완료 여부 |
| A/S 조회 | 모델명, 증상, 담당자, 처리이력, 유사사례 |
| 납품 조회 | 일시, 장소, 인수자, 출고상태 |

### 3.2 컨텍스트 연결

동일 현장에 대해 여러 시스템의 데이터를 연결:
- **계약관리**: 기본 정보, 품목, 금액
- **납품관리**: 분할 납품 현황, 사진
- **매출관리**: 세금계산서 매칭, 입금 현황
- **하자관리**: 보증 기간, AS 이력
- **아카이브**: 과거 카카오워크 대화 이력

### 3.3 금지 사항

- 추측으로 금액/일정 답변 금지 → 반드시 DB 조회
- 불확실한 정보는 "확인이 필요합니다" 표시
- 민감 정보(계좌번호 등) 노출 주의

---

## 4. 핵심 MCP Tool: `get_site_timeline`

현장 통합 타임라인 — 모든 시스템 데이터를 하나로 조합하는 핵심 Tool

### 입력
```
project_id 또는 search 키워드
```

### 출력
```json
{
  "site": {
    "name": "여수 선소테마정원",
    "buyer": "전라남도 여수시",
    "status": "미청구"
  },
  "contracts": [{
    "g2b_no": "R25TB01130073",
    "items": "철제가로등주 MTPF-201-4 x22, 베이스커버 x22",
    "amount": 14652000,
    "due_date": "2026-03-17",
    "payment": "미청구"
  }],
  "invoices": [],
  "warranty": null,
  "timeline": [
    {"date": "2025-10-30", "type": "contract", "content": "G2B 계약 체결"},
    {"date": "2025-10-31", "type": "workboard", "author": "이지훈", "content": "계약 접수 등록"},
    {"date": "2026-03-12", "type": "workboard", "author": "이지훈", "content": "벤투스 가로등주 출고"},
    {"date": "2026-03-12", "type": "workboard", "author": "이지훈", "content": "납품완료"}
  ],
  "suggested_actions": [
    "납품 완료 확인 — 세금계산서 발행이 필요합니다"
  ]
}
```

### 호출 조건
- 사용자가 특정 현장을 언급할 때 항상 호출
- 현장 상태 판단의 기초 데이터로 활용
- 타 Tool 결과를 조합하여 통합 뷰 제공

---

## 5. 향후 확장

| 기능 | 설명 |
|------|------|
| **자동 알림** | 납기 D-7/D-Day에 챗봇이 선제적으로 알림 |
| **일일업무보고 연동** | 챗봇 대화 내용 → 일일업무보고 자동 반영 |
| **납품 공지 자동 발송** | 챗봇에서 작성 → 카카오워크 채널 자동 발송 |
| **A/S 패턴 학습** | 모델별 고장 패턴 → 예방 정비 제안 |
| **변경계약 자동 감지** | G2B 동기화 시 변경계약 → 기존 계약에 연결 |
