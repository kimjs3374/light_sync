# 견적서 관리 (Quotation) Design Document

> **Summary**: 매그나텍 양식 견적서 CRUD + PDF 출력 상세 설계
>
> **Project**: Light-Sync ERP
> **Author**: ENG
> **Date**: 2026-03-19
> **Status**: Draft
> **Plan Reference**: `docs/01-plan/features/quotation.plan.md`

---

## 1. DB 모델 설계

### 1.1 Quotation (견적서)

```python
class Quotation(Base):
    __tablename__ = 'quotations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    quote_no = Column(String(20), unique=True, nullable=False)  # MT-YYMMDD-순번
    quote_date = Column(Date, nullable=False)                   # 견적일

    # 견적 조건
    validity_period = Column(String(100), default='견적일로부터 1개월')  # 견적유효
    delivery_date = Column(String(100), default='협의')                # 납기일
    payment_method = Column(String(100), default='현금')               # 대금지불
    bank_account = Column(String(200))                                 # 계좌번호

    # 건명
    project_name = Column(String(500))  # 건명 (자유 입력)

    # 수급자 정보
    customer_name = Column(String(200))     # 수급자명
    customer_contact = Column(String(100))  # 담당자
    customer_address = Column(String(500))  # 주소
    customer_tel = Column(String(50))
    customer_fax = Column(String(50))
    customer_email = Column(String(200))

    # 금액
    total_amount = Column(Float, default=0)       # 공급가액 합계
    tax_included = Column(Boolean, default=False)  # 부가세 포함 여부

    # 비고
    note = Column(Text)  # 비고 (줄바꿈 가능)

    # 상태
    status = Column(String(20), default='작성중')  # 작성중 / 발송 / 만료

    # 메타
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    items = relationship("QuotationItem", back_populates="quotation",
                         cascade="all, delete-orphan", order_by="QuotationItem.seq")
```

### 1.2 QuotationItem (견적 품목)

```python
class QuotationItem(Base):
    __tablename__ = 'quotation_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    quotation_id = Column(Integer, ForeignKey('quotations.id'), nullable=False)
    seq = Column(Integer, default=0)            # 순번
    item_id = Column(Integer, nullable=True)     # Item DB 연결 (nullable=수기입력)
    item_name = Column(String(300), nullable=False)  # 품명
    item_spec = Column(String(500))              # 규격
    unit = Column(String(50), default='개')      # 단위
    quantity = Column(Float, default=0)           # 수량
    unit_price = Column(Float, default=0)         # 단가
    amount = Column(Float, default=0)             # 금액 (수량*단가)
    note = Column(String(500))                    # 비고

    quotation = relationship("Quotation", back_populates="items")
```

### 1.3 마이그레이션 SQL

```sql
-- sql_editer.sql에 추가
CREATE TABLE IF NOT EXISTS quotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_no VARCHAR(20) UNIQUE NOT NULL,
    quote_date DATE NOT NULL,
    validity_period VARCHAR(100) DEFAULT '견적일로부터 1개월',
    delivery_date VARCHAR(100) DEFAULT '협의',
    payment_method VARCHAR(100) DEFAULT '현금',
    bank_account VARCHAR(200),
    project_name VARCHAR(500),
    customer_name VARCHAR(200),
    customer_contact VARCHAR(100),
    customer_address VARCHAR(500),
    customer_tel VARCHAR(50),
    customer_fax VARCHAR(50),
    customer_email VARCHAR(200),
    total_amount REAL DEFAULT 0,
    tax_included BOOLEAN DEFAULT 0,
    note TEXT,
    status VARCHAR(20) DEFAULT '작성중',
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quotation_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quotation_id INTEGER NOT NULL REFERENCES quotations(id) ON DELETE CASCADE,
    seq INTEGER DEFAULT 0,
    item_id INTEGER,
    item_name VARCHAR(300) NOT NULL,
    item_spec VARCHAR(500),
    unit VARCHAR(50) DEFAULT '개',
    quantity REAL DEFAULT 0,
    unit_price REAL DEFAULT 0,
    amount REAL DEFAULT 0,
    note VARCHAR(500)
);
```

---

## 2. 라우트 설계

### 2.1 routes/quotation.py

| Method | URL | Function | Description |
|--------|-----|----------|-------------|
| GET | `/quotation` | `quotation_list` | 견적서 목록 (검색/필터/페이지네이션) |
| GET/POST | `/quotation/create` | `quotation_create` | 견적서 생성 |
| GET | `/quotation/<id>` | `quotation_detail` | 견적서 상세 |
| POST | `/quotation/<id>/edit` | `quotation_edit` | 견적서 수정 |
| POST | `/quotation/<id>/delete` | `quotation_delete` | 견적서 삭제 |
| GET | `/quotation/<id>/pdf` | `quotation_pdf` | PDF 다운로드 |

### 2.2 견적번호 자동채번

