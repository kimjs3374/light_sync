"""시료관리 라우트 — 생산부 시료 스펙 + 시험이력 + QR 추적.

QR 라벨을 시료 실물에 부착하고, 스캔하면 /s/<token> 공개 페이지가 열린다.
공개 페이지는 로그인 없이 열람 가능하므로 내부메모·불합격·A/S분석은 제외한다.
"""

import datetime
import os

from flask import (
    Blueprint, Response, abort, current_app, flash, redirect,
    render_template, request, send_file, session, url_for,
)
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from modules.activity import log_activity
from modules.auth_decorators import menu_required
from modules.db_context import get_db
from modules.pagination import make_pagination
from modules.storage_adapter import download_bytes, upload_bytes
from modules.utils import parse_date, safe_int
from modules.models import (
    Certification, MEASURE_FIELDS, Project, Sample, SampleLog, SampleTest,
    SAMPLE_PURPOSE_CHOICES, SAMPLE_STATUS_CHOICES, TEST_AGENCY_SUGGESTIONS,
    TEST_CATEGORY_CHOICES, TEST_RESULT_CHOICES, TEST_TYPE_CHOICES,
    append_sample_log, generate_sample_no, normalize_model_code,
)

sample_bp = Blueprint('sample', __name__)

MIME_MAP = {
    'pdf': 'application/pdf', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
    'png': 'image/png', 'webp': 'image/webp', 'gif': 'image/gif',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'hwp': 'application/x-hwp',
}

# A4 라벨지 규격 프리셋 — (라벨명, 열, 행, 라벨폭mm, 라벨높이mm, 상여백mm, 좌여백mm)
LABEL_SHEETS = {
    'formtec3108': {'label': '폼텍 3108 (24칸 · 70×33.8mm)', 'cols': 3, 'rows': 8,
                    'w': 70.0, 'h': 33.8, 'top': 12.7, 'left': 0.0},
    'formtec3105': {'label': '폼텍 3105 (14칸 · 99.1×38.1mm)', 'cols': 2, 'rows': 7,
                    'w': 99.1, 'h': 38.1, 'top': 15.1, 'left': 4.6},
    'formtec3110': {'label': '폼텍 3110 (40칸 · 45.7×25.4mm)', 'cols': 4, 'rows': 10,
                    'w': 45.7, 'h': 25.4, 'top': 21.5, 'left': 9.0},
}

# TSC TE210 (203dpi · 4인치) 라벨 규격 프리셋 (mm)
#   pw/ph = 용지(대지) 크기 — 프린터 드라이버 용지 설정값
#   lw/lh = 실제 라벨(인쇄면) 크기 — 대지보다 작으면 좌우 여백이 생긴다
LABEL_ROLLS = {
    '72.5x40': {'label': '72.5 × 40 mm (라벨 70×40)', 'pw': 72.5, 'ph': 40, 'lw': 70, 'lh': 40},
    '60x40':   {'label': '60 × 40 mm',   'pw': 60,  'ph': 40, 'lw': 60,  'lh': 40},
    '50x30':   {'label': '50 × 30 mm',   'pw': 50,  'ph': 30, 'lw': 50,  'lh': 30},
    '40x30':   {'label': '40 × 30 mm',   'pw': 40,  'ph': 30, 'lw': 40,  'lh': 30},
    '100x50':  {'label': '100 × 50 mm',  'pw': 100, 'ph': 50, 'lw': 100, 'lh': 50},
}
DEFAULT_ROLL = '72.5x40'


def _safe_float(value, default):
    try:
        out = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    return out


