"""
홈택스 무인 세금계산서 수집 — 관리자 설정 라우트.

- 공동인증서(.der + .key) 업로드 → NPKI/ 로컬 비밀 디렉토리 저장
- 인증서 비밀번호 → Fernet 암호화 저장 (메일계정과 동일 키)
- 연결 테스트(로그인만), 수동 수집(백그라운드 스레드)
모두 @admin_required.
"""

import os
import threading
import datetime
import logging

from flask import Blueprint, request, jsonify

from modules.auth_decorators import admin_required
from modules.models import SessionLocal, HometaxCredential
from modules.services.mail_client import encrypt_password

logger = logging.getLogger(__name__)

hometax_bp = Blueprint('hometax', __name__)

# 인증서 보관 디렉토리 (.gitignore: NPKI/, *.der, *.key)
CERT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'NPKI'))


def _get_or_create(db):
    cred = db.query(HometaxCredential).order_by(HometaxCredential.id).first()
    if not cred:
        cred = HometaxCredential()
        db.add(cred)
        db.flush()
    return cred


def _status_dict(cred):
    if not cred:
        return {'configured': False}
    return {
        'configured': bool(cred.cert_der_path and cred.cert_key_path and cred.password_encrypted),
        'biz_no': cred.biz_no,
        'cert_subject': cred.cert_subject,
        'cert_expiry': cred.cert_expiry.isoformat() if cred.cert_expiry else None,
        'enabled': bool(cred.enabled),
        'last_sync_at': cred.last_sync_at.strftime('%Y-%m-%d %H:%M') if cred.last_sync_at else None,
        'last_sync_status': cred.last_sync_status,
        'last_sync_message': cred.last_sync_message,
    }


@hometax_bp.route('/admin/hometax/status', methods=['GET'])
@admin_required
def hometax_status():
    db = SessionLocal()
    try:
        cred = db.query(HometaxCredential).order_by(HometaxCredential.id).first()
        return jsonify({'ok': True, **_status_dict(cred)})
    finally:
        db.close()


@hometax_bp.route('/admin/hometax/save', methods=['POST'])
@admin_required
def hometax_save():
    """인증서 파일 + 비번 + 설정 저장. der/key 미첨부 시 기존 파일 유지."""
    db = SessionLocal()
    try:
        cred = _get_or_create(db)

        biz_no = (request.form.get('biz_no') or '').strip()
        password = request.form.get('password') or ''
        enabled = request.form.get('enabled') in ('Y', 'true', 'on', '1')

        der_file = request.files.get('cert_der')
        key_file = request.files.get('cert_key')

        os.makedirs(CERT_DIR, exist_ok=True)
        der_path = cred.cert_der_path or os.path.join(CERT_DIR, 'signCert.der')
        key_path = cred.cert_key_path or os.path.join(CERT_DIR, 'signPri.key')

        if der_file and der_file.filename:
            der_path = os.path.join(CERT_DIR, 'signCert.der')
            der_file.save(der_path)
            os.chmod(der_path, 0o600)
        if key_file and key_file.filename:
            key_path = os.path.join(CERT_DIR, 'signPri.key')
            key_file.save(key_path)
            os.chmod(key_path, 0o600)

        # 비번 입력 시에만 갱신
        if password:
            cred.password_encrypted = encrypt_password(password)

        cred.cert_der_path = der_path
        cred.cert_key_path = key_path
        if biz_no:
            cred.biz_no = biz_no
        cred.enabled = enabled

        # 인증서 주체/만료일 추출 (.der, 비번 불필요)
        try:
            if os.path.exists(der_path):
                from cryptography import x509
                with open(der_path, 'rb') as f:
                    c = x509.load_der_x509_certificate(f.read())
                cred.cert_subject = c.subject.rfc4514_string()[:300]
                # cryptography 42+ : naive not_valid_after 는 deprecated
                cred.cert_expiry = getattr(c, 'not_valid_after_utc', None) and c.not_valid_after_utc.date() \
                    or c.not_valid_after.date()
        except Exception as e:
            logger.warning('인증서 주체 추출 실패: %s', e)

        db.commit()
        return jsonify({'ok': True, **_status_dict(cred)})
    except Exception as e:
        db.rollback()
        logger.exception('홈택스 인증서 저장 실패')
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500
    finally:
        db.close()


@hometax_bp.route('/admin/hometax/test', methods=['POST'])
@admin_required
def hometax_test():
    """로그인만 시도하는 연결 테스트 (수집 안 함)."""
    db = SessionLocal()
    try:
        cred = db.query(HometaxCredential).order_by(HometaxCredential.id).first()
        if not cred:
            return jsonify({'ok': False, 'error': '인증서가 등록되지 않았습니다.'}), 400
        from modules.services.hometax_collector import test_connection
        info = test_connection(cred)
        return jsonify({'ok': True, **info})
    except Exception as e:
        logger.exception('홈택스 연결 테스트 실패')
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500
    finally:
        db.close()


# 수동 수집 중복 실행 방지
_sync_lock = threading.Lock()


def _bg_collect(begin, end):
    from modules.services.hometax_collector import run_collection
    try:
        run_collection(begin, end)
    finally:
        if _sync_lock.locked():
            _sync_lock.release()


@hometax_bp.route('/admin/hometax/sync', methods=['POST'])
@admin_required
def hometax_sync():
    """수동 수집을 백그라운드 스레드로 시작하고 즉시 반환. 진행상태는 status 폴링."""
    data = request.get_json(silent=True) or {}
    begin = end = None
    try:
        if data.get('from'):
            begin = datetime.datetime.strptime(data['from'], '%Y-%m-%d').date()
        if data.get('to'):
            end = datetime.datetime.strptime(data['to'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'ok': False, 'error': '날짜 형식 오류 (YYYY-MM-DD)'}), 400

    if not _sync_lock.acquire(blocking=False):
        return jsonify({'ok': False, 'error': '이미 수집이 진행 중입니다.'}), 409

    t = threading.Thread(target=_bg_collect, args=(begin, end), daemon=True)
    t.start()
    rng = f"{begin or '(최근10일)'} ~ {end or '오늘'}"
    return jsonify({'ok': True, 'message': f'수집을 시작했습니다 ({rng}). 잠시 후 상태를 확인하세요.'})
