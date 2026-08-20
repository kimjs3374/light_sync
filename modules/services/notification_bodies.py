"""여러 화면에서 같은 사건을 알릴 때 쓰는 본문 조립기.

출장 등록처럼 PC 폼 / 모바일 API / Mattermost 액션 세 군데서 같은 알림을 쏘는
경우가 있다. 그동안 각자 문구를 만들어 한 곳만 고치면 나머지가 어긋났다.
여기 한 곳에서만 만든다.

본문은 notification_format 규칙(`라벨: 값`, `· 항목`)을 따른다.
"""
from modules import notification_format as nf


def model_label(category, model_name, limit=40):
    """알림용 모델 표기.

    조달 원문이 그대로 들어와 `LED투광등기구, 매그나텍, ARENA(M)-600, 600W` 처럼
    콤마로 나열된다. 카테고리는 대개 앞에 중복되고, 콤마가 품목 구분자와 섞여
    여러 품목을 이어붙이면 어디까지가 한 품목인지 알 수 없다.
    → 카테고리를 떼고 콤마를 공백으로 바꿔 `매그나텍 ARENA(M)-600 600W` 로.
    """
    cat = (category or '').strip()
    model = (model_name or '').strip()
    if cat and model.startswith(cat):
        model = model[len(cat):].lstrip(' ,/·-')
    text = ' '.join(p.strip() for p in model.split(',') if p.strip()) or cat
    return text if len(text) <= limit else text[:limit - 1] + '…'


def trip_created(trip, member_labels, creator_label=None):
    """출장 등록 알림 본문.

    member_labels: '영업부 김선중 대리' 같은 표기 목록 (한국식 부서-이름-직급).
    """
    def when(dt):
        return dt.strftime('%Y-%m-%d %H:%M') if dt else None

    dep = when(getattr(trip, 'departure_date', None))
    ret = when(getattr(trip, 'return_date', None))
    members = ', '.join(m for m in (member_labels or []) if m)

    # 목적지는 알림 제목에 이미 들어가므로 본문에서는 출장명을 보여준다
    trip_title = getattr(trip, 'title', None)
    if trip_title and trip_title == getattr(trip, 'destination', None):
        trip_title = None

    return nf.body(
        nf.kv('출장명', trip_title),
        nf.kv('출발', dep),
        nf.kv('귀환', ret, blank='미정'),
        nf.kv('차량', getattr(trip, 'vehicle', None)),
        nf.kv('인원', members),
        nf.kv('등록', creator_label),
    )


def delivery_split_scheduled(split_no, quantity, scheduled, current_user):
    """납품 회차 등록 알림 본문."""
    return nf.body(
        nf.kv('회차', f"{split_no}차 {nf.qty(quantity)}EA"),
        nf.kv('납품예정일', scheduled),
        nf.kv('등록', current_user),
    )


def qty_change_lines(changes):
    """변경계약 수량반영 목록 — `· 모델 20 → 52EA` 로 한 품목씩.

    changes: [{'label': 표시명, 'old': 20, 'new': 52}, ...]
    """
    return nf.bullets([
        f"{c['label']} {nf.qty(c['old'])} {nf.ARROW} {nf.qty(c['new'])}EA"
        for c in changes if c.get('label')
    ])
