"""
웹메일 라우트.
- 메일함 목록, 메일 읽기, 작성, 설정
- IMAP/SMTP 연동은 mail_client.py에 위임
"""

import os
import logging
import uuid
from datetime import datetime, timedelta
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, jsonify, Response, current_app,
)
from modules.auth_decorators import login_required, menu_required, admin_required
from modules.db_context import get_db
from modules.models.mail_entities import (
    MailAccount, MailSharedAccess, MailContact, MailReadReceipt, MailLargeFile,
)
from modules import storage_adapter
from modules.models.auth_entities import User
from modules.services.mail_client import MailClient, decrypt_password, encrypt_password

logger = logging.getLogger(__name__)
mail_bp = Blueprint('mail', __name__)


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
        account = db.query(MailAccount).filter_by(
            user_id=user_id, is_shared=False, is_active=True
        ).first()
        if not account:
            return None, None, None  # 계정 미설정 (설정 페이지로 안내)

    try:
        password = decrypt_password(account.password_encrypted)
    except Exception:
        return None, None, '메일 비밀번호 복호화 실패. 관리자에게 문의하세요.'

    client = MailClient(
        imap_host=account.imap_host,
        imap_port=account.imap_port,
        smtp_host=account.smtp_host,
        smtp_port=account.smtp_port,
        username=account.username,
        password=password,
        use_ssl=account.use_ssl,
    )
    return client, account, None


def _get_user_accounts(db, user_id):
    """사용자가 접근 가능한 모든 메일 계정 목록."""
    # 개인 계정
    personal = db.query(MailAccount).filter_by(
        user_id=user_id, is_shared=False, is_active=True
    ).all()

    # 공용 계정 (shared_access 기반)
    shared_ids = db.query(MailSharedAccess.mail_account_id).filter_by(
        user_id=user_id
    ).all()
    shared_ids = [s[0] for s in shared_ids]

    shared = []
    if shared_ids:
        shared = db.query(MailAccount).filter(
            MailAccount.id.in_(shared_ids),
            MailAccount.is_active == True,
        ).all()

    # admin은 모든 공용계정 접근
    if session.get('role') == 'admin':
        all_shared = db.query(MailAccount).filter_by(
            is_shared=True, is_active=True
        ).all()
        existing_ids = {s.id for s in shared}
        for s in all_shared:
            if s.id not in existing_ids:
                shared.append(s)

    return personal, shared


# ---------------------------------------------------------------------------
# 페이지 라우트
# ---------------------------------------------------------------------------
@mail_bp.route('/mail')
@login_required
@menu_required('webmail')
def mail_inbox():
    """메일함 메인 화면."""
    with get_db() as db:
        personal, shared = _get_user_accounts(db, session['user_id'])
        has_account = len(personal) > 0

        # 현재 선택된 계정
        current_account_id = request.args.get('account', type=int)
        if not current_account_id and personal:
            current_account_id = personal[0].id

        current_folder = request.args.get('folder', 'INBOX')

        return render_template('mail_inbox.html',
                               personal_accounts=personal,
                               shared_accounts=shared,
                               has_account=has_account,
                               current_account_id=current_account_id,
                               current_folder=current_folder)


@mail_bp.route('/mail/read/<int:uid>')
@login_required
@menu_required('webmail')
def mail_read(uid):
    """메일 상세 보기 페이지."""
    folder = request.args.get('folder', 'INBOX')
    account_id = request.args.get('account', type=int)
    with get_db() as db:
        personal, shared = _get_user_accounts(db, session['user_id'])
        if not account_id and personal:
            account_id = personal[0].id
    return render_template('mail_read.html',
                           uid=uid, folder=folder, account_id=account_id)


@mail_bp.route('/mail/compose')
@login_required
@menu_required('webmail')
def mail_compose():
    """메일 작성 화면."""
    reply_uid = request.args.get('reply', type=int)
    reply_all = request.args.get('reply_all', type=int)
    forward_uid = request.args.get('forward', type=int)
    account_id = request.args.get('account', type=int)

    reply_data = None
    with get_db() as db:
        personal, shared = _get_user_accounts(db, session['user_id'])

        # 답장/전달 시 원본 메일 데이터
        source_uid = reply_uid or reply_all or forward_uid
        if source_uid and account_id:
            client, account, err = _get_mail_client(db, account_id)
            if client and not err:
                folder = request.args.get('folder', 'INBOX')
                try:
                    with client:
                        reply_data = client.fetch_message(source_uid, folder)
                except Exception as e:
                    logger.error("원본 메일 조회 실패: %s", e)

        return render_template('mail_compose.html',
                               personal_accounts=personal,
                               shared_accounts=shared,
                               reply_data=reply_data,
                               reply_uid=reply_uid,
                               reply_all=reply_all,
                               forward_uid=forward_uid,
                               current_account_id=account_id)


