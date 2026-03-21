## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 조도검증-설계관리 통합 연동 |
| 작성일 | 2026-03-21 |
| Plan 참조 | `docs/01-plan/features/illuminance-design-integration.plan.md` |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 조도검증↔설계관리 단절, 현장명 미반영, KS 하드코딩, 시설종류 고정, 기구 단일 |
| **Solution** | Project에 조도 설계필드 통합, 양방향 연동 API, 자유입력, 다중기구 |
| **Function UX Effect** | 설계관리 입력 → 조도검증 자동반영, 검증결과 → 설계관리에 표시 |
| **Core Value** | 중복 입력 제거, 데이터 일관성, 1현장 N사이트 대응 |

---

# Design: 조도검증-설계관리 통합 연동

## 1. DB 스키마 변경

### 1.1 Project 모델 — 조도 설계 필드 추가

```python
# modules/models/project_entities.py — 추가 필드

class Project(Base):
    # ... 기존 필드 유지 ...

    # 조도 설계 정보 (신규 4개)
    illuminance_facility_type = Column(String(100))   # 시설종류 (자유입력)
    illuminance_design_lux = Column(Float)            # 설계기준조도 (lx)
    illuminance_design_uo = Column(Float)             # 설계기준 균일도 (Uo)
    illuminance_fixtures = Column(Text)               # 기구 목록 JSON
    # 예: [{"type":"LED투광등","watt":400,"qty":8},{"type":"LED보안등","watt":100,"qty":4}]
```

### 1.2 IlluminanceArea 모델 — 기구 다중화

```python
# modules/models/misc_entities.py — 추가 필드

class IlluminanceArea(Base):
    # 기존: lamp_type, lamp_watt, lamp_qty (호환성 유지)
    # 신규:
    fixtures = Column(Text)  # JSON 배열
    # 예: [{"type":"LED투광등 400W","watt":400,"qty":4},{"type":"LED보안등 100W","watt":100,"qty":2}]
```

### 1.3 IlluminanceProject 모델 — 변경 없음

- `facility_type`: String(50) → String(100)으로 확장 (자유입력 대응)
- UI만 select → input+datalist로 변경

### 1.4 SQL 마이그레이션

```sql
-- projects 테이블
ALTER TABLE projects ADD COLUMN IF NOT EXISTS illuminance_facility_type VARCHAR(100);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS illuminance_design_lux FLOAT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS illuminance_design_uo FLOAT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS illuminance_fixtures TEXT;

-- illuminance_areas 테이블
ALTER TABLE illuminance_areas ADD COLUMN IF NOT EXISTS fixtures TEXT;

-- illuminance_projects 테이블 (facility_type 확장)
ALTER TABLE illuminance_projects ALTER COLUMN facility_type TYPE VARCHAR(100);
```

---

## 2. API 엔드포인트

### 2.1 GET /api/project/<id>/illuminance-info

설계현장의 조도 설계정보를 반환하는 AJAX API.

```python
# routes/api.py 또는 routes/illuminance.py 에 추가

@ilv_bp.route('/api/project-illuminance/<int:project_id>')
@login_required
def api_project_illuminance(project_id):
    """설계현장의 조도 설계정보 반환 (조도검증 신규등록에서 AJAX 호출)"""
    with get_db() as db:
        p = db.query(Project).get(project_id)
        if not p:
            return jsonify({'error': 'not found'}), 404

        fixtures = []
        if p.illuminance_fixtures:
            try:
                fixtures = json.loads(p.illuminance_fixtures)
            except:
                pass

        return jsonify({
            'project_name': p.temp_name,
            'site_address': p.site_address or '',
            'facility_type': p.illuminance_facility_type or '',
            'design_lux': p.illuminance_design_lux,
            'design_uo': p.illuminance_design_uo,
            'fixtures': fixtures,
        })
```

### 2.2 POST /project/contract_detail/<id> action=update_illuminance

설계관리에서 조도 설계정보 저장.

