"""전자결재 도메인 Tools (4개)

approval_documents / approval_steps / approval_comments 조회.
휴가·지출·품의·출장·연장근무 양식을 다루며, 상태값은 DB 원문(draft/pending/
approved/rejected/canceled) 대신 한글 라벨을 함께 반환한다.
"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s

# DB 상태 ↔ 한글 (approval_entities.DOC_STATUS 와 동일)
_DOC_STATUS = {
    'draft': '작성중', 'pending': '진행중', 'approved': '완료',
    'rejected': '반려', 'canceled': '회수',
}
_STEP_STATUS = {
    'waiting': '대기', 'current': '결재중', 'approved': '승인', 'rejected': '반려',
}
# 한글 → DB (사용자가 '진행중' 같은 말로 물어볼 때)
_STATUS_KO2EN = {v: k for k, v in _DOC_STATUS.items()}
_FORM_KO2EN = {
    '휴가': 'leave', '휴가신청서': 'leave', '연차': 'leave',
    '지출': 'expense', '지출결의서': 'expense',
    '품의': 'proposal', '품의서': 'proposal',
    '출장': 'trip', '출장신청서': 'trip',
    '연장근무': 'overtime', '야근': 'overtime',
}


def _resolve_user(session, username):
    """Mattermost username / 이메일 로컬파트 / 실명 → User."""
    from modules.models.entities import User
    if not username:
        return None
    u = session.query(User).filter(User.username == username).first()
    if not u:
        u = session.query(User).filter(User.email.ilike(f"{username}@%")).first()
    if not u:
        u = session.query(User).filter(User.full_name == username).first()
    return u


def _doc_brief(d):
    return {
        "id": d.id,
        "doc_no": _s(d.doc_no),
        "form_key": _s(d.form_key),
        "form_name": _s(d.form_name),
        "title": _s(d.title),
        "drafter": _s(d.drafter_name),
        "drafter_dept": _s(d.drafter_dept),
        "status": _DOC_STATUS.get(d.status, _s(d.status)),
        "current_step": d.current_step,
        "effect_active": bool(d.effect_active),
        "amount": int(d.amount) if d.amount is not None else None,
        "submitted_at": d.submitted_at.strftime('%Y-%m-%d %H:%M') if d.submitted_at else "",
        "completed_at": d.completed_at.strftime('%Y-%m-%d %H:%M') if d.completed_at else "",
    }


def register(mcp: FastMCP):

    @mcp.tool()
    def get_approval_documents(
        status: Optional[str] = None,
        form: Optional[str] = None,
        drafter: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 30,
    ) -> str:
        """전자결재 문서 목록 조회.
        ★ '결재 문서', '올라온 결재', '반려된 거', '이번달 지출결의' 등의 질문에 사용.

        Args:
            status: 작성중 / 진행중 / 완료 / 반려 / 회수 (생략 시 전체)
            form: 휴가 / 지출 / 품의 / 출장 / 연장근무 (생략 시 전체)
            drafter: 기안자 이름
            search: 제목 검색
            limit: 최대 건수 (기본 30, 최신순)
        """
        from modules.models import ApprovalDocument
        session = get_session()
        try:
            q = session.query(ApprovalDocument)
            if status:
                q = q.filter(ApprovalDocument.status == _STATUS_KO2EN.get(status, status))
            if form:
                q = q.filter(ApprovalDocument.form_key == _FORM_KO2EN.get(form, form))
            if drafter:
                q = q.filter(ApprovalDocument.drafter_name.ilike(f"%{drafter}%"))
            if search:
                q = q.filter(ApprovalDocument.title.ilike(f"%{search}%"))

            docs = q.order_by(ApprovalDocument.id.desc()).limit(limit).all()
            items = [_doc_brief(d) for d in docs]

            by_status = {}
            for it in items:
                by_status[it["status"]] = by_status.get(it["status"], 0) + 1

            return json.dumps({
                "count": len(items),
                "by_status": by_status,
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_approval_detail(
        doc_id: Optional[int] = None,
        doc_no: Optional[str] = None,
    ) -> str:
        """전자결재 문서 상세 — 양식 입력값, 결재선 진행상태, 의견까지.
        ★ 'EA-2026-0008 어떻게 됐어', '그 휴가신청 누가 결재중이야' 등에 사용.

        Args:
            doc_id: 문서 ID
            doc_no: 문서번호 (예: EA-2026-0008)
        """
        from modules.models import ApprovalDocument
        if not doc_id and not doc_no:
            return json.dumps({"error": "doc_id 또는 doc_no 가 필요합니다."}, ensure_ascii=False)
        session = get_session()
        try:
            q = session.query(ApprovalDocument)
            d = (q.filter(ApprovalDocument.id == doc_id).first() if doc_id
                 else q.filter(ApprovalDocument.doc_no == doc_no).first())
            if not d:
                return json.dumps({"error": "문서를 찾을 수 없습니다."}, ensure_ascii=False)

            out = _doc_brief(d)
            out["content"] = _s(d.content)
            out["form_data"] = d.form_data or {}
            out["steps"] = [{
                "order": s.step_order,
                "approver": _s(s.approver_name),
                "position": _s(s.approver_position),
                "dept": _s(s.approver_dept),
                "role": '합의' if s.role == 'agreement' else '결재',
                "status": _STEP_STATUS.get(s.status, _s(s.status)),
                "comment": _s(s.comment),
                "acted_at": s.acted_at.strftime('%Y-%m-%d %H:%M') if s.acted_at else "",
            } for s in d.steps]
            out["comments"] = [{
                "user": _s(c.user_name),
                "content": _s(c.content),
                "created_at": c.created_at.strftime('%Y-%m-%d %H:%M') if c.created_at else "",
            } for c in d.comments]
            out["references"] = [_s(r.user_name) for r in d.references]
            out["attachment_count"] = len(d.attachments)

            cur = d.current_approver_step()
            out["waiting_on"] = _s(cur.approver_name) if cur else ""

            return json.dumps(out, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_my_pending_approvals(requester_username: str) -> str:
        """내가 지금 결재해야 할 문서 목록 (결재 차례가 나에게 온 것).
        ★ '내가 결재할 거 있어?', '결재 대기 뭐 있어' 질문에 사용.

        Args:
            requester_username: 요청자 계정명 (Mattermost username / 메일 아이디 / 실명)
        """
        from modules.models import ApprovalDocument
        from modules.models.approval_entities import ApprovalStep
        session = get_session()
        try:
            user = _resolve_user(session, requester_username)
            if not user:
                return json.dumps({"error": f"사용자를 찾을 수 없습니다: {requester_username}"},
                                  ensure_ascii=False)

            steps = (session.query(ApprovalStep)
                     .filter(ApprovalStep.approver_id == user.id,
                             ApprovalStep.status == 'current')
                     .all())
            doc_ids = [s.document_id for s in steps]
            docs = []
            if doc_ids:
                docs = (session.query(ApprovalDocument)
                        .filter(ApprovalDocument.id.in_(doc_ids),
                                ApprovalDocument.status == 'pending')
                        .order_by(ApprovalDocument.submitted_at.asc().nullslast())
                        .all())

            return json.dumps({
                "user": _s(user.full_name),
                "pending_count": len(docs),
                "items": [_doc_brief(d) for d in docs],
                "note": "결재 차례(step.status='current')가 본인에게 온 진행중 문서만.",
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_my_approval_drafts(requester_username: str, limit: int = 20) -> str:
        """내가 상신한 결재 문서와 진행 상태.
        ★ '내 결재 어디까지 갔어', '내가 올린 거 상태' 질문에 사용.

        Args:
            requester_username: 요청자 계정명
            limit: 최대 건수 (기본 20, 최신순)
        """
        from modules.models import ApprovalDocument
        session = get_session()
        try:
            user = _resolve_user(session, requester_username)
            if not user:
                return json.dumps({"error": f"사용자를 찾을 수 없습니다: {requester_username}"},
                                  ensure_ascii=False)

            docs = (session.query(ApprovalDocument)
                    .filter(ApprovalDocument.drafter_id == user.id)
                    .order_by(ApprovalDocument.id.desc())
                    .limit(limit).all())

            items = []
            for d in docs:
                b = _doc_brief(d)
                cur = d.current_approver_step()
                b["waiting_on"] = _s(cur.approver_name) if cur else ""
                items.append(b)

            return json.dumps({
                "user": _s(user.full_name),
                "count": len(items),
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()
