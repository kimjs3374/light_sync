"""전자결재 비즈니스 로직

- 기본 양식 4종 시드 (휴가/지출결의/품의/출장) — 관리자가 추후 수정/추가 가능
- 직급/부서 기반 기본 결재선 자동 구성 (기안자 → 부서장 → 대표)
- 결재번호 채번 (EA-YYYY-NNNN)
- 상신/승인/반려/회수 상태 전이 + 알림
"""
import datetime
import os

from modules.models import (
    ApprovalDocument,
    ApprovalFormTemplate,
    ApprovalStep,
    User,
)

# 직급 서열 (낮을수록 하위)
# 사원 < 주임 < 대리 < 과장 < 차장 < 부장 < 이사 < 상무 < 전무 < 대표
POSITION_RANK = {
    '사원': 10, '주임': 20, '대리': 30, '과장': 40, '차장': 50,
    '부장': 60, '이사': 70, '상무': 80, '전무': 90, '대표': 100,
    '대표이사': 100,
}

# 경영진 결재 체인 기준 직급 — 부장 이상은 전부 순차 결재
# (부장 → 이사 → 상무 → 전무 → 대표 순으로 각 존재자가 모두 결재)
SENIOR_THRESHOLD = POSITION_RANK['부장']  # 60

# 결재선 토큰 → 라벨
LINE_TOKEN_LABEL = {
    'drafter': '기안자',
    'dept_head': '부서장',
    'executive': '경영진',
}

# 결재선 자동 구성에서 제외할 그룹 (시스템 계정)
_EXCLUDED_GROUPS = {'최고관리자'}


def position_rank(position):
    return POSITION_RANK.get((position or '').strip(), 0)


# ────────────────────────────────────────────────────────
# 기본 양식 시드
# ────────────────────────────────────────────────────────

DEFAULT_FORMS = [
    {
        'form_key': 'leave',
        'name': '휴가신청서',
        'icon': '🏖️',
        'description': '연차/반차/병가/경조사 등 휴가 신청',
        'has_amount': False,
        'sort_order': 10,
        'default_line': ['drafter', 'dept_head', 'executive'],
        'field_schema': [
            {'key': 'leave_type', 'label': '휴가종류', 'type': 'select', 'required': True,
             'options': ['연차', '병가', '경조사', '공가', '기타']},
            {'key': 'period', 'label': '기간', 'type': 'select', 'required': True,
             'options': ['종일', '오전반차', '오후반차']},
            {'key': 'start_date', 'label': '시작일', 'type': 'date', 'required': True},
            {'key': 'end_date', 'label': '종료일', 'type': 'date', 'required': False},
            {'key': 'start_time', 'label': '시작시각', 'type': 'time', 'required': False},
            {'key': 'end_time', 'label': '종료시각', 'type': 'time', 'required': False},
            {'key': 'days', 'label': '사용일수', 'type': 'number', 'required': True, 'suffix': '일'},
            {'key': 'emergency_contact', 'label': '비상연락처', 'type': 'text', 'required': False},
            {'key': 'reason', 'label': '사유', 'type': 'textarea', 'required': False},
        ],
    },
    {
        'form_key': 'expense',
        'name': '지출결의서',
        'icon': '💳',
        'description': '경비/구매 지출 결의',
        'has_amount': True,
        'amount_field': 'amount',
        'sort_order': 20,
        'default_line': ['drafter', 'dept_head', 'executive'],
        'field_schema': [
            {'key': 'expense_date', 'label': '지출일', 'type': 'date', 'required': True},
            {'key': 'items', 'label': '지출명세', 'type': 'lineitems', 'required': True,
             'columns': [
                 {'key': 'item', 'label': '지출항목'},
                 {'key': 'amount', 'label': '금액', 'type': 'number'},
                 {'key': 'payee', 'label': '사용처/거래처'},
             ]},
            {'key': 'payment_method', 'label': '결제수단', 'type': 'select', 'required': False,
             'options': ['법인카드', '계좌이체', '현금', '개인카드(환급)']},
            {'key': 'reason', 'label': '지출사유', 'type': 'textarea', 'required': True},
        ],
    },
    {
        'form_key': 'proposal',
        'name': '품의서',
        'icon': '📝',
        'description': '구매/계약/일반 안건 품의 (일반기안)',
        'has_amount': True,
        'amount_field': 'amount',
        'sort_order': 30,
        'default_line': ['drafter', 'dept_head', 'executive'],
        'field_schema': [
            {'key': 'category', 'label': '구분', 'type': 'select', 'required': False,
             'options': ['구매', '계약', '인사', '일반', '기타']},
            {'key': 'amount', 'label': '금액(선택)', 'type': 'number', 'required': False, 'suffix': '원'},
            {'key': 'content', 'label': '품의내용', 'type': 'textarea', 'required': True},
        ],
    },
    {
        'form_key': 'trip',
        'name': '출장신청서',
        'icon': '🚗',
        'description': '국내/해외 출장 신청',
        'has_amount': False,
        'sort_order': 40,
        'default_line': ['drafter', 'dept_head', 'executive'],
        'field_schema': [
            {'key': 'destination', 'label': '출장지', 'type': 'text', 'required': True},
            {'key': 'start_date', 'label': '출발일', 'type': 'date', 'required': True},
            {'key': 'end_date', 'label': '복귀일', 'type': 'date', 'required': True},
            {'key': 'companions', 'label': '동행자', 'type': 'text', 'required': False},
            {'key': 'transport', 'label': '교통수단', 'type': 'select', 'required': False,
             'options': ['회사차량', '개인차량', '대중교통', '항공', '기타']},
            {'key': 'purpose', 'label': '출장목적', 'type': 'textarea', 'required': True},
        ],
    },
]


