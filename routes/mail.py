"""
웹메일 라우트.
- 메일함 목록, 메일 읽기, 작성, 설정
- IMAP/SMTP 연동은 mail_client.py에 위임
"""

import os
import re
import time
import json
import logging
import uuid
from datetime import datetime, timedelta
from urllib.parse import quote as urlquote

from sqlalchemy import func

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, jsonify, Response, current_app, g,
)
from modules.auth_decorators import (
    login_required, menu_required, admin_required, _try_token_auth,
)
from modules.db_context import get_db
from modules.models.mail_entities import (
    MailAccount, MailSharedAccess, MailContact, MailReadReceipt, MailLargeFile,
    MailLabel, MailRule, MailAutoReply, MailAutoForward, MailScheduled,
    MailPin, MailTemplate, MailSharedRead, MailBlocklist, MailFolderPref,
)
from modules import storage_adapter
from modules.models.procurement_entities import EmailHistory
from modules.models.auth_entities import User
from modules.pagination import make_pagination
from modules.services.mail_client import (
    MailClient, decrypt_password, encrypt_password, _decode_header_value,
)
from modules.services.vcard import parse_contacts_file, build_vcf

logger = logging.getLogger(__name__)
mail_bp = Blueprint('mail', __name__)


# ── 디버그용 타이밍 로그 (느린 요청 진단) ─────────────────────────────────
@mail_bp.before_request
def _mail_timing_start():
    import time as _t
    g._mail_t0 = _t.perf_counter()


@mail_bp.after_request
def _mail_timing_end(response):
    import time as _t
    t0 = getattr(g, '_mail_t0', None)
    if t0 is not None:
        elapsed = _t.perf_counter() - t0
        qs = request.query_string.decode('latin-1', errors='replace')[:120]
        # 실패 응답(4xx/5xx)은 소요시간과 무관하게 무조건 기록 — 빠르게 떨어지는 400도 놓치지 않음
        if response.status_code >= 400:
            detail = ''
            # JSON 에러 응답이면 사유(error 메시지)까지 남김 — 어떤 400인지 사후 식별용
            try:
                if response.is_json:
                    body = response.get_json(silent=True) or {}
                    if isinstance(body, dict) and body.get('error'):
                        detail = ' error=' + str(body['error'])[:200]
            except Exception:
                pass
            logger.warning(
                'MAIL_FAIL %d %.2fs %s %s qs=%s%s',
                response.status_code, elapsed, request.method, request.path, qs, detail,
            )
        # 정상 응답은 200ms 이상만 로그 (이하면 정상)
        elif elapsed >= 0.2:
            logger.info(
                'MAIL_TIMING %.2fs %s %s qs=%s',
                elapsed, request.method, request.path, qs,
            )
    return response

# ── 워커별 폴더 목록 캐시 ────────────────────────────────────────────────
# list_folders() 는 폴더당 IMAP STATUS UNSEEN 을 호출하므로 폴더 7개면 RTT 7번.
# 같은 워커에 동일 계정 요청이 30초 내 반복되면 캐시로 즉시 응답하여
# 페이지 첫 진입 + 새로고침의 체감 속도를 크게 줄인다.
# 클라이언트가 ?refresh=1 을 보내면 캐시를 우회한다 (메일 삭제/플래그 변경 직후).
_FOLDER_CACHE: dict = {}
_FOLDER_CACHE_TTL = 300  # 5분


# ---------------------------------------------------------------------------
# 헬퍼: 현재 사용자의 메일 클라이언트 얻기
# ---------------------------------------------------------------------------
def _account_allowed(db, account_id):
    """설정류 API(자동회신·자동전달·자동분류)의 계정 접근 확인.

    이 API 들은 메일을 열지 않으므로 _get_mail_client 를 부를 이유가 없었고,
    그 바람에 **account_id 를 그냥 믿고 있었다** — 남의 계정 번호만 넣으면
    자동전달 주소를 바꿔 남의 메일을 받아볼 수 있었다(2026-09-15 막음).
    잣대는 _get_mail_client 와 같다: 내 계정이거나, 내가 권한을 받은 공용계정.
    """
    user_id = session.get('user_id')
    if not user_id or not account_id:
        return False
    account = db.query(MailAccount).filter_by(id=account_id).first()
    if not account:
        return False
    if account.user_id == user_id:
        return True
    if account.is_shared:
        if session.get('role') == 'admin':
            return True
        return bool(db.query(MailSharedAccess).filter_by(
            mail_account_id=account.id, user_id=user_id).first())
    return False   # 남의 개인 계정은 관리자도 여기서는 못 만진다


def _get_mail_client(db, account_id=None):
    """현재 세션 사용자의 MailClient 인스턴스 생성.
    account_id가 주어지면 해당 계정, 없으면 개인 계정.
    공용계정은 shared_access 권한 확인.
    Returns: (MailClient, MailAccount, error_msg)
    """
    user_id = session.get('user_id')
    if not user_id:
        return None, None, '로그인이 필요합니다.'

    if account_id:
        account = db.query(MailAccount).filter_by(id=account_id, is_active=True).first()
        if not account:
            return None, None, '메일 계정을 찾을 수 없습니다.'
        # 본인 계정이거나 공유 권한이 있는지 확인
        if account.user_id != user_id and not account.is_shared:
            return None, None, '접근 권한이 없습니다.'
        if account.is_shared:
            access = db.query(MailSharedAccess).filter_by(
                mail_account_id=account.id, user_id=user_id
            ).first()
            if not access and session.get('role') != 'admin':
                return None, None, '공용계정 접근 권한이 없습니다.'
    else:
        account = db.query(MailAccount).filter(
            MailAccount.user_id == user_id,
            MailAccount.is_shared == False,
            MailAccount.is_active == True,
            MailAccount.account_type.in_(['internal', None]),
        ).first()
        if not account:
            return None, None, None  # 계정 미설정 (설정 페이지로 안내)

    try:
        password = decrypt_password(account.password_encrypted)
    except Exception:
        return None, None, '메일 비밀번호 복호화 실패. 관리자에게 문의하세요.'

    is_external = getattr(account, 'account_type', 'internal') == 'external'
    client = MailClient(
        imap_host=account.imap_host,
        imap_port=account.imap_port,
        smtp_host=account.smtp_host,
        smtp_port=account.smtp_port,
        username=account.username,
        password=password,
        use_ssl=account.use_ssl,
        verify_cert=is_external,
    )
    # 워커별 IMAP 연결 풀 사용 — connect+LOGIN 비용 절약
    client.use_pool = True
    return client, account, None


def _get_user_accounts(db, user_id):
    """사용자가 접근 가능한 모든 메일 계정 목록."""
    # 개인 계정 (internal만)
    personal = db.query(MailAccount).filter(
        MailAccount.user_id == user_id,
        MailAccount.is_shared == False,
        MailAccount.is_active == True,
        MailAccount.account_type.in_(['internal', None]),
    ).all()

    # 공용 계정 (shared_access 기반, sort_order 정렬)
    shared_rows = db.query(MailSharedAccess.mail_account_id, MailSharedAccess.sort_order).filter_by(
        user_id=user_id
    ).order_by(MailSharedAccess.sort_order).all()
    shared_ids = [s[0] for s in shared_rows]
    shared_order = {s[0]: s[1] for s in shared_rows}

    shared = []
    if shared_ids:
        shared = db.query(MailAccount).filter(
            MailAccount.id.in_(shared_ids),
            MailAccount.is_active == True,
        ).all()
        shared.sort(key=lambda a: shared_order.get(a.id, 0))

    # admin도 shared_access 기반으로만 접근 (시스템관리에서 별도 설정)
    if False and session.get('role') == 'admin':
        all_shared = db.query(MailAccount).filter_by(
            is_shared=True, is_active=True
        ).all()
        existing_ids = {s.id for s in shared}
        for s in all_shared:
            if s.id not in existing_ids:
                shared.append(s)

    return personal, shared


def _get_external_accounts(db, user_id):
    """사용자의 외부메일 계정 목록."""
    return db.query(MailAccount).filter(
        MailAccount.user_id == user_id,
        MailAccount.account_type == 'external',
        MailAccount.is_active == True,
    ).order_by(MailAccount.sort_order, MailAccount.id).all()


# ---------------------------------------------------------------------------
# 페이지 라우트
# ---------------------------------------------------------------------------
@mail_bp.route('/mail')
@login_required
def mail_inbox():
    """메일함 메인 — 개인메일로 리다이렉트."""
    return redirect(url_for('mail.mail_personal'))


@mail_bp.route('/mail/personal')
@login_required
@menu_required('mail_personal')
def mail_personal():
    """개인메일함 — 본인 계정만."""
    with get_db() as db:
        personal, _ = _get_user_accounts(db, session['user_id'])
        has_account = len(personal) > 0

        current_account_id = request.args.get('account', type=int)
        if not current_account_id and personal:
            current_account_id = personal[0].id

        current_folder = request.args.get('folder', 'INBOX')

        return render_template('mail_inbox.html',
                               personal_accounts=personal,
                               shared_accounts=[],
                               has_account=has_account,
                               current_account_id=current_account_id,
                               current_folder=current_folder,
                               mail_mode='personal')


@mail_bp.route('/mail/shared')
@login_required
@menu_required('mail_shared')
def mail_shared():
    """공용메일함 — 공용 계정만."""
    with get_db() as db:
        _, shared = _get_user_accounts(db, session['user_id'])
        has_account = len(shared) > 0

        current_account_id = request.args.get('account', type=int)
        if not current_account_id and shared:
            current_account_id = shared[0].id

        current_folder = request.args.get('folder', 'INBOX')

        return render_template('mail_inbox.html',
                               personal_accounts=[],
                               shared_accounts=shared,
                               has_account=has_account,
                               current_account_id=current_account_id,
                               current_folder=current_folder,
                               mail_mode='shared')


@mail_bp.route('/mail/read/<int:uid>')
@login_required
def mail_read(uid):
    """메일 상세 보기 페이지."""
    folder = request.args.get('folder', 'INBOX')
    account_id = request.args.get('account', type=int)
    mode = request.args.get('mode', 'personal')
    g.active_menu_key = 'mail_external' if mode == 'external' else ('mail_shared' if mode == 'shared' else 'mail_personal')
    with get_db() as db:
        personal, shared = _get_user_accounts(db, session['user_id'])
        if mode == 'external':
            external = _get_external_accounts(db, session['user_id'])
            all_accounts = external
            if not account_id and external:
                account_id = external[0].id
        else:
            all_accounts = (personal if mode == 'personal' else []) + (shared if mode == 'shared' else [])
            if not account_id and personal:
                account_id = personal[0].id
    return render_template('mail_read.html',
                           uid=uid, folder=folder, account_id=account_id, mail_mode=mode,
                           all_accounts=all_accounts)


@mail_bp.route('/mail/compose')
@login_required
def mail_compose():
    """메일 작성 화면."""
    mode = request.args.get('mode', 'personal')
    g.active_menu_key = 'mail_external' if mode == 'external' else ('mail_shared' if mode == 'shared' else 'mail_personal')
    reply_uid = request.args.get('reply', type=int)
    reply_all = request.args.get('reply_all', type=int)
    forward_uid = request.args.get('forward', type=int)
    resend_uid = request.args.get('resend', type=int)
    draft_uid = request.args.get('draft', type=int)
    account_id = request.args.get('account', type=int)
    self_send = request.args.get('self', type=int)  # 내게쓰기로 열기

    reply_data = None
    with get_db() as db:
        personal, shared = _get_user_accounts(db, session['user_id'])
        external = _get_external_accounts(db, session['user_id'])

        # 답장/전달/다시보내기/임시보관함 이어쓰기 시 원본 메일 데이터
        source_uid = reply_uid or reply_all or forward_uid or resend_uid or draft_uid
        if source_uid and account_id:
            client, account, err = _get_mail_client(db, account_id)
            if client and not err:
                folder = request.args.get('folder', 'INBOX')
                try:
                    with client:
                        reply_data = client.fetch_message(source_uid, folder)
                except Exception as e:
                    logger.error("원본 메일 조회 실패: %s", e)

        if mode == 'external':
            compose_accounts = external
        elif mode == 'shared':
            compose_accounts = shared
        else:
            compose_accounts = personal

        # 로그인 사용자 정보에서 서명 생성
        current_user = db.query(User).filter_by(id=session['user_id']).first()
        user_signature_html = current_user.to_signature_html() if current_user else ''

        return render_template('mail_compose.html',
                               personal_accounts=personal if mode == 'personal' else [],
                               shared_accounts=shared if mode == 'shared' else [],
                               compose_accounts=compose_accounts,
                               reply_data=reply_data,
                               reply_uid=reply_uid,
                               reply_all=reply_all,
                               forward_uid=forward_uid,
                               resend_uid=resend_uid,
                               draft_uid=draft_uid,
                               current_account_id=account_id,
                               user_signature_html=user_signature_html,
                               self_send=bool(self_send),
                               mail_mode=mode)


@mail_bp.route('/mail/sent-complete')
@login_required
def mail_sent_complete():
    """메일 발송 완료 화면 — alert 대신 결과 페이지로 안내."""
    mode = request.args.get('mode', 'personal')
    g.active_menu_key = 'mail_external' if mode == 'external' else ('mail_shared' if mode == 'shared' else 'mail_personal')
    return render_template('mail_sent_complete.html',
                           sent=session.get('mail_sent_result'),
                           mail_mode=mode)


@mail_bp.route('/mail/send-history')
@login_required
@menu_required('mail_send_history')
def mail_send_history():
    """ERP 업무메일 발송이력 — 발주서·가공발주 등 시스템이 보낸 메일.

    웹메일 화면에서 쓴 메일은 각 계정 보낸편지함에 남지만, ERP가 자동으로
    보내는 메일은 email_history 테이블에만 쌓인다. 그 기록을 보는 화면.
    """
    from sqlalchemy import or_

    page = request.args.get('page', 1, type=int)
    per_page = 50
    f_sender = request.args.get('sender', '').strip()
    f_status = request.args.get('status', '').strip()   # '' | success | fail
    f_q = request.args.get('q', '').strip()
    f_from = request.args.get('from', '').strip()
    f_to = request.args.get('to', '').strip()

    with get_db() as db:
        query = db.query(EmailHistory)
        if f_sender:
            query = query.filter(EmailHistory.sender == f_sender)
        if f_status == 'success':
            query = query.filter(EmailHistory.is_success.is_(True))
        elif f_status == 'fail':
            query = query.filter(EmailHistory.is_success.isnot(True))
        if f_q:
            like = f'%{f_q}%'
            query = query.filter(or_(
                EmailHistory.receiver.ilike(like),
                EmailHistory.subject.ilike(like),
                EmailHistory.po_ref.ilike(like),
            ))
        if f_from:
            try:
                query = query.filter(EmailHistory.send_date >= datetime.strptime(f_from, '%Y-%m-%d'))
            except ValueError:
                pass
        if f_to:
            try:
                query = query.filter(EmailHistory.send_date < datetime.strptime(f_to, '%Y-%m-%d') + timedelta(days=1))
            except ValueError:
                pass

        total = query.count()
        pagination = make_pagination(page, per_page, total)
        rows = (query.order_by(EmailHistory.send_date.desc())
                .offset((pagination['page'] - 1) * per_page).limit(per_page).all())

        # 표에 필요한 값만 미리 꺼내 둔다 (세션 닫힌 뒤 접근 방지)
        history = [{
            'id': r.id,
            'send_date': r.send_date,
            'sender': r.sender or '',
            'receiver': r.receiver or '',
            'subject': r.subject or '',
            'attachment': r.attachment or '',
            'is_success': bool(r.is_success),
            'error_message': r.error_message or '',
            'po_ref': r.po_ref or '',
        } for r in rows]

        senders = [x[0] for x in db.query(EmailHistory.sender).distinct()
                   .order_by(EmailHistory.sender).all() if x[0]]
        all_total = db.query(EmailHistory).count()
        fail_total = db.query(EmailHistory).filter(EmailHistory.is_success.isnot(True)).count()

    return render_template('mail_send_history.html',
                           history=history,
                           senders=senders,
                           pagination=pagination,
                           stats={'total': all_total, 'fail': fail_total,
                                  'success': all_total - fail_total, 'found': total},
                           filters={'sender': f_sender, 'status': f_status, 'q': f_q,
                                    'from': f_from, 'to': f_to})


@mail_bp.route('/mail/api/send-history/<int:hid>')
@login_required
@menu_required('mail_send_history')
def api_send_history_detail(hid):
    """발송이력 본문 상세."""
    with get_db() as db:
        r = db.query(EmailHistory).get(hid)
        if not r:
            return jsonify({'error': '이력을 찾을 수 없습니다.'}), 404
        return jsonify({
            'id': r.id,
            'send_date': r.send_date.strftime('%Y-%m-%d %H:%M:%S') if r.send_date else '',
            'sender': r.sender or '',
            'receiver': r.receiver or '',
            'subject': r.subject or '',
            'content': r.content or '',
            'attachment': r.attachment or '',
            'is_success': bool(r.is_success),
            'error_message': r.error_message or '',
            'po_ref': r.po_ref or '',
        })


@mail_bp.route('/mail/settings')
@login_required
def mail_settings():
    """메일 설정 — mode 파라미터로 개인/공용 분리."""
    mode = request.args.get('mode', 'personal')
    g.active_menu_key = 'mail_shared' if mode == 'shared' else 'mail_personal'
    with get_db() as db:
        personal, shared = _get_user_accounts(db, session['user_id'])
        if mode == 'shared':
            return render_template('mail_settings.html',
                                   personal_accounts=[],
                                   shared_accounts=shared,
                                   settings_mode='shared')
        else:
            return render_template('mail_settings.html',
                                   personal_accounts=personal,
                                   shared_accounts=[],
                                   settings_mode='personal')


@mail_bp.route('/mail/admin')
@admin_required
def mail_admin():
    """메일 관리자 설정."""
    with get_db() as db:
        all_accounts = db.query(MailAccount).filter_by(is_active=True).all()
        all_shared = db.query(MailAccount).filter_by(is_shared=True, is_active=True).all()
        users = db.query(User).filter_by(is_active=True).all()
        shared_access = db.query(MailSharedAccess).all()
        return render_template('mail_settings.html',
                               is_admin=True,
                               all_accounts=all_accounts,
                               all_shared=all_shared,
                               users=users,
                               shared_access=shared_access,
                               personal_accounts=[],
                               shared_accounts=[])


# ---------------------------------------------------------------------------
# API 라우트
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/messages')
@login_required
def api_messages():
    """메일 목록 JSON."""
    folder = request.args.get('folder', 'INBOX')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    account_id = request.args.get('account', type=int)
    unread_only = request.args.get('unread_only', '') == '1'
    search_criteria = request.args.get('search_criteria', '')

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        if not client:
            return jsonify({'error': '메일 계정이 설정되지 않았습니다.', 'no_account': True}), 404

        try:
            with client:
                if search_criteria:
                    result = client.fetch_messages(folder, page, per_page, search_criteria=search_criteria)
                elif unread_only:
                    result = client.fetch_messages(folder, page, per_page, search_criteria='UNSEEN')
                else:
                    result = client.fetch_messages(folder, page, per_page)
            return jsonify(result)
        except Exception as e:
            logger.error("메일 목록 조회 실패: %s", e)
            return jsonify({'error': f'메일 서버 연결 실패: {e}'}), 500