def _resolve_label_spec(args):
    """라벨 규격 확정 — 프리셋 + 쿼리 파라미터 미세조정.

    Chrome 인쇄에서 잘리거나 빈 페이지가 따라 나오는 원인은 대부분
    용지(대지)와 인쇄면 크기를 같은 값으로 잡아서다. 둘을 분리하고
    좌우/상하 오프셋을 mm 단위로 직접 보정할 수 있게 한다.
    """
    roll = args.get('roll') or DEFAULT_ROLL
    preset = LABEL_ROLLS.get(roll, LABEL_ROLLS[DEFAULT_ROLL])

    pw = round(_safe_float(args.get('pw'), preset['pw']), 2)
    ph = round(_safe_float(args.get('ph'), preset['ph']), 2)
    lw = round(_safe_float(args.get('lw'), preset['lw']), 2)
    lh = round(_safe_float(args.get('lh'), preset['lh']), 2)

    # 용지를 벗어나면 Chrome이 2페이지로 흘려보낸다 → 강제로 가둔다
    pw = min(max(pw, 10), 210)
    ph = min(max(ph, 10), 297)
    lw = min(max(lw, 10), pw)
    lh = min(max(lh, 10), ph)

    # 기본은 대지 중앙 정렬, adj_x/adj_y 로 ±mm 미세보정
    adj_x = round(_safe_float(args.get('adj_x'), 0), 2)
    adj_y = round(_safe_float(args.get('adj_y'), 0), 2)
    off_x = round((pw - lw) / 2 + adj_x, 2)
    off_y = round((ph - lh) / 2 + adj_y, 2)
    off_x = min(max(off_x, 0), max(pw - lw, 0))
    off_y = min(max(off_y, 0), max(ph - lh, 0))

    # QR 은 라벨 높이에 맞추되, 옆 글자 자리가 남도록 가로의 40%까지만.
    # 48%로 잡던 시절엔 70mm 라벨에서도 글자 폭이 33mm밖에 안 남아
    # 모델명·용도가 통째로 잘렸다. 30mm면 짧은 URL QR은 충분히 읽힌다.
    qr = round(min(lh - 3, lw * 0.40, 30), 2)
    qr = max(qr, 8)

    # 라벨 폭에 따라 글자 크기 단계 조정 (mm → pt 대략 환산)
    if lw >= 65:
        fonts = {'no': 10, 'model': 8.5, 'sub': 7, 'brand': 6}
    elif lw >= 55:
        fonts = {'no': 9.5, 'model': 8, 'sub': 6.5, 'brand': 6}
    elif lw >= 45:
        fonts = {'no': 8.5, 'model': 7, 'sub': 6, 'brand': 5.5}
    else:
        fonts = {'no': 7.5, 'model': 6.5, 'sub': 5.5, 'brand': 5}

    return {
        'roll': roll, 'pw': pw, 'ph': ph, 'lw': lw, 'lh': lh,
        'off_x': off_x, 'off_y': off_y, 'adj_x': adj_x, 'adj_y': adj_y,
        'qr': qr, 'fonts': fonts,
    }


# ── 내부 헬퍼 ────────────────────────────────────────────
def _user_name():
    return session.get('full_name') or session.get('username') or '시스템'


def _client_ip():
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[0].strip()[:100]
    return (request.remote_addr or '')[:100]


def _can_write():
    if session.get('role') == 'admin' or session.get('user_group') == '임원진':
        return True
    return 'sample' in session.get('writable_menus', [])


def _save_file(file_obj, subdir, key):
    """Supabase Storage 업로드 → (storage_path, 원본파일명). 파일 없으면 (None, None)."""
    if not file_obj or not file_obj.filename:
        return None, None
    data = file_obj.read()
    if not data:
        return None, None
    safe_name = secure_filename(file_obj.filename) or 'file'
    ext = os.path.splitext(safe_name)[1].lower() or '.pdf'
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    storage_path = f'documents/samples/{subdir}/{key}_{ts}{ext}'
    ok, err = upload_bytes(storage_path, data, file_obj.mimetype or 'application/octet-stream')
    if not ok:
        raise RuntimeError(f'파일 업로드 실패: {err}')
    return storage_path, file_obj.filename


def _serve_storage(path, download_name=None):
    """Supabase Storage 파일 프록시 응답."""
    data = download_bytes(path)
    if not data:
        local_path = os.path.join(current_app.static_folder, path)
        if os.path.exists(local_path):
            return send_file(local_path)
        abort(404)
    ext = os.path.splitext(path)[1].lower().lstrip('.')
    mime = MIME_MAP.get(ext, 'application/octet-stream')
    name = secure_filename(download_name or os.path.basename(path))
    return Response(data, mimetype=mime, headers={
        'Content-Disposition': f'inline; filename="{name}"',
    })


def _collect_spec_json(form):
    """가변 스펙 입력 (spec_key[] / spec_val[]) → dict."""
    keys = form.getlist('spec_key')
    vals = form.getlist('spec_val')
    out = {}
    for k, v in zip(keys, vals):
        k = (k or '').strip()
        v = (v or '').strip()
        if k and v:
            out[k] = v
    return out or None