```python
# routes/project.py — handle_detail_common 내 action 추가

elif action == 'update_illuminance':
    project.illuminance_facility_type = form.get('illuminance_facility_type') or None
    project.illuminance_design_lux = float(form.get('illuminance_design_lux') or 0) or None
    project.illuminance_design_uo = float(form.get('illuminance_design_uo') or 0) or None

    # 기구 목록: 동적 폼에서 배열로 받기
    fix_types = form.getlist('fix_type[]')
    fix_watts = form.getlist('fix_watt[]')
    fix_qtys = form.getlist('fix_qty[]')
    fixtures = []
    for t, w, q in zip(fix_types, fix_watts, fix_qtys):
        if t.strip():
            fixtures.append({
                'type': t.strip(),
                'watt': int(w) if w else 0,
                'qty': int(q) if q else 0,
            })
    project.illuminance_fixtures = json.dumps(fixtures, ensure_ascii=False) if fixtures else None

    db.commit()
    flash('조도 설계정보가 저장되었습니다.', 'success')
    append_history_log(db, ...)
```

---

## 3. 설계관리 UI (contract_detail.html)

### 3.1 조도 설계정보 카드 — 기존 lux 바 아래에 추가

위치: line 94~107 `{% if lux %}` 블록 바로 아래

```html
{# ─── 조도 설계정보 카드 ─── #}
<div class="card border-0 shadow-sm mb-4">
    <div class="card-header d-flex justify-content-between align-items-center py-2"
         style="background: linear-gradient(135deg, #f8fafc, #f1f5f9); border-bottom: 2px solid #e2e8f0;">
        <span class="fw-bold small">💡 조도 설계정보</span>
        <button class="btn btn-xs btn-outline-primary" data-bs-toggle="modal"
                data-bs-target="#editIlluminanceModal">수정</button>
    </div>
    <div class="card-body py-2">
        <div class="row g-2">
            <div class="col-md-3">
                <small class="text-muted">시설종류</small><br>
                <strong>{{ project.illuminance_facility_type or '미입력' }}</strong>
            </div>
            <div class="col-md-3">
                <small class="text-muted">설계기준조도</small><br>
                <strong>{{ project.illuminance_design_lux or '-' }} lx</strong>
            </div>
            <div class="col-md-3">
                <small class="text-muted">설계균일도</small><br>
                <strong>{{ project.illuminance_design_uo or '-' }}</strong>
            </div>
            <div class="col-md-3">
                <small class="text-muted">기구</small><br>
                {% if illuminance_fixtures %}
                    {% for f in illuminance_fixtures %}
                    <span class="badge bg-secondary">{{ f.type }} {{ f.watt }}W × {{ f.qty }}</span>
                    {% endfor %}
                {% else %}
                    <span class="text-muted">미입력</span>
                {% endif %}
            </div>
        </div>

        {# 연결된 조도검증 프로젝트 목록 #}
        {% if linked_illuminance_projects %}
        <hr class="my-2">
        <small class="text-muted fw-bold">조도검증 현황</small>
        <div class="mt-1">
            {% for ip in linked_illuminance_projects %}
            <a href="{{ url_for('illuminance.detail', project_id=ip.id) }}"
               class="d-block text-decoration-none small mb-1">
                {% if ip.status == 'reported' %}✅{% elif ip.status == 'measured' %}📊{% else %}⏳{% endif %}
                {{ ip.project_name }}
                {% if ip.areas %}
                    ({{ ip.areas | length }}구역)
                {% endif %}
            </a>
            {% endfor %}
        </div>
        {% endif %}

        <a href="{{ url_for('illuminance.new') }}?erp_project_id={{ project.id }}"
           class="btn btn-xs btn-outline-success mt-2">+ 조도검증 등록</a>
    </div>
</div>
```

### 3.2 조도 설계정보 수정 모달

