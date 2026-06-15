"""Mattermost 알림 어댑터.

notification_engine.notify() → _send_mattermost() 호출 시 동작.
Incoming Webhook 방식. 채널별 URL을 .env에서 읽어 이벤트→채널 라우팅.

환경변수:
    MM_WEBHOOK_DEFAULT       — 매칭 안 된 이벤트의 fallback 채널 URL (필수)
    MM_WEBHOOK_SALES         — ~영업 채널 (선택)
    MM_WEBHOOK_PRODUCTION    — ~생산 채널 (선택)
    MM_WEBHOOK_MANAGEMENT    — ~관리 채널 (선택)
    MM_WEBHOOK_AS            — ~AS 채널 (선택)

채널 매핑(EVENT_CHANNEL_MAP)이 없거나 환경변수가 비면 default로 폴백.
"""
from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────
# 이벤트 → 채널 라우팅 매트릭스
#   값은 환경변수 키. .env에서 URL 읽음. 빈 값/없으면 default fallback.
# ────────────────────────────────────────────────────────
EVENT_CHANNEL_MAP: Dict[str, str] = {
    # 계약/영업
    'contract.created':       'MM_WEBHOOK_SALES',
    'issue.flagged':          'MM_WEBHOOK_SALES',

    # 납품/생산
    'delivery.scheduled':     'MM_WEBHOOK_PRODUCTION',
    'delivery.due_d7':        'MM_WEBHOOK_PRODUCTION',
    'delivery.due_d1':        'MM_WEBHOOK_PRODUCTION',
    'delivery.overdue':       'MM_WEBHOOK_PRODUCTION',
    'delivery.completed':     'MM_WEBHOOK_PRODUCTION',
    'production.item_complete': 'MM_WEBHOOK_PRODUCTION',
    'production.site_complete': 'MM_WEBHOOK_PRODUCTION',
    'material.received':      'MM_WEBHOOK_PRODUCTION',
    'material.overdue':       'MM_WEBHOOK_PRODUCTION',
    'processing.completed':   'MM_WEBHOOK_PRODUCTION',
    'inventory.low_stock':    'MM_WEBHOOK_PRODUCTION',

    # 관리
    'document.deadline_d7':   'MM_WEBHOOK_MANAGEMENT',
    'tax_invoice.issued':     'MM_WEBHOOK_MANAGEMENT',
    'billing.completed':      'MM_WEBHOOK_MANAGEMENT',
    'billing.reverted':       'MM_WEBHOOK_MANAGEMENT',
    'cert.expiring':          'MM_WEBHOOK_MANAGEMENT',

    # AS
    'warranty.expiring':      'MM_WEBHOOK_AS',

    # 공통 (모두)
    'daily.digest':           'MM_WEBHOOK_DEFAULT',
    'trip.created':           'MM_WEBHOOK_DEFAULT',
}


def _resolve_webhook_url(event_type: str) -> Optional[str]:
    env_key = EVENT_CHANNEL_MAP.get(event_type, 'MM_WEBHOOK_DEFAULT')
    url = os.environ.get(env_key, '').strip()
    if url:
        return url
    # fallback
    fallback = os.environ.get('MM_WEBHOOK_DEFAULT', '').strip()
    return fallback or None


def _build_payload(title: str, message: str, link: Optional[str], emoji: str) -> Dict[str, Any]:
    """Mattermost incoming webhook payload.

    링크가 있으면 attachment에 actions 대신 본문 끝에 마크다운 링크로 추가.
    굳이 attachment 안 쓰고 message 한 줄로 간단히.
    """
    base_url = os.environ.get('SERVER_BASE_URL', '').rstrip('/')
    text_parts = [f"{emoji} **{title}**"]
    if message:
        text_parts.append(message)
    if link and base_url:
        text_parts.append(f"→ [ERP에서 보기]({base_url}{link})")
    elif link:
        text_parts.append(f"→ ERP: `{link}`")
    return {
        "text": "\n".join(text_parts),
        "username": "ERP 알림",
        "icon_emoji": ":robot_face:",
    }


def _emoji_for(event_type: str) -> str:
    """이벤트 타입별 emoji prefix"""
    prefix = event_type.split('.', 1)[0]
    return {
        'contract':       '📋',
        'delivery':       '🚚',
        'production':     '🏭',
        'material':       '📦',
        'inventory':      '📊',
        'processing':     '⚙️',
        'document':       '📄',
        'tax_invoice':    '💰',
        'billing':        '💳',
        'warranty':       '🛡️',
        'cert':           '📜',
        'daily':          '📅',
        'trip':           '✈️',
        'issue':          '⚠️',
    }.get(prefix, '🔔')


def send_mattermost_notification(
    event_type: str,
    title: str,
    message: str,
    link: Optional[str] = None,
    *,
    text_override: Optional[str] = None,
    timeout: float = 5.0,
) -> bool:
    """Mattermost 채널에 알림 push.

    Returns:
        성공 시 True. URL 미설정/네트워크 오류 시 False (예외 발생 안 함).
    """
    url = _resolve_webhook_url(event_type)
    if not url:
        logger.debug("[mm-noti] webhook URL 없음 — skip: %s", event_type)
        return False

    if text_override:
        payload = {
            "text": text_override,
            "username": "ERP 알림",
            "icon_emoji": ":robot_face:",
        }
    else:
        emoji = _emoji_for(event_type)
        payload = _build_payload(title, message, link, emoji)

    try:
        r = requests.post(url, json=payload, timeout=timeout)
        if r.status_code >= 400:
            logger.error("[mm-noti] %s → %s (status=%d body=%s)",
                         event_type, url[:60], r.status_code, r.text[:200])
            return False
        return True
    except requests.RequestException as e:
        logger.warning("[mm-noti] %s post 실패: %s", event_type, e)
        return False