def _collect_measured_json(form):
    """측정값 입력 → dict. 빈 값은 제외."""
    out = {}
    for key, _label, _unit in MEASURE_FIELDS:
        raw = (form.get(f'measure_{key}') or '').strip()
        if raw:
            out[key] = raw
    extra_k = form.getlist('measure_key')
    extra_v = form.getlist('measure_val')
    for k, v in zip(extra_k, extra_v):
        k = (k or '').strip()
        v = (v or '').strip()
        if k and v:
            out[k] = v
    return out or None


def _apply_sample_form(sample, form):
    """폼 → 시료 필드 반영 (스펙/보관/연결). 시료번호·토큰은 건드리지 않는다."""
    sample.model_name = (form.get('model_name') or '').strip()
    sample.item_cd = (form.get('item_cd') or '').strip() or None
    sample.purpose = form.get('purpose') or '사내시험'
    sample.status = form.get('status') or '보관중'
    sample.mfg_date = parse_date(form.get('mfg_date'))
    sample.made_by = (form.get('made_by') or '').strip() or None
    sample.location = (form.get('location') or '').strip() or None
    sample.project_id = safe_int(form.get('project_id'), 0) or None

    sample.led_chip = (form.get('led_chip') or '').strip() or None
    sample.pcb_spec = (form.get('pcb_spec') or '').strip() or None
    sample.cct = (form.get('cct') or '').strip() or None
    sample.lens_angle = (form.get('lens_angle') or '').strip() or None
    sample.smps_model = (form.get('smps_model') or '').strip() or None
    sample.input_voltage = (form.get('input_voltage') or '').strip() or None
    sample.ip_grade = (form.get('ip_grade') or '').strip() or None
    sample.body_material = (form.get('body_material') or '').strip() or None

    for field in ('watt', 'lumen', 'weight'):
        raw = (form.get(field) or '').strip()
        try:
            setattr(sample, field, float(raw) if raw else None)
        except ValueError:
            setattr(sample, field, None)

    sample.spec_json = _collect_spec_json(form)
    sample.public_note = (form.get('public_note') or '').strip() or None
    sample.internal_note = (form.get('internal_note') or '').strip() or None


# ── 목록 ─────────────────────────────────────────────────
@sample_bp.route('/samples')
@menu_required('sample')
def sample_list():
    page = safe_int(request.args.get('page'), 1)
    per_page = 50
    q = (request.args.get('q') or '').strip()
    purpose = (request.args.get('purpose') or '').strip()
    status = (request.args.get('status') or '').strip()
    expiry = (request.args.get('expiry') or '').strip()

    today = datetime.date.today()

    with get_db() as db:
        query = db.query(Sample).options(joinedload(Sample.tests)).filter(
            Sample.is_active.is_(True)
        )

        if q:
            like = f'%{q}%'
            query = query.filter(or_(
                Sample.sample_no.ilike(like),
                Sample.model_name.ilike(like),
                Sample.location.ilike(like),
                Sample.made_by.ilike(like),
            ))
        if purpose:
            query = query.filter(Sample.purpose == purpose)
        if status:
            query = query.filter(Sample.status == status)

        # 성적서 만료 필터 — sample_tests.valid_until 기준 서브쿼리 사전필터
        if expiry:
            sub = db.query(SampleTest.sample_id).filter(SampleTest.valid_until.isnot(None))
            if expiry == 'expired':
                sub = sub.filter(SampleTest.valid_until < today)
            elif expiry == 'critical':
                sub = sub.filter(SampleTest.valid_until >= today,
                                 SampleTest.valid_until <= today + datetime.timedelta(days=7))
            elif expiry == 'warning':
                sub = sub.filter(SampleTest.valid_until >= today,
                                 SampleTest.valid_until <= today + datetime.timedelta(days=30))
            query = query.filter(Sample.id.in_(sub))

        total = query.count()
        pagination = make_pagination(page, per_page, total)
        samples = (query.order_by(Sample.model_code, Sample.seq.desc())
                   .offset((pagination['page'] - 1) * per_page)
                   .limit(per_page).all())

        base = db.query(Sample).filter(Sample.is_active.is_(True))
        expiring_sub = db.query(SampleTest.sample_id).filter(
            SampleTest.valid_until.isnot(None),
            SampleTest.valid_until >= today,
            SampleTest.valid_until <= today + datetime.timedelta(days=30),
        )
        expired_sub = db.query(SampleTest.sample_id).filter(
            SampleTest.valid_until.isnot(None),
            SampleTest.valid_until < today,
        )
        stats = {
            'total': base.count(),
            'stored': base.filter(Sample.status == '보관중').count(),
            'testing': base.filter(Sample.status == '시험중').count(),
            'out': base.filter(Sample.status == '반출').count(),
            'expiring': base.filter(Sample.id.in_(expiring_sub)).count(),
            'expired': base.filter(Sample.id.in_(expired_sub)).count(),
        }

        return render_template(
            'sample_list.html',
            samples=samples,
            pagination=pagination,
            stats=stats,
            purpose_choices=SAMPLE_PURPOSE_CHOICES,
            status_choices=SAMPLE_STATUS_CHOICES,
            filters={'q': q, 'purpose': purpose, 'status': status, 'expiry': expiry},
            can_write=_can_write(),
        )


