# C:\light_sync\routes\technical.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from modules.auth_decorators import login_required
import json
from sqlalchemy.orm import joinedload
from modules.db_context import get_db
from modules.utils import safe_int
from modules.models import Project, SportsModule

tech_bp = Blueprint('tech', __name__)

@tech_bp.route('/lux_calculator', methods=['GET', 'POST'])
@login_required
def lux_calculator():
    with get_db() as db:
        # 1번 수정: 수정 모드 (기존 데이터 불러오기)
        edit_id = request.args.get('edit_id')
        edit_data = None
        if edit_id:
            edit_data = db.query(SportsModule).get(int(edit_id))

        if request.method == 'POST':
            try:
                lux_floats = [float(v) for v in request.form.getlist('lux_data[]') if v]
                avg = sum(lux_floats)/len(lux_floats) if lux_floats else 0
                design_lux = float(request.form.get('design_lux'))

                # 2번 수정: 설계 조도 대비 달성률(%) 계산
                achievement_rate = (avg / design_lux * 100) if design_lux > 0 else 0

                # 기존 데이터가 있으면 업데이트, 없으면 신규 생성
                calc_id = request.form.get('calc_id')
                if calc_id:
                    calc = db.query(SportsModule).get(int(calc_id))
                else:
                    calc = SportsModule()

                calc.project_id = safe_int(request.form.get('project_id'))
                calc.grid_layout = f"{request.form.get('grid_rows')}x{request.form.get('grid_cols')}"
                calc.design_lux = design_lux
                calc.measured_lux_data = json.dumps(lux_floats)
                calc.avg_lux = round(avg, 2)
                calc.u1_uniformity = round(min(lux_floats)/avg if avg > 0 else 0, 3)

                db.add(calc)
                db.commit()
                flash(f"✅ 저장 완료 (달성률: {round(achievement_rate, 1)}%)", "success")
                return redirect(url_for('tech.lux_calculator'))
            except Exception as e:
                db.rollback()
                current_app.logger.exception('lux_calculator save failed')
                flash('저장 처리 중 오류가 발생했습니다.', 'danger')

        projects = db.query(Project).all()
        recent = db.query(SportsModule).options(joinedload(SportsModule.project)).order_by(SportsModule.id.desc()).all()
        return render_template('lux_calculator.html', projects=projects, recent=recent, edit_data=edit_data)