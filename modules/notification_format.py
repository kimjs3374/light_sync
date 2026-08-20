"""알림 본문 포맷 — 3개 채널(ERP 인앱 / 카카오워크 / Mattermost)이 같은 문구를 쓴다.

그동안 호출부마다 문구를 따로 만들었다. 카카오용은 줄바꿈으로 예쁘게 조립하면서
인앱용 `detail` 은 `·` 로 이어붙인 한 줄을 따로 넘기는 식이라, 같은 사건인데
채널마다 다르게 보이고 인앱 쪽은 읽기 어려웠다.

이제 호출부는 **본문 하나만** 만들어 넘기고, 채널별 장식(제목 강조·링크·이모지)은
notification_engine 이 붙인다.

표기 규칙
    라벨: 값          ← 콜론 앞 공백 없음, 뒤 한 칸
    · 항목            ← 목록은 가운뎃점 + 한 칸
    이전 → 이후       ← 변경은 화살표
    빈 줄             ← 문단 구분은 한 줄만 (연속 빈 줄은 자동 정리)

값이 비면 그 줄은 통째로 빼야 '담당: -' 같은 빈 줄이 안 쌓인다.
"""
import re

# 과거 알림 메시지 끝에 dedupe 키가 그대로 붙어 나갔다 (' [dk:overdue-4080]').
# 지금은 안 붙이지만 남아 있는 알림이 있어 표시할 때 걷어낸다.
_LEGACY_DEDUPE_RE = re.compile(r'\s*\[dk:[^\]]*\]\s*$')

BULLET = '·'
ARROW = '→'

# body() 안에서 "여기서 문단을 나눈다"는 뜻으로 쓰는 표식.
# 빈 문자열은 '값이 없어서 버릴 줄'과 구분되지 않아 별도 상수를 둔다.
BLANK = '\x00blank'


def kv(label, value, blank=None):
    """`라벨: 값` 한 줄. 값이 비면 None (호출부에서 그대로 버려진다).

    blank 를 주면 빈 값도 그 문구로 표시한다 (예: kv('담당', name, blank='미배정')).
    """
    if value is None or value == '':
        if blank is None:
            return None
        value = blank
    return f"{label}: {value}"


def change(label, old, new, blank='미입력'):
    """`라벨: 이전 → 이후`. 새로 채운 값이면 화살표 없이 값만 보여준다."""
    old_txt = '' if old is None else str(old)
    new_txt = blank if new in (None, '') else str(new)
    if not old_txt:
        return f"{label}: {new_txt}"
    return f"{label}: {old_txt} {ARROW} {new_txt}"


def bullet(text):
    """목록 한 줄."""
    return f"{BULLET} {text}" if text else None


def bullets(items, limit=None, more_label='건'):
    """목록 여러 줄. limit 을 넘으면 `· 외 N건` 으로 접는다."""
    items = [i for i in items if i]
    if limit is not None and len(items) > limit:
        rest = len(items) - limit
        return [bullet(i) for i in items[:limit]] + [f"{BULLET} 외 {rest}{more_label}"]
    return [bullet(i) for i in items]


def body(*parts):
    """본문 조립 — 빈 값 제거 + 연속 빈 줄 정리.

    parts 는 문자열, 여러 줄 문자열, 문자열 리스트를 섞어 넘길 수 있다.

    - 값이 없어 None/'' 로 들어온 조각은 통째로 버린다 (kv() 가 그렇게 돌려준다)
    - 여러 줄 문자열 안의 빈 줄은 의도한 문단 구분으로 보고 살린다
    - 조각과 조각 사이에 빈 줄을 넣고 싶으면 BLANK 를 끼운다
    - 어느 경우든 빈 줄이 두 줄 이상 겹치거나 앞뒤에 남지는 않는다
    """
    lines = []
    for part in parts:
        if part is None:
            continue
        chunk = part if isinstance(part, (list, tuple)) else [part]
        for piece in chunk:
            if piece is None:
                continue
            text = str(piece)
            if text == '' or text.isspace():
                continue                      # 값이 비어 버릴 조각
            if text == BLANK:
                lines.append(BLANK)
                continue
            for line in text.split('\n'):
                line = line.rstrip()
                if line.endswith(':'):
                    continue          # 값이 비어 라벨만 남은 줄
                lines.append(line if line else BLANK)

    out = []
    for line in lines:
        if line == BLANK:
            if not out or out[-1] == '':
                continue                      # 앞머리·연속 빈 줄 방지
            out.append('')
        else:
            out.append(line)
    while out and out[-1] == '':
        out.pop()
    return '\n'.join(out)


def preview(text, limit=80):
    """목록·패널에 한 줄로 줄여 보여줄 미리보기.

    여러 줄 본문의 첫 줄만 쓴다. 첫 줄이 짧으면 다음 줄을 ` · ` 로 이어 붙여
    한 줄 안에서 최대한 정보를 보여준다.
    """
    text = clean(text)
    if not text:
        return ''
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if not lines:
        return ''
    out = lines[0].lstrip(BULLET).strip()
    for extra in lines[1:]:
        extra = extra.lstrip(BULLET).strip()
        if len(out) + len(extra) + 3 > limit:
            break
        out = f"{out} · {extra}"
    return out if len(out) <= limit else out[:limit - 1].rstrip() + '…'


def clean(text):
    """표시 직전 정리 — 과거에 새어 나간 내부 키 제거."""
    if not text:
        return ''
    return _LEGACY_DEDUPE_RE.sub('', str(text)).strip()


def qty(value):
    """수량 표기 — LED는 EA 단위 정수 (소수점 노출 금지)."""
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return str(value or 0)


def money(value):
    """금액 표기 — 원 단위 정수 + 천단위 콤마."""
    try:
        return f"{int(round(float(value))):,}원"
    except (TypeError, ValueError):
        return str(value or 0)
