"""
routes/illuminance.py — 조도설계 검증 시스템
Blueprint: ilv_bp  prefix: /illuminance
"""
import json
import os
import uuid
import datetime
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify, current_app)
from modules.auth_decorators import login_required
from modules.db_context import get_db
from modules.models.entities import IlluminanceProject, IlluminanceArea, IlluminanceMeasured, Project
from modules.services.illuminance_pdf_parser import ReluxPdfParser, get_ks_standard, judge_ks

ilv_bp = Blueprint('illuminance', __name__, url_prefix='/illuminance')

UPLOAD_FOLDER = os.path.join('static', 'uploads', 'illuminance_pdf')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ──────────────────────────────────────────────────────────────
# 목록
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/')
@login_required
def index():
    with get_db() as db:
        projects = db.query(IlluminanceProject).order_by(
            IlluminanceProject.created_at.desc()
        ).all()
        return render_template('illuminance_list.html', projects=projects)


# ──────────────────────────────────────────────────────────────
# 신규 등록 폼
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/new', methods=['GET'])
@login_required
def new():
    preselect_id = request.args.get('erp_project_id', type=int)
    with get_db() as db:
        erp_projects = db.query(Project).order_by(Project.created_at.desc()).all()
        return render_template('illuminance_new.html',
                               erp_projects=erp_projects,
                               preselect_id=preselect_id)


# ──────────────────────────────────────────────────────────────
# API: PDF 업로드 → 페이지 목록 반환
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/api/project-illuminance/<int:project_id>')
@login_required
def api_project_illuminance(project_id):
    """설계현장의 조도 설계정보 반환"""
    with get_db() as db:
        p = db.query(Project).get(project_id)
        if not p:
            return jsonify({'error': 'not found'}), 404
        fixtures = []
        if p.illuminance_fixtures:
            try:
                fixtures = json.loads(p.illuminance_fixtures)
            except Exception:
                pass
        # fallback: 설계반영 자재목록에서 조명기구 파싱
        if not fixtures and p.materials:
            from modules.models.constants import LIGHTING_DETAIL_ITEMS
            for mat in p.materials:
                if mat.category in LIGHTING_DETAIL_ITEMS:
                    fixtures.append({
                        'type': mat.category,
                        'model': mat.model_name or '',
                        'watt': 0,
                        'qty': mat.quantity or 0,
                    })
        return jsonify({
            'project_name': p.temp_name,
            'site_address': p.site_address or '',
            'facility_type': p.illuminance_facility_type or '',
            'fixtures': fixtures,
        })


@ilv_bp.route('/api/upload-pdf', methods=['POST'])
@login_required
def api_upload_pdf():
    f = request.files.get('pdf')
    if not f or not f.filename.lower().endswith('.pdf'):
        return jsonify({'success': False, 'error': 'PDF 파일만 허용됩니다'}), 400
    try:
        token = uuid.uuid4().hex
        saved_name = f"{token}.pdf"
        save_path = os.path.join(UPLOAD_FOLDER, saved_name)
        f.save(save_path)

        parser = ReluxPdfParser(save_path)
        pages = parser.analyze_pages()

        return jsonify({
            'success': True,
            'total_pages': len(pages),
            'pages': pages,
            'upload_token': token,
            'original_name': f.filename,
        })
    except Exception as e:
        current_app.logger.exception('PDF upload failed')
        return jsonify({'success': False, 'error': str(e)}), 500


# ──────────────────────────────────────────────────────────────
# API: 선택 페이지 파싱 → 격자 데이터 반환
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/api/parse-pages', methods=['POST'])
@login_required
def api_parse_pages():
    data = request.get_json()
    token = data.get('upload_token')
    selections = data.get('selections', [])  # [{page_index, area_name}]

    if not token or not selections:
        return jsonify({'success': False, 'error': '파라미터 오류'}), 400

    pdf_path = os.path.join(UPLOAD_FOLDER, f"{token}.pdf")
    if not os.path.exists(pdf_path):
        return jsonify({'success': False, 'error': 'PDF 파일을 찾을 수 없습니다'}), 404

    try:
        parser = ReluxPdfParser(pdf_path)
        areas = []
        for sel in selections:
            parsed = parser.parse_page(sel['page_index'])
            parsed['area_name'] = sel.get('area_name') or parsed.get('area_name', '구역')
            areas.append(parsed)
        return jsonify({'success': True, 'areas': areas})
    except Exception as e:
        current_app.logger.exception('PDF parse failed')
        return jsonify({'success': False, 'error': str(e)}), 500


