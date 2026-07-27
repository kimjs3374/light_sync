"""계약 품목별 스펙 추출/검증/포맷 유틸리티.

project.py에서 분리된 스펙 관련 공용 함수.
"""
import json
import logging
import os

from modules.utils import safe_int, is_true_value
from modules.models import (
    DETAIL_ITEM_OPTIONS,
    normalize_detail_item,
    CONTRACT_ITEM_SPEC_SCHEMA,
    SPEC_FIELD_LABELS,
)

logger = logging.getLogger(__name__)

BOOLEAN_SPEC_FIELDS = {'has_stabilizer_box', 'is_integrated', 'is_painted'}

# 관리자설정(영업관리 > 스펙항목 설정)이 저장하는 필드 메타.
# {"필드키": {"label": "표시명", "type": "text|select|boolean|date", ...}}
SPEC_META_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'spec_meta.json')

_meta_cache = {'mtime': None, 'data': {}}


def load_spec_meta():
    """저장된 스펙 필드 메타를 읽는다. 파일이 없거나 깨졌으면 빈 dict.

    알림·히스토리 문구 생성 중에 호출되므로 **절대 예외를 던지지 않는다** —
    여기서 터지면 협의내용 저장 자체가 실패한다.
    """
    try:
        mtime = os.path.getmtime(SPEC_META_PATH)
    except OSError:
        _meta_cache['mtime'], _meta_cache['data'] = None, {}
        return {}
    if _meta_cache['mtime'] != mtime:
        try:
            with open(SPEC_META_PATH, encoding='utf-8') as f:
                loaded = json.load(f)
            _meta_cache['data'] = loaded if isinstance(loaded, dict) else {}
        except Exception as exc:
            logger.warning('[스펙메타] 읽기 실패 — 기본 라벨 사용: %s', exc)
            _meta_cache['data'] = {}
        _meta_cache['mtime'] = mtime
    return _meta_cache['data']


def spec_field_label(key):
    """필드키 → 표시명. 관리자설정 저장값 > 기본 라벨 > 키 원문 순."""
    meta = load_spec_meta().get(key)
    if isinstance(meta, dict):
        label = (meta.get('label') or '').strip()
        if label:
            return label
    return SPEC_FIELD_LABELS.get(key, key)


def is_boolean_spec_field(key):
    """관리자설정에서 boolean 으로 지정한 필드도 예/아니오로 표기한다."""
    if key in BOOLEAN_SPEC_FIELDS:
        return True
    meta = load_spec_meta().get(key)
    return isinstance(meta, dict) and meta.get('type') == 'boolean'


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