@mail_bp.route('/mail/api/messages/<int:uid>')
@login_required
def api_message_detail(uid):
    """메일 본문 JSON."""
    folder = request.args.get('folder', 'INBOX')
    account_id = request.args.get('account', type=int)

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        if not client:
            return jsonify({'error': '메일 계정 미설정'}), 404

        try:
            with client:
                result = client.fetch_message(uid, folder)
            if not result:
                return jsonify({'error': '메일을 찾을 수 없습니다.'}), 404
            # html_body는 fetch_message() 단계에서 sanitize_html()로 이미 세정됨
            # (data:/cid: 인라인 이미지 스킴 포함). 여기서 더 좁은 정책으로 재세정하면
            # 인라인 이미지(data:)·표 속성 등이 다시 제거되므로 중복 세정하지 않는다.
            return jsonify(result)
        except Exception as e:
            logger.error("메일 조회 실패: %s", e)
            return jsonify({'error': f'메일 조회 실패: {e}'}), 500


@mail_bp.route('/mail/api/send', methods=['POST'])
@login_required
def api_send():
    """메일 발송."""
    account_id = request.form.get('account_id', type=int)
    to = [a.strip() for a in request.form.get('to', '').split(',') if a.strip()]
    cc = [a.strip() for a in request.form.get('cc', '').split(',') if a.strip()]
    bcc = [a.strip() for a in request.form.get('bcc', '').split(',') if a.strip()]
    subject = request.form.get('subject', '')
    html_body = request.form.get('body', '')

    # 임시보관함에서 이어쓴 메일이면 발송 후 원본 임시본 삭제
    draft_replace_uid = request.form.get('draft_replace_uid', type=int)
    draft_folder = request.form.get('draft_folder', '')

    # 대용량 첨부(이미 임시 위치에 올라가 있음) — 발송이 확정된 지금 옮기고 링크를 만든다
    try:
        large_items = json.loads(request.form.get('large_files', '[]'))
    except Exception as e:
        # 여기서 조용히 넘기면 첨부 링크가 통째로 사라진 채 메일이 나간다
        logger.error('large_files 해석 실패 — 첨부 링크 없이 발송될 뻔: %s', e)
        large_items = []

    if not to:
        return jsonify({'error': '받는 사람을 입력하세요.'}), 400

    # 첨부파일
    attachments = []
    files = request.files.getlist('attachments')
    for f in files:
        if f.filename:
            attachments.append((f.filename, f.read()))

    # 전달 시 원본 첨부파일 가져오기
    forward_source_uid = request.form.get('forward_source_uid', type=int)
    forward_account_id = request.form.get('forward_account_id', type=int)
    forward_folder = request.form.get('forward_folder', 'INBOX')
    forward_parts_json = request.form.get('forward_parts', '')

    with get_db() as db:
        if large_items:
            try:
                html_body += _large_files_html(_promote_large_files(db, large_items))
            except RuntimeError as e:
                return jsonify({'error': str(e)}), 500

        # 원본 첨부파일 IMAP에서 fetch
        if forward_source_uid and forward_account_id and forward_parts_json:
            try:
                forward_parts = json.loads(forward_parts_json)
                fwd_client, fwd_account, fwd_err = _get_mail_client(db, forward_account_id)
                if fwd_client and not fwd_err:
                    with fwd_client:
                        for part_id in forward_parts:
                            fname, ctype, data = fwd_client.fetch_attachment(
                                forward_source_uid, str(part_id), forward_folder
                            )
                            if fname and data:
                                attachments.append((fname, data))
            except Exception as e:
                logger.error("전달 첨부파일 로드 실패: %s", e)
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        if not client:
            return jsonify({'error': '메일 계정 미설정'}), 404

        # 공용계정 발송 권한 확인
        if account.is_shared:
            access = db.query(MailSharedAccess).filter_by(
                mail_account_id=account.id, user_id=session['user_id']
            ).first()
            if not access or not access.can_send:
                if session.get('role') != 'admin':
                    return jsonify({'error': '이 공용계정으로 발송할 권한이 없습니다.'}), 403

        try:
            # 수신확인 트래킹 픽셀 삽입
            tracking_id = uuid.uuid4().hex[:16]
            domain = os.environ.get('FLASK_DOMAIN', 'work.mgnt.kr')
            pixel_url = f'https://{domain}/mail/t/{tracking_id}.gif'
            pixel_tag = f'<img src="{pixel_url}" width="1" height="1" style="display:none;" alt="">'
            html_body_with_tracking = html_body + pixel_tag

            # HTML에서 text/plain 본문 자동 생성 (스팸 점수 개선)
            import re as _re
            _plain = _re.sub(r'<br\s*/?\s*>', '\n', html_body)
            _plain = _re.sub(r'<[^>]+>', '', _plain)
            _plain = _re.sub(r'&nbsp;', ' ', _plain)
            _plain = _re.sub(r'&amp;', '&', _plain)
            _plain = _re.sub(r'&lt;', '<', _plain)
            _plain = _re.sub(r'&gt;', '>', _plain)
            _plain = _re.sub(r'\n{3,}', '\n\n', _plain).strip()

            with client:
                result = client.send_message(
                    from_addr=account.email,
                    to=to, cc=cc or None, bcc=bcc or None,
                    subject=subject,
                    html_body=html_body_with_tracking,
                    text_body=_plain,
                    attachments=attachments or None,
                    from_name=account.display_name,
                )

            # 수신확인 레코드 저장
            receipt = MailReadReceipt(
                tracking_id=tracking_id,
                sender_user_id=session['user_id'],
                mail_account_id=account.id,
                to_email=to[0],
                subject=subject,
            )
            db.add(receipt)

            # 수신자 주소록 자동 수집 (사내 직원 제외, 중복 제외)
            all_recipients = list(to) + list(cc or []) + list(bcc or [])
            import os as _os
            _domain = _os.environ.get('MAILCOW_DOMAIN', 'mgnt.kr')
            internal_emails = {f'{u.username.lower()}@{_domain}' for u in db.query(User.username).all()}
            existing_contacts = {c.email.lower() for c in db.query(MailContact.email).filter_by(user_id=session['user_id']).all()}
            for addr in all_recipients:
                addr_lower = addr.strip().lower()
                if addr_lower and addr_lower not in internal_emails and addr_lower not in existing_contacts:
                    db.add(MailContact(
                        user_id=session['user_id'],
                        name=addr_lower.split('@')[0],
                        email=addr_lower,
                    ))
                    existing_contacts.add(addr_lower)

            db.commit()

            # 임시보관함에서 이어쓴 메일이면 원본 임시본 삭제 (발송 완료 후)
            if draft_replace_uid and draft_folder:
                try:
                    with client:
                        client.delete_messages([draft_replace_uid], folder=draft_folder)
                except Exception as e:
                    logger.warning("발송 후 임시본 삭제 실패(uid=%s): %s", draft_replace_uid, e)

            # 발송완료 페이지에서 보여줄 요약 (쿠키 크기 고려해 주소는 20건까지)
            session['mail_sent_result'] = {
                'from_email': account.email,
                'from_name': account.display_name or '',
                'account_id': account.id,
                'to': to[:20],
                'to_count': len(to),
                'cc': cc[:20],
                'cc_count': len(cc),
                'bcc_count': len(bcc),
                'subject': subject or '(제목 없음)',
                'attachment_count': len(attachments),
                'is_self': (len(to) == 1 and not cc and not bcc
                            and to[0].strip().lower() == account.email.lower()),
                'sent_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
            }

            return jsonify(result)
        except Exception as e:
            logger.error("메일 발송 실패: %s", e)
            return jsonify({'error': f'메일 발송 실패: {e}'}), 500


@mail_bp.route('/mail/api/draft', methods=['POST'])
@login_required
def api_save_draft():
    """임시저장 — 작성 중인 메일을 임시보관함(Drafts)에 저장.

    replace_uid 가 있으면 기존 임시본을 교체(삭제 후 재저장)한다.
    답장/전달/이어쓰기의 원본 첨부는 forward_* 파라미터로 IMAP에서 재첨부한다.
    """
    account_id = request.form.get('account_id', type=int)
    to = [a.strip() for a in request.form.get('to', '').split(',') if a.strip()]
    cc = [a.strip() for a in request.form.get('cc', '').split(',') if a.strip()]
    bcc = [a.strip() for a in request.form.get('bcc', '').split(',') if a.strip()]
    subject = request.form.get('subject', '')
    html_body = request.form.get('body', '')
    replace_uid = request.form.get('replace_uid', type=int)

    # 새로 첨부한 파일
    attachments = []
    for f in request.files.getlist('attachments'):
        if f.filename:
            attachments.append((f.filename, f.read()))

    # 원본 첨부(전달/이어쓰기) IMAP 재첨부
    forward_source_uid = request.form.get('forward_source_uid', type=int)
    forward_account_id = request.form.get('forward_account_id', type=int)
    forward_folder = request.form.get('forward_folder', 'INBOX')
    forward_parts_json = request.form.get('forward_parts', '')

    with get_db() as db:
        if forward_source_uid and forward_account_id and forward_parts_json:
            try:
                forward_parts = json.loads(forward_parts_json)
                fwd_client, fwd_account, fwd_err = _get_mail_client(db, forward_account_id)
                if fwd_client and not fwd_err:
                    with fwd_client:
                        for part_id in forward_parts:
                            fname, ctype, data = fwd_client.fetch_attachment(
                                forward_source_uid, str(part_id), forward_folder
                            )
                            if fname and data:
                                attachments.append((fname, data))
            except Exception as e:
                logger.error("임시저장 원본 첨부 로드 실패: %s", e)

        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        if not client:
            return jsonify({'error': '메일 계정 미설정'}), 404

        try:
            with client:
                result = client.save_draft(
                    from_addr=account.email,
                    to=to, cc=cc or None, bcc=bcc or None,
                    subject=subject,
                    html_body=html_body,
                    attachments=attachments or None,
                    from_name=account.display_name,
                    replace_uid=replace_uid,
                )
            if not result.get('success'):
                return jsonify({'error': result.get('error', '임시저장 실패')}), 500
            return jsonify(result)
        except Exception as e:
            logger.error("임시저장 실패: %s", e)
            return jsonify({'error': f'임시저장 실패: {e}'}), 500


@mail_bp.route('/mail/api/flags', methods=['POST'])
@login_required
def api_flags():
    """플래그 변경 (읽음/안읽음, 별표)."""
    data = request.get_json()
    uids = data.get('uids', [])
    flag = data.get('flag', '\\Seen')
    action = data.get('action', 'add')
    folder = data.get('folder', 'INBOX')
    account_id = data.get('account_id')

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        try:
            with client:
                client.set_flags(uids, flag, action, folder)
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@mail_bp.route('/mail/api/move', methods=['POST'])
@login_required
def api_move():
    """메일 폴더 이동."""
    data = request.get_json()
    uids = data.get('uids', [])
    dest_folder = data.get('dest_folder')
    src_folder = data.get('src_folder', 'INBOX')
    account_id = data.get('account_id')

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        try:
            with client:
                client.move_messages(uids, dest_folder, src_folder)
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@mail_bp.route('/mail/api/messages', methods=['DELETE'])
@login_required
def api_delete():
    """메일 삭제 (휴지통 이동)."""
    data = request.get_json()
    uids = data.get('uids', [])
    folder = data.get('folder', 'INBOX')
    account_id = data.get('account_id')

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400

        # 공용계정 삭제 권한
        if account.is_shared:
            access = db.query(MailSharedAccess).filter_by(
                mail_account_id=account.id, user_id=session['user_id']
            ).first()
            if not access or not access.can_delete:
                if session.get('role') != 'admin':
                    return jsonify({'error': '삭제 권한이 없습니다.'}), 403

        try:
            with client:
                client.delete_messages(uids, folder)
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@mail_bp.route('/mail/api/folders')
@login_required
def api_folders():
    """폴더 + 라벨 목록.

    기본: INBOX 만 STATUS UNSEEN (빠른 응답).
    ?all_unread=1: 모든 폴더 STATUS UNSEEN (느리지만 정확). 백그라운드 호출용.
    ?refresh=1: 캐시 우회.
    """
    import time as _t
    account_id = request.args.get('account', type=int)
    refresh = request.args.get('refresh') == '1'
    all_unread = request.args.get('all_unread') == '1'

    cache_key = (account_id, all_unread) if account_id else None

    if not refresh and cache_key:
        cached = _FOLDER_CACHE.get(cache_key)
        if cached and cached['expires_at'] > _t.time():
            return jsonify({'folders': cached['folders'], 'labels': cached['labels']})

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        if not client:
            return jsonify({'error': '메일 계정 미설정', 'no_account': True}), 404
        try:
            with client:
                folders = client.list_folders(all_unread=all_unread)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

        # 라벨 조회
        labels = db.query(MailLabel).filter_by(account_id=account_id).order_by(MailLabel.sort_order, MailLabel.name).all()
        labels_data = [{'id': l.id, 'name': l.name, 'color': l.color} for l in labels]

        if cache_key:
            _FOLDER_CACHE[cache_key] = {
                'folders': folders, 'labels': labels_data,
                'expires_at': _t.time() + _FOLDER_CACHE_TTL,
            }
        return jsonify({'folders': folders, 'labels': labels_data})


# ---------------------------------------------------------------------------
# 메일함 관리 (만들기 · 이름 바꾸기 · 지우기)
# ---------------------------------------------------------------------------
# IMAP 폴더를 직접 건드린다 — 메일 프로그램(아웃룩·휴대폰)에도 그대로 보인다.
# 그래서 두 가지를 반드시 막는다:
#   ① 시스템 메일함(받은편지함·보낸편지함·임시보관함·휴지통·스팸)은 손대지 않는다.
#      이름을 바꾸는 순간 우리 화면도, 발송 사본 저장도 그 폴더를 못 찾는다.
#   ② 비어 있지 않은 메일함은 **한 번 더 확인받는다.** IMAP DELETE 는 안에 든
#      메일을 같이 지우고, 휴지통으로 가지도 않는다.
# ---------------------------------------------------------------------------

# 한글 이름도 함께 막는다 — 서버에 '임시보관함' 같은 한글 폴더가 실제로 있을 수 있고,
# 우리가 만들어 내는 '내게쓴메일함' 과 이름이 겹치는 폴더도 손대면 화면이 어긋난다.
# (화면 쪽 잣대는 mail_app/src/lib/folders.js 의 SYS_EXACT — 같은 이름을 쓴다)
_SYSTEM_FOLDERS = (
    'inbox', 'sent', 'drafts', 'draft', 'trash', 'junk', 'spam', 'archive', 'archived',
    '받은편지함', '보낸편지함', '임시보관함', '휴지통', '스팸', '보관함',
    '내게쓴메일함', '내게쓴편지함',
)


def _is_system_folder(name):
    # 띄어쓰기는 지우고 본다 — 실제로 '임시 보관함'(공백 포함) 폴더가 있었다.
    # 공백 하나 때문에 기본 메일함 보호가 새면 그 자리에서만 지워진다.
    n = (name or '').strip().lower().replace(' ', '')
    base = n.split('.')[-1].split('/')[-1]
    return n in _SYSTEM_FOLDERS or base in _SYSTEM_FOLDERS


def _clear_folder_cache(account_id):
    """메일함이 바뀌면 캐시를 버린다 — 안 버리면 최대 5분 동안 옛 목록이 보인다."""
    for key in [k for k in _FOLDER_CACHE if k[0] == account_id]:
        _FOLDER_CACHE.pop(key, None)


def _check_folder_name(name):
    """새 메일함 이름 검사. 계층은 parent 로 받으므로 구분자는 이름에 못 들어간다."""
    name = (name or '').strip()
    if not name:
        return None, '메일함 이름을 입력하세요.'
    if len(name) > 60:
        return None, '메일함 이름이 너무 깁니다 (60자까지).'
    if any(ch in name for ch in './\"%*'):
        return None, '이름에 쓸 수 없는 글자가 있습니다 ( . / \\ " % * ).'
    return name, None


@mail_bp.route('/mail/api/folders', methods=['POST'])
@login_required
def api_folder_create():
    """메일함 만들기. parent 를 주면 그 아래에 만든다."""
    data = request.get_json(silent=True) or {}
    account_id = data.get('account_id')
    name, err = _check_folder_name(data.get('name'))
    if err:
        return jsonify({'error': err}), 400
    parent = (data.get('parent') or '').strip()

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err or not client:
            return jsonify({'error': err or '메일 계정 미설정'}), 400
        try:
            with client:
                delimiter = client.folder_delimiter()
                full = f'{parent}{delimiter}{name}' if parent else name
                existing = {f['name'] if isinstance(f, dict) else f for f in client.list_folders()}
                if full in existing:
                    return jsonify({'error': f'이미 있는 메일함입니다: {full}'}), 400
                client.create_folder(full)
        except Exception as e:
            logger.warning("메일함 생성 실패 (%s): %s", name, e)
            return jsonify({'error': f'만들지 못했습니다: {e}'}), 500

        _clear_folder_cache(account_id)
        logger.info("메일함 생성: user=%s account=%s %s", session['user_id'], account_id, full)
        return jsonify({'success': True, 'name': full})


@mail_bp.route('/mail/api/folders/rename', methods=['POST'])
@login_required
def api_folder_rename():
    """메일함 이름 바꾸기. 같은 부모 아래에서 마지막 마디만 바꾼다."""
    data = request.get_json(silent=True) or {}
    account_id = data.get('account_id')
    old = (data.get('name') or '').strip()
    new_name, err = _check_folder_name(data.get('new_name'))
    if err:
        return jsonify({'error': err}), 400
    if not old:
        return jsonify({'error': '바꿀 메일함을 고르세요.'}), 400
    if _is_system_folder(old):
        return jsonify({'error': '기본 메일함의 이름은 바꿀 수 없습니다.'}), 400

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err or not client:
            return jsonify({'error': err or '메일 계정 미설정'}), 400
        try:
            with client:
                delimiter = client.folder_delimiter()
                parts = old.split(delimiter)
                target = delimiter.join(parts[:-1] + [new_name]) if len(parts) > 1 else new_name
                if target == old:
                    return jsonify({'success': True, 'name': old})
                client.rename_folder(old, target)
        except Exception as e:
            logger.warning("메일함 이름변경 실패 (%s → %s): %s", old, new_name, e)
            return jsonify({'error': f'이름을 바꾸지 못했습니다: {e}'}), 500

        _clear_folder_cache(account_id)
        logger.info("메일함 이름변경: user=%s %s → %s", session['user_id'], old, target)
        return jsonify({'success': True, 'name': target})