# ──────────────────────────────────────────────────────────────
# 저장 (POST /new)
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/new', methods=['POST'])
@login_required
def new_save():
    form = request.form
    areas_json = form.get('areas_json', '[]')

    try:
        areas_data = json.loads(areas_json)
    except Exception:
        flash('구역 데이터 파싱 오류', 'danger')
        return redirect(url_for('illuminance.new'))

    with get_db() as db:
        try:
            erp_pid = form.get('erp_project_id')
            project = IlluminanceProject(
                project_name=form.get('project_name', '').strip(),
                erp_project_id=int(erp_pid) if erp_pid and erp_pid.isdigit() else None,
                customer=form.get('customer', '').strip() or None,
                location=form.get('location', '').strip() or None,
                install_date=_parse_date(form.get('install_date')),
                pdf_filename=form.get('upload_token', '') + '.pdf',
                facility_type=form.get('facility_type') or None,
                status='design',
                created_by=session.get('username'),
            )
            db.add(project)
            db.flush()  # id 확보

            facility = form.get('facility_type', '')

            ks = get_ks_standard(facility)
            ks_eav = ks.get('eav', 0)
            ks_uo = ks.get('uo', 0)

            for idx, area_d in enumerate(areas_data, start=1):
                area = IlluminanceArea(
                    project_id=project.id,
                    area_name=area_d.get('area_name', f'구역{idx}'),
                    area_index=idx,
                    installation_height=area_d.get('installation_height'),
                    lamp_type=area_d.get('lamp_type'),
                    lamp_watt=area_d.get('lamp_watt'),
                    lamp_qty=area_d.get('lamp_qty'),
                    tower_qty=area_d.get('tower_qty'),
                    simulation_date=_parse_date(area_d.get('simulation_date')),
                    design_eav=area_d.get('design_eav'),
                    design_emin=area_d.get('design_emin'),
                    design_emax=area_d.get('design_emax'),
                    design_uo=area_d.get('design_uo'),
                    design_ud=area_d.get('design_ud'),
                    maintenance_factor=area_d.get('maintenance_factor'),
                    total_flux=area_d.get('total_flux'),
                    total_power=area_d.get('total_power'),
                    power_per_area=area_d.get('power_per_area'),
                    grid_rows=area_d.get('grid_rows'),
                    grid_cols=area_d.get('grid_cols'),
                    grid_x_labels=json.dumps(area_d.get('x_labels', []), ensure_ascii=False),
                    grid_y_labels=json.dumps(area_d.get('y_labels', []), ensure_ascii=False),
                    design_grid=json.dumps(area_d.get('design_grid', []), ensure_ascii=False),
                    ks_eav_min=ks_eav,
                    ks_uo_min=ks_uo,
                    fixtures=json.dumps([{
                        'type': area_d.get('lamp_type', ''),
                        'watt': area_d.get('lamp_watt', 0),
                        'qty': area_d.get('lamp_qty', 0),
                    }], ensure_ascii=False) if area_d.get('lamp_type') else None,
                )
                db.add(area)

            db.commit()
            flash(f"✅ {project.project_name} 등록 완료 ({len(areas_data)}개 구역)", 'success')
            return redirect(url_for('illuminance.detail', project_id=project.id))
        except Exception:
            db.rollback()
            current_app.logger.exception('illuminance save failed')
            flash('저장 중 오류가 발생했습니다', 'danger')
            return redirect(url_for('illuminance.new'))