```html
<div class="modal fade" id="editIlluminanceModal" tabindex="-1">
    <div class="modal-dialog">
        <div class="modal-content">
            <form method="POST" action="{{ url_for('project.contract_detail', project_id=project.id) }}">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <input type="hidden" name="action" value="update_illuminance">
                <div class="modal-header">
                    <h6 class="modal-title fw-bold">💡 조도 설계정보 수정</h6>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <div class="mb-3">
                        <label class="form-label small fw-bold">시설종류</label>
                        <input type="text" name="illuminance_facility_type"
                               class="form-control form-control-sm"
                               list="facilityTypeList"
                               value="{{ project.illuminance_facility_type or '' }}"
                               placeholder="예: 풋살장, 주차장, 테니스장">
                        <datalist id="facilityTypeList">
                            <option value="풋살장">
                            <option value="축구장">
                            <option value="테니스장">
                            <option value="주차장">
                            <option value="보행로">
                            <option value="운동장">
                            <option value="공원">
                            <option value="체육관">
                            <option value="공장">
                            <option value="물류창고">
                            <option value="도로">
                        </datalist>
                    </div>
                    <div class="row g-2 mb-3">
                        <div class="col-6">
                            <label class="form-label small fw-bold">설계기준조도 (lx)</label>
                            <input type="number" name="illuminance_design_lux"
                                   class="form-control form-control-sm"
                                   value="{{ project.illuminance_design_lux or '' }}"
                                   step="any" min="0" placeholder="300">
                        </div>
                        <div class="col-6">
                            <label class="form-label small fw-bold">설계균일도 (Uo)</label>
                            <input type="number" name="illuminance_design_uo"
                                   class="form-control form-control-sm"
                                   value="{{ project.illuminance_design_uo or '' }}"
                                   step="0.01" min="0" max="1" placeholder="0.60">
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label small fw-bold">기구 목록</label>
                        <div id="fixtureRows">
                            {# JS로 동적 행 추가 #}
                        </div>
                        <button type="button" class="btn btn-xs btn-outline-secondary mt-1"
                                onclick="addFixtureRow()">+ 기구 추가</button>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">취소</button>
                    <button type="submit" class="btn btn-primary btn-sm">저장</button>
                </div>
            </form>
        </div>
    </div>
</div>
```

### 3.3 Route에서 데이터 전달

```python
# routes/project.py — contract_detail 뷰에서 추가 데이터 전달

# 조도 설계 기구 파싱
illuminance_fixtures = []
if project.illuminance_fixtures:
    try:
        illuminance_fixtures = json.loads(project.illuminance_fixtures)
    except:
        pass

# 연결된 조도검증 프로젝트
linked_illuminance_projects = db.query(IlluminanceProject).filter(
    IlluminanceProject.erp_project_id == project.id
).order_by(IlluminanceProject.created_at.desc()).all()

# 템플릿에 전달
return render_template('contract_detail.html',
    ...,
    illuminance_fixtures=illuminance_fixtures,
    linked_illuminance_projects=linked_illuminance_projects,
)
```

---

## 4. 조도검증 신규등록 개선 (illuminance_new)

### 4.1 시설종류: select → input+datalist

```html
<!-- Before -->
<select name="facility_type">
    <option value="풋살장">풋살장</option>
    ...5개 고정...
</select>

<!-- After -->
<input type="text" name="facility_type" id="fieldFacility"
       list="facilityList" class="form-control form-control-sm"
       placeholder="시설종류 입력 (예: 풋살장, 주차장)">
<datalist id="facilityList">
    <option value="풋살장">
    <option value="축구장">
    <option value="테니스장">
    <option value="주차장">
    <option value="보행로">
    <option value="운동장">
    <option value="공원">
    <option value="체육관">
    <option value="공장">
    <option value="물류창고">
    <option value="도로">
</datalist>
```

### 4.2 설계기준조도 직접입력 필드 추가

Step 1 폼에 추가:

```html
<div class="row g-2 mb-3">
    <div class="col-6">
        <label class="form-label small fw-bold">설계기준조도 (lx)</label>
        <input type="number" name="design_lux" id="fieldDesignLux"
               class="form-control form-control-sm"
               step="any" min="0" placeholder="설계기준 또는 KS기준">
        <small class="text-muted">미입력 시 시설종류 KS기준 자동적용</small>
    </div>
    <div class="col-6">
        <label class="form-label small fw-bold">설계균일도 (Uo)</label>
        <input type="number" name="design_uo" id="fieldDesignUo"
               class="form-control form-control-sm"
               step="0.01" min="0" max="1" placeholder="0.60">
    </div>
</div>
```

### 4.3 onErpProjectChange() 강화

