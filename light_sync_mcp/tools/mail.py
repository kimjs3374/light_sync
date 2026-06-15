"""FR-29: 메일 도메인 Tools (2개)

거래처 이메일 주소록(mail_contacts) + 이메일 송수신 이력(email_history) 검색.
DB 데이터: 약 1,100건 — 챗봇이 "xx회사 이메일 뭐야?", "최근 누구한테 메일 보냈어?"
같은 질문에 답할 수 있게 함.
"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_mail_contacts(
        query: Optional[str] = None,
        is_shared: Optional[bool] = None,
        limit: int = 30,
    ) -> str:
        """거래처 이메일 주소록 검색 — 이름/회사/이메일/메모에서 부분 검색.

        Args:
            query: 검색어 (이름, 회사명, 이메일, 메모 어디든 매칭)
            is_shared: True 면 공유 주소록만, False 면 개인만, None 이면 전체
            limit: 최대 반환 건수 (기본 30)
        """
        from sqlalchemy import text, or_, bindparam
        session = get_session()
        try:
            sql_parts = ["SELECT id, name, email, company, memo, is_shared, user_id, created_at",
                         "FROM light_sync.mail_contacts WHERE 1=1"]
            params = {}
            if query:
                sql_parts.append(
                    " AND (name ILIKE :q OR email ILIKE :q OR company ILIKE :q OR memo ILIKE :q)"
                )
                params['q'] = f'%{query}%'
            if is_shared is True:
                sql_parts.append(" AND is_shared = TRUE")
            elif is_shared is False:
                sql_parts.append(" AND is_shared = FALSE")
            sql_parts.append(" ORDER BY created_at DESC NULLS LAST LIMIT :lim")
            params['lim'] = limit

            rows = session.execute(text(' '.join(sql_parts)), params).fetchall()
            return json.dumps([{
                "id": r.id,
                "name": _s(r.name),
                "email": _s(r.email),
                "company": _s(r.company),
                "memo": _s(r.memo),
                "is_shared": bool(r.is_shared),
                "user_id": r.user_id,
                "created_at": _sd(r.created_at),
            } for r in rows], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_email_history(
        query: Optional[str] = None,
        sender: Optional[str] = None,
        receiver: Optional[str] = None,
        po_ref: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        only_success: bool = False,
        months_back: int = 24,
        include_old: bool = False,
        limit: int = 30,
    ) -> str:
        """이메일 송수신 이력 조회. 최근 24개월 기본, include_old=True 시 전체.

        Args:
            query: 제목/본문 검색어
            sender: 보낸 사람 (부분 일치)
            receiver: 받는 사람 (부분 일치)
            po_ref: PO 번호 연결 (예: 'PO-2026-001')
            date_from / date_to: YYYY-MM-DD
            only_success: True 면 발송 성공한 것만
            months_back: 최근 N개월 (기본 24). date_from 명시 또는 include_old 시 무시.
            include_old: True 면 전체 기간 (기본 False)
            limit: 최대 반환 (기본 30, 최신순)
        """
        from modules.models.entities import EmailHistory
        from sqlalchemy import or_
        import datetime
        session = get_session()
        try:
            q = session.query(EmailHistory)
            if query:
                q = q.filter(or_(
                    EmailHistory.subject.ilike(f'%{query}%'),
                    EmailHistory.content.ilike(f'%{query}%'),
                ))
            if sender:
                q = q.filter(EmailHistory.sender.ilike(f'%{sender}%'))
            if receiver:
                q = q.filter(EmailHistory.receiver.ilike(f'%{receiver}%'))
            if po_ref:
                q = q.filter(EmailHistory.po_ref.ilike(f'%{po_ref}%'))
            if date_from:
                q = q.filter(EmailHistory.send_date >= date_from)
            if date_to:
                q = q.filter(EmailHistory.send_date <= date_to)
            if only_success:
                q = q.filter(EmailHistory.is_success == True)
            # 기간 필터 — date_from/include_old 명시 안 됐을 때만
            cutoff = None
            if not date_from and not include_old and months_back > 0:
                cutoff = datetime.datetime.now() - datetime.timedelta(days=30 * months_back)
                q = q.filter(EmailHistory.send_date >= cutoff)
            mails = q.order_by(EmailHistory.send_date.desc().nullslast()).limit(limit).all()

            items = [{
                "id": m.id,
                "send_date": _sd(m.send_date),
                "sender": _s(m.sender),
                "receiver": _s(m.receiver),
                "subject": _s(m.subject),
                "content_preview": (m.content or '')[:200],
                "attachment": _s(m.attachment),
                "po_ref": _s(m.po_ref),
                "is_success": bool(m.is_success),
                "error_message": _s(m.error_message) if not m.is_success else None,
            } for m in mails]
            return json.dumps({
                "count": len(items),
                "filter_cutoff_date": str(cutoff)[:10] if cutoff else None,
                "include_old": include_old,
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()

    # ══════════════════════════════════════════════════════════════════════
    # IMAP 도구 — 실 메일함 조회 (Phase 1)
    # 핵심: requester_username 기반 권한 격리.
    # 다른 사람 메일 계정 접근 절대 금지 (mail_shared_access 권한 검증).
    # ══════════════════════════════════════════════════════════════════════

    def _resolve_mail_user(session, requester_username):
        """Mattermost username → User 객체. None 반환 시 권한 없음."""
        if not requester_username:
            return None
        from modules.models.entities import User
        u = session.query(User).filter(User.username == requester_username).first()
        if not u:
            u = session.query(User).filter(
                User.email.ilike(f"{requester_username}@%")
            ).first()
        return u

    def _accessible_accounts(session, user):
        """user 가 접근 가능한 mail_accounts 전체 (개인 + 공유)."""
        from modules.models.mail_entities import MailAccount, MailSharedAccess
        personal = session.query(MailAccount).filter_by(
            user_id=user.id, is_shared=False, is_active=True
        ).all()
        shared_ids = [r[0] for r in session.query(MailSharedAccess.mail_account_id)
                      .filter_by(user_id=user.id).all()]
        shared = []
        if shared_ids:
            shared = session.query(MailAccount).filter(
                MailAccount.id.in_(shared_ids),
                MailAccount.is_active == True,
            ).all()
        if (user.role or '').lower() == 'admin':
            all_shared = session.query(MailAccount).filter_by(
                is_shared=True, is_active=True
            ).all()
            existing = {a.id for a in shared}
            for a in all_shared:
                if a.id not in existing:
                    shared.append(a)
        return personal + shared

    def _open_imap(session, user, account_id=None):
        """권한 검증 + IMAP 클라이언트 생성. Returns (client_ctx, account, err)."""
        from modules.models.mail_entities import MailAccount, MailSharedAccess
        from modules.services.mail_client import MailClient, decrypt_password

        accessible = _accessible_accounts(session, user)
        accessible_ids = {a.id for a in accessible}

        if account_id:
            if account_id not in accessible_ids:
                return None, None, f"접근 권한 없는 mail_account_id={account_id} (사용자 '{user.username}' 의 권한 범위 밖)"
            account = session.get(MailAccount, account_id)
        else:
            account = next((a for a in accessible if not a.is_shared and a.user_id == user.id), None)
            if not account and accessible:
                account = accessible[0]
        if not account:
            return None, None, f"사용자 '{user.username}' 가 사용할 수 있는 메일 계정 없음"

        try:
            password = decrypt_password(account.password_encrypted)
        except Exception as e:
            return None, None, f"메일 비밀번호 복호화 실패: {e!s:.60}"

        client = MailClient(
            imap_host=account.imap_host, imap_port=account.imap_port,
            smtp_host=account.smtp_host, smtp_port=account.smtp_port,
            username=account.username, password=password,
            use_ssl=account.use_ssl,
        )
        return client, account, None

    @mcp.tool()
    def list_mail_accounts(requester_username: str) -> str:
        """사용자가 접근 가능한 메일 계정 목록 — 개인 + 공유 (권한 격리).

        Args:
            requester_username: 챗봇 채널 발신자 username (필수).
                                User 매칭 실패 시 빈 목록 반환.
        """
        session = get_session()
        try:
            user = _resolve_mail_user(session, requester_username)
            if not user:
                return json.dumps({
                    "status": "error",
                    "message": f"사용자 '{requester_username}' 식별 실패. 메일 접근 불가."
                }, ensure_ascii=False)
            accounts = _accessible_accounts(session, user)
            return json.dumps({
                "user": user.username,
                "user_full_name": _s(user.full_name),
                "count": len(accounts),
                "items": [{
                    "id": a.id,
                    "email": _s(a.email),
                    "display_name": _s(a.display_name),
                    "is_shared": bool(a.is_shared),
                    "account_type": _s(getattr(a, 'account_type', None)),
                    "is_personal": (a.user_id == user.id and not a.is_shared),
                } for a in accounts],
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def list_mail_folders(requester_username: str, account_id: Optional[int] = None) -> str:
        """메일 폴더 목록 (INBOX/Sent/Drafts/라벨 등). 권한 격리.

        Args:
            requester_username: 챗봇 발신자 (필수)
            account_id: 특정 계정 (생략 시 사용자의 개인 계정)
        """
        session = get_session()
        try:
            user = _resolve_mail_user(session, requester_username)
            if not user:
                return json.dumps({"status": "error",
                    "message": f"사용자 '{requester_username}' 식별 실패."}, ensure_ascii=False)
            client, account, err = _open_imap(session, user, account_id)
            if err:
                return json.dumps({"status": "error", "message": err}, ensure_ascii=False)
            try:
                with client as c:
                    folders = c.list_folders(all_unread=False)
            except Exception as e:
                return json.dumps({"status": "error",
                    "message": f"IMAP 연결 실패: {e!s:.100}"}, ensure_ascii=False)
            return json.dumps({
                "account_id": account.id,
                "account_email": _s(account.email),
                "folders": folders,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def list_inbox_messages(
        requester_username: str,
        account_id: Optional[int] = None,
        folder: str = "INBOX",
        limit: int = 30,
        unseen_only: bool = False,
    ) -> str:
        """받은편지함 메시지 목록 — 제목/보낸이/날짜/읽음 여부. 권한 격리.

        Args:
            requester_username: 챗봇 발신자 (필수)
            account_id: 특정 계정 (생략 시 사용자 개인 계정)
            folder: 폴더명 (기본 INBOX)
            limit: 최대 반환 (기본 30, 최신순)
            unseen_only: True 면 안 읽은 메일만
        """
        session = get_session()
        try:
            user = _resolve_mail_user(session, requester_username)
            if not user:
                return json.dumps({"status": "error",
                    "message": f"사용자 '{requester_username}' 식별 실패."}, ensure_ascii=False)
            client, account, err = _open_imap(session, user, account_id)
            if err:
                return json.dumps({"status": "error", "message": err}, ensure_ascii=False)
            try:
                criteria = "UNSEEN" if unseen_only else "ALL"
                with client as c:
                    result = c.fetch_messages(folder=folder, page=1,
                                              per_page=limit, search_criteria=criteria)
            except Exception as e:
                return json.dumps({"status": "error",
                    "message": f"IMAP 조회 실패: {e!s:.100}"}, ensure_ascii=False)
            # result 는 list 또는 dict — mail_client.fetch_messages 동작에 맞춤
            msgs = result.get('messages', []) if isinstance(result, dict) else (result or [])
            total = result.get('total', len(msgs)) if isinstance(result, dict) else len(msgs)
            return json.dumps({
                "account_id": account.id,
                "account_email": _s(account.email),
                "folder": folder,
                "total": total,
                "returned": len(msgs),
                "items": msgs,
            }, ensure_ascii=False, default=str)
        finally:
            session.close()

    @mcp.tool()
    def search_mailbox(
        requester_username: str,
        query: str,
        account_id: Optional[int] = None,
        folder: str = "INBOX",
        limit: int = 30,
    ) -> str:
        """메일함 검색 (서버측 IMAP SEARCH) — 제목/보낸이/본문. 권한 격리.

        Args:
            requester_username: 챗봇 발신자 (필수)
            query: 검색어
            account_id: 특정 계정 (생략 시 개인 계정)
            folder: 폴더 (기본 INBOX)
            limit: 최대 반환 (기본 30)
        """
        session = get_session()
        try:
            user = _resolve_mail_user(session, requester_username)
            if not user:
                return json.dumps({"status": "error",
                    "message": f"사용자 '{requester_username}' 식별 실패."}, ensure_ascii=False)
            if not query or not query.strip():
                return json.dumps({"status": "error",
                    "message": "검색어가 필요합니다."}, ensure_ascii=False)
            client, account, err = _open_imap(session, user, account_id)
            if err:
                return json.dumps({"status": "error", "message": err}, ensure_ascii=False)
            try:
                with client as c:
                    # IMAP SEARCH 는 UID 리스트만 반환 → fetch_by_uids 로 메타 조회
                    uids = c.search_messages(query=query.strip(), folder=folder) or []
                    if not isinstance(uids, list):
                        uids = list(uids)
                    # UID 내림차순(최신 근사) + limit 슬라이스 후 메타 조회
                    sorted_uids = sorted(uids, reverse=True)[:limit]
                    result = c.fetch_by_uids(folder, sorted_uids) if sorted_uids else {'messages': []}
                    msgs = result.get('messages', []) if isinstance(result, dict) else (result or [])
            except Exception as e:
                return json.dumps({"status": "error",
                    "message": f"IMAP 검색 실패: {e!s:.100}"}, ensure_ascii=False)
            return json.dumps({
                "account_id": account.id,
                "account_email": _s(account.email),
                "folder": folder,
                "query": query,
                "total_matched": len(uids),
                "returned": len(msgs),
                "items": msgs,
            }, ensure_ascii=False, default=str)
        finally:
            session.close()

    @mcp.tool()
    def read_mail_message(
        requester_username: str,
        uid: int,
        account_id: Optional[int] = None,
        folder: str = "INBOX",
        body_max_chars: int = 10000,
    ) -> str:
        """메일 본문 + 첨부 메타 조회. 권한 격리.

        Args:
            requester_username: 챗봇 발신자 (필수)
            uid: 메일 IMAP UID (list_inbox_messages / search_mailbox 결과의 uid)
            account_id: 특정 계정 (생략 시 개인 계정)
            folder: 폴더 (기본 INBOX)
            body_max_chars: 본문 최대 길이 (기본 1만자, 초과 시 끝 잘림 표시)
        """
        session = get_session()
        try:
            user = _resolve_mail_user(session, requester_username)
            if not user:
                return json.dumps({"status": "error",
                    "message": f"사용자 '{requester_username}' 식별 실패."}, ensure_ascii=False)
            client, account, err = _open_imap(session, user, account_id)
            if err:
                return json.dumps({"status": "error", "message": err}, ensure_ascii=False)
            try:
                with client as c:
                    msg = c.fetch_message(uid=int(uid), folder=folder)
            except Exception as e:
                return json.dumps({"status": "error",
                    "message": f"메일 조회 실패: {e!s:.100}"}, ensure_ascii=False)
            if not msg:
                return json.dumps({"status": "error",
                    "message": f"메일 uid={uid} 를 찾을 수 없습니다."}, ensure_ascii=False)
            # 본문 길이 제한
            if isinstance(msg, dict):
                body = msg.get('body') or msg.get('body_html') or msg.get('body_text') or ''
                if isinstance(body, str) and len(body) > body_max_chars:
                    msg['body_truncated'] = True
                    msg['body_original_length'] = len(body)
                    msg['body'] = body[:body_max_chars] + f"\n\n... [본문 {len(body) - body_max_chars}자 잘림]"
            return json.dumps({
                "account_id": account.id,
                "account_email": _s(account.email),
                "folder": folder,
                "uid": uid,
                "message": msg,
            }, ensure_ascii=False, default=str)
        finally:
            session.close()