# ──────────────────────────────────────────────────────────────
# API: 설계관리에서 PDF 업로드 → 원스톱 조도검증 프로젝트 생성
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/api/quick-create', methods=['POST'])
@login_required
def api_quick_create():
    """설계관리 페이지에서 PDF 올리면 조도검증 프로젝트를 자동 생성"""
    f = request.files.get('pdf')
    erp_project_id = request.form.get('erp_project_id', type=int)
    if not f or not f.filename.lower().endswith('.pdf'):
        return jsonify({'success': False, 'error': 'PDF 파일만 허용됩니다'}), 400
    if not erp_project_id:
        return jsonify({'success': False, 'error': '설계현장 ID가 필요합니다'}), 400

    try:
        # 1) PDF 저장
        token = uuid.uuid4().hex
        save_path = os.path.join(UPLOAD_FOLDER, f"{token}.pdf")
        f.save(save_path)

        # 2) 전체 페이지 분석 → 격자 있는 페이지만 자동 파싱
        parser = ReluxPdfParser(save_path)
        pages = parser.analyze_pages()
        grid_pages = [p for p in pages if p.get('has_grid')]
        if not grid_pages:
            return jsonify({'success': False, 'error': 'PDF에서 조도 격자표를 찾을 수 없습니다'}), 400

        areas_data = []
        for pg in grid_pages:
            parsed = parser.parse_page(pg['page_index'])
            parsed['area_name'] = pg.get('area_name') or parsed.get('area_name', '구역')
            areas_data.append(parsed)

        # 3) DB 저장
        with get_db() as db:
            erp_project = db.query(Project).get(erp_project_id)
            if not erp_project:
                return jsonify({'success': False, 'error': '설계현장을 찾을 수 없습니다'}), 404

            facility = erp_project.illuminance_facility_type or ''
            ks = get_ks_standard(facility)
            ks_eav = ks.get('eav', 0)
            ks_uo = ks.get('uo', 0)

            project = IlluminanceProject(
                project_name=erp_project.temp_name,
                erp_project_id=erp_project_id,
                facility_type=facility,
                pdf_filename=f"{token}.pdf",
                status='design',
                created_by=session.get('username'),
            )
            db.add(project)
            db.flush()

            for idx, area_d in enumerate(areas_data, start=1):
                area = IlluminanceArea(
                    project_id=project.id,
                    area_name=area_d.get('area_name', f'구역{idx}'),
                    area_index=idx,
                    installation_height=area_d.get('installation_height'),
                    lamp_type=area_d.get('lamp_type'),
                    lamp_watt=area_d.get('lamp_watt'),
                    lamp_qty=area_d.get('lamp_qty'),
                    tower_qty=area_d.get('tower_qty'),
                    simulation_date=_parse_date(area_d.get('simulation_date')),
                    design_eav=area_d.get('design_eav'),
                    design_emin=area_d.get('design_emin'),
                    design_emax=area_d.get('design_emax'),
                    design_uo=area_d.get('design_uo'),
                    design_ud=area_d.get('design_ud'),
                    maintenance_factor=area_d.get('maintenance_factor'),
                    total_flux=area_d.get('total_flux'),
                    total_power=area_d.get('total_power'),
                    power_per_area=area_d.get('power_per_area'),
                    grid_rows=area_d.get('grid_rows'),
                    grid_cols=area_d.get('grid_cols'),
                    grid_x_labels=json.dumps(area_d.get('x_labels', []), ensure_ascii=False),
                    grid_y_labels=json.dumps(area_d.get('y_labels', []), ensure_ascii=False),
                    design_grid=json.dumps(area_d.get('design_grid', []), ensure_ascii=False),
                    ks_eav_min=ks_eav,
                    ks_uo_min=ks_uo,
                    fixtures=json.dumps([{
                        'type': area_d.get('lamp_type', ''),
                        'watt': area_d.get('lamp_watt', 0),
                        'qty': area_d.get('lamp_qty', 0),
                    }], ensure_ascii=False) if area_d.get('lamp_type') else None,
                )
                db.add(area)

            db.commit()
            return jsonify({
                'success': True,
                'project_id': project.id,
                'project_name': project.project_name,
                'area_count': len(areas_data),
                'detail_url': url_for('illuminance.detail', project_id=project.id),
            })

    except Exception as e:
        current_app.logger.exception('quick-create failed')
        return jsonify({'success': False, 'error': str(e)}), 500


# ──────────────────────────────────────────────────────────────
# 프로젝트 상세 (구역 목록)
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/<int:project_id>')
@login_required
def detail(project_id):
    with get_db() as db:
        project = db.query(IlluminanceProject).get(project_id)
        if not project:
            flash('프로젝트를 찾을 수 없습니다', 'danger')
            return redirect(url_for('illuminance.index'))
        # 첫 번째 구역으로 바로 이동 (구역이 1개인 경우 편의)
        if len(project.areas) == 1:
            return redirect(url_for('illuminance.area',
                                    project_id=project_id,
                                    area_id=project.areas[0].id))
        return render_template('illuminance_detail.html', project=project)


