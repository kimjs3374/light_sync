# ──────────────────────────────────────────────────────────────────
# 조도 검증 라우트 스니펫 — tech_bp (routes/technical.py) 에 추가
# ──────────────────────────────────────────────────────────────────
# 이 파일은 독립 실행용이 아닙니다.
# 아래 라우트를 routes/technical.py 의 tech_bp Blueprint 안에 붙여넣으세요.
# ──────────────────────────────────────────────────────────────────

@tech_bp.route('/illuminance_verification')
@login_required
def illuminance_verification():
    """
    조도설계 검증 화면.
    향후 project_id 파라미터로 설계값 격자를 DB에서 로드.
    현재는 템플릿 내 JS 샘플 데이터로 동작.
    """
    project_name = request.args.get('project_name', '풋살장 16m×35m')
    return render_template(
        'illuminance_verification.html',
        project_name=project_name,
    )