# ── 등록 ─────────────────────────────────────────────────
@sample_bp.route('/samples/new', methods=['GET', 'POST'])
@menu_required('sample', write=True)
def sample_create():
    with get_db() as db:
        if request.method == 'POST':
            model_name = (request.form.get('model_name') or '').strip()
            if not model_name:
                flash('모델명은 필수입니다.', 'danger')
                return redirect(url_for('sample.sample_create'))

            sample = Sample()
            _apply_sample_form(sample, request.form)
            sample.created_by = _user_name()

            photo_path, _ = _save_file(request.files.get('photo'), 'photos',
                                       normalize_model_code(model_name))
            sample.photo_path = photo_path

            # 모델별 채번 — 동시 등록 충돌 시 3회까지 재시도
            for attempt in range(3):
                model_code, seq, sample_no = generate_sample_no(db, model_name)
                sample.model_code = model_code
                sample.seq = seq
                sample.sample_no = sample_no
                try:
                    db.add(sample)
                    db.flush()
                    break
                except IntegrityError:
                    db.rollback()
                    db.expunge_all()
                    if attempt == 2:
                        flash('시료번호 채번에 실패했습니다. 다시 시도해 주세요.', 'danger')
                        return redirect(url_for('sample.sample_create'))

            append_sample_log(db, sample.id, '등록',
                              f'{sample.sample_no} ({sample.model_name}) 시료 등록',
                              user_name=_user_name(), ip_address=_client_ip())
            log_activity(db, '시료관리', '등록', f'{sample.sample_no} 시료 등록',
                         ref_type='sample', ref_id=sample.id, ref_label=sample.sample_no,
                         user_name=_user_name())
            db.commit()
            flash(f'시료 "{sample.sample_no}" 등록 완료 — QR 라벨을 출력해 부착하세요.', 'success')
            return redirect(url_for('sample.sample_detail', sample_id=sample.id))

        projects = (db.query(Project)
                    .filter(Project.status.notin_(['취소']))
                    .order_by(Project.id.desc()).limit(300).all())
        return render_template(
            'sample_form.html', sample=None, projects=projects,
            purpose_choices=SAMPLE_PURPOSE_CHOICES,
            status_choices=SAMPLE_STATUS_CHOICES,
        )


