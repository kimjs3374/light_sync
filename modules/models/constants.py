# G2B 조달 기준 상세품목 (나라장터 세부품명 기준 통일)
DETAIL_ITEM_OPTIONS = [
    "LED투광등기구",
    "LED가로등기구",
    "LED보안등기구",
    "LED터널용등기구",
    "스포츠조명기구",
    "조명타워",
    "철제가로등주",
    "스테인리스가로등주",
    "가로등주부속자재",
    "LED경관조명기구",
    "태양광가로등",
]

# 생산팀 카테고리 매핑
PRODUCTION_TEAM1_CATEGORIES = {
    "철제가로등주", "스테인리스가로등주", "조명타워", "가로등주부속자재", "태양광가로등",
}
PRODUCTION_TEAM2_CATEGORIES = {
    "LED투광등기구", "LED가로등기구", "LED보안등기구", "LED터널용등기구", "스포츠조명기구", "LED경관조명기구",
}
PRODUCTION_TEAM_MAP = {
    'team1': PRODUCTION_TEAM1_CATEGORIES,
    'team2': PRODUCTION_TEAM2_CATEGORIES,
}

# 바코드 입력 허용 대상 (조명기구 계열)
LIGHTING_DETAIL_ITEMS = {
    "LED투광등기구",
    "LED가로등기구",
    "LED보안등기구",
    "LED터널용등기구",
    "스포츠조명기구",
    "LED경관조명기구",
    "태양광가로등",
}


# 계약 품목별 동적 입력 스키마 (JSON 저장 기준)
CONTRACT_ITEM_SPEC_SCHEMA = {
    "LED투광등기구": {
        "required": ["lens_angle", "spacing_distance", "body_type", "has_stabilizer_box"],
        "conditional_required": {
            "has_stabilizer_box": {
                "equals": True,
                "fields": ["stabilizer_vendor_contact", "stabilizer_address", "smps_shipment_schedule"]
            }
        }
    },
    "스포츠조명기구": {
        "required": ["lens_angle", "spacing_distance", "body_type", "has_stabilizer_box"],
        "conditional_required": {
            "has_stabilizer_box": {
                "equals": True,
                "fields": ["stabilizer_vendor_contact", "stabilizer_address", "smps_shipment_schedule"]
            }
        }
    },
    "LED가로등기구": {
        "required": ["spacing_distance", "is_integrated"],
    },
    "LED보안등기구": {
        "required": ["spacing_distance", "is_integrated"],
    },
    "LED터널용등기구": {
        "required": ["spacing_distance", "is_integrated"],
    },
    "조명타워": {
        "required": ["tower_height", "lamp_count"],
    },
    "철제가로등주": {
        "required": ["replace_or_new", "anchor_spacing", "arm_type", "is_painted"],
        "conditional_required": {
            "is_painted": {
                "equals": True,
                "fields": ["paint_color"]
            }
        }
    },
    "스테인리스가로등주": {
        "required": ["replace_or_new", "anchor_spacing", "arm_type", "stainless_finish_type"],
        "conditional_required": {
            "stainless_finish_type": {
                "equals": "도장",
                "fields": ["paint_color"]
            }
        }
    },
}

# 기존 ERP 레거시 명칭 → 조달 기준 명칭 변환
DETAIL_ITEM_ALIASES = {
    # 레거시 ERP 명칭
    "💡 조명기구": "LED투광등기구",
    "🗼 조명타워": "조명타워",
    "📦 기타부속": "가로등주부속자재",
    "조명기구": "LED투광등기구",
    "투광등기구": "LED투광등기구",
    "가로등기구": "LED가로등기구",
    "보안등기구": "LED보안등기구",
    "터널등기구": "LED터널용등기구",
    "LED경관조명": "LED경관조명기구",
    "경관조명": "LED경관조명기구",
    "스텐가로등주": "스테인리스가로등주",
    "철제가로등주(보안등주)": "철제가로등주",
    "스텐가로등주(보안등주)": "스테인리스가로등주",
    "타워": "조명타워",
    "미분류": "LED투광등기구",
    # G2B 세부품명 (이미 정규명칭이지만 안전하게)
    "LED투광등기구": "LED투광등기구",
    "LED가로등기구": "LED가로등기구",
    "LED보안등기구": "LED보안등기구",
    "LED터널용등기구": "LED터널용등기구",
    "LED터널등기구": "LED터널용등기구",
    "스테인리스가로등주": "스테인리스가로등주",
    "가로등주부속자재": "가로등주부속자재",
    "LED경관조명기구": "LED경관조명기구",
    "스포츠조명기구": "스포츠조명기구",
    "도로표지병": "가로등주부속자재",
}


# 관리 리스트 공통 우선순위 기준
# - 모든 관리 리스트 페이지에서 동일한 임계값을 참조하도록 글로벌 상수로 관리한다.
GLOBAL_PRIORITY_SETTINGS = {
    "shared": {
        "due_warning_days": 7,
        "due_caution_days": 14,
    },
    "project": {
        "due_warning_days": 7,
    },
    "contract": {
        "due_warning_days": 7,
    },
    "sales": {
        "due_warning_days": 7,
    },
    "material": {
        "due_warning_days": 7,
    },
    "production": {
        "due_warning_days": 7,
    },
    "delivery": {
        "due_warning_days": 7,
    },
}


PRIORITY_BADGE_STYLES = {
    "manual_top": {"label": "수동최우선", "css_class": "bg-danger"},
    "urgent": {"label": "긴급", "css_class": "bg-danger"},
    "overdue": {"label": "지연", "css_class": "bg-danger"},
    "due_soon": {"label": "일정임박", "css_class": "bg-warning text-dark"},
    "inspection": {"label": "전문검수", "css_class": "bg-info text-dark"},
    "sales_pending": {"label": "협의미완료", "css_class": "bg-secondary"},
    "material_pending": {"label": "자재확인필요", "css_class": "bg-primary"},
    "production_warning": {"label": "생산경고", "css_class": "bg-danger"},
    "delivery_today": {"label": "금일회차", "css_class": "bg-warning text-dark"},
    "delivery_unassigned": {"label": "담당자미배정", "css_class": "bg-dark"},
}


# ─── 워크플로우 상태 스텝 ──────────────────────────
SALES_STATUS_STEPS = ['계약확인', '상세협의중', '협의완료']

# 도면 필요 품목 (가공발주 대상)
DRAWING_REQUIRED_ITEMS = [
    '조명타워',
    '철제가로등주', '철제가로등주(보안등주)',
    '스텐가로등주', '스텐가로등주(보안등주)',
]
ADMIN_STATUS_STEPS = ['자재확인중', '발주진행중', '발주완료', '입고진행중', '입고완료']
PROD_STATUS_STEPS = ['자재대기중', '생산대기중', '생산중', '생산완료']