@mail_bp.route('/mail/settings')
@login_required
@menu_required('webmail')
def mail_settings():
    """메일 설정 화면."""
    with get_db() as db:
        personal, shared = _get_user_accounts(db, session['user_id'])
        return render_template('mail_settings.html',
                               personal_accounts=personal,
                               shared_accounts=shared)


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

    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        if not client:
            return jsonify({'error': '메일 계정이 설정되지 않았습니다.', 'no_account': True}), 404

        try:
            with client:
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

    if not to:
        return jsonify({'error': '받는 사람을 입력하세요.'}), 400

    # 첨부파일
    attachments = []
    files = request.files.getlist('attachments')
    for f in files:
        if f.filename:
            attachments.append((f.filename, f.read()))

    with get_db() as db:
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

            with client:
                result = client.send_message(
                    from_addr=account.email,
                    to=to, cc=cc or None, bcc=bcc or None,
                    subject=subject,
                    html_body=html_body_with_tracking,
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
            internal_emails = {u.email.lower() for u in db.query(User.email).filter(User.email.isnot(None)).all() if u.email}
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

            return jsonify(result)
        except Exception as e:
            logger.error("메일 발송 실패: %s", e)
            return jsonify({'error': f'메일 발송 실패: {e}'}), 500


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
    """폴더 목록."""
    account_id = request.args.get('account', type=int)
    with get_db() as db:
        client, account, err = _get_mail_client(db, account_id)
        if err:
            return jsonify({'error': err}), 400
        if not client:
            return jsonify({'error': '메일 계정 미설정', 'no_account': True}), 404
        try:
            with client:
                folders = client.list_folders()
            return jsonify({'folders': folders})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


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
                # 검색된 UID들의 목록 가져오기
                if uids:
                    result = client.fetch_messages(folder, page=1, per_page=100)
                    # 검색 UID에 해당하는 것만 필터
                    uid_set = set(uids)
                    result['messages'] = [m for m in result['messages'] if m['uid'] in uid_set]
                    result['total'] = len(result['messages'])
                else:
                    result = {'messages': [], 'total': 0, 'page': 1, 'pages': 1}
            return jsonify(result)
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@mail_bp.route('/mail/api/contacts/suggest')
@login_required
def api_contacts_suggest():
    """주소록 자동완성."""
    q = request.args.get('q', '').strip()
    if not q or len(q) < 1:
        return jsonify([])

    results = []
    with get_db() as db:
        # 사내 직원
        users = db.query(User).filter(
            User.is_active == True,
            User.email.isnot(None),
            (User.full_name.ilike(f'%{q}%') | User.email.ilike(f'%{q}%'))
        ).limit(10).all()
        for u in users:
            if u.email:
                results.append({
                    'name': u.full_name,
                    'email': u.email,
                    'type': 'internal',
                })

        # 외부 주소록
        contacts = db.query(MailContact).filter(
            MailContact.user_id == session['user_id'],
            (MailContact.name.ilike(f'%{q}%') | MailContact.email.ilike(f'%{q}%'))
        ).limit(10).all()
        for c in contacts:
            results.append({
                'name': c.name,
                'email': c.email,
                'company': c.company,
                'type': 'external',
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
                return jsonify({'error': '권한이 없습니다.'}), 403
        else:
            account = MailAccount(user_id=user_id)
            db.add(account)

        account.email = data.get('email', account.email)
        account.display_name = data.get('display_name', account.display_name)
        account.imap_host = data.get('imap_host', account.imap_host or '192.168.0.101')
        account.imap_port = data.get('imap_port', account.imap_port or 993)
        account.smtp_host = data.get('smtp_host', account.smtp_host or '192.168.0.101')
        account.smtp_port = data.get('smtp_port', account.smtp_port or 587)
        account.username = data.get('username', account.username)
        account.signature = data.get('signature', account.signature)

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
        account.imap_host = data.get('imap_host', '192.168.0.101')
        account.imap_port = data.get('imap_port', 993)
        account.smtp_host = data.get('smtp_host', '192.168.0.101')
        account.smtp_port = data.get('smtp_port', 587)
        account.username = data['username']
        account.is_shared = True
        account.signature = data.get('signature', '')

        password = data.get('password')
        if password:
            account.password_encrypted = encrypt_password(password)

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


# ---------------------------------------------------------------------------
# 주소록 API
# ---------------------------------------------------------------------------
@mail_bp.route('/mail/api/contacts', methods=['GET'])
@login_required
def api_contacts_list():
    """외부 주소록 목록."""
    with get_db() as db:
        contacts = db.query(MailContact).filter_by(
            user_id=session['user_id']
        ).order_by(MailContact.name).all()
        return jsonify([{
            'id': c.id,
            'name': c.name,
            'email': c.email,
            'company': c.company,
            'memo': c.memo,
        } for c in contacts])


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