```javascript
function onErpProjectChange(sel) {
    const opt = sel.options[sel.selectedIndex];
    if (!opt.value) return;

    // 현장명, 위치: 항상 반영 (기존: 빈 경우만)
    document.getElementById('fieldName').value = opt.dataset.name || '';
    document.getElementById('fieldLocation').value = opt.dataset.addr || '';

    // 설계관리에서 조도정보 가져오기 (AJAX)
    fetch('/illuminance/api/project-illuminance/' + opt.value)
        .then(r => r.json())
        .then(data => {
            if (data.facility_type) {
                document.getElementById('fieldFacility').value = data.facility_type;
            }
            if (data.design_lux) {
                document.getElementById('fieldDesignLux').value = data.design_lux;
            }
            if (data.design_uo) {
                document.getElementById('fieldDesignUo').value = data.design_uo;
            }
            // 기구 정보도 표시 (읽기전용 참고용)
            if (data.fixtures && data.fixtures.length) {
                const info = data.fixtures.map(f => f.type + ' ' + f.watt + 'W × ' + f.qty).join(', ');
                let el = document.getElementById('erpFixtureInfo');
                if (el) el.textContent = '설계관리 기구: ' + info;
            }
        })
        .catch(() => {});
}
```

### 4.4 URL 파라미터로 설계현장 자동선택

설계관리에서 `[+ 조도검증 등록]` 클릭 시 `/illuminance/new?erp_project_id=123`으로 이동.

```python
# routes/illuminance.py — new() 수정
@ilv_bp.route('/new', methods=['GET'])
@login_required
def new():
    with get_db() as db:
        erp_projects = db.query(Project).order_by(Project.created_at.desc()).all()
        preselect_id = request.args.get('erp_project_id', type=int)
        return render_template('illuminance_new.html',
                               erp_projects=erp_projects,
                               preselect_id=preselect_id)
```

```html
<!-- illuminance_new.html — select에 preselect 적용 -->
<select name="erp_project_id" id="erpProjectSelect" onchange="onErpProjectChange(this)">
    <option value="">— 기존 현장과 연결하지 않음 —</option>
    {% for ep in erp_projects %}
    <option value="{{ ep.id }}"
            data-name="{{ ep.temp_name }}"
            data-addr="{{ ep.site_address or '' }}"
            {{ 'selected' if preselect_id == ep.id }}>
        [{{ ep.project_no }}] {{ ep.temp_name }}
    </option>
    {% endfor %}
</select>

<script>
// 페이지 로드 시 preselect가 있으면 자동 채움
document.addEventListener('DOMContentLoaded', function() {
    var sel = document.getElementById('erpProjectSelect');
    if (sel && sel.value) onErpProjectChange(sel);
});
</script>
```

### 4.5 KS 기준 → 설계기준조도 우선 로직

```python
# routes/illuminance.py — new_save() 수정

# 저장 시 KS 기준 결정 우선순위:
# 1. 사용자가 직접 입력한 design_lux
# 2. ERP 설계관리에서 가져온 값 (Project.illuminance_design_lux)
# 3. 시설종류 기반 KS 기준 (get_ks_standard) — fallback

user_design_lux = float(form.get('design_lux') or 0)
user_design_uo = float(form.get('design_uo') or 0)

if user_design_lux:
    ks_eav = user_design_lux
    ks_uo = user_design_uo or 0
elif erp_project and erp_project.illuminance_design_lux:
    ks_eav = erp_project.illuminance_design_lux
    ks_uo = erp_project.illuminance_design_uo or 0
else:
    ks = get_ks_standard(facility)
    ks_eav = ks.get('eav', 0)
    ks_uo = ks.get('uo', 0)
```

---

## 5. 기구 다중화

### 5.1 Area 저장 시 fixtures JSON 생성

PDF 파서가 이미 `lamp_type`, `lamp_watt`, `lamp_qty` 를 추출하므로,
신규등록 시 이를 fixtures JSON으로도 저장:

```python
# routes/illuminance.py — new_save() Area 생성 부분

area = IlluminanceArea(
    project_id=project.id,
    area_name=area_d.get('area_name', f'구역{idx}'),
    lamp_type=area_d.get('lamp_type'),
    lamp_watt=area_d.get('lamp_watt'),
    lamp_qty=area_d.get('lamp_qty'),
    # 신규: fixtures JSON (현재는 단일 기구)
    fixtures=json.dumps([{
        'type': area_d.get('lamp_type', ''),
        'watt': area_d.get('lamp_watt', 0),
        'qty': area_d.get('lamp_qty', 0),
    }], ensure_ascii=False) if area_d.get('lamp_type') else None,
    # ... 나머지 필드
)
```