# ── 수정 ─────────────────────────────────────────────────
@sample_bp.route('/samples/<int:sample_id>/edit', methods=['GET', 'POST'])
@menu_required('sample', write=True)
def sample_edit(sample_id):
    with get_db() as db:
        sample = db.get(Sample, sample_id)
        if not sample:
            flash('시료를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('sample.sample_list'))

        if request.method == 'POST':
            before_status = sample.status
            _apply_sample_form(sample, request.form)

            new_photo, _ = _save_file(request.files.get('photo'), 'photos', sample.sample_no)
            if new_photo:
                sample.photo_path = new_photo

            changes = ['스펙/정보 수정']
            if before_status != sample.status:
                changes.append(f'상태 {before_status} → {sample.status}')
            append_sample_log(db, sample.id, '수정', ' · '.join(changes),
                              user_name=_user_name(), ip_address=_client_ip())
            db.commit()
            flash('시료 정보 수정 완료', 'success')
            return redirect(url_for('sample.sample_detail', sample_id=sample.id))

        projects = (db.query(Project)
                    .filter(Project.status.notin_(['취소']))
                    .order_by(Project.id.desc()).limit(300).all())
        return render_template(
            'sample_form.html', sample=sample, projects=projects,
            purpose_choices=SAMPLE_PURPOSE_CHOICES,
            status_choices=SAMPLE_STATUS_CHOICES,
        )


# ── 상세 ─────────────────────────────────────────────────
@sample_bp.route('/samples/<int:sample_id>')
@menu_required('sample')
def sample_detail(sample_id):
    with get_db() as db:
        sample = (db.query(Sample)
                  .options(joinedload(Sample.tests), joinedload(Sample.logs))
                  .filter(Sample.id == sample_id).first())
        if not sample:
            flash('시료를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('sample.sample_list'))

        certs = (db.query(Certification)
                 .filter(Certification.is_active.is_(True))
                 .order_by(Certification.cert_type, Certification.cert_name).all())

        public_url = url_for('sample.sample_public', token=sample.qr_token, _external=True)
        return render_template(
            'sample_detail.html',
            sample=sample,
            certs=certs,
            public_url=public_url,
            category_choices=TEST_CATEGORY_CHOICES,
            type_choices=TEST_TYPE_CHOICES,
            result_choices=TEST_RESULT_CHOICES,
            agency_suggestions=TEST_AGENCY_SUGGESTIONS,
            measure_fields=MEASURE_FIELDS,
            status_choices=SAMPLE_STATUS_CHOICES,
            roll_presets=LABEL_ROLLS,
            default_roll=DEFAULT_ROLL,
            can_write=_can_write(),
        )


# ── 상태 변경 ────────────────────────────────────────────
@sample_bp.route('/samples/<int:sample_id>/status', methods=['POST'])
@menu_required('sample', write=True)
def sample_status(sample_id):
    new_status = (request.form.get('status') or '').strip()
    note = (request.form.get('note') or '').strip()
    with get_db() as db:
        sample = db.get(Sample, sample_id)
        if not sample:
            flash('시료를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('sample.sample_list'))
        if new_status not in SAMPLE_STATUS_CHOICES:
            flash('알 수 없는 상태입니다.', 'danger')
            return redirect(url_for('sample.sample_detail', sample_id=sample_id))

        before = sample.status
        sample.status = new_status
        content = f'{before} → {new_status}'
        if note:
            content += f' ({note})'
        append_sample_log(db, sample.id, '상태변경', content,
                          user_name=_user_name(), ip_address=_client_ip())
        log_activity(db, '시료관리', '상태변경', f'{sample.sample_no} {content}',
                     ref_type='sample', ref_id=sample.id, ref_label=sample.sample_no,
                     user_name=_user_name())
        db.commit()
        flash(f'상태 변경 완료 — {content}', 'success')
    return redirect(url_for('sample.sample_detail', sample_id=sample_id))


# ── 폐기(비활성) ─────────────────────────────────────────
@sample_bp.route('/samples/<int:sample_id>/delete', methods=['POST'])
@menu_required('sample', write=True)
def sample_delete(sample_id):
    with get_db() as db:
        sample = db.get(Sample, sample_id)
        if sample:
            sample.is_active = False
            sample.status = '폐기'
            append_sample_log(db, sample.id, '폐기', '시료 폐기 처리 (목록에서 제외)',
                              user_name=_user_name(), ip_address=_client_ip())
            db.commit()
            flash(f'{sample.sample_no} 폐기 처리했습니다.', 'success')
    return redirect(url_for('sample.sample_list'))


# ── 시험 기록 등록 ───────────────────────────────────────
@sample_bp.route('/samples/<int:sample_id>/tests', methods=['POST'])
@menu_required('sample', write=True)
def test_create(sample_id):
    with get_db() as db:
        sample = db.get(Sample, sample_id)
        if not sample:
            flash('시료를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('sample.sample_list'))

        test = SampleTest(
            sample_id=sample.id,
            test_category=request.form.get('test_category') or '공인시험',
            test_type=(request.form.get('test_type') or '').strip() or None,
            agency=(request.form.get('agency') or '').strip() or None,
            request_date=parse_date(request.form.get('request_date')),
            report_no=(request.form.get('report_no') or '').strip() or None,
            issued_date=parse_date(request.form.get('issued_date')),
            valid_until=parse_date(request.form.get('valid_until')),
            result=(request.form.get('result') or '').strip() or None,
            measured_json=_collect_measured_json(request.form),
            certification_id=safe_int(request.form.get('certification_id'), 0) or None,
            tester=(request.form.get('tester') or '').strip() or None,
            note=(request.form.get('note') or '').strip() or None,
            created_by=_user_name(),
        )
        path, orig_name = _save_file(request.files.get('report_file'), 'tests', sample.sample_no)
        test.file_path = path
        test.file_name = orig_name

        db.add(test)
        db.flush()

        desc = f'{test.test_category} · {test.test_type or "-"}'
        if test.agency:
            desc += f' · {test.agency}'
        if test.result:
            desc += f' · {test.result}'
        append_sample_log(db, sample.id, '시험등록', desc,
                          user_name=_user_name(), ip_address=_client_ip())
        log_activity(db, '시료관리', '시험등록', f'{sample.sample_no} {desc}',
                     ref_type='sample', ref_id=sample.id, ref_label=sample.sample_no,
                     user_name=_user_name())
        db.commit()
        flash('시험 기록 등록 완료', 'success')
    return redirect(url_for('sample.sample_detail', sample_id=sample_id))


@sample_bp.route('/samples/tests/<int:test_id>/delete', methods=['POST'])
@menu_required('sample', write=True)
def test_delete(test_id):
    with get_db() as db:
        test = db.get(SampleTest, test_id)
        if not test:
            abort(404)
        sample_id = test.sample_id
        desc = f'{test.test_category} · {test.report_no or test.test_type or "-"} 삭제'
        db.delete(test)
        append_sample_log(db, sample_id, '시험삭제', desc,
                          user_name=_user_name(), ip_address=_client_ip())
        db.commit()
        flash('시험 기록 삭제 완료', 'success')
    return redirect(url_for('sample.sample_detail', sample_id=sample_id))


@sample_bp.route('/samples/tests/<int:test_id>/file')
@menu_required('sample')
def test_file(test_id):
    """성적서 원본 (사내 열람 — 불합격 포함 전부)"""
    with get_db() as db:
        test = db.get(SampleTest, test_id)
        if not test or not test.file_path:
            abort(404)
        return _serve_storage(test.file_path, test.file_name)


@sample_bp.route('/samples/<int:sample_id>/photo')
@menu_required('sample')
def sample_photo(sample_id):
    with get_db() as db:
        sample = db.get(Sample, sample_id)
        if not sample or not sample.photo_path:
            abort(404)
        return _serve_storage(sample.photo_path)


# ── QR 이미지 ────────────────────────────────────────────
@sample_bp.route('/samples/<int:sample_id>/qr.png')
@menu_required('sample')
def sample_qr(sample_id):
    from modules.services.sample_qr import build_label_qr_png
    with get_db() as db:
        sample = db.get(Sample, sample_id)
        if not sample:
            abort(404)
        url = url_for('sample.sample_public', token=sample.qr_token, _external=True)
    png = build_label_qr_png(url)
    return Response(png, mimetype='image/png',
                    headers={'Cache-Control': 'public, max-age=86400'})


# ── 라벨 출력 : 단건 (TSC TE210 등 라벨프린터) ───────────
@sample_bp.route('/samples/<int:sample_id>/label')
@menu_required('sample')
def sample_label(sample_id):
    spec = _resolve_label_spec(request.args)
    with get_db() as db:
        sample = db.get(Sample, sample_id)
        if not sample:
            abort(404)
        return render_template('sample_label_single.html',
                               sample=sample, spec=spec,
                               roll=spec['roll'], roll_presets=LABEL_ROLLS,
                               pdf_query=_spec_query(spec))


def _spec_query(spec):
    """현재 규격을 PDF 링크에 그대로 넘기기 위한 쿼리 dict."""
    return {'roll': spec['roll'], 'pw': spec['pw'], 'ph': spec['ph'],
            'lw': spec['lw'], 'lh': spec['lh'],
            'adj_x': spec['adj_x'], 'adj_y': spec['adj_y']}


def _label_payload(sample):
    sub = sample.purpose or ''
    if sample.mfg_date:
        sub = f'{sub} · {sample.mfg_date.strftime("%Y-%m-%d")}' if sub else sample.mfg_date.strftime('%Y-%m-%d')
    return {
        'sample_no': sample.sample_no,
        'model_name': sample.model_name,
        'sub': sub,
        'qr_token': sample.qr_token,
    }


def _render_label_pdf(samples, spec, filename):
    from modules.services.sample_label_pdf import build_label_pdf

    def public_url_of(token):
        return url_for('sample.sample_public', token=token, _external=True)

    pdf = build_label_pdf([_label_payload(s) for s in samples], spec, public_url_of)
    return Response(pdf, mimetype='application/pdf', headers={
        'Content-Disposition': f'inline; filename="{filename}"',
        'Cache-Control': 'no-store',
    })


# ── 라벨 PDF : 실치수 고정 (브라우저 축소 방지) ──────────
@sample_bp.route('/samples/<int:sample_id>/label.pdf')
@menu_required('sample')
def sample_label_pdf(sample_id):
    spec = _resolve_label_spec(request.args)
    copies = max(1, min(safe_int(request.args.get('copies'), 1), 50))
    with get_db() as db:
        sample = db.get(Sample, sample_id)
        if not sample:
            abort(404)
        return _render_label_pdf([sample] * copies, spec, f'{sample.sample_no}_label.pdf')


@sample_bp.route('/samples/labels.pdf')
@menu_required('sample')
def sample_labels_pdf():
    """선택한 시료들을 라벨프린터용 PDF로 — 라벨 1장 = 1페이지."""
    spec = _resolve_label_spec(request.args)
    copies = max(1, min(safe_int(request.args.get('copies'), 1), 50))
    raw_ids = (request.args.get('ids') or '').strip()
    id_list = [i for i in (safe_int(v, 0) for v in raw_ids.split(',') if v.strip()) if i]

    with get_db() as db:
        query = db.query(Sample).filter(Sample.is_active.is_(True))
        if id_list:
            query = query.filter(Sample.id.in_(id_list))
        samples = query.order_by(Sample.model_code, Sample.seq).all()
        if id_list:
            order = {sid: idx for idx, sid in enumerate(id_list)}
            samples.sort(key=lambda s: order.get(s.id, 9999))
        expanded = [s for s in samples for _ in range(copies)]
        return _render_label_pdf(expanded, spec, 'magnatech_sample_labels.pdf')


# ── 라벨 출력 : A4 시트 ──────────────────────────────────
@sample_bp.route('/samples/labels')
@menu_required('sample')
def sample_labels():
    sheet_key = request.args.get('sheet') or 'formtec3108'
    sheet = LABEL_SHEETS.get(sheet_key, LABEL_SHEETS['formtec3108'])
    start_offset = max(0, safe_int(request.args.get('offset'), 0))
    copies = max(1, min(safe_int(request.args.get('copies'), 1), 20))

    raw_ids = (request.args.get('ids') or '').strip()
    id_list = [safe_int(v, 0) for v in raw_ids.split(',') if v.strip()]
    id_list = [i for i in id_list if i]

    with get_db() as db:
        query = db.query(Sample).filter(Sample.is_active.is_(True))
        if id_list:
            query = query.filter(Sample.id.in_(id_list))
        samples = query.order_by(Sample.model_code, Sample.seq).all()

        if id_list:  # 선택 순서 유지
            order = {sid: idx for idx, sid in enumerate(id_list)}
            samples.sort(key=lambda s: order.get(s.id, 9999))

        cells = []
        for _ in range(start_offset):
            cells.append(None)
        for s in samples:
            for _ in range(copies):
                cells.append({
                    'id': s.id,
                    'sample_no': s.sample_no,
                    'model_name': s.model_name,
                    'purpose': s.purpose,
                    'mfg_date': s.mfg_date.strftime('%Y-%m-%d') if s.mfg_date else '',
                })

        per_page_cells = sheet['cols'] * sheet['rows']
        pages = [cells[i:i + per_page_cells] for i in range(0, len(cells), per_page_cells)] or [[]]

        return render_template('sample_labels.html',
                               pages=pages, sheet=sheet, sheet_key=sheet_key,
                               sheets=LABEL_SHEETS, per_page_cells=per_page_cells,
                               offset=start_offset, copies=copies, ids=raw_ids,
                               total_labels=len([c for c in cells if c]))


# ── A4 스펙시트 인쇄 : 시료 스펙 + 큰 QR ────────────────
# 라벨(실물 부착용)과 목적이 다르다. 이쪽은 A4 한 장에 스펙·시험이력을
# 크게 찍어 회의·검사 때 보는 용도라, 시료 1건 = A4 1페이지로 낸다.
def _render_sample_sheets(samples):
    # 기본은 가로(297×210). 세로 184mm 폭으로는 시험이력 8개 열이 죄다 두 줄로
    # 접힌다 — 가로면 폭이 271mm라 한 줄로 떨어져 훨씬 읽힌다.
    orient = 'portrait' if request.args.get('orient') == 'portrait' else 'landscape'
    items = [{'sample': s} for s in samples]
    # 세로↔가로 전환 링크 — 현재 쿼리(ids 등)를 그대로 물고 방향만 바꾼다
    args = request.args.to_dict(flat=True)
    args['orient'] = 'portrait' if orient == 'landscape' else 'landscape'
    toggle_url = url_for(request.endpoint, **(request.view_args or {}), **args)

    return render_template('sample_sheet.html', items=items, orient=orient,
                           toggle_url=toggle_url,
                           printed_at=datetime.datetime.now(),
                           printed_by=_user_name())


@sample_bp.route('/samples/<int:sample_id>/sheet')
@menu_required('sample')
def sample_sheet(sample_id):
    with get_db() as db:
        sample = (db.query(Sample)
                  .options(joinedload(Sample.tests))
                  .filter(Sample.id == sample_id).first())
        if not sample:
            abort(404)
        return _render_sample_sheets([sample])


@sample_bp.route('/samples/sheets')
@menu_required('sample')
def sample_sheets():
    """선택한 시료들을 A4 스펙시트로 — 1건당 1페이지."""
    raw_ids = (request.args.get('ids') or '').strip()
    id_list = [i for i in (safe_int(v, 0) for v in raw_ids.split(',') if v.strip()) if i]

    with get_db() as db:
        query = (db.query(Sample)
                 .options(joinedload(Sample.tests))
                 .filter(Sample.is_active.is_(True)))
        if id_list:
            query = query.filter(Sample.id.in_(id_list))
        samples = query.order_by(Sample.model_code, Sample.seq).all()
        if id_list:  # 선택 순서 유지
            order = {sid: idx for idx, sid in enumerate(id_list)}
            samples.sort(key=lambda s: order.get(s.id, 9999))
        return _render_sample_sheets(samples)


# =========================================================
# 공개 QR 페이지 — 로그인 불필요
# =========================================================
@sample_bp.route('/s/<token>')
def sample_public(token):
    """QR 스캔 진입점. 내부메모·불합격·A/S분석은 노출하지 않는다."""
    with get_db() as db:
        sample = (db.query(Sample)
                  .options(joinedload(Sample.tests))
                  .filter(Sample.qr_token == token).first())
        if not sample or not sample.is_active:
            return render_template('sample_public.html', sample=None), 404

        sample.scan_count = (sample.scan_count or 0) + 1
        sample.last_scanned_at = datetime.datetime.now()
        append_sample_log(db, sample.id, 'QR스캔', 'QR 라벨 스캔 열람',
                          user_name='외부', origin='qr', ip_address=_client_ip())
        db.commit()

        is_staff = bool(session.get('user_id'))
        return render_template('sample_public.html',
                               sample=sample,
                               tests=sample.public_tests,
                               is_staff=is_staff)


@sample_bp.route('/s/<token>/test/<int:test_id>/file')
def sample_public_file(token, test_id):
    """공개 성적서 열람 — 공개 대상 시험만 허용."""
    with get_db() as db:
        sample = db.query(Sample).filter(Sample.qr_token == token).first()
        if not sample or not sample.is_active:
            abort(404)
        test = db.get(SampleTest, test_id)
        if not test or test.sample_id != sample.id or not test.file_path:
            abort(404)
        if not test.is_public:
            abort(403)
        return _serve_storage(test.file_path, test.file_name)