# ──────────────────────────────────────────────────────────────
# 구역 상세 (히트맵 + 실측 입력 + 비교)
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/<int:project_id>/area/<int:area_id>')
@login_required
def area(project_id, area_id):
    with get_db() as db:
        project = db.query(IlluminanceProject).get(project_id)
        ilv_area = db.query(IlluminanceArea).get(area_id)
        if not project or not ilv_area:
            flash('데이터를 찾을 수 없습니다', 'danger')
            return redirect(url_for('illuminance.index'))

        latest = ilv_area.latest_measurement
        measured_grid = latest.measured_grid_parsed if latest else None

        area_fixtures = []
        if ilv_area.fixtures:
            try:
                area_fixtures = json.loads(ilv_area.fixtures)
            except Exception:
                pass

        return render_template('illuminance_area.html',
                               project_id=project_id,
                               project_name=project.project_name,
                               area_id=area_id,
                               area_name=ilv_area.area_name,
                               grid_rows=ilv_area.grid_rows or 0,
                               grid_cols=ilv_area.grid_cols or 0,
                               x_labels=ilv_area.x_labels_parsed,
                               y_labels=ilv_area.y_labels_parsed,
                               design_grid=ilv_area.design_grid_parsed,
                               measured_grid=measured_grid,
                               ks_standard=ilv_area.ks_eav_min,
                               fixture_watt=ilv_area.lamp_watt,
                               fixture_count=ilv_area.lamp_qty,
                               height=ilv_area.installation_height,
                               measurements=ilv_area.measurements,
                               area_fixtures=area_fixtures)


# ──────────────────────────────────────────────────────────────
# 실측값 저장
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/<int:project_id>/area/<int:area_id>/measure', methods=['POST'])
@login_required
def save_measure(project_id, area_id):
    with get_db() as db:
        ilv_area = db.query(IlluminanceArea).get(area_id)
        if not ilv_area:
            return jsonify({'success': False, 'error': '구역 없음'}), 404

        try:
            is_json = request.is_json
            if is_json:
                jdata = request.get_json(silent=True) or {}
                raw_grid = jdata.get('grid_data', [])
                grid_raw = json.dumps(raw_grid) if isinstance(raw_grid, list) else raw_grid
            else:
                grid_raw = request.form.get('grid_data', '[]')
            grid = json.loads(grid_raw)

            # 통계 계산
            flat = [v for row in grid for v in row if v is not None]
            if flat:
                eav  = sum(flat) / len(flat)
                emin = min(flat)
                emax = max(flat)
                uo   = emin / eav if eav else 0
                ud   = emin / emax if emax else 0
            else:
                eav = emin = emax = uo = ud = None

            ks_pass = judge_ks(eav, uo, ilv_area.ks_eav_min, ilv_area.ks_uo_min)
            eav_ach = (eav / ilv_area.design_eav * 100) if (eav and ilv_area.design_eav) else None
            uo_ach  = (uo  / ilv_area.design_uo  * 100) if (uo  and ilv_area.design_uo)  else None

            def _fget(key, default=''):
                if is_json:
                    return jdata.get(key, default)
                return request.form.get(key, default)

            m = IlluminanceMeasured(
                area_id=area_id,
                measure_date=_parse_date(_fget('measure_date')) or datetime.date.today(),
                measured_by=(_fget('measured_by') or _fget('measurer')).strip() or None,
                weather=_fget('weather') or None,
                instrument=(_fget('instrument') or _fget('device')).strip() or None,
                measured_eav=round(eav, 1) if eav else None,
                measured_emin=emin,
                measured_emax=emax,
                measured_uo=round(uo, 3) if uo else None,
                measured_ud=round(ud, 3) if ud else None,
                measured_grid=json.dumps(grid, ensure_ascii=False),
                ks_pass=ks_pass,
                eav_achievement=round(eav_ach, 1) if eav_ach else None,
                uo_achievement=round(uo_ach, 1) if uo_ach else None,
                notes=_fget('notes').strip() or None,
            )
            db.add(m)

            # 프로젝트 상태 업데이트
            project = db.query(IlluminanceProject).get(project_id)
            if project and project.status == 'design':
                project.status = 'measured'

            db.commit()
            if is_json:
                return jsonify({'success': True, 'ks_pass': ks_pass,
                                'measured_eav': m.measured_eav, 'measured_uo': m.measured_uo})
            flash('✅ 실측값 저장 완료', 'success')
            return redirect(url_for('illuminance.area',
                                    project_id=project_id, area_id=area_id))
        except Exception:
            db.rollback()
            current_app.logger.exception('measure save failed')
            if is_json:
                return jsonify({'success': False, 'error': '저장 중 오류'}), 500
            flash('저장 중 오류가 발생했습니다', 'danger')
            return redirect(url_for('illuminance.area',
                                    project_id=project_id, area_id=area_id))


