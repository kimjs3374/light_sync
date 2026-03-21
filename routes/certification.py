import datetime
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from sqlalchemy import and_
from modules.auth_decorators import login_required, admin_required
from modules.db_context import get_db
from modules.utils import safe_int, parse_date
from modules.pagination import make_pagination
from modules.models import (
    Certification, CERT_TYPE_CHOICES, Notification, User,
)

cert_bp = Blueprint("certification", __name__)

UPLOAD_SUBDIR = 'certifications'


def _save_cert_file(file_obj):
    """인증서 파일 저장 → 상대경로 반환"""
    if not file_obj or not file_obj.filename:
        return None
    upload_dir = os.path.join(current_app.static_folder, 'uploads', UPLOAD_SUBDIR)
    os.makedirs(upload_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    safe_name = file_obj.filename.replace(' ', '_')
    fname = f"{ts}_{safe_name}"
    file_obj.save(os.path.join(upload_dir, fname))
    return f"uploads/{UPLOAD_SUBDIR}/{fname}"


# -------------------------------------------------------------------
# 1. 인증서 목록 + 만료 알림 대시보드
# -------------------------------------------------------------------
@cert_bp.route('/certifications')
@login_required
def cert_list():
    page = safe_int(request.args.get('page'), 1)
    per_page = 20
    cert_type_filter = request.args.get('cert_type', '').strip()
    status_filter = request.args.get('status', '').strip()

    with get_db() as db:
        query = db.query(Certification).filter(Certification.is_active.is_(True))

        if cert_type_filter:
            query = query.filter(Certification.cert_type == cert_type_filter)

        query = query.order_by(Certification.expiry_date.asc().nullslast())

        total = query.count()
        pagination = make_pagination(page, per_page, total)
        certs = query.offset((pagination['page'] - 1) * per_page).limit(per_page).all()

        # 만료 통계
        today = datetime.date.today()
        all_active = db.query(Certification).filter(Certification.is_active.is_(True)).all()
        stats = {
            'total': len(all_active),
            'expired': sum(1 for c in all_active if c.expiry_date and c.expiry_date < today),
            'critical': sum(1 for c in all_active if c.expiry_date and 0 <= (c.expiry_date - today).days <= 7),
            'warning': sum(1 for c in all_active if c.expiry_date and 7 < (c.expiry_date - today).days <= 30),
            'ok': sum(1 for c in all_active if c.expiry_date and (c.expiry_date - today).days > 30),
        }

    return render_template(
        'certification_list.html',
        certs=certs,
        stats=stats,
        pagination=pagination,
        cert_types=CERT_TYPE_CHOICES,
        filters={'cert_type': cert_type_filter, 'status': status_filter},
        today=today,
    )


# -------------------------------------------------------------------
# 2. 인증서 등록/수정
# -------------------------------------------------------------------
@cert_bp.route('/certifications/create', methods=['GET', 'POST'])
@login_required
@admin_required
def cert_create():
    with get_db() as db:
        if request.method == 'POST':
            file_path = _save_cert_file(request.files.get('cert_file'))
            cert = Certification(
                cert_type=request.form.get('cert_type', '기타'),
                cert_name=request.form.get('cert_name', '').strip(),
                cert_no=request.form.get('cert_no', '').strip() or None,
                issued_by=request.form.get('issued_by', '').strip() or None,
                issued_date=parse_date(request.form.get('issued_date')),
                expiry_date=parse_date(request.form.get('expiry_date')),
                product_model=request.form.get('product_model', '').strip() or None,
                alert_days=safe_int(request.form.get('alert_days'), 30),
                file_path=file_path,
                note=request.form.get('note', '').strip() or None,
            )
            db.add(cert)
            db.commit()
            flash(f'인증서 "{cert.cert_name}" 등록 완료', 'success')
            return redirect(url_for('certification.cert_list'))

    return render_template('certification_form.html', cert=None, cert_types=CERT_TYPE_CHOICES)


@cert_bp.route('/certifications/<int:cert_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def cert_edit(cert_id):
    with get_db() as db:
        cert = db.query(Certification).get(cert_id)
        if not cert:
            flash('인증서를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('certification.cert_list'))

        if request.method == 'POST':
            cert.cert_type = request.form.get('cert_type', cert.cert_type)
            cert.cert_name = request.form.get('cert_name', '').strip()
            cert.cert_no = request.form.get('cert_no', '').strip() or None
            cert.issued_by = request.form.get('issued_by', '').strip() or None
            cert.issued_date = parse_date(request.form.get('issued_date'))
            cert.expiry_date = parse_date(request.form.get('expiry_date'))
            cert.product_model = request.form.get('product_model', '').strip() or None
            cert.alert_days = safe_int(request.form.get('alert_days'), 30)
            cert.note = request.form.get('note', '').strip() or None

            new_file = request.files.get('cert_file')
            if new_file and new_file.filename:
                cert.file_path = _save_cert_file(new_file)

            db.commit()
            flash('인증서 수정 완료', 'success')
            return redirect(url_for('certification.cert_list'))

    return render_template('certification_form.html', cert=cert, cert_types=CERT_TYPE_CHOICES)


@cert_bp.route('/certifications/<int:cert_id>/delete', methods=['POST'])
@login_required
@admin_required
def cert_delete(cert_id):
    with get_db() as db:
        cert = db.query(Certification).get(cert_id)
        if cert:
            cert.is_active = False
            db.commit()
            flash('인증서 비활성화 완료', 'success')
    return redirect(url_for('certification.cert_list'))


# -------------------------------------------------------------------
# 3. 인증서 만료 알림 체크 (대시보드에서 호출)
# -------------------------------------------------------------------
def check_cert_expiry_alerts(db):
    """만료 임박 인증서 알림 생성 (대시보드 로드 시 호출)
    Returns: list of dicts for dashboard display
    """
    today = datetime.date.today()
    alerts = []
    certs = db.query(Certification).filter(
        Certification.is_active.is_(True),
        Certification.expiry_date.isnot(None),
    ).all()

    for c in certs:
        days = (c.expiry_date - today).days
        if days < 0:
            alerts.append({
                'level': 'danger',
                'message': f'[인증서 만료] {c.cert_name} ({c.cert_no or "-"}) — {abs(days)}일 경과',
                'cert_id': c.id,
            })
        elif days <= c.alert_days:
            level = 'danger' if days <= 7 else 'warning'
            alerts.append({
                'level': level,
                'message': f'[인증서 만료 {days}일 전] {c.cert_name} ({c.cert_no or "-"})',
                'cert_id': c.id,
            })
    return alerts
