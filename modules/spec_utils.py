"""계약 품목별 스펙 추출/검증/포맷 유틸리티.

project.py에서 분리된 스펙 관련 공용 함수.
"""
from modules.utils import safe_int, is_true_value
from modules.models import (
    DETAIL_ITEM_OPTIONS,
    normalize_detail_item,
    CONTRACT_ITEM_SPEC_SCHEMA,
)

BOOLEAN_SPEC_FIELDS = {'has_stabilizer_box', 'is_integrated', 'is_painted'}


def extract_contract_item_spec(form, category):
    """폼 데이터에서 계약 품목별 스펙 JSON을 추출."""
    category = normalize_detail_item(category, default=DETAIL_ITEM_OPTIONS[0])
    schema = CONTRACT_ITEM_SPEC_SCHEMA.get(category, {})
    req = schema.get('required', [])
    cond_req = schema.get('conditional_required', {})

    spec = {}

    for field in req:
        raw = form.get(f'spec_{field}')
        if isinstance(raw, str):
            raw = raw.strip()
        spec[field] = raw

    for trigger, rule in cond_req.items():
        current = spec.get(trigger)
        expected = rule.get('equals')
        if isinstance(expected, bool):
            current_cmp = is_true_value(current)
        else:
            current_cmp = current
        if current_cmp == expected:
            for field in rule.get('fields', []):
                raw = form.get(f'spec_{field}')
                if isinstance(raw, str):
                    raw = raw.strip()
                spec[field] = raw

    for key, val in list(spec.items()):
        if key in BOOLEAN_SPEC_FIELDS:
            spec[key] = is_true_value(val)
        elif key == 'lamp_count':
            spec[key] = safe_int(val, 0)
        elif val is None:
            spec[key] = ''

    return spec


def validate_contract_item_spec(category, spec):
    """스펙 딕셔너리의 필수 필드 검증. 누락 필드 리스트 반환."""
    category = normalize_detail_item(category, default=DETAIL_ITEM_OPTIONS[0])
    schema = CONTRACT_ITEM_SPEC_SCHEMA.get(category, {})
    req = schema.get('required', [])
    cond_req = schema.get('conditional_required', {})

    missing = []
    for field in req:
        value = spec.get(field)
        if value in (None, '', []):
            missing.append(field)

    for trigger, rule in cond_req.items():
        current = spec.get(trigger)
        expected = rule.get('equals')
        if current == expected:
            for field in rule.get('fields', []):
                value = spec.get(field)
                if value in (None, '', []):
                    missing.append(field)

    return missing


def format_spec_summary(category, spec):
    """스펙 요약 문자열 생성."""
    if not isinstance(spec, dict) or not spec:
        return '-'

    category = normalize_detail_item(category, default=DETAIL_ITEM_OPTIONS[0])
    if category == '투광등기구':
        return f"렌즈:{spec.get('lens_angle') or '-'}, 이격:{spec.get('spacing_distance') or '-'}"
    if category in ('가로등기구', '보안등기구', '터널등기구'):
        return f"이격:{spec.get('spacing_distance') or '-'}, 일체형:{'예' if spec.get('is_integrated') else '아니오'}"
    if category == '조명타워':
        return f"높이:{spec.get('tower_height') or '-'}, 등수:{spec.get('lamp_count') or 0}"
    if category in ('철제가로등주', '스텐가로등주'):
        return f"앙카:{spec.get('anchor_spacing') or '-'}, 암대:{spec.get('arm_type') or '-'}"
    return '-'
