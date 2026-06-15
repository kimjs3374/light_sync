"""전자결재 비즈니스 로직

- 기본 양식 4종 시드 (휴가/지출결의/품의/출장) — 관리자가 추후 수정/추가 가능
- 직급/부서 기반 기본 결재선 자동 구성 (기안자 → 부서장 → 대표)
- 결재번호 채번 (EA-YYYY-NNNN)
- 상신/승인/반려/회수 상태 전이 + 알림
"""
import datetime

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
    """승인 완료된 휴가신청서 문서 (form_key='leave')."""
    return (db.query(ApprovalDocument)
            .filter(ApprovalDocument.form_key == 'leave',
                    ApprovalDocument.status == 'approved')
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
    """상신: draft → pending. 결재번호 부여, 1차 결재자 current 설정."""
    if doc.status != 'draft':
        raise ValueError('이미 상신된 문서입니다.')
    if not doc.steps:
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


def approve_step(db, doc, step, comment=None):
    """현재 결재자가 승인. 다음 단계로 진행하거나 최종 완료."""
    if doc.status != 'pending':
        raise ValueError('진행 중인 문서가 아닙니다.')
    if step.status != 'current':
        raise ValueError('현재 결재 차례가 아닙니다.')

    step.status = 'approved'
    step.comment = comment
    step.acted_at = datetime.datetime.now()

    ordered = sorted(doc.steps, key=lambda s: s.step_order)
    next_step = None
    for s in ordered:
        if s.status == 'waiting':
            next_step = s
            break

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
    doc.status = 'rejected'
    doc.completed_at = datetime.datetime.now()
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
    base = os.environ.get('SERVER_BASE_URL', '').rstrip('/')
    return f'{base}/approval/{doc.id}' if base else f'/approval/{doc.id}'


def _send_mm_dm(db, user_id, message):
    """대상 사용자에게 Mattermost DM (username 기준). 실패 무시."""
    try:
        u = db.query(User).get(user_id)
        if not u or not u.username:
            return
        from modules.services.mattermost_api import send_dm
        send_dm(u.username, message)
    except Exception:
        pass


def _notify_next_approver(db, doc, step):
    """결재 차례가 된 사람에게 ERP 알림 + Mattermost DM."""
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
    _send_mm_dm(db, step.approver_id,
                f"📋 **결재요청** — {doc.form_name}\n"
                f"{doc.drafter_name}님이 상신: **{doc.title}**\n"
                f"→ [결재하기]({_doc_link(doc)})")


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
    if approved:
        msg = (f"✅ **결재완료** — {doc.form_name}\n"
               f"**{doc.title}** 최종 승인되었습니다\n→ [문서보기]({_doc_link(doc)})")
    else:
        who = rejecter.approver_name if rejecter else ''
        msg = (f"⛔ **결재반려** — {doc.form_name}\n"
               f"**{doc.title}** — {who}님이 반려\n→ [문서보기]({_doc_link(doc)})")
    _send_mm_dm(db, doc.drafter_id, msg)
