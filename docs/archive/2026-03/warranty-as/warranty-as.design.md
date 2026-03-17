# 하자보증/AS 관리 Design Document

> **Summary**: 하자보증 기간 추적 + AS 접수~완료 워크플로우 + 하자유형별 통계 상세 설계
>
> **Project**: Light-Sync ERP
> **Author**: ENG
> **Date**: 2026-03-17
> **Status**: Draft
> **Planning Doc**: [warranty-as.plan.md](../../01-plan/features/warranty-as.plan.md)

---

## 1. Overview

### 1.1 Design Goals

- 기존 ERP 패턴(Blueprint, get_db, Jinja2, Bootstrap 5) 100% 준수
- Contract 모델을 수정하지 않고 별도 Warranty 모델로 분리
- AS 워크플로우를 WarrantyCase + WarrantyCaseLog로 타임라인 관리
- 기존 notification_utils.py를 활용한 보증만료 알림

### 1.2 Design Principles

- 최소 모델 설계: 3개 모델로 보증 + AS + 이력 전체 커버
- 기존 납품관리 연계: Delivery → Warranty 자연 연결
- 하자유형 코드화: 통계/분석 기반 확보

---

## 2. Architecture

### 2.1 Component Diagram

```
기존:
[Project] 1──N [Contract] 1──N [Delivery]

신규 추가:
[Contract] 1──1 [Warranty] 1──N [WarrantyCase] 1──N [WarrantyCaseLog]
```

### 2.2 신규 Blueprint 등록 (app.py)

```python
from routes.warranty import warranty_bp
app.register_blueprint(warranty_bp)
```

---

## 3. Data Model

### 3.1 Warranty (하자보증 정보)

```python
class Warranty(Base):
    __tablename__ = 'warranties'
    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=False, unique=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)

    warranty_start = Column(Date, nullable=True)       # 보증 시작일 (검수완료일 기준)
    warranty_end = Column(Date, nullable=True)          # 보증 종료일
    warranty_amount = Column(Integer, default=0)        # 보증금액 (원)
    insurance_no = Column(String(100), nullable=True)   # 보증보험증권번호
    insurance_returned = Column(Boolean, default=False) # 보증보험 반환 여부
    note = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    contract = relationship("Contract", backref="warranty")
    project = relationship("Project")
    cases = relationship("WarrantyCase", back_populates="warranty", cascade="all, delete-orphan",
                         order_by="WarrantyCase.created_at.desc()")
```

### 3.2 WarrantyCase (AS 접수건)

```python
DEFECT_TYPES = [
    ('LED_MODULE', 'LED 모듈 불량'),
    ('SMPS', 'SMPS 고장'),
    ('HEAT', '방열 이상'),
    ('LENS', '렌즈/리플렉터 손상'),
    ('MOISTURE', '결로/침수'),
    ('CONTROL', '제어 불량'),
    ('OTHER', '기타'),
]

CASE_STATUS_STEPS = ['접수', '현장확인', '수리중', '완료', '보류']

class WarrantyCase(Base):
    __tablename__ = 'warranty_cases'
    id = Column(Integer, primary_key=True, autoincrement=True)
    warranty_id = Column(Integer, ForeignKey('warranties.id'), nullable=False)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)

    case_no = Column(String(50), nullable=False)        # AS-2026-001 형식
    defect_type = Column(String(30), nullable=False)     # DEFECT_TYPES 코드
    symptom = Column(Text, nullable=False)               # 증상 설명
    status = Column(String(20), default='접수')           # CASE_STATUS_STEPS

    reported_by = Column(String(100), nullable=True)     # 접수자 (발주처 담당자명)
    reported_date = Column(Date, nullable=False)         # 접수일
    site_visit_date = Column(Date, nullable=True)        # 현장확인일
    completed_date = Column(Date, nullable=True)         # 완료일

    cause_analysis = Column(Text, nullable=True)         # 원인분석
    action_taken = Column(Text, nullable=True)           # 처리내용
    replaced_parts = Column(String(500), nullable=True)  # 교체부품

    assigned_to = Column(String(100), nullable=True)     # 담당 기사
    created_by = Column(String(50), default='사용자')
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    warranty = relationship("Warranty", back_populates="cases")
    project = relationship("Project")
    logs = relationship("WarrantyCaseLog", back_populates="case", cascade="all, delete-orphan",
                        order_by="WarrantyCaseLog.created_at.desc()")
```

### 3.3 WarrantyCaseLog (AS 처리 이력)

```python
class WarrantyCaseLog(Base):
    __tablename__ = 'warranty_case_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey('warranty_cases.id'), nullable=False)

    log_type = Column(String(20), default='status_change')  # status_change / note / visit
    old_status = Column(String(20), nullable=True)
    new_status = Column(String(20), nullable=True)
    content = Column(Text, nullable=True)
    created_by = Column(String(50), default='사용자')
    created_at = Column(DateTime, default=datetime.datetime.now)

    case = relationship("WarrantyCase", back_populates="logs")
```