# ──────────────────────────────────────────────────────────────
# 프로젝트 수정
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/<int:project_id>/edit', methods=['POST'])
@login_required
def edit_project(project_id):
    with get_db() as db:
        project = db.query(IlluminanceProject).get(project_id)
        if not project:
            return jsonify({'success': False, 'error': '프로젝트 없음'}), 404
        form = request.get_json(silent=True) or request.form
        project.project_name  = (form.get('project_name') or '').strip() or project.project_name
        project.customer      = (form.get('customer') or '').strip() or None
        project.location      = (form.get('location') or '').strip() or None
        project.facility_type = form.get('facility_type') or project.facility_type
        project.install_date  = _parse_date(form.get('install_date')) or project.install_date
        erp_pid = form.get('erp_project_id')
        project.erp_project_id = int(erp_pid) if erp_pid and str(erp_pid).isdigit() else None
        db.commit()
        return jsonify({'success': True})


# ──────────────────────────────────────────────────────────────
# 프로젝트 삭제
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/<int:project_id>/delete', methods=['POST'])
@login_required
def delete_project(project_id):
    with get_db() as db:
        project = db.query(IlluminanceProject).get(project_id)
        if not project:
            flash('프로젝트를 찾을 수 없습니다', 'danger')
            return redirect(url_for('illuminance.index'))
        name = project.project_name
        db.delete(project)
        db.commit()
        flash(f'"{name}" 삭제 완료', 'success')
        return redirect(url_for('illuminance.index'))


# ──────────────────────────────────────────────────────────────
# 구역명 수정 (AJAX)
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/<int:project_id>/area/<int:area_id>/edit-name', methods=['POST'])
@login_required
def edit_area_name(project_id, area_id):
    with get_db() as db:
        area = db.query(IlluminanceArea).get(area_id)
        if not area:
            return jsonify({'success': False, 'error': '구역 없음'}), 404
        data = request.get_json(silent=True) or {}
        name = (data.get('area_name') or '').strip()
        if not name:
            return jsonify({'success': False, 'error': '이름 필요'}), 400
        area.area_name = name
        db.commit()
        return jsonify({'success': True, 'area_name': name})


# ──────────────────────────────────────────────────────────────
# 구역 삭제
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/<int:project_id>/area/<int:area_id>/delete', methods=['POST'])
@login_required
def delete_area(project_id, area_id):
    with get_db() as db:
        area = db.query(IlluminanceArea).get(area_id)
        if not area:
            return jsonify({'success': False, 'error': '구역 없음'}), 404
        db.delete(area)
        db.commit()
        return jsonify({'success': True})


# ──────────────────────────────────────────────────────────────
# 실측 기록 삭제 (AJAX)
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/<int:project_id>/area/<int:area_id>/measure/<int:measure_id>/delete', methods=['POST'])
@login_required
def delete_measure(project_id, area_id, measure_id):
    with get_db() as db:
        m = db.query(IlluminanceMeasured).get(measure_id)
        if not m or m.area_id != area_id:
            return jsonify({'success': False, 'error': '기록 없음'}), 404
        db.delete(m)
        db.commit()
        return jsonify({'success': True})


# ──────────────────────────────────────────────────────────────
# API: 격자 JSON 반환
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/api/area/<int:area_id>/grid')
@login_required
def api_grid(area_id):
    with get_db() as db:
        area = db.query(IlluminanceArea).get(area_id)
        if not area:
            return jsonify({'error': '구역 없음'}), 404
        return jsonify({
            'rows': area.grid_rows,
            'cols': area.grid_cols,
            'x_labels': area.x_labels_parsed,
            'y_labels': area.y_labels_parsed,
            'design_grid': area.design_grid_parsed,
        })


# ──────────────────────────────────────────────────────────────
# 리포트 (A4 인쇄용)
# ──────────────────────────────────────────────────────────────
@ilv_bp.route('/<int:project_id>/report')
@login_required
def report(project_id):
    with get_db() as db:
        project = db.query(IlluminanceProject).get(project_id)
        if not project:
            flash('프로젝트를 찾을 수 없습니다', 'danger')
            return redirect(url_for('illuminance.index'))
        areas_data = []
        for area in project.areas:
            latest = area.latest_measurement
            areas_data.append({
                'area': area,
                'latest': latest,
            })
        return render_template('illuminance_report.html',
                               project=project,
                               areas_data=areas_data)


# ──────────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────────
def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.datetime.strptime(str(val)[:10], '%Y-%m-%d').date()
    except Exception:
        return None