@mail_bp.route('/mail/api/folders', methods=['DELETE'])
@login_required
def api_folder_delete():
    """메일함 지우기. 비어 있지 않으면 force 없이는 지우지 않는다."""
    data = request.get_json(silent=True) or {}
    account_id = data.get('account_id')
    name = (data.get('name') or '').strip()
    force = bool(data.get('force'))
    if not name:
        return jsonify({'error': '지울 메일함을 고르세요.'}), 400
    if _is_system_folder(name):
        return jsonify({'error': '기본 메일함은 지울 수 없습니다.'}), 400

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err or not client:
            return jsonify({'error': err or '메일 계정 미설정'}), 400
        try:
            with client:
                delimiter = client.folder_delimiter()
                all_names = [f['name'] if isinstance(f, dict) else f for f in client.list_folders()]
                # 하위 메일함까지 한 묶음으로 본다.
                # 부모만 지우면 IMAP 은 **껍데기(\NoSelect)를 남긴다** — 화면에는
                # 그대로 보이는데 열리지 않아, 지웠는데 안 지워진 것처럼 된다.
                children = [n for n in all_names if n.startswith(name + delimiter)]
                targets = sorted(children, key=lambda n: n.count(delimiter), reverse=True) + [name]

                total = sum(client.folder_message_count(n) for n in targets)
                if (total or children) and not force:
                    # 몇 통이, 몇 개 메일함이 함께 사라지는지 알려 주고 한 번 더 받는다
                    return jsonify({'error': 'not_empty', 'count': total,
                                    'children': len(children)}), 409
                removed, missing = 0, 0
                for n in targets:
                    try:
                        client.delete_folder(n)
                        removed += 1
                    except Exception as e:
                        # 부모는 하위가 있는 동안 껍데기로만 남아 있다가 하위를 지우면
                        # 같이 사라진다 — 그때 "없는 메일함" 오류가 난다. 이건 실패가 아니다.
                        if 'NONEXISTENT' in str(e) or "doesn't exist" in str(e):
                            missing += 1
                            continue
                        raise
                if not removed and not missing:
                    raise RuntimeError('지운 메일함이 없습니다')
        except Exception as e:
            logger.warning("메일함 삭제 실패 (%s): %s", name, e)
            return jsonify({'error': f'지우지 못했습니다: {e}'}), 500

        _clear_folder_cache(account_id)
        logger.info("메일함 삭제: user=%s account=%s %s (하위 %s개, %s통)",
                    session['user_id'], account_id, name, len(children), total)
        return jsonify({'success': True, 'removed': removed, 'messages': total})


# ---------------------------------------------------------------------------
# 메일함 순서 · 그룹
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/folder-prefs')
@login_required
def api_folder_prefs_get():
    """이 계정의 메일함 순서·그룹."""
    account_id = request.args.get('account', type=int)
    with get_db() as db:
        if not _account_allowed(db, account_id):
            return jsonify({'error': '접근 권한이 없습니다.'}), 403
        rows = db.query(MailFolderPref).filter_by(account_id=account_id).order_by(
            MailFolderPref.sort_order, MailFolderPref.id).all()
        return jsonify({'items': [
            {'folder': r.folder, 'sort_order': r.sort_order, 'group_name': r.group_name or ''}
            for r in rows
        ]})


@mail_bp.route('/mail/api/folder-prefs', methods=['POST'])
@login_required
def api_folder_prefs_save():
    """메일함 순서·그룹 저장 (화면이 정렬한 목록을 통째로 보낸다).

    한 줄씩 저장하지 않는다 — 끌어다 놓으면 여러 줄의 순서가 한꺼번에 바뀌므로,
    한 줄씩 보내면 중간에 끊겼을 때 순서가 뒤엉킨다.
    """
    data = request.get_json(silent=True) or {}
    account_id = data.get('account_id')
    items = data.get('items') or []

    with get_db() as db:
        if not _account_allowed(db, account_id):
            return jsonify({'error': '접근 권한이 없습니다.'}), 403

        existing = {r.folder: r for r in
                    db.query(MailFolderPref).filter_by(account_id=account_id).all()}
        seen = set()
        for i, item in enumerate(items):
            folder = (item.get('folder') or '').strip()
            if not folder:
                continue
            group = (item.get('group_name') or '').strip()[:60]
            row = existing.get(folder)
            if not row:
                row = MailFolderPref(account_id=account_id, folder=folder)
                db.add(row)
            row.sort_order = i
            row.group_name = group or None
            seen.add(folder)

        # 화면에서 사라진 메일함(지웠거나 이름이 바뀐 것)의 줄은 치운다
        for folder, row in existing.items():
            if folder not in seen:
                db.delete(row)

        db.commit()
        return jsonify({'success': True, 'count': len(seen)})


# ---------------------------------------------------------------------------
# 스팸 — 수신차단 / 수신허용
# ---------------------------------------------------------------------------
# 메일서버(mailcow) 쪽 스팸 필터와는 **별개**다. 여기 있는 것은 "이 주소는
# 스팸함으로" 라는 우리 쪽 목록이다. 판정은 modules/services/mail_classifier.py
# 한 곳에서 한다 — 화면과 자동 처리가 같은 잣대를 써야 한다.
# ---------------------------------------------------------------------------

def _junk_folder(client):
    """이 계정의 스팸함 이름 (Junk / Spam / INBOX.Junk … 서버마다 다르다)."""
    try:
        for f in client.list_folders():
            name = f['name'] if isinstance(f, dict) else f
            low = name.lower()
            if 'junk' in low or 'spam' in low:
                return name
    except Exception:
        pass
    return 'Junk'


def _blocklist_entries(db, account_id):
    rows = db.query(MailBlocklist).filter_by(account_id=account_id).order_by(
        MailBlocklist.kind, MailBlocklist.value).all()
    return [{'id': r.id, 'kind': r.kind, 'value': r.value, 'memo': r.memo or '',
             'created_at': r.created_at.strftime('%Y-%m-%d') if r.created_at else ''} for r in rows]


@mail_bp.route('/mail/api/spam/list')
@login_required
def api_spam_list():
    """수신차단 · 수신허용 목록."""
    account_id = request.args.get('account', type=int)
    with get_db() as db:
        if not _account_allowed(db, account_id):
            return jsonify({'error': '접근 권한이 없습니다.'}), 403
        return jsonify({'items': _blocklist_entries(db, account_id)})


@mail_bp.route('/mail/api/spam/list', methods=['POST'])
@login_required
def api_spam_add():
    """차단·허용 주소 추가. 주소(kim@x.co.kr) 또는 도메인(@x.co.kr) 둘 다 받는다."""
    from modules.services.mail_classifier import normalize_block_value

    data = request.get_json(silent=True) or {}
    account_id = data.get('account_id')
    kind = 'allow' if data.get('kind') == 'allow' else 'block'
    value = normalize_block_value(data.get('value'))
    if not value or ' ' in value or '.' not in value:
        return jsonify({'error': '메일주소나 도메인을 정확히 입력하세요. (예: kim@x.co.kr, @x.co.kr)'}), 400

    with get_db() as db:
        if not _account_allowed(db, account_id):
            return jsonify({'error': '접근 권한이 없습니다.'}), 403
        row = db.query(MailBlocklist).filter(
            MailBlocklist.account_id == account_id,
            MailBlocklist.kind == kind,
            func.lower(MailBlocklist.value) == value,
        ).first()
        if not row:
            row = MailBlocklist(account_id=account_id, kind=kind, value=value)
            db.add(row)
        row.memo = (data.get('memo') or '').strip()
        db.commit()
        return jsonify({'success': True, 'id': row.id, 'value': value, 'kind': kind})


@mail_bp.route('/mail/api/spam/list/<int:entry_id>', methods=['DELETE'])
@login_required
def api_spam_delete(entry_id):
    with get_db() as db:
        row = db.query(MailBlocklist).filter_by(id=entry_id).first()
        if not row or not _account_allowed(db, row.account_id):
            return jsonify({'error': '찾을 수 없습니다.'}), 404
        db.delete(row)
        db.commit()
        return jsonify({'success': True})


@mail_bp.route('/mail/api/spam/apply', methods=['POST'])
@login_required
def api_spam_apply():
    """받은편지함을 훑어 차단 주소에서 온 메일을 스팸함으로 옮긴다."""
    from modules.services.mail_classifier import spam_verdict

    data = request.get_json(silent=True) or {}
    account_id = data.get('account_id')
    # only: 방금 차단한 그 주소만 — 목록 전체를 훑지 않아 **바로** 끝난다.
    # 500통을 다시 읽는 동안 기다리게 하면 "차단했는데 그대로 있다" 로 보인다.
    only = (data.get('only') or '').strip().lower()

    with get_db() as db:
        entries = _blocklist_entries(db, account_id) if _account_allowed(db, account_id) else None
        if entries is None:
            return jsonify({'error': '접근 권한이 없습니다.'}), 403
        if not any(e['kind'] == 'block' for e in entries):
            return jsonify({'success': True, 'moved': 0, 'checked': 0,
                            'message': '차단 주소가 없습니다.'})

        client, account, err = _get_mail_client(db, account_id)
        if err or not client:
            return jsonify({'error': err or '메일 계정 미설정'}), 400
        try:
            with client:
                junk = _junk_folder(client)
                imap = client._imap
                imap.select_folder('INBOX', readonly=False)
                if only:
                    # IMAP 이 찾아 준다 — 우리가 한 통씩 열어 볼 이유가 없다.
                    # 도메인만 차단한 경우엔 주소 조각으로 찾는다(FROM 은 부분일치다).
                    uids = imap.search(['FROM', only])
                else:
                    uids = imap.search('ALL')
                moved, checked = 0, 0
                # 최근 500통까지만 본다 — 메일함이 크면 한 번에 다 훑을 수 없다
                for uid in list(uids)[-500:]:
                    raw = imap.fetch([uid], ['ENVELOPE'])
                    env = raw.get(uid, {}).get(b'ENVELOPE')
                    if not env or not env.from_ or not env.from_[0]:
                        continue
                    f = env.from_[0]
                    mbox = (f.mailbox or b'').decode(errors='replace')
                    host = (f.host or b'').decode(errors='replace')
                    checked += 1
                    if spam_verdict(entries, f'{mbox}@{host}') == 'block':
                        client.move_messages([uid], junk, src_folder='INBOX')
                        moved += 1
        except Exception as e:
            logger.warning("스팸 적용 실패: %s", e)
            return jsonify({'error': f'적용하지 못했습니다: {e}'}), 500

        _clear_folder_cache(account_id)
        logger.info("스팸 적용: user=%s account=%s %s통 → %s", session['user_id'], account_id, moved, junk)
        return jsonify({'success': True, 'moved': moved, 'checked': checked, 'folder': junk})


@mail_bp.route('/mail/api/spam/empty', methods=['POST'])
@login_required
def api_spam_empty():
    """스팸함 비우기 — 되돌릴 수 없다(휴지통을 거치지 않는다)."""
    data = request.get_json(silent=True) or {}
    account_id = data.get('account_id')

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err or not client:
            return jsonify({'error': err or '메일 계정 미설정'}), 400
        try:
            with client:
                junk = _junk_folder(client)
                imap = client._imap
                imap.select_folder(junk, readonly=False)
                uids = imap.search('ALL')
                if not uids:
                    return jsonify({'success': True, 'deleted': 0, 'folder': junk})
                imap.add_flags(uids, [b'\\Deleted'])
                imap.expunge()
        except Exception as e:
            logger.warning("스팸함 비우기 실패: %s", e)
            return jsonify({'error': f'비우지 못했습니다: {e}'}), 500

        _clear_folder_cache(account_id)
        logger.info("스팸함 비우기: user=%s account=%s %s통", session['user_id'], account_id, len(uids))
        return jsonify({'success': True, 'deleted': len(uids), 'folder': junk})


# ---------------------------------------------------------------------------
# 자동 처리(자동회신·자동전달·자동분류)가 실제로 돌고 있는지
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/automation-status')
@login_required
def api_automation_status():
    """마지막 자동 처리 시각.

    설정만 저장되고 **아무 일도 안 일어나는** 상태를 화면이 알 수 있어야 한다.
    crontab 의 `flask process-mail-automation` 이 돌 때마다 시각을 남긴다.
    """
    from modules.scheduler import AUTOMATION_STAMP

    last, stale = None, True
    try:
        with open(AUTOMATION_STAMP, encoding='utf-8') as f:
            last = f.read().strip()
        if last:
            delta = datetime.now() - datetime.fromisoformat(last)
            stale = delta.total_seconds() > 3600   # 1시간 넘게 안 돌았으면 안 도는 것으로 본다
    except FileNotFoundError:
        last = None
    except Exception as e:
        logger.warning("자동 처리 시각 확인 실패: %s", e)

    return jsonify({'last_run': last, 'stale': stale})


@mail_bp.route('/mail/api/accounts')
@login_required
def api_accounts():
    """현재 사용자가 접근 가능한 계정 목록 (IMAP 미사용, 가볍게 호출 가능).

    ?include_external=1 이면 외부메일(네이버·다음 등) 계정도 함께 준다.
    기본값을 바꾸지 않는 이유: 모바일 메일 화면이 같은 API 를 쓰고 있어
    목록이 갑자기 늘면 그쪽 계정 선택이 달라진다. 새 화면만 옵트인한다.
    """
    include_external = request.args.get('include_external') == '1'
    with get_db() as db:
        personal, shared = _get_user_accounts(db, session['user_id'])
        rows = list(personal) + list(shared)
        if include_external:
            rows += list(_get_external_accounts(db, session['user_id']))
        accounts = []
        for acc in rows:
            accounts.append({
                'id': acc.id,
                'email': acc.email,
                'display_name': acc.display_name or '',
                'is_shared': bool(acc.is_shared),
                # 추가 필드 — 기존 소비자(모바일)는 무시하므로 그대로 둬도 안전하다
                'account_type': getattr(acc, 'account_type', None) or 'internal',
            })
        return jsonify({'accounts': accounts})


@mail_bp.route('/mail/api/inbox-unread')
@login_required
def api_inbox_unread():
    """단일 계정의 INBOX UNSEEN 카운트만 빠르게 조회 (폴링용).

    list_folders()는 폴더당 STATUS 호출이 누적되어 비쌈. 새 메일 폴링은
    INBOX 하나만 보면 되므로 RTT 1번으로 끝낸다.
    """
    account_id = request.args.get('account', type=int)
    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        if not client:
            return jsonify({'unread': 0, 'no_account': True})
        try:
            with client:
                unread = client.inbox_unread_count()
            return jsonify({'unread': int(unread)})
        except Exception as e:
            logger.warning('inbox-unread account=%s 실패: %s', account_id, e)
            return jsonify({'error': str(e)}), 500


@mail_bp.route('/mail/api/unread-count')
@login_required
def api_unread_count():
    """개인+공용 계정 INBOX 안 읽음 합계.

    모바일 More 메뉴/대시보드 뱃지 등에서 호출. 한 사용자의 모든 활성 계정을
    돌며 IMAP STATUS UNSEEN 을 조회하므로 비용이 적지 않다. 호출측에서 60초
    이상 캐시하는 것을 권장한다.
    """
    with get_db() as db:
        personal, shared = _get_user_accounts(db, session['user_id'])
        accounts = list(personal) + list(shared)

        total = 0
        per_account = []
        for acc in accounts:
            unread = 0
            error = None
            try:
                client, account, err = _get_mail_client(db, acc.id)
                if err or not client:
                    error = err or 'no_client'
                else:
                    with client:
                        unread = client.inbox_unread_count()
            except Exception as e:
                logger.warning('unread-count account=%s 실패: %s', acc.id, e)
                error = str(e)
            total += unread
            per_account.append({
                'account_id': acc.id,
                'email': acc.email,
                'display_name': acc.display_name or '',
                'is_shared': bool(acc.is_shared),
                'unread': unread,
                'error': error,
            })
        return jsonify({'total': total, 'accounts': per_account})


@mail_bp.route('/mail/api/attachment/<int:uid>/<part_id>')
@login_required
def api_attachment(uid, part_id):
    """첨부파일 다운로드."""
    folder = request.args.get('folder', 'INBOX')
    account_id = request.args.get('account', type=int)

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        try:
            with client:
                filename, content_type, file_bytes = client.fetch_attachment(uid, part_id, folder)
            if not file_bytes:
                return jsonify({'error': '첨부파일을 찾을 수 없습니다.'}), 404

            from urllib.parse import quote
            encoded_name = quote(filename or 'attachment', safe='')
            return Response(
                file_bytes,
                mimetype=content_type or 'application/octet-stream',
                headers={
                    'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_name}",
                }
            )
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@mail_bp.route('/mail/api/attachments-zip/<int:uid>')
@login_required
def api_attachments_zip(uid):
    """메일의 모든 첨부파일을 ZIP으로 한 번에 다운로드."""
    import io
    import re
    import zipfile
    from urllib.parse import quote

    folder = request.args.get('folder', 'INBOX')
    account_id = request.args.get('account', type=int)
    subject = (request.args.get('subject', '') or '').strip()
    # 파일명으로 못 쓰는 문자 치환 + 길이 제한
    safe_subject = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', subject).strip()[:120]
    zip_name = f'{safe_subject or f"attachments_{uid}"}.zip'

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        try:
            with client:
                files = client.fetch_all_attachments(uid, folder)
            if not files:
                return jsonify({'error': '첨부파일이 없습니다.'}), 404

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                used = {}
                for filename, data in files:
                    orig = filename or 'attachment'
                    name = orig
                    # 동일 파일명 중복 시 (1), (2) 접미사
                    if orig in used:
                        used[orig] += 1
                        base, dot, ext = orig.rpartition('.')
                        if dot:
                            name = f"{base} ({used[orig]}).{ext}"
                        else:
                            name = f"{orig} ({used[orig]})"
                    else:
                        used[orig] = 0
                    zf.writestr(name, data)
            buf.seek(0)

            encoded_name = quote(zip_name, safe='')
            return Response(
                buf.getvalue(),
                mimetype='application/zip',
                headers={
                    'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_name}",
                }
            )
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@mail_bp.route('/mail/api/search')
@login_required
def api_search():
    """메일 검색."""
    q = request.args.get('q', '').strip()
    folder = request.args.get('folder', 'INBOX')
    account_id = request.args.get('account', type=int)

    if not q:
        return jsonify({'uids': []})

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        try:
            with client:
                uids = client.search_messages(q, folder)
                if uids:
                    result = client.fetch_by_uids(folder, uids)
                else:
                    result = {'messages': [], 'total': 0, 'page': 1, 'pages': 1}
            return jsonify(result)
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@mail_bp.route('/mail/api/contacts/suggest')
@login_required
def api_contacts_suggest():
    """주소록 자동완성 + 주소록 모달 전체 목록."""
    q = request.args.get('q', '').strip()
    limit = request.args.get('limit', '10')
    try:
        limit = int(limit)
    except ValueError:
        limit = 10

    # q가 없으면 전체 목록 모드 (주소록 모달용)
    show_all = not q

    results = []
    with get_db() as db:
        import os
        _mail_domain = os.environ.get('MAILCOW_DOMAIN', 'mgnt.kr')

        # 사내 직원 (사내메일 = username@mgnt.kr)
        user_q = db.query(User).filter(User.is_active == True)
        if not show_all:
            user_q = user_q.filter(
                (User.full_name.ilike(f'%{q}%') | User.username.ilike(f'%{q}%'))
            )
        users = user_q.order_by(User.full_name).limit(limit).all()
        for u in users:
            results.append({
                'name': u.full_name,
                'email': f'{u.username}@{_mail_domain}',
                'company': '(주)매그나텍',
                'type': 'internal',
            })

        # 회사 공용 + 내 주소록. 범위를 자르는 잣대는 목록 API 와 같은 것을 쓴다
        # (or_(is_shared, user_id==me) 로 두면 남이 공유로 표시한 개인 줄까지 새어 나온다)
        from sqlalchemy import or_
        contact_q = db.query(MailContact).filter(
            or_(
                (MailContact.user_id.is_(None)) & (MailContact.is_shared == True),
                MailContact.user_id == session['user_id'],
            )
        )
        if not show_all:
            contact_q = contact_q.filter(
                (MailContact.name.ilike(f'%{q}%') | MailContact.email.ilike(f'%{q}%'))
            )
        contacts = contact_q.order_by(MailContact.name).limit(limit).all()
        for c in contacts:
            results.append({
                'name': c.name,
                'email': c.email,
                'company': c.company,
                'phone': c.phone or '',
                'type': 'shared' if c.user_id is None else 'personal',
            })

    return jsonify(results)