```python
def _generate_quote_no(db):
    """견적번호: MT-YYMMDD-순번 (당일 기준)"""
    today = datetime.date.today()
    prefix = f"MT-{today.strftime('%y%m%d')}-"

    last = db.query(Quotation).filter(
        Quotation.quote_no.like(f'{prefix}%')
    ).order_by(desc(Quotation.quote_no)).first()

    if last:
        try:
            last_num = int(last.quote_no.replace(prefix, ''))
            return f'{prefix}{last_num + 1:02d}'
        except ValueError:
            pass
    return f'{prefix}01'
```

### 2.3 목록 필터

- `q`: 검색어 (견적번호, 수급자명, 건명)
- `status`: 상태 필터 (작성중/발송/만료)
- `date_from`, `date_to`: 기간 필터
- `page`: 페이지네이션 (20건/페이지)

### 2.4 생성 폼 처리

POST 데이터 구조:
```
quote_date, project_name, customer_name, customer_contact,
customer_address, customer_tel, customer_fax, customer_email,
validity_period, delivery_date, payment_method, note,
item_name[], item_spec[], unit[], quantity[], unit_price[], item_note[], item_id[]
```

- 품목 배열을 순회하며 QuotationItem 생성
- `amount = quantity * unit_price` 자동 계산
- `total_amount = sum(items.amount)` 자동 합산

---

## 3. PDF 설계 (quote_pdf.py)

### 3.1 레이아웃 (견적서 샘플 기준)

