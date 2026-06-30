"""
웹메일 라우트.
- 메일함 목록, 메일 읽기, 작성, 설정
- IMAP/SMTP 연동은 mail_client.py에 위임
"""

import os
import json
import logging
import uuid
from datetime import datetime, timedelta
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, jsonify, Response, current_app, g,
)
from modules.auth_decorators import login_required, menu_required, admin_required
from modules.db_context import get_db
from modules.models.mail_entities import (
    MailAccount, MailSharedAccess, MailContact, MailReadReceipt, MailLargeFile,
    MailLabel, MailRule, MailAutoReply, MailAutoForward, MailScheduled,
    MailPin, MailTemplate, MailSharedRead,
)
from modules import storage_adapter
from modules.models.auth_entities import User
from modules.services.mail_client import MailClient, decrypt_password, encrypt_password

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
                               mail_mode=mode)


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
        # 원본 첨부파일 IMAP에서 fetch
        if forward_source_uid and forward_account_id and forward_parts_json:
            try:
                import json
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


@mail_bp.route('/mail/api/accounts')
@login_required
def api_accounts():
    """현재 사용자가 접근 가능한 계정 목록 (IMAP 미사용, 가볍게 호출 가능)."""
    with get_db() as db:
        personal, shared = _get_user_accounts(db, session['user_id'])
        accounts = []
        for acc in list(personal) + list(shared):
            accounts.append({
                'id': acc.id,
                'email': acc.email,
                'display_name': acc.display_name or '',
                'is_shared': bool(acc.is_shared),
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

        # 공유 + 개인 주소록
        from sqlalchemy import or_
        contact_q = db.query(MailContact).filter(
            or_(MailContact.is_shared == True,
                MailContact.user_id == session['user_id'])
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
                'type': 'shared' if c.is_shared else 'external',
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
            if not rule:
                return jsonify({'error': '규칙을 찾을 수 없습니다.'}), 404
        else:
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
        db.query(MailRule).filter_by(id=rule_id).delete()
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
                            from_name = (f.name or b'').decode(errors='replace')

                        subject = ''
                        if env.subject:
                            subject = env.subject.decode('utf-8', errors='replace') if isinstance(env.subject, bytes) else (env.subject or '')

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
            fwd = db.query(MailAutoForward).filter_by(id=fwd_id).first()
        else:
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
        db.query(MailAutoForward).filter_by(id=fwd_id).delete()
        db.commit()
        return jsonify({'success': True})


# ---------------------------------------------------------------------------
# 예약발송 API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/schedule', methods=['POST'])
@login_required
def api_schedule_send():
    data = request.get_json()
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
        db.add(sched)
        db.commit()
        return jsonify({'success': True, 'id': sched.id})


@mail_bp.route('/mail/api/schedule')
@login_required
def api_schedule_list():
    account_id = request.args.get('account', type=int)
    with get_db() as db:
        rows = db.query(MailScheduled).filter_by(
            account_id=account_id, status='pending'
        ).order_by(MailScheduled.scheduled_at).all()
        return jsonify([{
            'id': r.id, 'to': r.to_addresses, 'subject': r.subject,
            'scheduled_at': r.scheduled_at.strftime('%Y-%m-%d %H:%M'),
        } for r in rows])


@mail_bp.route('/mail/api/schedule/<int:sched_id>', methods=['DELETE'])
@login_required
def api_schedule_cancel(sched_id):
    with get_db() as db:
        db.query(MailScheduled).filter_by(id=sched_id, status='pending').delete()
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
    """고급 검색: 발신자, 수신자, 날짜, 첨부 등."""
    account_id = request.args.get('account', type=int)
    from_addr = request.args.get('from', '')
    to_addr = request.args.get('to', '')
    subject = request.args.get('subject', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    has_attach = request.args.get('has_attachment', '')
    folder = request.args.get('folder', 'INBOX')

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        try:
            with client:
                # IMAP 검색 쿼리 빌드
                criteria = []
                if from_addr:
                    criteria.append(f'FROM "{from_addr}"')
                if to_addr:
                    criteria.append(f'TO "{to_addr}"')
                if subject:
                    criteria.append(f'SUBJECT "{subject}"')
                if date_from:
                    from datetime import datetime as _dt
                    d = _dt.strptime(date_from, '%Y-%m-%d')
                    criteria.append(f'SINCE {d.strftime("%d-%b-%Y")}')
                if date_to:
                    from datetime import datetime as _dt2
                    d = _dt2.strptime(date_to, '%Y-%m-%d')
                    criteria.append(f'BEFORE {d.strftime("%d-%b-%Y")}')

                search_str = ' '.join(criteria) if criteria else 'ALL'
                results = client.search(folder, search_str)
                return jsonify({'success': True, 'uids': results[:200]})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


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
@mail_bp.route('/mail/api/contacts', methods=['GET'])
@login_required
def api_contacts_list():
    """주소록 목록 (사내 직원 + 공유 + 개인). 페이징+검색 지원."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    q = (request.args.get('q', '') or '').strip().lower()

    with get_db() as db:
        import os
        _mail_domain = os.environ.get('MAILCOW_DOMAIN', 'mgnt.kr')
        all_items = []

        # 사내 직원
        users = db.query(User).filter(User.is_active == True).order_by(User.full_name).all()
        for u in users:
            all_items.append({
                'id': None,
                'name': u.full_name,
                'email': f'{u.username}@{_mail_domain}',
                'company': '(주)매그나텍',
                'memo': f'{u.user_group or ""} {u.position or ""}'.strip(),
                'type': 'internal',
            })

        # 공유 연락처
        shared_contacts = db.query(MailContact).filter_by(
            is_shared=True
        ).order_by(MailContact.name).all()
        for c in shared_contacts:
            all_items.append({
                'id': c.id,
                'name': c.name,
                'email': c.email,
                'company': c.company or '',
                'memo': c.memo or '',
                'type': 'shared',
            })

        # 개인 외부 연락처
        contacts = db.query(MailContact).filter_by(
            user_id=session['user_id'], is_shared=False
        ).order_by(MailContact.name).all()
        for c in contacts:
            all_items.append({
                'id': c.id,
                'name': c.name,
                'email': c.email,
                'company': c.company or '',
                'memo': c.memo or '',
                'type': 'external',
            })

        # 검색 필터
        if q:
            all_items = [c for c in all_items
                         if q in c['name'].lower() or q in c['email'].lower()
                         or q in c['company'].lower()]

        total = len(all_items)
        start = (page - 1) * per_page
        items = all_items[start:start + per_page]

        return jsonify({
            'items': items,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page,
        })


@mail_bp.route('/mail/api/contacts', methods=['POST'])
@login_required
def api_contacts_save():
    """외부 연락처 추가/수정."""
    data = request.get_json()
    with get_db() as db:
        contact_id = data.get('id')
        if contact_id:
            c = db.query(MailContact).filter_by(id=contact_id, user_id=session['user_id']).first()
            if not c:
                return jsonify({'error': '연락처를 찾을 수 없습니다.'}), 404
        else:
            c = MailContact(user_id=session['user_id'])
            db.add(c)

        c.name = data['name']
        c.email = data['email']
        c.company = data.get('company', '')
        c.memo = data.get('memo', '')
        db.commit()
        return jsonify({'success': True, 'id': c.id})


@mail_bp.route('/mail/api/contacts/<int:contact_id>', methods=['DELETE'])
@login_required
def api_contacts_delete(contact_id):
    """외부 연락처 삭제."""
    with get_db() as db:
        c = db.query(MailContact).filter_by(id=contact_id, user_id=session['user_id']).first()
        if c:
            db.delete(c)
            db.commit()
        return jsonify({'success': True})


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

        from urllib.parse import quote as urlquote
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