@mail_bp.route('/mail/api/account/switch', methods=['POST'])
@login_required
def api_account_switch():
    """계정 전환."""
    data = request.get_json()
    account_id = data.get('account_id')
    # 권한만 확인
    with get_db() as db:
        _, _, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
    return jsonify({'success': True, 'account_id': account_id})


# ---------------------------------------------------------------------------
# 설정 API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/account', methods=['POST'])
@login_required
def api_account_save():
    """메일 계정 저장/수정."""
    data = request.get_json()
    user_id = session['user_id']

    with get_db() as db:
        account_id = data.get('id')
        if account_id:
            account = db.query(MailAccount).filter_by(id=account_id).first()
            if not account:
                return jsonify({'error': '계정을 찾을 수 없습니다.'}), 404
            if account.user_id != user_id and session.get('role') != 'admin':
                # 공용 계정이면 shared_access 확인
                if account.is_shared:
                    has_access = db.query(MailSharedAccess).filter_by(
                        mail_account_id=account_id, user_id=user_id
                    ).first()
                    if not has_access:
                        return jsonify({'error': '권한이 없습니다.'}), 403
                else:
                    return jsonify({'error': '권한이 없습니다.'}), 403
        else:
            account = MailAccount(user_id=user_id)
            db.add(account)

        # 일반 사용자: display_name, signature, 비밀번호 변경 가능
        account.display_name = data.get('display_name', account.display_name)
        account.signature = data.get('signature', account.signature)

        # 비밀번호는 본인 계정이면 변경 가능
        if account.user_id == user_id or session.get('role') == 'admin':
            password = data.get('password')
            if password:
                account.password_encrypted = encrypt_password(password)

        # 서버 설정은 관리자만
        if session.get('role') == 'admin':
            if 'email' in data:
                account.email = data['email']
            if 'imap_host' in data:
                account.imap_host = data['imap_host']
            if 'imap_port' in data:
                account.imap_port = data['imap_port']
            if 'smtp_host' in data:
                account.smtp_host = data['smtp_host']
            if 'smtp_port' in data:
                account.smtp_port = data['smtp_port']
            if 'username' in data:
                account.username = data['username']
            password = data.get('password')
            if password:
                account.password_encrypted = encrypt_password(password)

        db.commit()
        return jsonify({'success': True, 'id': account.id})


@mail_bp.route('/mail/api/account/<int:account_id>/test', methods=['POST'])
@login_required
def api_account_test(account_id):
    """메일 계정 연결 테스트."""
    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'success': False, 'error': err}), 400
        try:
            with client:
                folders = client.list_folders()
            return jsonify({'success': True, 'folders': len(folders), 'message': f'연결 성공! {len(folders)}개 폴더 발견'})
        except Exception as e:
            return jsonify({'success': False, 'error': f'연결 실패: {e}'}), 400