---

## 4. API Specification

### 4.1 Endpoint List

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | /warranty | 하자보증/AS 관리 리스트 | Required |
| GET | /warranty/create | AS 접수 폼 | Required |
| POST | /warranty/create | AS 접수 처리 | Required |
| GET | /warranty/<int:case_id> | AS 상세 페이지 | Required |
| POST | /warranty/<int:case_id> | AS 상태변경/처리내역 업데이트 | Required |
| GET | /warranty/register/<int:contract_id> | 보증정보 등록 폼 | Required |
| POST | /warranty/register/<int:contract_id> | 보증정보 저장 | Required |

### 4.2 Route: warranty_list (GET /warranty)

```python
@warranty_bp.route('/warranty')
@login_required
def warranty_list():
    q = (request.args.get('q') or '').strip().lower()
    status_filter = request.args.get('status', 'all')   # all/접수/현장확인/수리중/완료/보류
    defect_filter = request.args.get('defect', 'all')    # all/LED_MODULE/SMPS/...
    sort_by = request.args.get('sort', 'created_desc')
    page = safe_int(request.args.get('page'), 1)
    per_page = 20

    with get_db() as db:
        query = db.query(WarrantyCase).options(
            joinedload(WarrantyCase.warranty).joinedload(Warranty.contract),
            joinedload(WarrantyCase.project),
        )

        # 텍스트 검색 (프로젝트명, 관리번호, 케이스번호)
        # 상태 필터
        # 하자유형 필터
        # 정렬 (최신접수순 / 접수일순)
        # 페이지네이션

        # 통계 집계
        stats = {
            'total': ...,
            'filtered': ...,
            'open': ...,       # 완료 제외 건수
            'by_defect': {...} # 하자유형별 카운트
        }

        return render_template('warranty_list.html',
            cases=paginated_cases,
            stats=stats,
            filters=filters,
            pagination=pagination,
            defect_types=DEFECT_TYPES,
            status_steps=CASE_STATUS_STEPS,
        )
```

### 4.3 Route: warranty_create (GET/POST /warranty/create)

```python
@warranty_bp.route('/warranty/create', methods=['GET', 'POST'])
@login_required
def warranty_create():
    with get_db() as db:
        if request.method == 'POST':
            warranty_id = safe_int(request.form.get('warranty_id'))
            warranty = db.get(Warranty, warranty_id)
            if not warranty:
                flash('보증정보를 먼저 등록해주세요.', 'danger')
                return redirect(url_for('warranty.warranty_list'))

            # case_no 자동생성: AS-{year}-{seq:03d}
            year = str(datetime.date.today().year)
            count = db.query(WarrantyCase).filter(
                WarrantyCase.case_no.like(f'AS-{year}-%')
            ).count()
            case_no = f'AS-{year}-{count + 1:03d}'

            case = WarrantyCase(
                warranty_id=warranty.id,
                project_id=warranty.project_id,
                case_no=case_no,
                defect_type=request.form.get('defect_type'),
                symptom=request.form.get('symptom'),
                reported_by=request.form.get('reported_by'),
                reported_date=parse_date(request.form.get('reported_date')) or datetime.date.today(),
                assigned_to=request.form.get('assigned_to'),
                created_by=session.get('full_name', '사용자'),
            )
            db.add(case)
            db.flush()

            # 초기 로그
            db.add(WarrantyCaseLog(
                case_id=case.id,
                log_type='status_change',
                new_status='접수',
                content=f'AS 접수 - {dict(DEFECT_TYPES).get(case.defect_type, case.defect_type)}',
                created_by=session.get('full_name', '사용자'),
            ))
            db.commit()
            flash(f'AS 접수 완료: {case_no}', 'success')
            return redirect(url_for('warranty.warranty_detail', case_id=case.id))

        # GET: 보증 등록된 계약 목록
        warranties = db.query(Warranty).options(
            joinedload(Warranty.contract),
            joinedload(Warranty.project),
        ).order_by(Warranty.id.desc()).all()

        return render_template('warranty_create.html',
            warranties=warranties,
            defect_types=DEFECT_TYPES,
        )
```

### 4.4 Route: warranty_detail (GET/POST /warranty/<case_id>)

