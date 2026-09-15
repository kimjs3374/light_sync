"""메일 자동분류 엔진 — 규칙 기반 폴더 이동 / 라벨 부여."""

import json
import re
import logging

logger = logging.getLogger(__name__)


def match_condition(cond: dict, mail: dict) -> bool:
    """단일 조건 매칭."""
    field = cond.get('field', '')
    op = cond.get('op', 'contains')
    value = cond.get('value', '').lower()

    # 메일에서 대상 값 추출
    if field == 'from_email':
        target = (mail.get('from_email') or '').lower()
    elif field == 'from_domain':
        email = mail.get('from_email') or ''
        target = email.split('@')[-1].lower() if '@' in email else ''
    elif field == 'from_name':
        target = (mail.get('from_name') or '').lower()
    elif field == 'to_email':
        target = (mail.get('to_email') or '').lower()
    elif field == 'subject':
        target = (mail.get('subject') or '').lower()
    elif field == 'has_attachment':
        has = bool(mail.get('has_attachment'))
        return (value == 'true') == has
    else:
        return False

    if op == 'equals':
        return target == value
    elif op == 'contains':
        return value in target
    elif op == 'starts_with':
        return target.startswith(value)
    elif op == 'ends_with':
        return target.endswith(value)
    elif op == 'not_contains':
        return value not in target
    elif op == 'regex':
        try:
            return bool(re.search(value, target, re.IGNORECASE))
        except re.error:
            return False
    return False


def match_rule(rule_conditions: list, logic: str, mail: dict) -> bool:
    """규칙의 전체 조건 매칭 (AND/OR)."""
    if not rule_conditions:
        return False
    results = [match_condition(c, mail) for c in rule_conditions]
    if logic == 'OR':
        return any(results)
    return all(results)


def classify_mail(rules: list, mail: dict) -> list:
    """메일에 매칭되는 규칙 찾기. 반환: [{'action_type', 'action_value'}, ...]"""
    actions = []
    for rule in rules:
        if not rule.get('is_active', True):
            continue
        conditions = json.loads(rule.get('conditions_json', '[]'))
        logic = rule.get('condition_logic', 'AND')
        if match_rule(conditions, logic, mail):
            actions.append({
                'rule_id': rule['id'],
                'rule_name': rule['name'],
                'action_type': rule['action_type'],
                'action_value': rule['action_value'],
            })
            if rule.get('stop_processing', True):
                break
    return actions


def apply_actions(client, uid: int, folder: str, actions: list) -> list:
    """IMAP 클라이언트로 액션 실행. 반환: 실행 결과 로그."""
    results = []
    for action in actions:
        atype = action['action_type']
        avalue = action.get('action_value', '')
        try:
            if atype == 'move_folder':
                if avalue and avalue != folder:
                    client.move_messages([uid], avalue, src_folder=folder)
                    results.append(f"[{action['rule_name']}] → 폴더 이동: {avalue}")
            elif atype == 'mark_read':
                client.set_flags([uid], '\\Seen', action='add', folder=folder)
                results.append(f"[{action['rule_name']}] → 읽음 표시")
            elif atype == 'delete':
                client.move_messages([uid], 'Trash', src_folder=folder)
                results.append(f"[{action['rule_name']}] → 삭제 (휴지통)")
            elif atype == 'add_label':
                keyword = f"label_{avalue}"
                client.set_flags([uid], keyword, action='add', folder=folder)
                results.append(f"[{action['rule_name']}] → 라벨: {avalue}")
        except Exception as e:
            results.append(f"[{action['rule_name']}] 실패: {e}")
            logger.exception("자동분류 액션 실패: rule=%s uid=%s", action['rule_name'], uid)
    return results

# ---------------------------------------------------------------------------
# 수신차단 / 수신허용 (스팸)
# ---------------------------------------------------------------------------

def normalize_block_value(value: str) -> str:
    """차단·허용 목록에 넣을 값 다듬기.

    'KIM@X.co.kr' → 'kim@x.co.kr', '@X.co.kr' → 'x.co.kr', 'X.co.kr' → 'x.co.kr'.
    도메인을 '@' 붙은 채로도, 안 붙은 채로도 적기 때문에 한 모양으로 맞춰 둔다 —
    안 맞추면 같은 도메인이 두 줄로 쌓이고 한 줄만 먹는다.
    """
    v = (value or '').strip().lower()
    if v.startswith('@'):
        v = v[1:]
    return v


def spam_verdict(entries, from_email: str):
    """보낸사람에 대한 판정. 'allow' | 'block' | None.

    **허용이 차단을 이긴다.** 도메인 단위로 막아 두고 그 안의 거래처 한 곳만
    받는 것이 실제로 제일 흔한 쓰임인데, 차단이 이기면 그게 불가능해진다.
    """
    addr = (from_email or '').strip().lower()
    if not addr:
        return None
    domain = addr.split('@')[-1]

    def hit(value):
        v = normalize_block_value(value)
        if not v:
            return False
        if '@' in v:
            return addr == v
        return domain == v or domain.endswith('.' + v)

    if any(hit(e.get('value')) for e in entries if e.get('kind') == 'allow'):
        return 'allow'
    if any(hit(e.get('value')) for e in entries if e.get('kind') == 'block'):
        return 'block'
    return None