```
┌─────────────────────────────────────────────────────────────┐
│  [로고]                                    MagnaTech 로고    │
│                                                             │
│                    견  적  서                                │
│                                                             │
│  견적일 : 2026년 03월 10일                                   │
│  사업자등록번호 408-81-68519    납기일    협의                │
│  견적서 NO. MT-260310-17       대금지불  현금                │
│                                견적유효  견적일로부터 1개월   │
│                                계좌번호                      │
│                                                             │
│  ┌─────────────────┐  ┌───────────────────────────────┐    │
│  │ 공급자 ㈜매그나텍 │  │ 수급자  보성군                 │    │
│  │ 담당자            │  │ 건  명  벌교 종합스포츠시설...  │    │
│  │ 주소  전남 장성... │  │ 담당자                        │    │
│  │ Tel  061-392-5508 │  │ 주소                          │    │
│  │ Fax  061-392-5518 │  │ Tel                           │    │
│  │ E-mail sales@...  │  │ Fax                           │    │
│  │ Homepage www...   │  │ E-mail                        │    │
│  └─────────────────┘  └───────────────────────────────┘    │
│                                            (단위 : 원)      │
│  ┌──┬────────┬──────┬──┬──┬──────┬──────┬────┐            │
│  │NO│ 품명   │ 규격 │단위│수량│ 단 가 │ 금액 │비고│            │
│  ├──┼────────┼──────┼──┼──┼──────┼──────┼────┤            │
│  │ 1│ LORA.. │무선..│개 │ 1│625,000│625,000│    │            │
│  │..│ ...    │ ...  │..│..│ ...   │ ...  │ .. │            │
│  └──┴────────┴──────┴──┴──┴──────┴──────┴────┘            │
│                                                             │
│                             합 계    62,625,000             │
│                                                             │
│  [비고]                                                     │
│  -.부가세 별도가                      매그나텍 주식회사       │
│  -.견적 외 추가비용 별도              박선후 / 대표이사       │
│  -.납품은 현장 준공일정에 따름        [직인]                 │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 PDF 구현 방식

- po_pdf.py 패턴 재사용 (ReportLab canvas 직접 그리기)
- `_find_korean_font()` 공유
- 컬럼 비율: No(5%), 품명(25%), 규격(15%), 단위(6%), 수량(7%), 단가(15%), 금액(17%), 비고(10%)
- 페이지 넘김: 행 y좌표가 하단 여백(35mm) 이하일 때 `c.showPage()`
- 공급자 정보: 하드코딩 (매그나텍 고정)
- 수급자 정보: DB에서 동적

### 3.3 PDF 차별점 (발주서 vs 견적서)

| 항목 | 발주서 (po_pdf) | 견적서 (quote_pdf) |
|------|----------------|-------------------|
| 제목 | 발 주 서 | 견 적 서 |
| 메타정보 | 발주번호, 발주일자 | 견적일, 견적NO, 납기일, 대금지불, 견적유효, 계좌번호 |
| 상단 정보 | 수신/발신 (거래처→매그나텍) | 공급자/수급자 (매그나텍→고객) |
| 하단 | 합계 박스 | 합계 + 비고 + 대표이사 직인 |
| 안내문구 | "아래와 같이 발주하오니..." | 없음 (테이블 바로 시작) |

---

## 4. 템플릿 설계

### 4.1 quotation_list.html

```
┌────────────────────────────────────────────────────────────┐
│ [Page Hero] 견적서 관리                     [+ 견적서 작성] │
├────────────────────────────────────────────────────────────┤
│ [Stats] 전체 | 작성중 | 발송 | 만료                        │
├────────────────────────────────────────────────────────────┤
│ [Filter Bar] 검색 | 상태 | 기간                            │
├────────────────────────────────────────────────────────────┤
│ 견적번호 | 견적일 | 수급자 | 건명 | 합계금액 | 상태         │
│ MT-260310-17 │ 03-10 │ 보성군 │ 벌교... │ 62,625,000 │ 작성중│
│ ...                                                        │
├────────────────────────────────────────────────────────────┤
│ [Pagination]                                               │
└────────────────────────────────────────────────────────────┘
```

### 4.2 quotation_create.html

```
┌────────────────────────────────────────────────────────────┐
│ [Page Hero] 견적서 작성                                     │
├────────────────────────────────────────────────────────────┤
│ Section 1: 기본정보                                        │
│ ┌──────────┬──────────┬──────────┐                        │
│ │ 견적일    │ 납기일    │ 대금지불  │                        │
│ │ [date]   │ [text]   │ [text]   │                        │
│ ├──────────┴──────────┴──────────┤                        │
│ │ 건명                            │                        │
│ │ [text ─────────────────────── ] │                        │
│ └────────────────────────────────┘                        │
├────────────────────────────────────────────────────────────┤
│ Section 2: 수급자 정보                                     │
│ ┌──────────┬──────────┬──────────┐                        │
│ │ 수급자명  │ 담당자    │ Tel      │                        │
│ │ [text]   │ [text]   │ [text]   │                        │
│ ├──────────┼──────────┼──────────┤                        │
│ │ 주소      │ Fax      │ E-mail   │                        │
│ │ [text]   │ [text]   │ [text]   │                        │
│ └──────────┴──────────┴──────────┘                        │
├────────────────────────────────────────────────────────────┤
│ Section 3: 품목                                            │
│ ┌──┬──────┬──────┬──┬──┬──────┬──────┬──┬──┐            │
│ │No│ 품명 │ 규격 │단위│수량│ 단가 │ 금액 │비고│삭제│            │
│ ├──┼──────┼──────┼──┼──┼──────┼──────┼──┼──┤            │
│ │ 1│[검색]│[text]│[t]│[n]│ [n]  │ auto │[t]│[x]│            │
│ └──┴──────┴──────┴──┴──┴──────┴──────┴──┴──┘            │
│ [+ 품목 추가]                                              │
│                                                            │
│ 공급가액: 62,625,000원 │ 부가세: 6,262,500원               │
│ 합  계: 68,887,500원                                      │
├────────────────────────────────────────────────────────────┤
│ Section 4: 비고                                            │
│ [textarea]                                                 │
├────────────────────────────────────────────────────────────┤
│ [저장] [취소]                                              │
└────────────────────────────────────────────────────────────┘
```

### 4.3 quotation_detail.html

```
┌────────────────────────────────────────────────────────────┐
│ [Page Hero] MT-260310-17          [PDF] [수정] [삭제]      │
├────────────────────────────────────────────────────────────┤
│ 공급자: ㈜매그나텍        │ 수급자: 보성군                  │
│ 건명: 벌교 종합스포츠시설 조성사업                          │
├────────────────────────────────────────────────────────────┤
│ 품목 테이블 (읽기 전용)                                    │
├────────────────────────────────────────────────────────────┤
│ 합계: 62,625,000원                                        │
│ 비고: 부가세 별도, 견적 외 추가비용 별도                    │
└────────────────────────────────────────────────────────────┘
```

---

## 5. 메뉴 등록

### 5.1 config.py MENU_REGISTRY

```python
# --- 영업부 --- 섹션에 추가
("quotation",  {"label": "견적관리", "group": "영업부", "endpoint": "quotation.quotation_list"}),
```

### 5.2 DEFAULT_GROUP_MENUS

```python
"영업부": "project,contract,sales,quotation,delivery,procurement,procurement_summary,warranty",
"임원진": "...,quotation,...",
```

### 5.3 app.py Blueprint 등록

```python
from routes.quotation import quotation_bp
app.register_blueprint(quotation_bp)
```

---

## 6. 구현 순서 (Implementation Order)

| Step | Task | Files | FR |
|------|------|-------|-----|
| 1 | DB 모델 추가 | `entities.py`, `__init__.py` | - |
| 2 | DB 마이그레이션 | `sql_editer.sql` | - |
| 3 | 라우트 CRUD | `routes/quotation.py` | FR-01~06, 08~10 |
| 4 | PDF 서비스 | `modules/services/quote_pdf.py` | FR-07 |
| 5 | 목록 템플릿 | `templates/quotation_list.html` | FR-09 |
| 6 | 생성 템플릿 | `templates/quotation_create.html` | FR-03~05 |
| 7 | 상세 템플릿 | `templates/quotation_detail.html` | FR-01 |
| 8 | 메뉴 등록 | `config.py`, `app.py` | - |

---

## 7. API 엔드포인트 (기존 재사용)

- `GET /api/vendors/search?q=` — 거래처 검색 (purchase_order.py에 이미 존재)
- `GET /api/items/search?q=` — 품목 검색 (purchase_order.py에 이미 존재)

신규 API 불필요 — 기존 발주서의 거래처/품목 검색 API 공유 사용.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-19 | Initial design | ENG |