```python
@warranty_bp.route('/warranty/<int:case_id>', methods=['GET', 'POST'])
@login_required
def warranty_detail(case_id):
    with get_db() as db:
        case = db.query(WarrantyCase).options(
            joinedload(WarrantyCase.warranty).joinedload(Warranty.contract),
            joinedload(WarrantyCase.project),
            joinedload(WarrantyCase.logs),
        ).get(case_id)

        if not case:
            flash('AS건을 찾을 수 없습니다.', 'danger')
            return redirect(url_for('warranty.warranty_list'))

        if request.method == 'POST':
            action = request.form.get('action')
            handle_warranty_action(db, case, action, request.form, session)
            db.commit()
            return redirect(url_for('warranty.warranty_detail', case_id=case_id))

        return render_template('warranty_detail.html',
            case=case,
            defect_types=dict(DEFECT_TYPES),
            status_steps=CASE_STATUS_STEPS,
        )
```

### 4.5 Route: warranty_register (GET/POST /warranty/register/<contract_id>)

```python
@warranty_bp.route('/warranty/register/<int:contract_id>', methods=['GET', 'POST'])
@login_required
def warranty_register(contract_id):
    with get_db() as db:
        contract = db.query(Contract).options(
            joinedload(Contract.project)
        ).get(contract_id)

        if not contract:
            flash('계약을 찾을 수 없습니다.', 'danger')
            return redirect(url_for('warranty.warranty_list'))

        existing = db.query(Warranty).filter(Warranty.contract_id == contract_id).first()

        if request.method == 'POST':
            if existing:
                # 업데이트
                existing.warranty_start = parse_date(request.form.get('warranty_start'))
                existing.warranty_end = parse_date(request.form.get('warranty_end'))
                existing.warranty_amount = safe_int(request.form.get('warranty_amount'))
                existing.insurance_no = request.form.get('insurance_no', '').strip()
                existing.insurance_returned = request.form.get('insurance_returned') == '1'
                existing.note = request.form.get('note', '').strip()
            else:
                # 신규 생성
                db.add(Warranty(
                    contract_id=contract_id,
                    project_id=contract.project_id,
                    warranty_start=parse_date(request.form.get('warranty_start')),
                    warranty_end=parse_date(request.form.get('warranty_end')),
                    warranty_amount=safe_int(request.form.get('warranty_amount')),
                    insurance_no=request.form.get('insurance_no', '').strip(),
                    note=request.form.get('note', '').strip(),
                ))
            db.commit()
            flash('하자보증 정보가 저장되었습니다.', 'success')
            return redirect(url_for('warranty.warranty_list'))

        return render_template('warranty_register.html',
            contract=contract,
            warranty=existing,
        )
```

---

## 5. Service Layer

### 5.1 `modules/services/warranty_actions.py`

```python
def handle_warranty_action(db, case, action, form, session_data):
    """AS건 상태변경/처리 통합 핸들러"""
    user_name = session_data.get('full_name', '사용자')

    if action == 'update_status':
        new_status = form.get('new_status')
        if new_status and new_status != case.status:
            old = case.status
            case.status = new_status
            if new_status == '현장확인':
                case.site_visit_date = parse_date(form.get('site_visit_date')) or datetime.date.today()
            elif new_status == '완료':
                case.completed_date = parse_date(form.get('completed_date')) or datetime.date.today()
            db.add(WarrantyCaseLog(
                case_id=case.id, log_type='status_change',
                old_status=old, new_status=new_status,
                content=form.get('status_memo', '').strip() or f'{old} → {new_status}',
                created_by=user_name,
            ))

    elif action == 'update_detail':
        case.cause_analysis = form.get('cause_analysis', '').strip()
        case.action_taken = form.get('action_taken', '').strip()
        case.replaced_parts = form.get('replaced_parts', '').strip()
        case.assigned_to = form.get('assigned_to', '').strip()
        db.add(WarrantyCaseLog(
            case_id=case.id, log_type='note',
            content='처리 내역 업데이트',
            created_by=user_name,
        ))

    elif action == 'add_note':
        content = form.get('note_content', '').strip()
        if content:
            db.add(WarrantyCaseLog(
                case_id=case.id, log_type='note',
                content=content,
                created_by=user_name,
            ))
```

---

## 6. UI/UX Design

### 6.1 warranty_list.html

```
┌──────────────────────────────────────────────────────────┐
│  🔧 하자보증 / AS 관리                    [+ AS 접수]    │
├──────────────────────────────────────────────────────────┤
│ [통계카드] 전체 | 미완료 | LED모듈 | SMPS | 방열 | ...   │
├──────────────────────────────────────────────────────────┤
│ [검색] ______  [상태] ▼  [하자유형] ▼  [정렬] ▼  [검색]  │
├──────────────────────────────────────────────────────────┤
│ 케이스번호 | 현장명 | 하자유형 | 상태 | 접수일 | 담당    │
│ AS-2026-001 | ○○체육관 | LED모듈 | 수리중 | 03-15 | 홍길동 │
│ AS-2026-002 | △△경기장 | SMPS   | 접수   | 03-16 | -    │
│ ...                                                      │
├──────────────────────────────────────────────────────────┤
│ [페이지네이션]                                            │
└──────────────────────────────────────────────────────────┘
```