def seed_form_templates(db):
    """기본 양식이 없으면 시드. 이미 있으면 건드리지 않음(관리자 수정 보존)."""
    created = 0
    for spec in DEFAULT_FORMS:
        exists = db.query(ApprovalFormTemplate).filter_by(form_key=spec['form_key']).first()
        if exists:
            continue
        db.add(ApprovalFormTemplate(
            form_key=spec['form_key'],
            name=spec['name'],
            icon=spec.get('icon'),
            description=spec.get('description'),
            field_schema=spec['field_schema'],
            default_line=spec.get('default_line'),
            has_amount=spec.get('has_amount', False),
            amount_field=spec.get('amount_field'),
            sort_order=spec.get('sort_order', 0),
            is_active=True,
        ))
        created += 1
    if created:
        db.flush()
    return created


def get_active_forms(db):
    return (db.query(ApprovalFormTemplate)
            .filter(ApprovalFormTemplate.is_active.is_(True))
            .order_by(ApprovalFormTemplate.sort_order, ApprovalFormTemplate.id)
            .all())


# ────────────────────────────────────────────────────────
# 승인된 휴가 → 대시보드/현황판 부재 표시
# ────────────────────────────────────────────────────────

def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.datetime.strptime(str(s).strip()[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _approved_leave_docs(db):
    """효력 있는 휴가신청서 문서 (form_key='leave').
    최종 완료(approved) 또는 부서장 선효력(effect_active) 모두 포함."""
    from sqlalchemy import or_
    return (db.query(ApprovalDocument)
            .filter(ApprovalDocument.form_key == 'leave',
                    or_(ApprovalDocument.status == 'approved',
                        ApprovalDocument.effect_active.is_(True)))
            .all())


def _leave_event(doc):
    """휴가 문서 → 부재 이벤트 dict (iCal 이벤트와 동일 형태, end는 exclusive)."""
    fd = doc.form_data or {}
    # 신규: start_dt/end_dt (날짜+시각), 구버전: start_date/end_date
    start = _parse_date(fd.get('start_dt')) or _parse_date(fd.get('start_date'))
    end = _parse_date(fd.get('end_dt')) or _parse_date(fd.get('end_date')) or start
    if not start:
        return None
    return {
        'leave_type': fd.get('leave_type') or '휴가',
        'name': doc.drafter_name,
        'dept': doc.drafter_dept or '',
        'start': start,
        'end': end + datetime.timedelta(days=1),  # exclusive
        'source': 'approval',
        'doc_id': doc.id,
    }


def get_approved_leaves_for_date(db, target_date):
    """target_date에 휴가 중인 승인 문서 이벤트 목록."""
    out = []
    for doc in _approved_leave_docs(db):
        ev = _leave_event(doc)
        if ev and ev['start'] <= target_date < ev['end']:
            out.append(ev)
    return out


def get_approved_leaves_for_month(db, year, month):
    """월 단위 날짜별 휴가 이벤트 dict {date: [event, ...]}."""
    month_start = datetime.date(year, month, 1)
    month_end = datetime.date(year + 1, 1, 1) if month == 12 else datetime.date(year, month + 1, 1)
    result = {}
    for doc in _approved_leave_docs(db):
        ev = _leave_event(doc)
        if not ev:
            continue
        day = max(ev['start'], month_start)
        end = min(ev['end'], month_end)
        while day < end:
            result.setdefault(day, []).append(ev)
            day += datetime.timedelta(days=1)
    return result


# ────────────────────────────────────────────────────────
# 결재선 자동 구성
# ────────────────────────────────────────────────────────

def find_dept_head(db, dept, min_rank=0):
    """같은 부서에서 기안자보다 상위인 최상위 직급자(부서장) 반환.
    부서 최상위가 기안자 본인(또는 동급 이하)이면 None."""
    if not dept or dept in _EXCLUDED_GROUPS:
        return None
    candidates = (db.query(User)
                  .filter(User.is_active.is_(True), User.user_group == dept).all())
    candidates = [u for u in candidates if position_rank(u.position) > min_rank]
    if not candidates:
        return None
    candidates.sort(key=lambda u: position_rank(u.position), reverse=True)
    return candidates[0]


def get_senior_chain(db, min_rank=0):
    """부장 이상 경영진 전원을 직급 오름차순으로 반환.
    부장 → 이사 → 상무 → 전무 → 대표 순서로 모두 결재."""
    candidates = (db.query(User)
                  .filter(User.is_active.is_(True),
                          User.user_group.notin_(tuple(_EXCLUDED_GROUPS)))
                  .all())
    seniors = [u for u in candidates
               if position_rank(u.position) >= SENIOR_THRESHOLD
               and position_rank(u.position) > min_rank]
    seniors.sort(key=lambda u: position_rank(u.position))  # 오름차순 (부장→…→대표)
    return seniors


def resolve_default_line(db, drafter, line_tokens=None):
    """기본 결재선 토큰 → 실제 결재자 리스트(dict) 변환.

    기안자 → 부서장 → 부장 → 이사 → 상무 → 전무 → 대표 (존재자 전부).
    기안자보다 하위/동급, 중복은 제외.
    반환: [{approver_id, approver_name, approver_position, approver_dept, role}, ...]
    """
    tokens = line_tokens or ['dept_head', 'executive']
    drafter_rank = position_rank(drafter.position)
    steps = []
    seen = {drafter.id}

    def _add(user, role='approval'):
        if not user or user.id in seen:
            return
        # 기안자보다 상위 직급만
        if position_rank(user.position) <= drafter_rank:
            return
        seen.add(user.id)
        steps.append({
            'approver_id': user.id,
            'approver_name': user.full_name,
            'approver_position': user.position,
            'approver_dept': user.user_group,
            'role': role,
        })

    for tok in tokens:
        if tok == 'drafter':
            continue  # 기안자는 결재선에 넣지 않음
        elif tok == 'dept_head':
            _add(find_dept_head(db, drafter.user_group, min_rank=drafter_rank))
        elif tok == 'executive':
            for sr in get_senior_chain(db, min_rank=drafter_rank):
                _add(sr)
        elif isinstance(tok, int):
            _add(db.query(User).get(tok))
    return steps


# 양식별 기본 참조자 (이름 기준 — 동명이인 없음 확인됨)
# 휴가신청서·지출결의서 → 관리부 서은미 과장
DEFAULT_REF_NAMES = {
    'leave': ['서은미'],
    'expense': ['서은미'],
}


def resolve_default_refs(db, form_key):
    """양식별 기본 참조자 User 리스트를 반환한다. (없으면 빈 리스트)"""
    names = DEFAULT_REF_NAMES.get(form_key, [])
    out, seen = [], set()
    for nm in names:
        u = (db.query(User)
             .filter(User.full_name == nm, User.is_active.is_(True))
             .order_by(User.id).first())
        if u and u.id not in seen:
            seen.add(u.id)
            out.append(u)
    return out


# ────────────────────────────────────────────────────────
# 결재번호 채번
# ────────────────────────────────────────────────────────

def generate_doc_no(db):
    """EA-YYYY-NNNN 형식. 연도별 시퀀스."""
    year = datetime.date.today().year
    prefix = f'EA-{year}-'
    last = (db.query(ApprovalDocument)
            .filter(ApprovalDocument.doc_no.like(prefix + '%'))
            .order_by(ApprovalDocument.doc_no.desc())
            .first())
    if last and last.doc_no:
        try:
            seq = int(last.doc_no.rsplit('-', 1)[1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f'{prefix}{seq:04d}'


# ────────────────────────────────────────────────────────
# 상태 전이
# ────────────────────────────────────────────────────────

def submit_document(db, doc):
    """상신: draft → pending. 결재번호 부여, 1차 결재자 current 설정.

    결재선이 비어 있으면 — 기안자가 조직 최상위라 자동산정 결재선이 비는
    경우(= 본인 위로 결재권자가 없음)에 한해 '본인 전결'로 즉시 완료한다.
    권한이 있는 사람이 결재선을 임의로 비운 경우(상위 결재자가 존재)는 차단.
    """
    if doc.status != 'draft':
        raise ValueError('이미 상신된 문서입니다.')
    if not doc.steps:
        drafter = db.query(User).get(doc.drafter_id)
        if drafter and not resolve_default_line(db, drafter):
            return _self_approve(db, doc)
        raise ValueError('결재선이 비어 있습니다. 결재자를 1명 이상 지정하세요.')

    if not doc.doc_no:
        doc.doc_no = generate_doc_no(db)
    doc.status = 'pending'
    doc.submitted_at = datetime.datetime.now()

    ordered = sorted(doc.steps, key=lambda s: s.step_order)
    for i, s in enumerate(ordered):
        s.status = 'current' if i == 0 else 'waiting'
    doc.current_step = ordered[0].step_order
    _notify_next_approver(db, doc, ordered[0])
    return doc


def _self_approve(db, doc):
    """본인 전결: 결재권자가 없는 최상위 기안자 → 상신 즉시 전결 완료.

    기안자 본인을 role='전결' 단계로 1건 기록하고 문서를 approved 로 종료한다.
    """
    now = datetime.datetime.now()
    if not doc.doc_no:
        doc.doc_no = generate_doc_no(db)
    doc.status = 'approved'
    doc.submitted_at = now
    doc.completed_at = now
    doc.steps.append(ApprovalStep(
        step_order=1, approver_id=doc.drafter_id,
        approver_name=doc.drafter_name, approver_position=doc.drafter_position,
        approver_dept=doc.drafter_dept, role='전결', status='approved',
        acted_at=now, comment='본인 전결'))
    doc.current_step = 1
    _notify_completed(db, doc, approved=True)
    return doc


def _form_effect_on_dept_head(db, form_key):
    """양식이 '부서장 결재 시 효력 발생'으로 설정되었는지."""
    t = (db.query(ApprovalFormTemplate)
         .filter_by(form_key=form_key).first())
    return bool(t and getattr(t, 'effect_on_dept_head', False))


def approve_step(db, doc, step, comment=None):
    """현재 결재자가 승인. 다음 단계로 진행하거나 최종 완료.
    양식이 '부서장 전결 효력' 설정이면 첫 결재단계(부서장) 승인 시점에
    선효력(effect_active)을 발생시킨다 — 이후 임원 결재와 무관하게 효력 인정."""
    if doc.status != 'pending':
        raise ValueError('진행 중인 문서가 아닙니다.')
    if step.status != 'current':
        raise ValueError('현재 결재 차례가 아닙니다.')

    step.status = 'approved'
    step.comment = comment
    step.acted_at = datetime.datetime.now()
    _finalize_step_messages(db, doc, step, approved=True)  # 양쪽 채널 메시지 갱신(버튼 제거)

    ordered = sorted(doc.steps, key=lambda s: s.step_order)
    next_step = next((s for s in ordered if s.status == 'waiting'), None)

    # 부서장(첫 결재단계) 승인 → 선효력 발생 (양식 설정 시, 1회만)
    first_order = ordered[0].step_order if ordered else None
    if (not doc.effect_active and step.step_order == first_order
            and _form_effect_on_dept_head(db, doc.form_key)):
        doc.effect_active = True
        doc.effected_at = datetime.datetime.now()
        if next_step:  # 임원 결재가 남은 경우에만 별도 '효력발생' 알림
            _notify_effect_active(db, doc, step)

    if next_step:
        next_step.status = 'current'
        doc.current_step = next_step.step_order
        _notify_next_approver(db, doc, next_step)
    else:
        doc.status = 'approved'
        doc.completed_at = datetime.datetime.now()
        _notify_completed(db, doc, approved=True)
    return doc


def reject_step(db, doc, step, comment=None):
    """반려: 문서 전체 rejected. 기안자에게 알림."""
    if doc.status != 'pending':
        raise ValueError('진행 중인 문서가 아닙니다.')
    if step.status != 'current':
        raise ValueError('현재 결재 차례가 아닙니다.')

    step.status = 'rejected'
    step.comment = comment
    step.acted_at = datetime.datetime.now()
    _finalize_step_messages(db, doc, step, approved=False)  # 양쪽 채널 메시지 갱신(버튼 제거)
    doc.status = 'rejected'
    doc.completed_at = datetime.datetime.now()
    # 부서장 선효력이 발생했더라도 임원 반려 시 효력 취소
    if doc.effect_active:
        doc.effect_active = False
        doc.effected_at = None
    _notify_completed(db, doc, approved=False, rejecter=step)
    return doc


def cancel_document(db, doc):
    """회수: 기안자가 진행 중 문서를 회수. 첫 결재 승인 전에만 가능."""
    if doc.status != 'pending':
        raise ValueError('진행 중인 문서만 회수할 수 있습니다.')
    approved_exists = any(s.status == 'approved' for s in doc.steps)
    if approved_exists:
        raise ValueError('이미 결재가 진행되어 회수할 수 없습니다.')
    doc.status = 'canceled'
    doc.completed_at = datetime.datetime.now()
    for s in doc.steps:
        if s.status in ('current', 'waiting'):
            s.status = 'waiting'
    return doc


# ────────────────────────────────────────────────────────
# 알림 (notify 단일 진입점 — target_override 사용)
# ────────────────────────────────────────────────────────

def _doc_link(doc):
    base = (os.environ.get('SERVER_BASE_URL') or os.environ.get('ERP_BASE_URL') or '').rstrip('/')
    return f'{base}/approval/{doc.id}' if base else f'/approval/{doc.id}'


def _fmt_number(val, suffix=''):
    """숫자 천단위 콤마 + 접미사. 변환 실패 시 원문."""
    try:
        n = float(str(val).replace(',', ''))
        s = f'{int(n):,}' if n == int(n) else f'{n:,.2f}'.rstrip('0').rstrip('.')
        return f'{s}{suffix}'
    except (ValueError, TypeError):
        return f'{val}{suffix}'


def _fmt_lineitems(rows, columns):
    """lineitems(지출명세 등) 한 줄 요약: 건수 + 금액합계."""
    rows = rows or []
    if not rows:
        return ''
    amt_key = next((c.get('key') for c in (columns or []) if c.get('key') == 'amount'), None)
    total = 0
    if amt_key:
        for r in rows:
            try:
                total += float(str((r or {}).get(amt_key, 0)).replace(',', '') or 0)
            except (ValueError, TypeError):
                pass
    label_key = next((c.get('key') for c in (columns or []) if c.get('key') != amt_key), None)
    first = (rows[0] or {}).get(label_key, '') if label_key else ''
    head = f'{first} 외 {len(rows)-1}건' if len(rows) > 1 and first else (first or f'{len(rows)}건')
    return f'{head}' + (f' (합계 {_fmt_number(total, "원")})' if total else '')


def build_doc_summary(db, doc, max_fields=8):
    """양식 field_schema 기반으로 결재 내용을 'label : value' 리스트로 요약.

    빈 값/시스템 필드는 생략. textarea는 한 줄로 줄여 길이 제한.
    어떤 양식(커스텀 포함)에도 동작하도록 스키마 주도 방식.
    """
    fd = doc.form_data or {}
    lines = []
    tmpl = (db.query(ApprovalFormTemplate)
            .filter_by(form_key=doc.form_key).first()) if doc.form_key else None
    schema = (tmpl.field_schema if tmpl else None) or []
    for fld in schema:
        if len(lines) >= max_fields:
            break
        key, label, ftype = fld.get('key'), fld.get('label', ''), fld.get('type')
        if not key:
            continue
        raw = fd.get(key)
        if ftype == 'lineitems':
            val = _fmt_lineitems(raw, fld.get('columns'))
        elif raw in (None, '', [], {}):
            continue
        elif ftype == 'number':
            val = _fmt_number(raw, fld.get('suffix', ''))
        elif ftype == 'textarea':
            val = ' '.join(str(raw).split())
            if len(val) > 100:
                val = val[:100] + '…'
        else:
            val = str(raw)
            if fld.get('suffix'):
                val = f'{val} {fld["suffix"]}'
        if val in (None, ''):
            continue
        lines.append(f'{label} : {val}')
    # 스키마가 없거나 비면 공통 필드로 폴백
    if not lines:
        if doc.amount:
            lines.append(f'금액 : {_fmt_number(doc.amount, "원")}')
        if doc.content:
            c = ' '.join(str(doc.content).split())
            lines.append(f'내용 : {c[:100] + ("…" if len(c) > 100 else "")}')
    return lines


def _send_mm_dm(db, user_id, message, attachments=None):
    """대상 사용자에게 Mattermost DM (username 기준). 실패 무시."""
    try:
        u = db.query(User).get(user_id)
        if not u or not u.username:
            return
        from modules.services.mattermost_api import send_dm
        send_dm(u.username, message, attachments=attachments)
    except Exception:
        pass


def _mm_approval_buttons(doc, step, summary_lines=None, reminder_days=None):
    """Mattermost 결재요청 DM용 승인/반려 버튼 attachment.

    integration.url = ERP 콜백(/mattermost/action). context.data에 doc/step id.
    summary_lines: 결재 내용 요약(label : value 리스트) — 본문에 표로 표시.
    reminder_days: 지정 시 '미결재 독촉' 헤더로 표시(경과일수).
    """
    base = (os.environ.get('ERP_BASE_URL') or os.environ.get('SERVER_BASE_URL') or '').rstrip('/')
    action_url = f'{base}/mattermost/action'
    data = {'doc_id': doc.id, 'step_id': step.id}
    if reminder_days is not None:
        wtxt = f"{reminder_days}일 경과" if reminder_days > 0 else "오늘 접수"
        head = f"⏰ **미결재 독촉** — {doc.form_name} ({wtxt})"
    else:
        head = f"📋 **결재요청** — {doc.form_name}"
    body = (f"{head}\n"
            f"기안자 : {doc.drafter_name}\n"
            f"제목 : **{doc.title}**")
    if summary_lines:
        body += "\n\n" + "\n".join(f"• {ln}" for ln in summary_lines)
    return [{
        'color': '#2d8cff',
        'text': body,
        'actions': [
            {'id': 'approve', 'name': '✅ 승인', 'style': 'good',
             'integration': {'url': action_url,
                             'context': {'action_type': 'approval_approve', 'data': data}}},
            {'id': 'reject', 'name': '❌ 반려', 'style': 'danger',
             'integration': {'url': action_url,
                             'context': {'action_type': 'approval_reject', 'data': data}}},
        ],
    }]


def _send_kakao_approval_dm(db, doc, step, summary_lines=None, reminder_days=None):
    """결재자에게 카카오워크 승인/반려 버튼 DM. 성공 시 {'conversation_id','message_id'} 반환."""
    try:
        u = db.query(User).get(step.approver_id)
        if not u:
            return None
        from modules.kakaowork_notifier import send_approval_request_dm
        return send_approval_request_dm(
            approver_name=step.approver_name or u.full_name,
            approver_dept=step.approver_dept or (u.user_group or ''),
            approver_email=u.email or '',
            doc_id=doc.id, step_id=step.id,
            form_name=doc.form_name, drafter_name=doc.drafter_name,
            title=doc.title, doc_link=_doc_link(doc),
            summary_lines=summary_lines or [], reminder_days=reminder_days)
    except Exception:
        return None


def _send_approval_request_dms(db, doc, step, reminder_days=None):
    """결재요청/독촉 버튼 DM을 MM+카카오 양쪽 발송하고 메시지 참조를 step.notify_refs에 저장.

    저장된 참조는 한쪽에서 처리 시 양쪽 메시지 갱신(_finalize_step_messages)에 사용.
    """
    try:
        summary = build_doc_summary(db, doc)
    except Exception:
        summary = []
    head = "⏰ **미결재 독촉**" if reminder_days is not None else "📋 **결재요청**"
    summary_block = ("\n" + "\n".join(f"  · {ln}" for ln in summary)) if summary else ""
    refs = dict(step.notify_refs or {})
    # Mattermost (post 참조 반환)
    try:
        u = db.query(User).get(step.approver_id)
        if u and u.username:
            from modules.services.mattermost_api import send_dm_with_ref
            ref = send_dm_with_ref(
                u.username,
                f"{head} — {doc.form_name}\n"
                f"기안자 : {doc.drafter_name}\n"
                f"제목 : **{doc.title}**{summary_block}\n"
                f"→ [결재하기]({_doc_link(doc)})",
                attachments=_mm_approval_buttons(doc, step, summary, reminder_days=reminder_days))
            if ref:
                refs['mm'] = ref
    except Exception:
        pass
    # KakaoWork (conversation/message 참조 반환)
    kref = _send_kakao_approval_dm(db, doc, step, summary, reminder_days=reminder_days)
    if kref:
        refs['kakao'] = kref
    step.notify_refs = refs or None


def _send_kakao_text_to_user(db, user_id, text):
    """ERP User → 카카오워크(이름+부서 매칭) 단순 텍스트 DM. 실패 무시."""
    try:
        u = db.query(User).get(user_id)
        if not u:
            return
        from modules.kakaowork_notifier import find_user_id, send_dm_text
        uid = find_user_id(u.full_name, dept=u.user_group or '', email=u.email or '')
        if uid:
            send_dm_text(uid, text)
    except Exception:
        pass


def _finalize_step_messages(db, doc, step, approved):
    """결재 처리(승인/반려) 후 양쪽 채널 알림 메시지 갱신.

    - Mattermost: 메시지를 '처리완료'로 수정 + 버튼 제거 (작성자=결재봇 토큰).
    - KakaoWork: 메시지 수정/삭제 API가 없어 '처리완료' 후속 메시지 발송(남은 버튼은 가드됨).
    """
    refs = step.notify_refs or {}
    verb = "승인" if approved else "반려"
    icon = "✅" if approved else "❌"
    txt = (f"{icon} {verb} 완료 — [{doc.doc_no or ''}] {doc.title}\n"
           f"처리자 : {step.approver_name}")
    mm = refs.get('mm') or {}
    if mm.get('post_id'):
        try:
            from modules.services.mattermost_api import update_approval_post
            update_approval_post(mm['post_id'], txt)
        except Exception:
            pass
    kakao = refs.get('kakao') or {}
    if kakao.get('conversation_id'):
        try:
            from modules.kakaowork_notifier import send_text_to_conversation
            send_text_to_conversation(kakao['conversation_id'],
                                      txt + "\n(처리되어 위 버튼은 더 이상 유효하지 않습니다.)")
        except Exception:
            pass


def _notify_next_approver(db, doc, step):
    """결재 차례가 된 사람에게 ERP 알림 + Mattermost/카카오워크 버튼 DM."""
    try:
        from modules.notification_engine import notify
        notify(db, 'approval.requested', {
            'doc_id': doc.id,
            'doc_no': doc.doc_no or '',
            'form_name': doc.form_name,
            'title': doc.title,
            'drafter_name': doc.drafter_name,
        }, target_override=f'user:{step.approver_id}',
            dedupe_key=f'approval.requested:{doc.id}:step{step.step_order}')
    except Exception:
        pass
    _send_approval_request_dms(db, doc, step)


def send_pending_reminders(db):
    """미결재(현재 차례) 문서를 결재자별로 모아 독촉 알림 — ERP 인앱 + MM/카카오 DM.

    매일 09:00 crontab(remind-pending-approvals)에서 호출. 반환 (결재자수, 문서수).
    """
    steps = (db.query(ApprovalStep)
             .join(ApprovalDocument, ApprovalStep.document_id == ApprovalDocument.id)
             .filter(ApprovalDocument.status == 'pending', ApprovalStep.status == 'current')
             .all())
    by_approver = {}
    for s in steps:
        by_approver.setdefault(s.approver_id, []).append(s)

    now = datetime.datetime.now()
    total_docs = 0
    for approver_id, slist in by_approver.items():
        docs_info = []
        for s in slist:
            doc = s.document
            base_dt = doc.submitted_at or doc.created_at
            waited = (now - base_dt).days if base_dt else 0
            docs_info.append((doc, s, waited))
        docs_info.sort(key=lambda x: x[2], reverse=True)  # 오래 대기한 순
        total_docs += len(docs_info)

        # ERP 인앱 알림 (하루 1회 dedupe — 건수 요약)
        try:
            from modules.notification_engine import notify
            notify(db, 'approval.reminder', {'pending_count': len(docs_info)},
                   target_override=f'user:{approver_id}',
                   dedupe_key=f'approval.reminder:{approver_id}:{now.strftime("%Y%m%d")}')
        except Exception:
            pass
        # 문서별 버튼 DM (승인/반려 + 카카오 상세보기) — 독촉 헤더, 메시지 참조 갱신
        for doc, step, waited in docs_info:
            _send_approval_request_dms(db, doc, step, reminder_days=waited)
    return len(by_approver), total_docs


def _notify_effect_active(db, doc, step):
    """부서장 결재로 선효력 발생 → 기안자·참조자에게 알림 (임원 결재는 진행 중)."""
    try:
        from modules.notification_engine import notify
        targets = [f'user:{doc.drafter_id}']
        for ref in doc.references:
            targets.append(f'user:{ref.user_id}')
        notify(db, 'approval.effected', {
            'doc_id': doc.id,
            'doc_no': doc.doc_no or '',
            'form_name': doc.form_name,
            'title': doc.title,
            'approver_name': step.approver_name,
        }, target_override=targets,
            dedupe_key=f'approval.effected:{doc.id}')
    except Exception:
        pass
    link = _doc_link(doc)
    _send_mm_dm(db, doc.drafter_id,
                f"📌 **효력발생** — {doc.form_name}\n"
                f"**{doc.title}** — {step.approver_name}님 결재로 효력이 발생했습니다 "
                f"(임원 결재 진행 중)\n→ [문서보기]({link})")
    _send_kakao_text_to_user(db, doc.drafter_id,
                f"📌 효력발생 — {doc.form_name}\n{doc.title} — {step.approver_name}님 결재로 효력이 "
                f"발생했습니다 (임원 결재 진행 중).\n{link}")


def _notify_completed(db, doc, approved, rejecter=None):
    """기안자·참조자에게 ERP 알림 + 기안자에게 Mattermost DM."""
    try:
        from modules.notification_engine import notify
        event = 'approval.approved' if approved else 'approval.rejected'
        targets = [f'user:{doc.drafter_id}']
        for ref in doc.references:
            targets.append(f'user:{ref.user_id}')
        notify(db, event, {
            'doc_id': doc.id,
            'doc_no': doc.doc_no or '',
            'form_name': doc.form_name,
            'title': doc.title,
            'rejecter_name': rejecter.approver_name if rejecter else '',
        }, target_override=targets,
            dedupe_key=f'{event}:{doc.id}')
    except Exception:
        pass
    link = _doc_link(doc)
    if approved:
        msg = (f"✅ **결재완료** — {doc.form_name}\n"
               f"**{doc.title}** 최종 승인되었습니다\n→ [문서보기]({link})")
        kakao_txt = f"✅ 결재완료 — {doc.form_name}\n{doc.title} 최종 승인되었습니다.\n{link}"
    else:
        who = rejecter.approver_name if rejecter else ''
        msg = (f"⛔ **결재반려** — {doc.form_name}\n"
               f"**{doc.title}** — {who}님이 반려\n→ [문서보기]({link})")
        kakao_txt = f"⛔ 결재반려 — {doc.form_name}\n{doc.title} — {who}님이 반려했습니다.\n{link}"
    _send_mm_dm(db, doc.drafter_id, msg)
    _send_kakao_text_to_user(db, doc.drafter_id, kakao_txt)
