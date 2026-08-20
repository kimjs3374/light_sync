"""
메일 발송량 급증 감시.

2026-08-12 오픈릴레이 사고(사흘간 약 105,600건 스팸 발송)가 아무에게도 감지되지
않은 채 거래처 반송메일로 뒤늦게 발견된 것을 계기로 추가.

스팸은 ERP를 거치지 않으므로 EmailHistory 로는 잡을 수 없다. postfix 컨테이너
로그의 실제 발송(status=sent) 건수를 직접 센다.

기준치 (2026-08-12 실측):
  - 정상일 10분 최대   : 22건
  - 공격일 10분 최대   : 2,086건
  약 100배 차이라 임계 100건이면 오탐 없이 1분 내 감지된다.
"""

import os
import re
import time
import logging
import subprocess
from collections import Counter

logger = logging.getLogger(__name__)

POSTFIX_CONTAINER = os.environ.get('POSTFIX_CONTAINER', 'mailcowdockerized-postfix-mailcow-1')
WINDOW_MINUTES = int(os.environ.get('MAIL_VOLUME_WINDOW_MIN', '10'))
THRESHOLD = int(os.environ.get('MAIL_VOLUME_THRESHOLD', '100'))
# 같은 사고로 반복 알림이 쏟아지지 않게 억제하는 간격
ALERT_COOLDOWN_SEC = int(os.environ.get('MAIL_VOLUME_COOLDOWN_SEC', '3600'))
# 그룹방이 아니라 담당자 개인 DM으로 보낸다 (2026-08-12 지시)
ALERT_TO_NAME = os.environ.get('MAIL_VOLUME_ALERT_TO', '김정수')
STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'logs', '.mail_volume_alert_state')

_RE_TO_DOMAIN = re.compile(r'to=<[^>]+@([^>]+)>')
_RE_FROM = re.compile(r'from=<([^>]*)>')
# 발신자는 status=sent 줄이 아니라 qmgr 줄에 있어 큐ID로 이어붙여야 한다
_RE_QID = re.compile(r'\]: ([0-9A-F]{6,}): ')


def _read_postfix_log(minutes):
    """postfix 컨테이너 로그에서 최근 N분치를 읽는다."""
    try:
        out = subprocess.run(
            ['docker', 'logs', POSTFIX_CONTAINER, '--since', f'{minutes}m'],
            capture_output=True, text=True, timeout=120,
        )
        return (out.stdout or '') + (out.stderr or '')
    except FileNotFoundError:
        logger.error('[메일감시] docker 명령을 찾을 수 없음 — 감시 불가')
    except subprocess.TimeoutExpired:
        logger.error('[메일감시] docker logs 타임아웃 (로그 과대 가능성)')
    except Exception as e:
        logger.error('[메일감시] 로그 조회 실패: %s', e)
    return ''


def _last_alert_at():
    try:
        with open(STATE_FILE) as f:
            return float(f.read().strip())
    except Exception:
        return 0.0


def _mark_alerted():
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            f.write(str(time.time()))
    except Exception as e:
        logger.warning('[메일감시] 상태파일 기록 실패: %s', e)


def collect_stats(minutes=None):
    """최근 N분간 발송 통계를 모은다."""
    minutes = minutes or WINDOW_MINUTES
    raw = _read_postfix_log(minutes)

    sent_lines, rejects = [], 0
    qid_from = {}
    for line in raw.splitlines():
        if 'status=sent' in line:
            sent_lines.append(line)
            continue
        if 'Client host rejected' in line:
            rejects += 1
            continue
        # qmgr 줄에서 큐ID → 발신자 매핑을 모아둔다
        if 'from=<' in line:
            mq, mf = _RE_QID.search(line), _RE_FROM.search(line)
            if mq and mf and mf.group(1):
                qid_from.setdefault(mq.group(1), mf.group(1))

    # 내부 배달(dovecot LMTP)은 외부 발송이 아니므로 제외
    outbound = [l for l in sent_lines if 'relay=dovecot' not in l]

    domains = Counter()
    senders = Counter()
    for line in outbound:
        m = _RE_TO_DOMAIN.search(line)
        if m:
            domains[m.group(1)] += 1
        mq = _RE_QID.search(line)
        if mq and mq.group(1) in qid_from:
            senders[qid_from[mq.group(1)]] += 1

    return {
        'window_minutes': minutes,
        'outbound': len(outbound),
        'internal': len(sent_lines) - len(outbound),
        'rejects': rejects,
        'top_domains': domains.most_common(5),
        'top_senders': senders.most_common(5),
    }


def build_alert_text(stats):
    """카카오워크로 보낼 알림 문구를 만든다."""
    lines = [
        '[ERP 보안] 메일 발송량 급증 감지',
        '',
        f"최근 {stats['window_minutes']}분간 외부 발송 {stats['outbound']:,}건 "
        f"(임계 {THRESHOLD:,}건)",
    ]
    if stats['rejects']:
        lines.append(f"인증 없는 릴레이 시도 차단 {stats['rejects']:,}건")
    if stats['top_domains']:
        lines.append('')
        lines.append('수신 도메인 상위')
        for d, c in stats['top_domains']:
            lines.append(f'  {d} {c:,}건')
    if stats['top_senders']:
        lines.append('')
        lines.append('발신 계정 상위')
        for s, c in stats['top_senders']:
            lines.append(f'  {s} {c:,}건')
    lines.append('')
    lines.append('평상시 10분 최대는 22건입니다. 모르는 발신 계정이나 '
                 '해외 수신 도메인이 보이면 즉시 확인이 필요합니다.')
    return '\n'.join(lines)


def run_volume_check(dry_run=False, force=False):
    """발송량을 확인하고 임계 초과 시 알림을 보낸다.

    Returns: dict — 통계 + alerted/skipped 여부
    """
    stats = collect_stats()
    exceeded = stats['outbound'] >= THRESHOLD
    result = {**stats, 'threshold': THRESHOLD, 'exceeded': exceeded,
              'alerted': False, 'suppressed': False}

    if not exceeded and not force:
        return result

    elapsed = time.time() - _last_alert_at()
    if elapsed < ALERT_COOLDOWN_SEC and not force:
        result['suppressed'] = True
        logger.info('[메일감시] 임계 초과(%d건)이나 %d분 전 알림 발송으로 억제',
                    stats['outbound'], int(elapsed / 60))
        return result

    text = build_alert_text(stats)
    logger.warning('[메일감시] 발송량 급증: 최근 %d분 %d건 (임계 %d)',
                   stats['window_minutes'], stats['outbound'], THRESHOLD)

    if dry_run:
        result['text'] = text
        return result

    try:
        from modules.kakaowork_notifier import find_user_id, send_dm_text
        uid = find_user_id(ALERT_TO_NAME)
        if uid:
            result['alerted'] = bool(send_dm_text(uid, text))
        else:
            logger.error('[메일감시] 알림 대상 %r 카카오워크 계정을 찾지 못함', ALERT_TO_NAME)
    except Exception as e:
        logger.error('[메일감시] 알림 발송 실패: %s', e)

    if result['alerted']:
        _mark_alerted()
    result['text'] = text
    return result