# ---------------------------------------------------------------------------
# 관리자 API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/admin/test-connection', methods=['POST'])
@admin_required
def api_admin_test_connection():
    """등록 전 IMAP 연결 테스트 (폼 데이터 직접 사용)."""
    data = request.get_json()
    imap_host = data.get('imap_host', '')
    imap_port = int(data.get('imap_port', 993))
    use_ssl = data.get('use_ssl', True)
    username = data.get('username') or data.get('email', '')
    password = data.get('password', '')

    if not imap_host or not username or not password:
        return jsonify({'success': False, 'error': '필수 항목을 입력하세요.'}), 400

    try:
        from imapclient import IMAPClient
        import ssl as _ssl
        ssl_context = _ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = _ssl.CERT_NONE

        client = IMAPClient(imap_host, port=imap_port, ssl=use_ssl, ssl_context=ssl_context, timeout=10)
        client.login(username, password)
        folders = client.list_folders()
        client.logout()
        return jsonify({'success': True, 'message': f'연결 성공! {len(folders)}개 폴더 확인'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@mail_bp.route('/mail/api/admin/shared', methods=['POST'])
@admin_required
def api_admin_shared_account():
    """공용계정 생성/수정 (admin)."""
    data = request.get_json()
    with get_db() as db:
        account_id = data.get('id')
        if account_id:
            account = db.query(MailAccount).filter_by(id=account_id).first()
        else:
            account = MailAccount(is_shared=True)
            db.add(account)

        account.email = data['email']
        account.display_name = data.get('display_name', '')
        mailcow_host = os.environ.get('MAILCOW_URL', '127.0.0.1').replace('https://', '').replace('http://', '').split(':')[0]
        account.imap_host = data.get('imap_host', mailcow_host)
        account.imap_port = data.get('imap_port', int(os.environ.get('MAILCOW_IMAPS_PORT', '9993')))
        account.smtp_host = data.get('smtp_host', mailcow_host)
        account.smtp_port = data.get('smtp_port', int(os.environ.get('MAILCOW_SUBMISSION_PORT', '5587')))
        account.username = data.get('username', data['email'])
        account.is_shared = True
        account.use_ssl = data.get('use_ssl', True)
        account.signature = data.get('signature', '')

        password = data.get('password')
        if password:
            account.password_encrypted = encrypt_password(password)
            try:
                from modules.services.mailcow_api import sync_password as _mc_sync
                _mc_sync(account.email or data['email'], password)
            except Exception:
                logger.warning('Mailcow password sync failed for %s', account.email)

        db.commit()
        return jsonify({'success': True, 'id': account.id})


@mail_bp.route('/mail/api/admin/shared-access', methods=['POST'])
@admin_required
def api_admin_shared_access():
    """공용계정 접근 권한 설정 (admin)."""
    data = request.get_json()
    with get_db() as db:
        # 기존 권한 삭제 후 재설정
        mail_account_id = data['mail_account_id']
        db.query(MailSharedAccess).filter_by(mail_account_id=mail_account_id).delete()

        for access in data.get('access_list', []):
            sa = MailSharedAccess(
                mail_account_id=mail_account_id,
                user_id=access['user_id'],
                can_send=access.get('can_send', False),
                can_delete=access.get('can_delete', False),
            )
            db.add(sa)
        db.commit()
        return jsonify({'success': True})


@mail_bp.route('/mail/api/admin/mail-config')
@admin_required
def api_admin_mail_config():
    """메일설정 탭 데이터: 공용계정 + 사용자 + 접근 권한."""
    with get_db() as db:
        shared = db.query(MailAccount).filter_by(is_shared=True, is_active=True).all()
        users = db.query(User).filter(User.is_active == True, User.is_approved == True).order_by(User.user_group, User.full_name).all()
        access_rows = db.query(MailSharedAccess).all()

        access_map = {}
        for a in access_rows:
            access_map.setdefault(a.user_id, []).append({
                'account_id': a.mail_account_id,
                'can_send': bool(a.can_send),
                'can_delete': bool(a.can_delete),
            })

        return jsonify({
            'shared_accounts': [{
                'id': s.id, 'email': s.email, 'display_name': s.display_name,
                'username': s.username, 'use_ssl': bool(s.use_ssl),
                'imap_host': s.imap_host, 'imap_port': s.imap_port,
                'smtp_host': s.smtp_host, 'smtp_port': s.smtp_port,
                'is_active': s.is_active,
            } for s in shared],
            'users': [{
                'id': u.id, 'name': u.full_name, 'group': u.user_group or '', 'position': u.position or '',
            } for u in users],
            'access': access_map,
        })


@mail_bp.route('/mail/api/admin/mail-access', methods=['POST'])
@admin_required
def api_admin_mail_access():
    """공용메일 접근 권한 일괄 저장 (계정별 보기/발송/삭제)."""
    access_list = request.get_json()  # [{user_id, account_id, read, send, delete}, ...]
    with get_db() as db:
        db.query(MailSharedAccess).delete()

        granted_user_ids = set()
        for item in access_list:
            db.add(MailSharedAccess(
                mail_account_id=item['account_id'],
                user_id=item['user_id'],
                can_send=item.get('send', False),
                can_delete=item.get('delete', False),
            ))
            granted_user_ids.add(item['user_id'])

        # mail_shared 메뉴 권한 동기화
        all_users = db.query(User).filter(User.is_active == True).all()
        for u in all_users:
            menus = [m.strip() for m in (u.extra_menus or '').split(',') if m.strip()]
            has_mail_shared = any(m.split(':')[0] == 'mail_shared' for m in menus)

            if u.id in granted_user_ids and not has_mail_shared:
                menus.append('mail_shared:rw')
                u.extra_menus = ','.join(menus)
            elif u.id not in granted_user_ids and has_mail_shared:
                menus = [m for m in menus if m.split(':')[0] != 'mail_shared']
                u.extra_menus = ','.join(menus)

        db.commit()
        return jsonify({'success': True})


@mail_bp.route('/mail/api/admin/shared/<int:account_id>', methods=['DELETE'])
@admin_required
def api_admin_delete_shared(account_id):
    """공용계정 삭제."""
    with get_db() as db:
        db.query(MailSharedAccess).filter_by(mail_account_id=account_id).delete()
        db.query(MailReadReceipt).filter_by(mail_account_id=account_id).delete()
        db.query(MailAccount).filter_by(id=account_id, is_shared=True).delete()
        db.commit()
        return jsonify({'success': True})


# ---------------------------------------------------------------------------
# 공용메일 순서 변경 API
@mail_bp.route('/mail/api/shared-order', methods=['POST'])
@login_required
def api_shared_order():
    """공용메일 탭 순서 변경."""
    data = request.get_json()
    order = data.get('order', [])  # [account_id, ...]
    user_id = session['user_id']
    with get_db() as db:
        for i, aid in enumerate(order):
            db.query(MailSharedAccess).filter_by(
                user_id=user_id, mail_account_id=aid
            ).update({'sort_order': i})
        db.commit()
        return jsonify({'success': True})


# ---------------------------------------------------------------------------
# 외부메일 순서 변경 API
@mail_bp.route('/mail/api/external-order', methods=['POST'])
@login_required
def api_external_order():
    """외부메일 탭 순서 변경."""
    data = request.get_json()
    order = data.get('order', [])  # [account_id, ...]
    user_id = session['user_id']
    with get_db() as db:
        for i, aid in enumerate(order):
            db.query(MailAccount).filter_by(
                id=aid, user_id=user_id, account_type='external'
            ).update({'sort_order': i})
        db.commit()
        return jsonify({'success': True})


# 라벨 API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/labels', methods=['POST'])
@login_required
def api_label_save():
    """라벨 생성/수정."""
    data = request.get_json()
    account_id = data.get('account_id')
    with get_db() as db:
        label_id = data.get('id')
        if label_id:
            label = db.query(MailLabel).filter_by(id=label_id).first()
            if not label:
                return jsonify({'error': '라벨을 찾을 수 없습니다.'}), 404
        else:
            label = MailLabel(account_id=account_id)
            db.add(label)
        label.name = data.get('name', label.name if label_id else '')
        label.color = data.get('color', label.color if label_id else '#64748b')
        label.sort_order = data.get('sort_order', label.sort_order if label_id else 0)
        db.commit()
        return jsonify({'success': True, 'id': label.id})


@mail_bp.route('/mail/api/labels/<int:label_id>', methods=['DELETE'])
@login_required
def api_label_delete(label_id):
    """라벨 삭제."""
    with get_db() as db:
        db.query(MailLabel).filter_by(id=label_id).delete()
        db.commit()
        return jsonify({'success': True})


# ---------------------------------------------------------------------------
# 자동분류 규칙 API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/rules')
@login_required
def api_rules_list():
    """자동분류 규칙 목록. shared=true면 공용메일 공유 규칙."""
    account_id = request.args.get('account', type=int)
    with get_db() as db:
        if not _account_allowed(db, account_id):
            return jsonify({'error': '접근 권한이 없습니다.'}), 403
        rules = db.query(MailRule).filter_by(account_id=account_id).order_by(MailRule.priority, MailRule.id).all()
        return jsonify([{
            'id': r.id, 'name': r.name, 'priority': r.priority,
            'is_active': r.is_active, 'conditions_json': r.conditions_json,
            'condition_logic': r.condition_logic, 'action_type': r.action_type,
            'action_value': r.action_value, 'stop_processing': r.stop_processing,
            'is_shared': r.is_shared,
        } for r in rules])


@mail_bp.route('/mail/api/rules', methods=['POST'])
@login_required
def api_rule_save():
    """자동분류 규칙 생성/수정."""
    data = request.get_json()
    with get_db() as db:
        rule_id = data.get('id')
        if rule_id:
            rule = db.query(MailRule).filter_by(id=rule_id).first()
            if not rule or not _account_allowed(db, rule.account_id):
                return jsonify({'error': '규칙을 찾을 수 없습니다.'}), 404
        else:
            if not _account_allowed(db, data.get('account_id')):
                return jsonify({'error': '접근 권한이 없습니다.'}), 403
            rule = MailRule(account_id=data.get('account_id'))
            db.add(rule)
        rule.name = data.get('name', '')
        rule.priority = data.get('priority', 0)
        rule.is_active = data.get('is_active', True)
        rule.conditions_json = json.dumps(data.get('conditions', []), ensure_ascii=False)
        rule.condition_logic = data.get('condition_logic', 'AND')
        rule.action_type = data.get('action_type', 'move_folder')
        rule.action_value = data.get('action_value', '')
        rule.stop_processing = data.get('stop_processing', True)
        db.commit()
        return jsonify({'success': True, 'id': rule.id})


@mail_bp.route('/mail/api/rules/<int:rule_id>', methods=['DELETE'])
@login_required
def api_rule_delete(rule_id):
    """자동분류 규칙 삭제."""
    with get_db() as db:
        rule = db.query(MailRule).filter_by(id=rule_id).first()
        if not rule or not _account_allowed(db, rule.account_id):
            return jsonify({'error': '규칙을 찾을 수 없습니다.'}), 404
        db.delete(rule)
        db.commit()
        return jsonify({'success': True})


@mail_bp.route('/mail/api/rules/apply', methods=['POST'])
@login_required
def api_rules_apply():
    """받은편지함 메일에 자동분류 규칙 적용."""
    import json as _json
    from modules.services.mail_classifier import classify_mail, apply_actions

    data = request.get_json()
    account_id = data.get('account_id')
    folder = data.get('folder', 'INBOX')

    with get_db() as db:
        # 규칙 로드
        rules = db.query(MailRule).filter_by(account_id=account_id, is_active=True).order_by(MailRule.priority, MailRule.id).all()
        if not rules:
            return jsonify({'success': True, 'message': '적용할 규칙이 없습니다.', 'processed': 0})

        rules_data = [{
            'id': r.id, 'name': r.name, 'conditions_json': r.conditions_json,
            'condition_logic': r.condition_logic, 'action_type': r.action_type,
            'action_value': r.action_value, 'stop_processing': r.stop_processing,
            'is_active': r.is_active,
        } for r in rules]

        # IMAP 연결
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400

        results = []
        processed = 0
        try:
            with client:
                imap = client._imap
                imap.select_folder(folder, readonly=False)
                all_uids = imap.search('ALL')
                if not all_uids:
                    return jsonify({'success': True, 'processed': 0, 'actions': 0, 'details': []})

                # 배치 단위로 ENVELOPE 조회 (메모리 절약)
                batch_size = 200
                for i in range(0, len(all_uids), batch_size):
                    batch_uids = all_uids[i:i + batch_size]
                    raw = imap.fetch(batch_uids, ['ENVELOPE', 'BODY.PEEK[HEADER.FIELDS (CONTENT-TYPE TO)]'])

                    for uid in batch_uids:
                        if uid not in raw:
                            continue
                        env = raw[uid].get(b'ENVELOPE')
                        if not env:
                            continue

                        header_bytes = raw[uid].get(b'BODY[HEADER.FIELDS (CONTENT-TYPE TO)]', b'').decode(errors='replace')
                        has_attach = 'multipart/mixed' in header_bytes.lower()

                        from_addr = ''
                        from_name = ''
                        if env.from_ and len(env.from_) > 0:
                            f = env.from_[0]
                            from_addr = f'{(f.mailbox or b"").decode(errors="replace")}@{(f.host or b"").decode(errors="replace")}'
                            from_name = _decode_header_value((f.name or b'').decode(errors='replace'))

                        # 제목·보낸사람 이름은 **반드시 풀어서** 비교한다.
                        # IMAP 이 주는 값은 '=?utf-8?b?…?=' 라, 그대로 두면
                        # "제목에 '공고' 포함" 같은 한글 조건이 한 번도 안 맞는다.
                        subject = ''
                        if env.subject:
                            raw_subject = (env.subject.decode('utf-8', errors='replace')
                                           if isinstance(env.subject, bytes) else (env.subject or ''))
                            subject = _decode_header_value(raw_subject)

                        # To 주소: ENVELOPE + 헤더에서 파싱 (포워딩된 메일 대응)
                        to_addrs = []
                        if env.to:
                            for t in env.to:
                                addr = f'{(t.mailbox or b"").decode(errors="replace")}@{(t.host or b"").decode(errors="replace")}'
                                to_addrs.append(addr.lower())
                        if not to_addrs:
                            import re as _re
                            to_match = _re.search(r'(?i)^To:\s*(.+?)(?:\r?\n(?!\s)|$)', header_bytes, _re.DOTALL)
                            if to_match:
                                to_addrs = [a.strip().lower() for a in to_match.group(1).split(',')]
                        to_email_str = ', '.join(to_addrs) if to_addrs else account.email

                        mail_data = {
                            'from_email': from_addr,
                            'from_name': from_name,
                            'to_email': to_email_str,
                            'subject': subject,
                            'has_attachment': has_attach,
                        }
                        actions = classify_mail(rules_data, mail_data)
                        if actions:
                            action_results = apply_actions(client, uid, folder, actions)
                            results.extend(action_results)
                        processed += 1
        except Exception as e:
            return jsonify({'error': f'분류 실행 오류: {e}'}), 500

        return jsonify({
            'success': True,
            'processed': processed,
            'actions': len(results),
            'details': results,
        })



# ---------------------------------------------------------------------------
# 자동회신 API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/auto-reply', methods=['GET'])
@login_required
def api_auto_reply_get():
    account_id = request.args.get('account', type=int)
    with get_db() as db:
        if not _account_allowed(db, account_id):
            return jsonify({'error': '접근 권한이 없습니다.'}), 403
        ar = db.query(MailAutoReply).filter_by(account_id=account_id).first()
        if not ar:
            return jsonify({'is_active': False, 'subject': '부재중 자동회신', 'body': '', 'start_date': '', 'end_date': '', 'reply_once': True})
        return jsonify({
            'id': ar.id, 'is_active': ar.is_active, 'subject': ar.subject, 'body': ar.body,
            'start_date': ar.start_date.strftime('%Y-%m-%d') if ar.start_date else '',
            'end_date': ar.end_date.strftime('%Y-%m-%d') if ar.end_date else '',
            'reply_once': ar.reply_once,
        })


@mail_bp.route('/mail/api/auto-reply', methods=['POST'])
@login_required
def api_auto_reply_save():
    data = request.get_json()
    account_id = data.get('account_id')
    with get_db() as db:
        if not _account_allowed(db, account_id):
            return jsonify({'error': '접근 권한이 없습니다.'}), 403
        ar = db.query(MailAutoReply).filter_by(account_id=account_id).first()
        if not ar:
            ar = MailAutoReply(account_id=account_id)
            db.add(ar)
        ar.is_active = data.get('is_active', False)
        ar.subject = data.get('subject', '부재중 자동회신')
        ar.body = data.get('body', '')
        ar.start_date = data.get('start_date') or None
        ar.end_date = data.get('end_date') or None
        ar.reply_once = data.get('reply_once', True)
        if not data.get('is_active'):
            ar.replied_addresses = ''
        db.commit()
        return jsonify({'success': True})


# ---------------------------------------------------------------------------
# 자동전달 API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/auto-forward', methods=['GET'])
@login_required
def api_auto_forward_get():
    account_id = request.args.get('account', type=int)
    with get_db() as db:
        if not _account_allowed(db, account_id):
            return jsonify({'error': '접근 권한이 없습니다.'}), 403
        rows = db.query(MailAutoForward).filter_by(account_id=account_id).all()
        return jsonify([{
            'id': r.id, 'forward_to': r.forward_to, 'is_active': r.is_active, 'keep_copy': r.keep_copy,
        } for r in rows])


@mail_bp.route('/mail/api/auto-forward', methods=['POST'])
@login_required
def api_auto_forward_save():
    data = request.get_json()
    account_id = data.get('account_id')
    with get_db() as db:
        fwd_id = data.get('id')
        if fwd_id:
            # 고칠 때는 **그 줄이 달린 계정**을 본다. account_id 만 믿으면
            # 내 계정 번호를 적어 남의 전달규칙을 고칠 수 있다.
            fwd = db.query(MailAutoForward).filter_by(id=fwd_id).first()
            if not fwd or not _account_allowed(db, fwd.account_id):
                return jsonify({'error': '전달 규칙을 찾을 수 없습니다.'}), 404
        else:
            if not _account_allowed(db, account_id):
                return jsonify({'error': '접근 권한이 없습니다.'}), 403
            fwd = MailAutoForward(account_id=account_id)
            db.add(fwd)
        fwd.forward_to = data.get('forward_to', '')
        fwd.is_active = data.get('is_active', True)
        fwd.keep_copy = data.get('keep_copy', True)
        db.commit()
        return jsonify({'success': True, 'id': fwd.id})


@mail_bp.route('/mail/api/auto-forward/<int:fwd_id>', methods=['DELETE'])
@login_required
def api_auto_forward_delete(fwd_id):
    with get_db() as db:
        fwd = db.query(MailAutoForward).filter_by(id=fwd_id).first()
        if not fwd or not _account_allowed(db, fwd.account_id):
            return jsonify({'error': '전달 규칙을 찾을 수 없습니다.'}), 404
        db.delete(fwd)
        db.commit()
        return jsonify({'success': True})


# ---------------------------------------------------------------------------
# 예약발송 API
# ---------------------------------------------------------------------------
# 예약발송 첨부 보관 위치 (Supabase Storage)
_SCHED_ATTACH_PREFIX = 'mail-scheduled'


def _store_scheduled_attachments(sched_id, files):
    """예약 메일의 첨부를 Storage 에 올리고 메타데이터 목록을 돌려준다.

    files: [(filename, bytes, content_type), ...]
    반환:  [{'filename':…, 'path':…, 'size':…, 'content_type':…}, ...]

    예약은 몇 시간 뒤에 실행되므로 파일 바이트를 메모리나 DB 본문에 들고 있을
    수 없다. Storage 에 올려 두고 경로만 DB(attachments_json)에 적는다.
    """
    stored = []
    for fname, data, ctype in files:
        if not fname or not data:
            continue
        ext = os.path.splitext(fname)[1] or ''
        # 번호 대신 임의 이름 — 예약을 수정할 때 남겨둔 첨부를 덮어쓰지 않도록
        path = f'{_SCHED_ATTACH_PREFIX}/{sched_id}/{uuid.uuid4().hex[:10]}{ext}'
        ok, msg = storage_adapter.upload_bytes(
            path, data, content_type=ctype or 'application/octet-stream')
        if not ok:
            logger.error('예약 첨부 업로드 실패: %s → %s (%s)', fname, path, msg)
            raise RuntimeError(f'첨부 저장 실패: {fname}')
        stored.append({
            'filename': fname, 'path': path,
            'size': len(data), 'content_type': ctype or '',
        })
    return stored


def _delete_scheduled_attachments(attachments_json):
    """예약이 취소·완료됐을 때 Storage 에 남은 첨부를 지운다."""
    try:
        for a in json.loads(attachments_json or '[]'):
            if a.get('path'):
                storage_adapter.delete_object(a['path'])
    except Exception as e:
        logger.warning('예약 첨부 정리 실패: %s', e)


@mail_bp.route('/mail/api/schedule', methods=['POST'])
@login_required
def api_schedule_send():
    """예약발송 등록.

    JSON 과 multipart 를 모두 받는다 — 기존 ERP 작성 화면은 JSON 으로 부르고,
    새 메일 화면은 첨부를 실어 multipart 로 부른다.
    """
    is_form = bool(request.files) or not request.is_json
    if is_form:
        data = {
            'account_id': request.form.get('account_id', type=int),
            'to': request.form.get('to', ''),
            'cc': request.form.get('cc', ''),
            'bcc': request.form.get('bcc', ''),
            'subject': request.form.get('subject', ''),
            'body': request.form.get('body', ''),
            'scheduled_at': request.form.get('scheduled_at', ''),
        }
    else:
        data = request.get_json() or {}

    if not data.get('account_id') or not data.get('scheduled_at'):
        return jsonify({'error': '계정과 예약 시각이 필요합니다.'}), 400

    # 연도 네 자리로 제한 — 화면 제한만으로는 직접 호출을 못 막는다
    _at = str(data['scheduled_at']).strip()
    for _fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            _parsed = datetime.strptime(_at, _fmt)
            break
        except ValueError:
            _parsed = None
    if _parsed is None:
        return jsonify({'error': '예약 시각 형식을 확인해주세요.'}), 400
    if _parsed.year > 9999:
        return jsonify({'error': '예약 연도는 9999년까지만 됩니다.'}), 400
    if _parsed <= datetime.now():
        return jsonify({'error': '지난 시각으로는 예약할 수 없습니다.'}), 400

    with get_db() as db:
        sched = MailScheduled(
            account_id=data['account_id'],
            user_id=session['user_id'],
            to_addresses=data.get('to', ''),
            cc_addresses=data.get('cc', ''),
            bcc_addresses=data.get('bcc', ''),
            subject=data.get('subject', ''),
            body=data.get('body', ''),
            scheduled_at=data['scheduled_at'],
        )
        # 대용량 첨부는 예약 시점에 바로 링크로 바꿔 본문에 넣는다
        try:
            large_items = json.loads(request.form.get('large_files', '[]'))
        except Exception as e:
            logger.error('예약 large_files 해석 실패: %s', e)
            large_items = []
        if large_items:
            try:
                sched.body = (sched.body or '') + _large_files_html(
                    _promote_large_files(db, large_items))
            except RuntimeError as e:
                db.rollback()
                return jsonify({'error': str(e)}), 500

        db.add(sched)
        db.flush()   # 첨부 경로에 쓸 id 확보

        # 새로 올린 파일 + 전달 원본 첨부(IMAP에서 바로 읽어 옮긴다)
        pending = []
        for f in request.files.getlist('attachments'):
            if f.filename:
                pending.append((f.filename, f.read(), f.mimetype))

        fwd_uid = request.form.get('forward_source_uid', type=int)
        fwd_account = request.form.get('forward_account_id', type=int)
        fwd_folder = request.form.get('forward_folder', 'INBOX')
        fwd_parts = request.form.get('forward_parts', '')
        if fwd_uid and fwd_account and fwd_parts:
            try:
                fwd_client, _fwd_acc, fwd_err = _get_mail_client(db, fwd_account)
                if fwd_client and not fwd_err:
                    with fwd_client:
                        for part_id in json.loads(fwd_parts):
                            fname, ctype, raw = fwd_client.fetch_attachment(
                                fwd_uid, str(part_id), fwd_folder)
                            if fname and raw:
                                pending.append((fname, raw, ctype))
            except Exception as e:
                logger.error('예약 전달 첨부 로드 실패: %s', e)

        if pending:
            try:
                sched.attachments_json = json.dumps(
                    _store_scheduled_attachments(sched.id, pending), ensure_ascii=False)
            except RuntimeError as e:
                db.rollback()
                return jsonify({'error': str(e)}), 500

        db.commit()
        return jsonify({
            'success': True, 'id': sched.id,
            'attachment_count': len(pending),
        })


@mail_bp.route('/mail/api/schedule')
@login_required
def api_schedule_list():
    """예약 대기 목록. status 를 주면 그 상태만 (기본: pending)."""
    account_id = request.args.get('account', type=int)
    status = request.args.get('status', 'pending')
    with get_db() as db:
        q = db.query(MailScheduled).filter_by(account_id=account_id)
        if status != 'all':
            q = q.filter(MailScheduled.status == status)
        rows = q.order_by(MailScheduled.scheduled_at).all()

        out = []
        for r in rows:
            try:
                n_att = len(json.loads(r.attachments_json or '[]'))
            except Exception:
                n_att = 0
            out.append({
                'id': r.id,
                'to': r.to_addresses,
                'cc': r.cc_addresses or '',
                'bcc': r.bcc_addresses or '',
                'subject': r.subject,
                'status': r.status,
                'attachment_count': n_att,
                'scheduled_at': r.scheduled_at.strftime('%Y-%m-%d %H:%M') if r.scheduled_at else '',
                'created_at': r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else '',
            })
        return jsonify(out)


def _own_schedule(db, sched_id):
    """내가 손댈 수 있는 대기 중 예약인지 확인해서 돌려준다.

    예전에는 id 만 맞으면 누구나 남의 예약을 지울 수 있었다.
    예약을 건 사람(또는 관리자)만 만지게 한다.
    """
    row = db.query(MailScheduled).filter_by(id=sched_id, status='pending').first()
    if not row:
        return None, ('이미 보냈거나 없는 예약입니다.', 404)
    if row.user_id != session.get('user_id') and session.get('role') != 'admin':
        return None, ('이 예약을 변경할 권한이 없습니다.', 403)
    return row, None


@mail_bp.route('/mail/api/schedule/<int:sched_id>')
@login_required
def api_schedule_detail(sched_id):
    """예약 메일 한 건의 본문·첨부 목록."""
    with get_db() as db:
        row = db.query(MailScheduled).filter_by(id=sched_id).first()
        if not row:
            return jsonify({'error': '예약을 찾을 수 없습니다.'}), 404
        if row.user_id != session.get('user_id') and session.get('role') != 'admin':
            return jsonify({'error': '이 예약을 볼 권한이 없습니다.'}), 403

        try:
            atts = json.loads(row.attachments_json or '[]')
        except Exception:
            atts = []

        return jsonify({
            'id': row.id,
            'status': row.status,
            'to': row.to_addresses, 'cc': row.cc_addresses or '', 'bcc': row.bcc_addresses or '',
            'subject': row.subject or '',
            # 본문은 이 사용자가 직접 쓴 HTML 이라 그대로 돌려준다
            'body': row.body or '',
            'scheduled_at': row.scheduled_at.strftime('%Y-%m-%d %H:%M') if row.scheduled_at else '',
            'created_at': row.created_at.strftime('%Y-%m-%d %H:%M') if row.created_at else '',
            'attachments': [{
                'index': i,
                'filename': a.get('filename', ''),
                'size': a.get('size', 0),
                'content_type': a.get('content_type', ''),
            } for i, a in enumerate(atts)],
        })


@mail_bp.route('/mail/api/schedule/<int:sched_id>/attachment/<int:idx>')
@login_required
def api_schedule_attachment(sched_id, idx):
    """예약 메일에 달아둔 첨부 내려받기 (Storage 에서 꺼내 그대로 넘긴다)."""
    with get_db() as db:
        row = db.query(MailScheduled).filter_by(id=sched_id).first()
        if not row:
            return jsonify({'error': '예약을 찾을 수 없습니다.'}), 404
        if row.user_id != session.get('user_id') and session.get('role') != 'admin':
            return jsonify({'error': '권한이 없습니다.'}), 403
        try:
            atts = json.loads(row.attachments_json or '[]')
        except Exception:
            atts = []
        if idx < 0 or idx >= len(atts):
            return jsonify({'error': '첨부를 찾을 수 없습니다.'}), 404

        a = atts[idx]
        data = storage_adapter.download_bytes(a.get('path', ''))
        if data is None:
            return jsonify({'error': '첨부 파일을 읽지 못했습니다.'}), 404

        filename = a.get('filename') or 'attachment'
        resp = Response(data, mimetype=a.get('content_type') or 'application/octet-stream')
        resp.headers['Content-Disposition'] = (
            "attachment; filename*=UTF-8''" + urlquote(filename)
        )
        return resp


@mail_bp.route('/mail/api/schedule/<int:sched_id>', methods=['PATCH'])
@login_required
def api_schedule_update(sched_id):
    """예약 시각 변경. 본문·첨부는 그대로 두고 보낼 시각만 바꾼다."""
    data = request.get_json() or {}
    at = (data.get('scheduled_at') or '').strip()
    if not at:
        return jsonify({'error': '변경할 시각이 필요합니다.'}), 400

    with get_db() as db:
        row, err = _own_schedule(db, sched_id)
        if err:
            return jsonify({'error': err[0]}), err[1]
        try:
            new_at = datetime.strptime(at, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                new_at = datetime.strptime(at, '%Y-%m-%d %H:%M')
            except ValueError:
                return jsonify({'error': '시각 형식을 확인해주세요.'}), 400
        if new_at <= datetime.now():
            return jsonify({'error': '지난 시각으로는 변경할 수 없습니다.'}), 400
        if new_at.year > 9999:
            return jsonify({'error': '예약 연도는 9999년까지만 됩니다.'}), 400

        row.scheduled_at = new_at
        db.commit()
        return jsonify({
            'success': True,
            'scheduled_at': new_at.strftime('%Y-%m-%d %H:%M'),
        })


@mail_bp.route('/mail/api/schedule/<int:sched_id>', methods=['PUT'])
@login_required
def api_schedule_replace(sched_id):
    """예약 메일 통째로 수정 — 받는사람·제목·본문·첨부·시각.

    첨부는 '남길 기존 첨부 번호(keep_attachments)' + '새로 올린 파일' 로 받는다.
    빠진 기존 첨부는 Storage 에서도 지운다.
    """
    with get_db() as db:
        row, err = _own_schedule(db, sched_id)
        if err:
            return jsonify({'error': err[0]}), err[1]

        at = (request.form.get('scheduled_at') or '').strip()
        parsed = None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
            try:
                parsed = datetime.strptime(at, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return jsonify({'error': '예약 시각 형식을 확인해주세요.'}), 400
        if parsed.year > 9999:
            return jsonify({'error': '예약 연도는 9999년까지만 됩니다.'}), 400
        if parsed <= datetime.now():
            return jsonify({'error': '지난 시각으로는 예약할 수 없습니다.'}), 400

        to = request.form.get('to', '')
        if not [a for a in to.split(',') if a.strip()]:
            return jsonify({'error': '받는 사람을 입력하세요.'}), 400

        try:
            old = json.loads(row.attachments_json or '[]')
        except Exception:
            old = []
        try:
            keep = set(json.loads(request.form.get('keep_attachments', '[]')))
        except Exception:
            keep = set(range(len(old)))

        kept = [a for i, a in enumerate(old) if i in keep]
        for i, a in enumerate(old):
            if i not in keep and a.get('path'):
                storage_adapter.delete_object(a['path'])

        pending = []
        for f in request.files.getlist('attachments'):
            if f.filename:
                pending.append((f.filename, f.read(), f.mimetype))
        try:
            added = _store_scheduled_attachments(sched_id, pending) if pending else []
        except RuntimeError as e:
            return jsonify({'error': str(e)}), 500

        row.to_addresses = to
        row.cc_addresses = request.form.get('cc', '')
        row.bcc_addresses = request.form.get('bcc', '')
        row.subject = request.form.get('subject', '')
        row.body = request.form.get('body', '')
        row.scheduled_at = parsed
        row.attachments_json = json.dumps(kept + added, ensure_ascii=False)
        db.commit()

        return jsonify({
            'success': True,
            'scheduled_at': parsed.strftime('%Y-%m-%d %H:%M'),
            'attachment_count': len(kept) + len(added),
        })


@mail_bp.route('/mail/api/schedule/<int:sched_id>', methods=['DELETE'])
@login_required
def api_schedule_cancel(sched_id):
    with get_db() as db:
        row, err = _own_schedule(db, sched_id)
        if err:
            # 이미 없는 건 성공으로 본다 (두 번 눌러도 오류가 안 뜨게)
            return (jsonify({'success': True}) if err[1] == 404
                    else (jsonify({'error': err[0]}), err[1]))
        # 예약을 지우면 Storage 에 올려둔 첨부도 같이 치운다
        _delete_scheduled_attachments(row.attachments_json)
        db.delete(row)
        db.commit()
        return jsonify({'success': True})


# ---------------------------------------------------------------------------
# 메일 고정 (핀) API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/pin', methods=['POST'])
@login_required
def api_pin_toggle():
    data = request.get_json()
    account_id = data['account_id']
    mail_uid = data['uid']
    folder = data.get('folder', 'INBOX')
    user_id = session['user_id']
    with get_db() as db:
        existing = db.query(MailPin).filter_by(
            account_id=account_id, user_id=user_id, mail_uid=mail_uid, folder=folder
        ).first()
        if existing:
            db.delete(existing)
            db.commit()
            return jsonify({'pinned': False})
        else:
            db.add(MailPin(account_id=account_id, user_id=user_id, mail_uid=mail_uid, folder=folder))
            db.commit()
            return jsonify({'pinned': True})


@mail_bp.route('/mail/api/pins')
@login_required
def api_pins_list():
    account_id = request.args.get('account', type=int)
    folder = request.args.get('folder', 'INBOX')
    with get_db() as db:
        pins = db.query(MailPin.mail_uid).filter_by(
            account_id=account_id, user_id=session['user_id'], folder=folder
        ).all()
        return jsonify([p[0] for p in pins])


# ---------------------------------------------------------------------------
# 중요 표시 (별표) API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/star', methods=['POST'])
@login_required
def api_star_toggle():
    data = request.get_json()
    account_id = data['account_id']
    uid = data['uid']
    folder = data.get('folder', 'INBOX')
    starred = data.get('starred', True)
    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        try:
            with client:
                if starred:
                    client.set_flags([uid], '\\Flagged', action='add', folder=folder)
                else:
                    client.set_flags([uid], '\\Flagged', action='remove', folder=folder)
            return jsonify({'success': True, 'starred': starred})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# 메일 템플릿 API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/templates')
@login_required
def api_templates_list():
    with get_db() as db:
        from sqlalchemy import or_
        rows = db.query(MailTemplate).filter(
            or_(MailTemplate.user_id == session['user_id'], MailTemplate.is_shared == True)
        ).order_by(MailTemplate.name).all()
        return jsonify([{
            'id': t.id, 'name': t.name, 'subject': t.subject, 'body': t.body,
            'to_addresses': t.to_addresses, 'cc_addresses': t.cc_addresses,
            'is_shared': t.is_shared, 'is_mine': t.user_id == session['user_id'],
        } for t in rows])


@mail_bp.route('/mail/api/templates', methods=['POST'])
@login_required
def api_template_save():
    data = request.get_json()
    with get_db() as db:
        tid = data.get('id')
        if tid:
            t = db.query(MailTemplate).filter_by(id=tid).first()
            if t and t.user_id != session['user_id'] and session.get('role') != 'admin':
                return jsonify({'error': '권한 없음'}), 403
        else:
            t = MailTemplate(user_id=session['user_id'])
            db.add(t)
        t.name = data.get('name', '')
        t.subject = data.get('subject', '')
        t.body = data.get('body', '')
        t.to_addresses = data.get('to_addresses', '')
        t.cc_addresses = data.get('cc_addresses', '')
        t.is_shared = data.get('is_shared', False)
        db.commit()
        return jsonify({'success': True, 'id': t.id})


@mail_bp.route('/mail/api/templates/<int:tid>', methods=['DELETE'])
@login_required
def api_template_delete(tid):
    with get_db() as db:
        t = db.query(MailTemplate).filter_by(id=tid).first()
        if t and (t.user_id == session['user_id'] or session.get('role') == 'admin'):
            db.delete(t)
            db.commit()
        return jsonify({'success': True})


# ---------------------------------------------------------------------------
# 공유 편지함 읽음 표시 API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/shared-read', methods=['POST'])
@login_required
def api_shared_read_mark():
    data = request.get_json()
    with get_db() as db:
        from sqlalchemy.dialects.postgresql import insert
        stmt = insert(MailSharedRead).values(
            account_id=data['account_id'], user_id=session['user_id'],
            mail_uid=data['uid'], folder=data.get('folder', 'INBOX'),
        ).on_conflict_do_nothing()
        db.execute(stmt)
        db.commit()
        return jsonify({'success': True})


@mail_bp.route('/mail/api/shared-read')
@login_required
def api_shared_read_list():
    """공유 메일의 읽은 사용자 목록."""
    account_id = request.args.get('account', type=int)
    uid = request.args.get('uid', type=int)
    folder = request.args.get('folder', 'INBOX')
    with get_db() as db:
        rows = db.execute(
            db.bind.execute if hasattr(db, 'bind') else db.execute.__func__,
        ) if False else None
        from sqlalchemy import text as _text
        rows = db.execute(_text("""
            SELECT u.full_name, u.position, sr.read_at
            FROM light_sync.mail_shared_read sr
            JOIN light_sync.users u ON sr.user_id = u.id
            WHERE sr.account_id = :aid AND sr.mail_uid = :uid AND sr.folder = :folder
            ORDER BY sr.read_at
        """), {'aid': account_id, 'uid': uid, 'folder': folder}).fetchall()
        return jsonify([{
            'name': r[0], 'position': r[1],
            'read_at': r[2].strftime('%m/%d %H:%M') if r[2] else '',
        } for r in rows])


# ---------------------------------------------------------------------------
# 고급 검색 API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/search-advanced')
@login_required
def api_search_advanced():
    """상세검색 — 보낸사람·받는사람·제목·본문·기간·첨부·읽음을 겹쳐서 찾는다.

    기본 검색(`/mail/api/search`)이 한 낱말을 여러 자리에서 훑는 것과 달리,
    여기서는 **조건을 모두 만족하는** 메일만 남긴다(IMAP SEARCH 는 AND 다).

    돌려주는 모양은 기본 검색과 같다 — 목록이 그대로 그릴 수 있어야 하니
    uid 만 주지 않고 메시지까지 채워서 준다.
    """
    account_id = request.args.get('account', type=int)
    folder = request.args.get('folder', 'INBOX')
    limit = 200

    def _arg(name):
        return (request.args.get(name) or '').strip()

    def _flag(name):
        return _arg(name).lower() in ('1', 'true', 'on', 'y')

    criteria = []
    used = []       # 무엇으로 찾았는지 — 화면이 조건 딱지를 띄우는 데 쓴다

    for key, imap_key, label in (
        ('from', 'FROM', '보낸사람'),
        ('to', 'TO', '받는사람'),
        ('subject', 'SUBJECT', '제목'),
        ('body', 'BODY', '본문'),
    ):
        value = _arg(key)
        if value:
            criteria += [imap_key, value]
            used.append(f'{label}: {value}')

    # 기간. BEFORE 는 그 날을 포함하지 않으므로 끝나는 날까지 담으려면 하루 뒤로 민다.
    for key, imap_key, label, shift in (
        ('date_from', 'SINCE', '시작', 0),
        ('date_to', 'BEFORE', '끝', 1),
    ):
        value = _arg(key)
        if not value:
            continue
        try:
            day = (datetime.strptime(value, '%Y-%m-%d') + timedelta(days=shift)).date()
        except ValueError:
            return jsonify({'error': f'날짜를 읽지 못했습니다: {value}'}), 400
        criteria += [imap_key, day]
        used.append(f'{label}: {value}')

    if _flag('has_attachment'):
        # IMAP 에 "첨부 있음" 조건은 없다. 목록이 첨부 아이콘을 띄울 때 보는 것과
        # 같은 잣대(최상위 Content-Type)를 쓴다 — 그래야 결과와 아이콘이 어긋나지 않는다.
        criteria += ['HEADER', 'Content-Type', 'multipart/mixed']
        used.append('첨부 있음')
    if _flag('unread'):
        criteria.append('UNSEEN')
        used.append('안읽음')
    if _flag('flagged'):
        criteria.append('FLAGGED')
        used.append('중요')

    if not criteria:
        return jsonify({'error': '검색 조건을 하나 이상 넣어주세요.'}), 400

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400

        # 받은편지함과 내게쓴메일함은 같은 INBOX 를 보낸사람으로 가른다.
        # 목록이 그렇게 나뉘어 있으니 검색도 같은 칸 안에서만 찾아야 한다.
        self_mode = _arg('self')
        if self_mode in ('exclude', 'only') and account and account.email:
            if self_mode == 'only':
                criteria += ['FROM', account.email]
            else:
                criteria += ['NOT', 'FROM', account.email]

        try:
            with client:
                uids, total = client.search_advanced(folder, criteria, limit=limit)
                result = client.fetch_by_uids(folder, uids) if uids else {
                    'messages': [], 'total': 0, 'page': 1, 'pages': 1,
                }
            # fetch_by_uids 는 가져온 개수를 total 로 넣는다 — 자르기 전 건수로 되돌린다
            result['total'] = total
            result['shown'] = len(result.get('messages') or [])
            result['truncated'] = total > len(uids)
            result['criteria'] = used
            return jsonify(result)
        except Exception as e:
            current_app.logger.warning('상세검색 실패 folder=%s criteria=%s: %s',
                                       folder, criteria, e)
            return jsonify({'error': f'검색하지 못했습니다: {e}'}), 500


# ---------------------------------------------------------------------------
# 메일 일괄 이동 API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/move-bulk', methods=['POST'])
@login_required
def api_move_bulk():
    data = request.get_json()
    account_id = data['account_id']
    uids = data.get('uids', [])
    src_folder = data.get('src_folder', 'INBOX')
    dest_folder = data.get('dest_folder', '')
    if not uids or not dest_folder:
        return jsonify({'error': '대상 폴더와 메일을 선택하세요.'}), 400
    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        try:
            with client:
                client.move_messages(uids, dest_folder, src_folder=src_folder)
            return jsonify({'success': True, 'moved': len(uids)})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# 원문 보기
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/messages/<int:uid>/raw')
@login_required
def api_message_raw(uid):
    """메일 원문(헤더 포함) 그대로.

    받는 쪽이 왜 스팸으로 봤는지, 보낸 서버가 어디였는지는 **헤더에만** 있다.
    ?download=1 이면 .eml 파일로 내려준다 — 다른 메일 프로그램에서 그대로 열린다.
    읽음 상태는 건드리지 않는다.
    """
    folder = request.args.get('folder', 'INBOX')
    account_id = request.args.get('account', type=int)
    download = request.args.get('download') == '1'

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err or not client:
            return jsonify({'error': err or '메일 계정 미설정'}), 400
        try:
            with client:
                raw = client.fetch_raw(uid, folder)
        except Exception as e:
            logger.warning("원문 조회 실패 (uid=%s): %s", uid, e)
            return jsonify({'error': f'원문을 읽지 못했습니다: {e}'}), 500

    if raw is None:
        return jsonify({'error': '메일을 찾을 수 없습니다.'}), 404

    headers = {}
    if download:
        filename = f'mail_{uid}.eml'
        headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{urlquote(filename)}"
    # 원문은 어떤 문자셋이 섞여 있을지 모른다 — 그대로 바이트로 내보내고
    # 화면이 utf-8 로 최선껏 읽는다(못 읽는 글자는 대체 문자로 둔다)
    return Response(raw, mimetype='message/rfc822' if download else 'text/plain; charset=utf-8',
                    headers=headers)


# ---------------------------------------------------------------------------
# 메일 인쇄 API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/print/<int:uid>')
@login_required
def mail_print(uid):
    folder = request.args.get('folder', 'INBOX')
    account_id = request.args.get('account', type=int)
    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return f"<h3>오류: {err}</h3>", 400
        try:
            with client:
                msg = client.fetch_message(uid, folder)
            return render_template('mail_print.html', msg=msg, account=account)
        except Exception as e:
            return f"<h3>오류: {e}</h3>", 500


# ---------------------------------------------------------------------------
# 주소록 API
# ---------------------------------------------------------------------------
#
# 주소록은 세 칸으로 갈라져 있다. 화면(mail_app)도 같은 이름으로 나눈다.
#
#   internal  사내 직원   users 테이블에서 만들어 준다. 저장하는 것이 아니라
#                        사람이 들어오고 나가면 저절로 따라온다 — 고칠 수 없다.
#   shared    회사 공용   user_id IS NULL AND is_shared. 누구나 보고 고친다.
#   personal  내 주소록   user_id = 나. 남에게 보이지 않는다.
#
# 남의 개인 주소록은 어떤 경로로도 읽히거나 고쳐지지 않는다 — 조회·저장·삭제·
# 내보내기가 모두 user_id 로 먼저 자른다.
# ---------------------------------------------------------------------------

_CONTACT_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


def _mail_domain():
    return os.environ.get('MAILCOW_DOMAIN', 'mgnt.kr')


def _contact_json(c, kind):
    """주소록 한 줄. editable 은 화면이 수정·삭제 버튼을 그릴지 정하는 잣대다."""
    return {
        'id': c.id,
        'name': c.name or '',
        'email': c.email or '',
        'company': c.company or '',
        'phone': getattr(c, 'phone', '') or '',
        'memo': c.memo or '',
        'type': kind,
        'editable': True,
    }


def _internal_contacts(db, q=''):
    """사내 직원 — 저장된 주소록이 아니라 계정 목록에서 만들어 낸다."""
    domain = _mail_domain()
    user_q = db.query(User).filter(User.is_active == True)
    if q:
        user_q = user_q.filter(User.full_name.ilike(f'%{q}%') | User.username.ilike(f'%{q}%'))
    out = []
    for u in user_q.order_by(User.full_name).all():
        out.append({
            'id': None,
            'name': u.full_name,
            'email': f'{u.username}@{domain}',
            'company': '(주)매그나텍',
            'phone': '',
            'memo': ' '.join(x for x in [u.user_group, u.position] if x),
            'type': 'internal',
            'editable': False,        # 사람이 바뀌면 따라오는 자리 — 여기서 고치지 않는다
        })
    return out


def _book_filter(query, book, user_id):
    """조회 범위를 한 곳에서만 자른다 — 남의 개인 주소록이 새어 나가지 않게."""
    if book == 'shared':
        return query.filter(MailContact.user_id.is_(None), MailContact.is_shared == True)
    return query.filter(MailContact.user_id == user_id)


def _find_contact(db, email, book, user_id):
    """같은 칸에 같은 주소가 이미 있는지. 중복은 새 줄을 만들지 않고 여기서 만난다."""
    q = db.query(MailContact).filter(func.lower(MailContact.email) == (email or '').strip().lower())
    return _book_filter(q, book, user_id).first()


def _load_contact(db, contact_id, user_id):
    """수정·삭제 대상 찾기. 내 것이거나 회사 공용인 것만 잡힌다."""
    c = db.query(MailContact).filter(MailContact.id == contact_id).first()
    if not c:
        return None, None
    if c.user_id == user_id:
        return c, 'personal'
    if c.user_id is None and c.is_shared:
        return c, 'shared'
    return None, None                 # 남의 개인 주소록


@mail_bp.route('/mail/api/contacts', methods=['GET'])
@login_required
def api_contacts_list():
    """주소록 목록. book = personal | shared | internal | all, 검색·페이징."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    q = (request.args.get('q', '') or '').strip()
    # type= 은 옛 화면(static/js/mail.js)이 쓰던 이름이라 둘 다 받는다
    book = (request.args.get('book') or request.args.get('type') or 'all').strip().lower()
    if book not in ('personal', 'shared', 'internal', 'all'):
        book = 'all'

    with get_db() as db:
        uid = session['user_id']
        ql = q.lower()

        def matches(item):
            if not ql:
                return True
            return (ql in item['name'].lower() or ql in item['email'].lower()
                    or ql in item['company'].lower() or ql in item['memo'].lower())

        internal = [c for c in _internal_contacts(db, q) if matches(c)]

        def rows(kind):
            qq = _book_filter(db.query(MailContact), kind, uid)
            if q:
                like = f'%{q}%'
                qq = qq.filter(MailContact.name.ilike(like) | MailContact.email.ilike(like)
                               | MailContact.company.ilike(like) | MailContact.memo.ilike(like))
            return [_contact_json(c, kind) for c in qq.order_by(MailContact.name).all()]

        shared = rows('shared')
        personal = rows('personal')

        # 탭 숫자는 지금 검색어 안에서 센다 — 탭을 옮겼을 때 보이는 건수와 어긋나면 안 된다
        counts = {
            'internal': len(internal), 'shared': len(shared),
            'personal': len(personal), 'all': len(internal) + len(shared) + len(personal),
        }
        all_items = {'internal': internal, 'shared': shared, 'personal': personal,
                     'all': personal + shared + internal}[book]

        total = len(all_items)
        per_page = max(1, min(per_page, 500))
        start = max(0, (page - 1) * per_page)
        return jsonify({
            'items': all_items[start:start + per_page],
            'total': total,
            'counts': counts,
            'book': book,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page,
        })


@mail_bp.route('/mail/api/contacts', methods=['POST'])
@login_required
def api_contacts_save():
    """연락처 추가·수정.

    book 으로 어느 주소록에 넣을지 고른다(personal | shared).
    같은 칸에 같은 주소가 이미 있으면 새로 만들지 않고 그 줄을 고친다 —
    "저장했는데 두 줄이 됐다" 가 제일 흔한 주소록 불만이다.
    """
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    book = 'shared' if (data.get('book') == 'shared' or data.get('is_shared')) else 'personal'

    if not email:
        return jsonify({'error': '메일주소를 입력하세요.'}), 400
    if not _CONTACT_EMAIL_RE.match(email):
        return jsonify({'error': f'메일주소 형식이 아닙니다: {email}'}), 400
    if not name:
        name = email.split('@')[0]          # 이름은 비워 둬도 목록에서 읽히게 채운다

    with get_db() as db:
        uid = session['user_id']
        contact_id = data.get('id')
        moved_book = None

        if contact_id:
            c, cur_book = _load_contact(db, contact_id, uid)
            if not c:
                return jsonify({'error': '연락처를 찾을 수 없습니다.'}), 404
            if cur_book != book:
                # 개인 ↔ 공용 옮기기. 옮겨 간 칸에 같은 주소가 있으면 거기 합친다
                dup = _find_contact(db, email, book, uid)
                if dup and dup.id != c.id:
                    db.delete(c)
                    c = dup
                moved_book = book
        else:
            c = _find_contact(db, email, book, uid)
            if not c:
                c = MailContact()
                db.add(c)

        c.user_id = None if book == 'shared' else uid
        c.is_shared = (book == 'shared')
        c.name = name[:100]
        c.email = email[:255]
        c.company = (data.get('company') or '').strip()[:200]
        c.phone = (data.get('phone') or '').strip()[:60]
        c.memo = (data.get('memo') or '').strip()
        db.commit()

        if book == 'shared':
            # 공용 주소록은 남이 쓰던 것도 바뀐다 — 누가 고쳤는지 로그에 남긴다
            logger.info("공용 주소록 저장: user=%s %s <%s>", uid, c.name, c.email)

        return jsonify({'success': True, 'id': c.id, 'book': book, 'moved': moved_book})


@mail_bp.route('/mail/api/contacts/<int:contact_id>', methods=['DELETE'])
@login_required
def api_contacts_delete(contact_id):
    """연락처 삭제. 내 주소록과 회사 공용만 — 남의 개인 주소록은 잡히지 않는다."""
    with get_db() as db:
        uid = session['user_id']
        c, book = _load_contact(db, contact_id, uid)
        if not c:
            return jsonify({'error': '연락처를 찾을 수 없습니다.'}), 404
        if book == 'shared':
            logger.info("공용 주소록 삭제: user=%s %s <%s>", uid, c.name, c.email)
        db.delete(c)
        db.commit()
        return jsonify({'success': True, 'book': book})


@mail_bp.route('/mail/api/contacts/import', methods=['POST'])
@login_required
def api_contacts_import():
    """쓰던 주소록 파일(.vcf/.csv) 그대로 가져오기.

    다음·네이버·구글·아웃룩이 내주는 파일을 그대로 받는다.
    dry_run=1 이면 저장하지 않고 무엇이 들어올지만 돌려준다 — 남의 주소록
    수백 건이 말없이 쏟아지는 것보다 먼저 보여주고 확인받는 편이 낫다.

    이미 있는 주소는 새 줄을 만들지 않는다:
      - 이름이 메일 앞부분 그대로면(보낼 때 자동수집된 흔적) 제대로 된 이름으로 바꾼다
      - 회사·전화·메모는 **비어 있을 때만** 채운다 (사람이 적어 둔 것을 덮지 않는다)
    """
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': '주소록 파일을 선택하세요.'}), 400

    raw = f.read()
    if len(raw) > 5 * 1024 * 1024:
        return jsonify({'error': '파일이 너무 큽니다 (5MB 까지).'}), 400

    book = 'shared' if request.form.get('book') == 'shared' else 'personal'
    dry_run = request.form.get('dry_run') in ('1', 'true', 'True')

    try:
        parsed, stats = parse_contacts_file(raw, f.filename)
    except Exception as e:
        logger.warning("주소록 파일 파싱 실패 (%s): %s", f.filename, e)
        return jsonify({'error': '주소록 파일을 읽지 못했습니다. vCard(.vcf) 또는 CSV 파일인지 확인해 주세요.'}), 400

    if not parsed:
        return jsonify({'error': '파일에서 메일주소를 찾지 못했습니다.', 'stats': stats}), 400

    with get_db() as db:
        uid = session['user_id']
        existing = {}
        for c in _book_filter(db.query(MailContact), book, uid).all():
            existing[(c.email or '').lower()] = c

        added, updated, skipped, preview = 0, 0, 0, []
        for item in parsed:
            cur = existing.get(item['email'].lower())
            if cur is None:
                added += 1
                state = 'add'
                if not dry_run:
                    c = MailContact(
                        user_id=None if book == 'shared' else uid,
                        is_shared=(book == 'shared'),
                        name=item['name'][:100], email=item['email'][:255],
                        company=item['company'][:200], phone=item['phone'][:60],
                        memo=item['memo'],
                    )
                    db.add(c)
                    existing[item['email'].lower()] = c
            else:
                changes = {}
                local = (cur.email or '').split('@')[0]
                if item['name'] and cur.name in ('', local) and cur.name != item['name']:
                    changes['name'] = item['name'][:100]
                for key, limit in (('company', 200), ('phone', 60), ('memo', None)):
                    if item[key] and not (getattr(cur, key, '') or '').strip():
                        changes[key] = item[key][:limit] if limit else item[key]
                if changes:
                    updated += 1
                    state = 'update'
                    if not dry_run:
                        for k, v in changes.items():
                            setattr(cur, k, v)
                else:
                    skipped += 1
                    state = 'skip'

            if len(preview) < 20:
                preview.append({**item, 'state': state})

        if not dry_run:
            db.commit()
            logger.info("주소록 가져오기: user=%s book=%s 추가=%s 갱신=%s 건너뜀=%s (%s)",
                        uid, book, added, updated, skipped, f.filename)

        return jsonify({
            'success': True, 'dry_run': dry_run, 'book': book, 'filename': f.filename,
            'stats': stats, 'added': added, 'updated': updated, 'skipped': skipped,
            'preview': preview,
        })


@mail_bp.route('/mail/api/contacts/export')
@login_required
def api_contacts_export():
    """주소록 내보내기 — vCard(.vcf) 또는 CSV. book 으로 어느 칸을 내보낼지 고른다."""
    book = (request.args.get('book') or 'personal').strip().lower()
    fmt = (request.args.get('format') or 'vcf').strip().lower()
    if book not in ('personal', 'shared', 'internal', 'all'):
        book = 'personal'

    with get_db() as db:
        uid = session['user_id']
        items = []
        if book in ('personal', 'all'):
            items += [_contact_json(c, 'personal') for c in
                      _book_filter(db.query(MailContact), 'personal', uid).order_by(MailContact.name).all()]
        if book in ('shared', 'all'):
            items += [_contact_json(c, 'shared') for c in
                      _book_filter(db.query(MailContact), 'shared', uid).order_by(MailContact.name).all()]
        if book in ('internal', 'all'):
            items += _internal_contacts(db)

    label = {'personal': '내주소록', 'shared': '회사공용주소록',
             'internal': '사내직원', 'all': '전체주소록'}[book]
    stamp = datetime.now().strftime('%Y%m%d')

    if fmt == 'csv':
        import csv as _csv
        from io import StringIO
        buf = StringIO()
        w = _csv.writer(buf)
        w.writerow(['이름', '이메일', '회사', '전화', '메모'])
        for c in items:
            w.writerow([c['name'], c['email'], c['company'], c['phone'], c['memo']])
        # 엑셀이 한글을 깨지 않게 BOM 을 붙인다
        body = '\ufeff' + buf.getvalue()
        mimetype, ext = 'text/csv; charset=utf-8', 'csv'
    else:
        body = build_vcf(items)
        mimetype, ext = 'text/vcard; charset=utf-8', 'vcf'

    filename = f'{label}_{stamp}.{ext}'
    return Response(body, mimetype=mimetype, headers={
        'Content-Disposition': f"attachment; filename*=UTF-8''{urlquote(filename)}",
    })


# ---------------------------------------------------------------------------
# 수신확인 트래킹
# ---------------------------------------------------------------------------
# 1x1 투명 GIF
_PIXEL_GIF = (
    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
    b'\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00'
    b'\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02'
    b'\x44\x01\x00\x3b'
)


@mail_bp.route('/mail/t/<tracking_id>.gif')
def tracking_pixel(tracking_id):
    """수신확인 트래킹 픽셀. 로그인 불필요 (수신자가 외부인)."""
    with get_db() as db:
        receipt = db.query(MailReadReceipt).filter_by(tracking_id=tracking_id).first()
        if receipt:
            if not receipt.read_at:
                receipt.read_at = datetime.now()
            receipt.read_count = (receipt.read_count or 0) + 1
            receipt.read_ip = request.remote_addr
            receipt.read_ua = request.headers.get('User-Agent', '')[:500]
            db.commit()

    return Response(
        _PIXEL_GIF,
        mimetype='image/gif',
        headers={
            'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
            'Pragma': 'no-cache',
            'Expires': '0',
        }
    )


@mail_bp.route('/mail/api/receipts')
@login_required
def api_receipts():
    """수신확인 목록 조회."""
    with get_db() as db:
        receipts = db.query(MailReadReceipt).filter_by(
            sender_user_id=session['user_id']
        ).order_by(MailReadReceipt.sent_at.desc()).limit(100).all()

        return jsonify([{
            'id': r.id,
            'tracking_id': r.tracking_id,
            'to_email': r.to_email,
            'subject': r.subject,
            'sent_at': r.sent_at.isoformat() if r.sent_at else None,
            'read_at': r.read_at.isoformat() if r.read_at else None,
            'read_count': r.read_count or 0,
            'is_read': r.read_at is not None,
        } for r in receipts])


# ---------------------------------------------------------------------------
# 대용량 파일 첨부 (Supabase Storage, 30일 후 삭제)
# ---------------------------------------------------------------------------
LARGE_FILE_THRESHOLD = 25 * 1024 * 1024  # 25MB
LARGE_FILE_EXPIRE_DAYS = 30


# 대용량 첨부 — 임시 보관 위치. 발송이 확정되면 mail-attachments/ 로 옮긴다.
_TEMP_ATTACH_PREFIX = 'mail-temp'
LARGE_FILE_THRESHOLD = 25 * 1024 * 1024   # 이보다 크면 링크 방식


@mail_bp.route('/mail/api/upload-config')
@login_required
def api_upload_config():
    """작성 화면이 대용량 업로드를 어디로 보낼지 알려준다.

    Cloudflare 를 거치면 업로드 용량이 막히므로(요청이 서버에 도달조차 못 한다)
    사내망에서는 내부 주소로 바로 올린다. 기존 ERP 작성 화면도 같은 방식이다.
    """
    return jsonify({
        'internal_url': os.environ.get('MAIL_UPLOAD_INTERNAL_URL', 'http://192.168.0.110:8501'),
        'threshold': LARGE_FILE_THRESHOLD,
        'expire_days': LARGE_FILE_EXPIRE_DAYS,
        # Cloudflare 를 지나는 요청 하나의 크기. 넉넉히 작게 잡는다.
        'chunk_size': 8 * 1024 * 1024,
    })


# 조각 업로드 임시 폴더. /tmp 를 쓰지 않는 이유: systemd PrivateTmp 가 켜져 있으면
# 서비스마다 /tmp 가 따로 보여 조각을 서로 못 찾는다.
_CHUNK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.upload_tmp')
_UPLOAD_ID_RE = re.compile(r'^[0-9a-f]{8,64}$')


def _chunk_dir(upload_id):
    """조각 보관 폴더. upload_id 는 16진수만 허용 — 경로를 벗어나지 못하게."""
    if not _UPLOAD_ID_RE.match(upload_id or ''):
        return None
    return os.path.join(_CHUNK_DIR, upload_id)


def _upload_auth_ok():
    remote = request.remote_addr or ''
    if remote.startswith('192.168.') or remote.startswith('10.') or remote == '127.0.0.1':
        return True
    return 'user_id' in session or _try_token_auth()


@mail_bp.route('/mail/api/upload-sign', methods=['POST'])
@login_required
def api_upload_sign():
    """대용량 첨부를 브라우저가 Storage 로 바로 올리도록 서명 URL 을 내준다.

    조각 업로드는 브라우저 → Cloudflare → 우리 서버 → 디스크 병합 → Storage 로
    같은 데이터를 두 번 실어 나른다. 서명 URL 을 쓰면 브라우저가 Storage 에
    바로 꽂아 우리 서버를 아예 거치지 않는다.

    서명은 서버만 할 수 있다 (service key 를 브라우저에 줄 수 없다).
    토큰은 1분짜리라 발급받자마자 올리기 시작해야 한다.
    """
    data = request.get_json(silent=True) or {}
    filename = data.get('filename') or 'attachment'

    cfg = storage_adapter.get_storage_config()
    internal_url = os.environ.get('SUPABASE_INTERNAL_URL', '').rstrip('/')
    public_url = _storage_base()
    if not cfg['enabled'] or not internal_url or not public_url:
        return jsonify({'error': '파일 저장소가 설정되지 않았습니다.'}), 500

    file_id = uuid.uuid4().hex[:16]
    ext = os.path.splitext(filename)[1] or ''
    temp_path = f'{_TEMP_ATTACH_PREFIX}/{file_id}{ext}'
    obj = urlquote(temp_path, safe='/')

    import requests as req
    try:
        r = req.post(
            f"{internal_url}/storage/v1/object/upload/sign/{cfg['bucket']}/{obj}",
            headers={
                'apikey': cfg['key'],
                'Authorization': f"Bearer {cfg['key']}",
                'Content-Type': 'application/json',
            },
            json={},
            timeout=20,
        )
    except Exception as e:
        logger.error('서명 URL 발급 실패: %s', e)
        return jsonify({'error': '업로드 준비에 실패했습니다.'}), 500

    if r.status_code != 200:
        logger.error('서명 URL 발급 실패: %s %s', r.status_code, r.text[:200])
        return jsonify({'error': '업로드 준비에 실패했습니다.'}), 500

    token = (r.json() or {}).get('token')
    if not token:
        return jsonify({'error': '업로드 토큰을 받지 못했습니다.'}), 500

    return jsonify({
        'success': True,
        'file_id': file_id,
        'temp_path': temp_path,
        # 사내면 서버 직결 주소, 밖이면 평소 주소
        'upload_url': f"{public_url}/storage/v1/object/upload/sign/{cfg['bucket']}/{obj}?token={token}",
        'lan': _is_lan_client(),
    })


# 사내에서 접속했는지 판별 — 사내면 업로드를 서버로 바로 보낸다.
#   사내 사용자도 지금은 VPS(서울)를 거쳐 되돌아오느라 tailnet 147Mbps 에 묶인다.
#   같은 건물 서버에 올리는 파일이 서울을 왕복하는 셈이다.
#   실측: VPS 경유 15.9MB/s vs 사내 직결 84.8MB/s
_LAN_PREFIXES = ('192.168.', '10.', '127.0.0.1')


def _client_ip():
    """실제 사용자 IP. VPS(nginx)가 X-Forwarded-For 로 넘겨주고
    ProxyFix(x_for=2) 가 remote_addr 에 반영한다."""
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return request.remote_addr or ''


def _is_lan_client():
    ip = _client_ip()
    if ip.startswith(_LAN_PREFIXES):
        return True
    # 172.16.0.0 ~ 172.31.255.255
    if ip.startswith('172.'):
        try:
            return 16 <= int(ip.split('.')[1]) <= 31
        except (IndexError, ValueError):
            return False
    return False


def _storage_base():
    """이 사용자가 써야 할 Storage 주소.

    사내면 서버에 바로 꽂는 주소(MAIL_STORAGE_LAN_URL), 밖이면 평소 주소.
    사내 주소는 공개 DNS 가 사설 IP 를 가리키게 해둔 것이라
    밖에서는 접속이 안 된다 — 그래서 사내 사용자에게만 내준다.
    """
    lan = os.environ.get('MAIL_STORAGE_LAN_URL', '').rstrip('/')
    if lan and _is_lan_client():
        return lan
    return os.environ.get('SUPABASE_URL', '').rstrip('/')


@mail_bp.route('/mail/api/upload-token', methods=['POST'])
@login_required
def api_upload_token():
    """100MB 넘는 첨부를 브라우저가 Storage 로 바로 올리게 해주는 토큰.

    단일 PUT 은 Cloudflare 가 100MB 에서 막는다. TUS(재개 업로드)는 6MB 씩
    나눠 보내므로 그 한도를 넘지 않으면서도 목적지는 Storage 직접이라
    우리 서버를 한 번도 거치지 않는다.

    service 키는 절대 브라우저에 주지 않는다. 대신 30분짜리 토큰을 만들어
    준다 — 이 토큰으로 할 수 있는 일은 storage.objects 정책상
    'company-files/mail-temp/' 아래 쓰기뿐이다.
    """
    import jwt as _jwt

    secret = os.environ.get('SUPABASE_JWT_SECRET') or _read_supabase_jwt_secret()
    if not secret:
        return jsonify({'error': '업로드 토큰을 만들 수 없습니다.'}), 500

    data = request.get_json(silent=True) or {}
    filename = data.get('filename') or 'attachment'
    file_id = uuid.uuid4().hex[:16]
    ext = os.path.splitext(filename)[1] or ''
    temp_path = f'{_TEMP_ATTACH_PREFIX}/{file_id}{ext}'

    now = int(time.time())
    token = _jwt.encode(
        {
            'role': 'authenticated',
            'sub': str(session.get('user_id') or ''),
            'aud': 'authenticated',
            'iat': now,
            'exp': now + 30 * 60,
        },
        secret, algorithm='HS256',
    )

    cfg = storage_adapter.get_storage_config()
    base = _storage_base()
    return jsonify({
        'success': True,
        'file_id': file_id,
        'temp_path': temp_path,
        'bucket': cfg['bucket'],
        'endpoint': f'{base}/storage/v1/upload/resumable',
        'token': token,
        'lan': _is_lan_client(),
    })


def _read_supabase_jwt_secret():
    """Supabase 설치 폴더에서 JWT 비밀키를 읽는다 (.env 에 없을 때)."""
    for path in ('/supabase/config/docker/.env',):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('JWT_SECRET='):
                        return line.split('=', 1)[1].strip()
        except Exception:
            continue
    return None


@mail_bp.route('/mail/api/upload-chunk', methods=['POST', 'OPTIONS'])
def api_upload_chunk():
    """대용량 첨부 조각 받기.

    Cloudflare 가 큰 요청을 막아 서버까지 오지 못하므로(로그에 흔적조차 없다)
    브라우저에서 파일을 잘라 보낸다. 조각 하나는 작아서 그대로 통과한다.
    """
    if request.method == 'OPTIONS':
        return '', 200
    if not _upload_auth_ok():
        return jsonify({'error': '인증이 필요합니다.'}), 401

    upload_id = request.form.get('upload_id', '')
    d = _chunk_dir(upload_id)
    if not d:
        return jsonify({'error': '잘못된 업로드 번호입니다.'}), 400
    try:
        index = int(request.form.get('index', '-1'))
    except ValueError:
        index = -1
    if index < 0:
        return jsonify({'error': '조각 번호가 없습니다.'}), 400

    chunk = request.files.get('chunk')
    if not chunk:
        return jsonify({'error': '조각이 없습니다.'}), 400

    os.makedirs(d, exist_ok=True)
    chunk.save(os.path.join(d, f'{index:06d}'))
    return jsonify({'success': True, 'index': index})


@mail_bp.route('/mail/api/upload-finish', methods=['POST', 'OPTIONS'])
def api_upload_finish():
    """조각을 이어 붙여 Storage 임시 위치로 올린다."""
    if request.method == 'OPTIONS':
        return '', 200
    if not _upload_auth_ok():
        return jsonify({'error': '인증이 필요합니다.'}), 401

    data = request.get_json(silent=True) or request.form
    upload_id = data.get('upload_id', '')
    filename = data.get('filename') or 'attachment'
    try:
        total = int(data.get('total', '0'))
    except ValueError:
        total = 0

    d = _chunk_dir(upload_id)
    if not d or not os.path.isdir(d):
        return jsonify({'error': '올라온 조각이 없습니다.'}), 400

    parts = sorted(os.listdir(d))
    if total and len(parts) != total:
        _rm_chunks(d)
        return jsonify({'error': f'조각이 모자랍니다 ({len(parts)}/{total}). 다시 올려주세요.'}), 400

    merged = os.path.join(d, 'merged')
    size = 0
    try:
        with open(merged, 'wb') as out:
            for name in parts:
                path = os.path.join(d, name)
                with open(path, 'rb') as f:
                    while True:
                        buf = f.read(1024 * 1024)
                        if not buf:
                            break
                        out.write(buf)
                        size += len(buf)
    except Exception as e:
        _rm_chunks(d)
        logger.exception('조각 병합 실패: %s', e)
        return jsonify({'error': f'파일 합치기 실패: {e}'}), 500

    file_id = uuid.uuid4().hex[:16]
    ext = os.path.splitext(filename)[1] or ''
    temp_path = f'{_TEMP_ATTACH_PREFIX}/{file_id}{ext}'

    internal_url = os.environ.get('SUPABASE_INTERNAL_URL', '').rstrip('/')
    cfg = storage_adapter.get_storage_config()
    if not internal_url or not cfg['enabled']:
        _rm_chunks(d)
        return jsonify({'error': '파일 저장소가 설정되지 않았습니다.'}), 500

    import requests as req
    upload_url = f"{internal_url}/storage/v1/object/{cfg['bucket']}/{urlquote(temp_path, safe='/')}"
    try:
        with open(merged, 'rb') as f:
            resp = req.post(
                upload_url,
                headers={
                    'apikey': cfg['key'],
                    'Authorization': f"Bearer {cfg['key']}",
                    'Content-Type': 'application/octet-stream',
                    'x-upsert': 'true',
                },
                data=f,
                timeout=1800,
            )
    except Exception as e:
        _rm_chunks(d)
        logger.exception('조각 업로드 전송 오류: %s', e)
        return jsonify({'error': f'업로드 오류: {e}'}), 500
    finally:
        pass

    if resp.status_code not in (200, 201):
        _rm_chunks(d)
        logger.error('조각 업로드 실패: %s — %s %s', filename, resp.status_code, resp.text[:300])
        return jsonify({'error': f'업로드 실패: {resp.text[:200]}'}), 500

    _rm_chunks(d)
    logger.info('조각 업로드 완료: %s (%s bytes, %d조각) → %s', filename, size, len(parts), temp_path)
    return jsonify({
        'success': True,
        'file_id': file_id,
        'filename': filename,
        'size': size,
        'temp_path': temp_path,
    })


@mail_bp.route('/mail/api/upload-chunk/<upload_id>', methods=['DELETE', 'OPTIONS'])
def api_upload_chunk_cancel(upload_id):
    """올리다 만 조각 정리."""
    if request.method == 'OPTIONS':
        return '', 200
    if not _upload_auth_ok():
        return jsonify({'error': '인증이 필요합니다.'}), 401
    d = _chunk_dir(upload_id)
    if d:
        _rm_chunks(d)
    return jsonify({'success': True})


def _rm_chunks(d):
    import shutil
    try:
        shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


@mail_bp.route('/mail/api/upload-temp', methods=['POST', 'OPTIONS'])
def api_upload_temp():
    """대용량 첨부 1단계 — 파일을 붙이는 즉시 임시 위치에 올린다.

    아직 MailLargeFile 레코드는 만들지 않는다. 발송이 확정돼야 링크가 생긴다.
    작성을 그만두면 /mail/api/upload-temp/<file_id> DELETE 로 지운다.
    """
    if request.method == 'OPTIONS':
        return '', 200

    remote = request.remote_addr or ''
    is_internal = remote.startswith('192.168.') or remote.startswith('10.') or remote == '127.0.0.1'
    if not is_internal and 'user_id' not in session and not _try_token_auth():
        return jsonify({'error': '인증이 필요합니다.'}), 401

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': '파일이 없습니다.'}), 400

    file_id = uuid.uuid4().hex[:16]
    ext = os.path.splitext(f.filename)[1] or ''
    temp_path = f'{_TEMP_ATTACH_PREFIX}/{file_id}{ext}'

    internal_url = os.environ.get('SUPABASE_INTERNAL_URL', '').rstrip('/')
    cfg = storage_adapter.get_storage_config()
    if not internal_url or not cfg['enabled']:
        return jsonify({'error': '파일 저장소가 설정되지 않았습니다.'}), 500

    import requests as req
    upload_url = f"{internal_url}/storage/v1/object/{cfg['bucket']}/{urlquote(temp_path, safe='/')}"
    try:
        resp = req.post(
            upload_url,
            headers={
                'apikey': cfg['key'],
                'Authorization': f"Bearer {cfg['key']}",
                'Content-Type': f.content_type or 'application/octet-stream',
                'x-upsert': 'true',
            },
            data=f.stream,
            timeout=1800,
        )
    except Exception as e:
        logger.exception('임시 업로드 오류: %s', e)
        return jsonify({'error': f'업로드 오류: {e}'}), 500

    if resp.status_code not in (200, 201):
        logger.error('임시 업로드 실패: %s — %s %s', f.filename, resp.status_code, resp.text[:300])
        return jsonify({'error': f'업로드 실패: {resp.text[:200]}'}), 500

    size = f.content_length or 0
    if not size:
        try:
            size = f.stream.tell()
        except Exception:
            size = 0

    logger.info('임시 업로드 완료: %s (%s bytes) → %s', f.filename, size, temp_path)
    return jsonify({
        'success': True,
        'file_id': file_id,
        'filename': f.filename,
        'size': size,
        'temp_path': temp_path,
        'content_type': f.content_type or '',
    })


@mail_bp.route('/mail/api/upload-temp/<file_id>', methods=['DELETE', 'OPTIONS'])
def api_upload_temp_delete(file_id):
    """작성 취소·첨부 제거 시 임시 파일 삭제."""
    if request.method == 'OPTIONS':
        return '', 200
    remote = request.remote_addr or ''
    is_internal = remote.startswith('192.168.') or remote.startswith('10.') or remote == '127.0.0.1'
    if not is_internal and 'user_id' not in session and not _try_token_auth():
        return jsonify({'error': '인증이 필요합니다.'}), 401

    ext = request.args.get('ext', '')
    if not re.fullmatch(r'\.[A-Za-z0-9]{0,10}', ext or '.'):
        ext = ''
    storage_adapter.delete_object(f'{_TEMP_ATTACH_PREFIX}/{file_id}{ext}')
    return jsonify({'success': True})


def _promote_large_files(db, items):
    """대용량 첨부 2단계 — 임시 위치에서 첨부 보관함으로 옮기고 링크를 만든다.

    items: [{file_id, filename, size, temp_path}]
    반환:  [{filename, size, download_url, expires_at}]
    """
    out = []
    dl_domain = os.environ.get('FLASK_DOMAIN', 'work.mgnt.kr')
    expires_at = datetime.now() + timedelta(days=LARGE_FILE_EXPIRE_DAYS)

    for it in items:
        file_id = str(it.get('file_id') or '')
        temp_path = str(it.get('temp_path') or '')
        filename = it.get('filename') or 'attachment'
        if not file_id or not temp_path:
            continue

        ext = os.path.splitext(temp_path)[1] or ''
        final_path = f'mail-attachments/{file_id}{ext}'
        ok, msg = storage_adapter.move_object(temp_path, final_path)
        if not ok:
            logger.error('대용량 첨부 이동 실패: %s → %s (%s)', temp_path, final_path, msg)
            raise RuntimeError(f'첨부 처리 실패: {filename}')

        db.add(MailLargeFile(
            file_id=file_id,
            sender_user_id=session.get('user_id'),
            original_filename=filename,
            file_size=int(it.get('size') or 0),
            storage_path=final_path,
            expires_at=expires_at,
        ))
        out.append({
            'filename': filename,
            'size': int(it.get('size') or 0),
            'download_url': f'https://{dl_domain}/mail/dl/{file_id}',
            'expires_at': expires_at.strftime('%Y-%m-%d'),
        })
    return out


def _large_files_html(links):
    """본문 끝에 붙일 대용량 첨부 안내표 — 기존 ERP 작성 화면과 같은 모양."""
    if not links:
        return ''
    rows = ''.join(
        f'<tr style="border-bottom:1px solid #f1f5f9;">'
        f'<td style="padding:6px 12px;">📄 <a href="{l["download_url"]}" style="color:#2563eb;">{l["filename"]}</a></td>'
        f'<td style="padding:6px 12px;color:#94a3b8;">{l["size"]:,}바이트</td>'
        f'<td style="padding:6px 12px;color:#dc2626;font-size:12px;">⏰ {l["expires_at"]}까지 다운로드 가능</td>'
        f'</tr>'
        for l in links
    )
    return ('<br><hr style="border-color:#e2e8f0;">'
            '<p style="color:#64748b;font-size:13px;">📎 <strong>대용량 첨부파일</strong></p>'
            f'<table style="border-collapse:collapse;font-size:13px;">{rows}</table>')


@mail_bp.route('/mail/api/upload-large', methods=['POST', 'OPTIONS'])
def api_upload_large():
    """대용량 파일 업로드 — 사내망 직접 → 서버 → Supabase 내부 경로."""
    if request.method == 'OPTIONS':
        return '', 200

    # 사내 IP 또는 로그인된 사용자만 허용
    remote = request.remote_addr or ''
    is_internal = remote.startswith('192.168.') or remote.startswith('10.') or remote == '127.0.0.1'
    if not is_internal and 'user_id' not in session:
        return jsonify({'error': '인증이 필요합니다.'}), 401

    try:
        f = request.files.get('file')
        if not f or not f.filename:
            return jsonify({'error': '파일이 없습니다.'}), 400

        file_id = uuid.uuid4().hex[:16]
        ext = os.path.splitext(f.filename)[1] or ''
        storage_path = f'mail-attachments/{file_id}{ext}'
        expires_at = datetime.now() + timedelta(days=LARGE_FILE_EXPIRE_DAYS)

        import requests as req
        internal_url = os.environ.get('SUPABASE_INTERNAL_URL', '').rstrip('/')
        cfg = storage_adapter.get_storage_config()
        if not internal_url or not cfg['enabled']:
            return jsonify({'error': '파일 저장소가 설정되지 않았습니다.'}), 500

        obj_path = urlquote(storage_path, safe='/')
        upload_url = f"{internal_url}/storage/v1/object/{cfg['bucket']}/{obj_path}"

        logger.info("대용량 업로드 시작: %s → %s", f.filename, storage_path)

        resp = req.post(
            upload_url,
            headers={
                'apikey': cfg['key'],
                'Authorization': f"Bearer {cfg['key']}",
                'Content-Type': f.content_type or 'application/octet-stream',
                'x-upsert': 'true',
            },
            data=f.stream,
            timeout=1800,
        )
        if resp.status_code not in (200, 201):
            logger.error("Storage 업로드 실패: %s — %s %s", f.filename, resp.status_code, resp.text[:300])
            return jsonify({'error': f'파일 업로드 실패: {resp.text[:200]}'}), 500

        file_size = f.content_length or 0
        if not file_size:
            try:
                file_size = f.stream.tell()
            except Exception:
                file_size = 0

        logger.info("대용량 업로드 성공: %s (%d bytes)", f.filename, file_size)

        with get_db() as db:
            record = MailLargeFile(
                file_id=file_id,
                sender_user_id=session.get('user_id') or None,
                original_filename=f.filename,
                file_size=file_size,
                storage_path=storage_path,
                expires_at=expires_at,
            )
            db.add(record)
            db.commit()

        dl_domain = os.environ.get('FLASK_DOMAIN', 'work.mgnt.kr')
        download_url = f'https://{dl_domain}/mail/dl/{file_id}'

        return jsonify({
            'success': True,
            'file_id': file_id,
            'filename': f.filename,
            'size': file_size,
            'download_url': download_url,
            'expires_at': expires_at.strftime('%Y-%m-%d'),
            'expires_days': LARGE_FILE_EXPIRE_DAYS,
        })
    except Exception as e:
        logger.exception("대용량 업로드 오류: %s", e)
        return jsonify({'error': f'업로드 오류: {e}'}), 500

    dl_domain = os.environ.get('FLASK_DOMAIN', 'work.mgnt.kr')
    download_url = f'https://{dl_domain}/mail/dl/{file_id}'

    return jsonify({
        'success': True,
        'file_id': file_id,
        'filename': f.filename,
        'size': file_size,
        'download_url': download_url,
        'expires_at': expires_at.strftime('%Y-%m-%d'),
        'expires_days': LARGE_FILE_EXPIRE_DAYS,
    })


@mail_bp.route('/mail/dl/<file_id>')
def download_large_file(file_id):
    """대용량 파일 다운로드 (로그인 불필요 — 외부 수신자도 다운로드 가능)."""
    with get_db() as db:
        record = db.query(MailLargeFile).filter_by(file_id=file_id).first()
        if not record:
            return render_template('error.html', error_message='파일을 찾을 수 없습니다.'), 404
        from datetime import timezone
        now_aware = datetime.now(timezone.utc)
        expires = record.expires_at.replace(tzinfo=timezone.utc) if record.expires_at.tzinfo is None else record.expires_at
        if record.is_deleted or now_aware > expires:
            return render_template('error.html',
                                   error_message='파일 다운로드 기간이 만료되었습니다. (보관기간 30일)'), 410

        record.download_count = (record.download_count or 0) + 1
        db.commit()

        filename = record.original_filename
        storage_path = record.storage_path

    # 로컬 디스크 캐시 (한 번 받으면 다시 Supabase 안 거침)
    CACHE_DIR = '/tmp/mail_dl_cache'
    os.makedirs(CACHE_DIR, exist_ok=True)
    from urllib.parse import quote as urlquote

    ext = os.path.splitext(storage_path)[1] or ''
    cache_file = os.path.join(CACHE_DIR, file_id + ext)

    encoded_name = urlquote(filename, safe='')

    # 캐시 파일이 이미 있으면 send_file로 커널 직접 전송 (sendfile syscall)
    if os.path.exists(cache_file):
        from flask import send_file as flask_send_file
        return flask_send_file(
            cache_file,
            mimetype='application/octet-stream',
            as_attachment=True,
            download_name=filename,
        )

    # 캐시 없음 → Supabase에서 받으면서 동시에 브라우저 스트리밍 + 캐시 저장
    import requests as req
    internal_url = os.environ.get('SUPABASE_INTERNAL_URL', '').rstrip('/')
    cfg = storage_adapter.get_storage_config()
    obj_path = urlquote(storage_path, safe='/')
    src_url = f"{internal_url}/storage/v1/object/{cfg['bucket']}/{obj_path}"

    upstream = req.get(src_url, headers={
        'apikey': cfg['key'],
        'Authorization': f"Bearer {cfg['key']}",
    }, stream=True, timeout=30)

    if upstream.status_code != 200:
        return render_template('error.html', error_message='파일을 가져올 수 없습니다.'), 500

    content_length = upstream.headers.get('Content-Length')
    cache_tmp = cache_file + '.tmp'

    def stream_and_cache():
        try:
            with open(cache_tmp, 'wb') as cf:
                for chunk in upstream.iter_content(chunk_size=1024 * 1024):
                    cf.write(chunk)
                    yield chunk
            # 완료 후 tmp → 정식 캐시 파일로 이동
            os.replace(cache_tmp, cache_file)
        except Exception:
            # 스트리밍 중 에러 시 임시파일 정리
            try:
                os.unlink(cache_tmp)
            except OSError:
                pass

    resp_headers = {
        'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_name}",
    }
    if content_length:
        resp_headers['Content-Length'] = content_length

    return Response(
        stream_and_cache(),
        mimetype='application/octet-stream',
        headers=resp_headers,
    )


@mail_bp.route('/mail/api/cleanup-expired', methods=['POST'])
@admin_required
def api_cleanup_expired():
    """만료된 대용량 파일 정리 (30일 지난 것 삭제)."""
    now = datetime.now()
    deleted = 0
    with get_db() as db:
        expired = db.query(MailLargeFile).filter(
            MailLargeFile.expires_at < now,
            MailLargeFile.is_deleted == False,
        ).all()
        for record in expired:
            storage_adapter.delete_object(record.storage_path)
            record.is_deleted = True
            deleted += 1
        db.commit()
    return jsonify({'success': True, 'deleted': deleted})


# ─── 사용자별 서명 API ────────────────────────────────────────────────
@mail_bp.route('/mail/api/user-signature', methods=['GET'])
@login_required
def api_get_user_signature():
    """로그인 사용자 정보 기반 서명 HTML 반환."""
    with get_db() as db:
        user = db.query(User).filter_by(id=session['user_id']).first()
        if not user:
            return jsonify({})
        return jsonify({'html': user.to_signature_html()})


# ---------------------------------------------------------------------------
# 외부메일 (개인별 Naver/Daum/Gmail 등 IMAP 연동)
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/external')
@login_required
@menu_required('mail_personal')
def mail_external():
    """외부메일함 — 사용자별 외부 IMAP 계정."""
    g.active_menu_key = 'mail_external'
    with get_db() as db:
        external = _get_external_accounts(db, session['user_id'])
        has_account = len(external) > 0

        current_account_id = request.args.get('account', type=int)
        if not current_account_id and external:
            current_account_id = external[0].id

        return render_template('mail_inbox.html',
                               personal_accounts=[],
                               shared_accounts=[],
                               external_accounts=external,
                               has_account=has_account,
                               current_account_id=current_account_id,
                               current_folder='INBOX',
                               mail_mode='external')


@mail_bp.route('/mail/external/settings')
@login_required
def mail_external_settings():
    """외부메일 설정 — 별도 페이지."""
    g.active_menu_key = 'mail_external'
    with get_db() as db:
        external = _get_external_accounts(db, session['user_id'])
        return render_template('mail_external_settings.html',
                               external_accounts=external)


@mail_bp.route('/mail/api/external', methods=['GET'])
@login_required
def api_external_list():
    """외부메일 계정 목록 JSON."""
    with get_db() as db:
        accounts = _get_external_accounts(db, session['user_id'])
        return jsonify([{
            'id': a.id,
            'email': a.email,
            'display_name': a.display_name,
            'imap_host': a.imap_host,
            'imap_port': a.imap_port,
            'smtp_host': a.smtp_host,
            'smtp_port': a.smtp_port,
            'username': a.username,
            'use_ssl': a.use_ssl,
            'is_active': a.is_active,
        } for a in accounts])


@mail_bp.route('/mail/api/external', methods=['POST'])
@login_required
def api_external_save():
    """외부메일 계정 추가/수정."""
    data = request.get_json()
    user_id = session['user_id']

    email_addr = (data.get('email') or '').strip()
    imap_host = (data.get('imap_host') or '').strip()
    username = (data.get('username') or email_addr).strip()
    password = (data.get('password') or '').strip()

    if not email_addr or not imap_host:
        return jsonify({'error': '이메일과 IMAP 서버는 필수입니다.'}), 400

    with get_db() as db:
        account_id = data.get('id')
        if account_id:
            account = db.query(MailAccount).filter_by(
                id=account_id, user_id=user_id, account_type='external'
            ).first()
            if not account:
                return jsonify({'error': '계정을 찾을 수 없습니다.'}), 404
        else:
            if not password:
                return jsonify({'error': '비밀번호를 입력하세요.'}), 400
            account = MailAccount(
                user_id=user_id,
                account_type='external',
                is_shared=False,
            )
            db.add(account)

        account.email = email_addr
        account.display_name = (data.get('display_name') or '').strip()
        account.imap_host = imap_host
        account.imap_port = int(data.get('imap_port') or 993)
        account.smtp_host = (data.get('smtp_host') or '').strip()
        account.smtp_port = int(data.get('smtp_port') or 587)
        account.username = username
        account.use_ssl = data.get('use_ssl', True)

        if password:
            account.password_encrypted = encrypt_password(password)

        db.commit()
        return jsonify({'success': True, 'id': account.id})


@mail_bp.route('/mail/api/external/<int:account_id>', methods=['DELETE'])
@login_required
def api_external_delete(account_id):
    """외부메일 계정 삭제."""
    with get_db() as db:
        account = db.query(MailAccount).filter_by(
            id=account_id, user_id=session['user_id'], account_type='external'
        ).first()
        if not account:
            return jsonify({'error': '계정을 찾을 수 없습니다.'}), 404
        account.is_active = False
        db.commit()
        return jsonify({'success': True})


@mail_bp.route('/mail/api/external/<int:account_id>/test', methods=['POST'])
@login_required
def api_external_test(account_id):
    """외부메일 IMAP 연결 테스트."""
    with get_db() as db:
        account = db.query(MailAccount).filter_by(
            id=account_id, user_id=session['user_id'], account_type='external'
        ).first()
        if not account:
            return jsonify({'success': False, 'error': '계정을 찾을 수 없습니다.'}), 404

        try:
            password = decrypt_password(account.password_encrypted)
        except Exception:
            return jsonify({'success': False, 'error': '비밀번호 복호화 실패'}), 400

        try:
            from imapclient import IMAPClient
            import ssl as _ssl
            ssl_context = _ssl.create_default_context()
            # 외부 서버는 정상 인증서 사용
            client = IMAPClient(account.imap_host, port=account.imap_port,
                                ssl=account.use_ssl, ssl_context=ssl_context, timeout=15)
            client.login(account.username, password)
            folders = client.list_folders()
            client.logout()
            return jsonify({'success': True, 'message': f'연결 성공! {len(folders)}개 폴더 확인'})
        except Exception as e:
            return jsonify({'success': False, 'error': f'연결 실패: {e}'}), 400


@mail_bp.route('/mail/api/external/test-new', methods=['POST'])
@login_required
def api_external_test_new():
    """신규 외부메일 등록 전 연결 테스트 (폼 데이터)."""
    data = request.get_json()
    imap_host = (data.get('imap_host') or '').strip()
    imap_port = int(data.get('imap_port') or 993)
    use_ssl = data.get('use_ssl', True)
    username = (data.get('username') or data.get('email', '')).strip()
    password = (data.get('password') or '').strip()

    if not imap_host or not username or not password:
        return jsonify({'success': False, 'error': 'IMAP 서버, 아이디, 비밀번호를 입력하세요.'}), 400

    try:
        from imapclient import IMAPClient
        import ssl as _ssl
        ssl_context = _ssl.create_default_context()
        client = IMAPClient(imap_host, port=imap_port,
                            ssl=use_ssl, ssl_context=ssl_context, timeout=15)
        client.login(username, password)
        folders = client.list_folders()
        client.logout()
        return jsonify({'success': True, 'message': f'연결 성공! {len(folders)}개 폴더 확인'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'연결 실패: {e}'}), 400