### 6.2 warranty_detail.html

```
┌──────────────────────────────────────────────────────────┐
│  AS-2026-001 상세                         [← 목록으로]   │
├──────────────────────────────────────────────────────────┤
│ 좌측 패널: AS 정보                                        │
│ ┌──────────────────────────────────────┐                  │
│ │ 현장명: ○○체육관                      │                  │
│ │ 계약명: LED 투광등 설치공사             │                  │
│ │ 하자유형: LED 모듈 불량                │                  │
│ │ 증상: 3번 기둥 2열 부분소등             │                  │
│ │ 접수일: 2026-03-15                    │                  │
│ │ 상태: [접수] → [현장확인] → [수리중]    │                  │
│ │                                        │                  │
│ │ [상태 변경] ▼ 메모: _____ [변경]       │                  │
│ └──────────────────────────────────────┘                  │
├──────────────────────────────────────────────────────────┤
│ 처리 내역 (수정 가능)                                     │
│ ┌──────────────────────────────────────┐                  │
│ │ 원인분석: ____________               │                  │
│ │ 처리내용: ____________               │                  │
│ │ 교체부품: ____________               │                  │
│ │ 담당기사: ____________  [저장]        │                  │
│ └──────────────────────────────────────┘                  │
├──────────────────────────────────────────────────────────┤
│ 처리 이력 타임라인                                        │
│ ● 2026-03-17 수리중 전환 - 홍길동                         │
│ ● 2026-03-16 현장확인 완료 - LED 모듈 3개 불량 확인       │
│ ● 2026-03-15 AS 접수 - LED 모듈 불량                     │
├──────────────────────────────────────────────────────────┤
│ 메모 추가: [_______________] [등록]                       │
└──────────────────────────────────────────────────────────┘
```

### 6.3 warranty_create.html

```
┌──────────────────────────────────────────────────────────┐
│  AS 접수                                                  │
├──────────────────────────────────────────────────────────┤
│ 보증 대상 계약: [▼ 선택] (보증등록된 계약만 표시)          │
│ 하자유형: [▼ LED모듈/SMPS/방열/렌즈/결로/제어/기타]       │
│ 증상 설명: [__________________________]                   │
│ 접수일: [____-__-__]                                      │
│ 접수자 (발주처): [______________]                          │
│ 담당 기사: [______________]                                │
│                                          [취소] [접수]    │
└──────────────────────────────────────────────────────────┘
```

### 6.4 warranty_register.html

```
┌──────────────────────────────────────────────────────────┐
│  하자보증 정보 등록 - {계약명}                             │
├──────────────────────────────────────────────────────────┤
│ 보증 시작일: [____-__-__] (검수완료일)                     │
│ 보증 종료일: [____-__-__]                                  │
│ 보증금액: [_______] 원                                     │
│ 보험증권번호: [______________]                              │
│ 보험 반환여부: [ ] 반환완료                                 │
│ 비고: [__________________________]                         │
│                                          [취소] [저장]     │
└──────────────────────────────────────────────────────────┘
```

### 6.5 사이드바 메뉴 추가 (base.html)

납품관리와 종합현황 사이에 추가:

```html
<a href="{{ url_for('warranty.warranty_list') }}">하자보증/AS</a>
```

---

## 7. Security Considerations

- [x] `@login_required` 모든 라우트 적용
- [x] CSRF 보호 (기존 Flask-WTF)
- [x] 보증금액은 Integer 저장 (XSS 방지)
- [x] SQL Injection 방지 (SQLAlchemy ORM)

---

## 8. Implementation Order

1. [ ] `modules/models/entities.py` — Warranty, WarrantyCase, WarrantyCaseLog 모델 추가
2. [ ] `modules/models/entities.py` — DEFECT_TYPES, CASE_STATUS_STEPS 상수 추가
3. [ ] `modules/models/__init__.py` — 신규 모델 export 추가
4. [ ] `modules/services/warranty_actions.py` — handle_warranty_action 서비스 함수
5. [ ] `routes/warranty.py` — warranty_bp Blueprint (list, create, detail, register)
6. [ ] `templates/warranty_list.html` — AS 리스트 (통계카드 + 검색/필터 + 테이블 + 페이지네이션)
7. [ ] `templates/warranty_create.html` — AS 접수 폼
8. [ ] `templates/warranty_detail.html` — AS 상세 (정보 + 처리내역 + 타임라인 + 메모)
9. [ ] `templates/warranty_register.html` — 보증정보 등록/수정 폼
10. [ ] `templates/base.html` — 사이드바 "하자보증/AS" 메뉴 추가
11. [ ] `app.py` — warranty_bp import 및 register_blueprint

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-17 | Initial draft | ENG |