향후 PDF 파서가 다중 기구를 인식하면 fixtures 배열에 N건 추가.

### 5.2 Area 상세 표시

```html
<!-- illuminance_area.html — 기구 정보 표시 -->
{% if area_fixtures %}
<div class="d-flex flex-wrap gap-1 mb-2">
    {% for f in area_fixtures %}
    <span class="badge bg-info">{{ f.type }} {{ f.watt }}W × {{ f.qty }}</span>
    {% endfor %}
</div>
{% else %}
<span class="text-muted">{{ fixture_watt }}W × {{ fixture_count }}</span>
{% endif %}
```

---

## 6. 양방향 연동: 조도검증 → 설계관리

### 6.1 조도검증 상세에서 설계관리 링크

```html
<!-- illuminance_detail.html — 프로젝트 정보 카드에 추가 -->
{% if project.erp_project %}
<div class="mt-2">
    <a href="{{ url_for('project.contract_detail', project_id=project.erp_project_id) }}"
       class="btn btn-xs btn-outline-primary">
        📋 설계관리 바로가기
    </a>
    {% if project.erp_project.illuminance_design_lux %}
    <small class="text-muted ms-2">
        설계기준: {{ project.erp_project.illuminance_design_lux }}lx
    </small>
    {% endif %}
</div>
{% endif %}
```

---

## 7. 구현 순서 (의존성 기반)

```
Step 1: DB 스키마
  ├─ project_entities.py — 4개 필드 추가
  ├─ misc_entities.py — IlluminanceArea.fixtures 추가
  └─ sql_editer.sql — ALTER TABLE 6건

Step 2: API
  └─ routes/illuminance.py — api_project_illuminance() 추가

Step 3: 설계관리 UI
  ├─ routes/project.py — action=update_illuminance + 데이터 전달
  └─ templates/contract_detail.html — 조도카드 + 수정모달 + 연결 목록

Step 4: 조도검증 신규등록
  ├─ templates/illuminance_new.html — facility input+datalist, design_lux 필드
  ├─ static/js/illuminance_new.js — onErpProjectChange() AJAX 강화
  ├─ routes/illuminance.py — new() preselect, new_save() KS 우선순위
  └─ illuminance_new.html — preselect_id 적용

Step 5: 기구 다중화
  ├─ routes/illuminance.py — fixtures JSON 저장
  └─ templates/illuminance_area.html — fixtures 표시

Step 6: 양방향 연동
  ├─ templates/illuminance_detail.html — 설계관리 링크
  └─ templates/contract_detail.html — 조도검증 현황 표시

Step 7: 검증
  └─ 신규등록→설계연결→정보반영→Area상세→설계관리 확인
```

## 8. 검증 계획

| 검증 항목 | 방법 |
|-----------|------|
| DB 마이그레이션 | `python -c "from modules.models import Project"` 필드 확인 |
| API 응답 | `/illuminance/api/project-illuminance/<id>` JSON 확인 |
| 설계관리 카드 | contract_detail에서 조도 설계정보 카드 렌더링 확인 |
| 신규등록 자동채움 | 설계현장 선택 → 현장명/시설종류/기준조도 반영 확인 |
| KS 우선순위 | design_lux 직접입력 > ERP 연동 > 시설종류 KS 순서 확인 |
| 기구 다중화 | fixtures JSON 저장/표시 확인 |
| 양방향 링크 | 조도검증↔설계관리 상호 이동 확인 |

## 9. 리스크 대응

| 리스크 | 확률 | 대응 |
|--------|------|------|
| 기존 facility_type 데이터 호환 | 낮 | VARCHAR(50)→(100) 확장, 기존값 유지 |
| fixtures JSON 파싱 실패 | 낮 | try-except + 빈 배열 fallback |
| contract_detail.html 비대화 | 중 | 조도 카드를 components/illuminance_card.html로 include 분리 |
| onErpProjectChange AJAX 실패 | 낮 | catch → 무시 (수동입력으로 fallback) |
