"""Mailcow API 연동 — 계정 생성/비밀번호 동기화"""

import logging
import os

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

MAILCOW_URL = os.environ.get("MAILCOW_URL", "https://127.0.0.1:8443")
MAILCOW_API_KEY = os.environ.get("MAILCOW_API_KEY", "")
MAILCOW_DOMAIN = os.environ.get("MAILCOW_DOMAIN", "mgnt.kr")


def _headers():
    return {"Content-Type": "application/json", "X-API-Key": MAILCOW_API_KEY}


def _is_shared_mailbox(email: str) -> bool:
    """mail_accounts 에 공유계정(is_shared)으로 등록된 주소인지.

    조회 실패 시 True 를 돌려 **막는 쪽으로** 판단한다 — 공유 메일함 비밀번호가
    덮어써지는 사고보다 개인 동기화가 한 번 걸러지는 편이 훨씬 낫다.
    """
    try:
        from sqlalchemy import text
        from modules.db_context import get_db
        with get_db() as db:
            row = db.execute(text(
                "SELECT 1 FROM light_sync.mail_accounts "
                "WHERE lower(email) = lower(:e) AND is_shared IS TRUE LIMIT 1"
            ), {"e": email}).first()
            return row is not None
    except Exception:
        logger.exception("공유 메일함 판정 실패 — 안전하게 동기화를 건너뜁니다: %s", email)
        return True


def sync_password(username: str, password: str) -> bool:
    """ERP 로그인 시 Mailcow 비밀번호를 동기화한다.

    ★ 공유 업무메일함은 절대 건드리지 않는다.
    ERP username 이 공유 메일함 주소와 겹치면(예: 대표이사 계정 username='magna' ↔
    업무메일 magna@mgnt.kr) 그 사람이 로그인할 때마다 공유 메일함 비밀번호가
    개인 ERP 비밀번호로 덮어써져, 그 메일함을 함께 쓰는 사람들의 IMAP 로그인이 전부 깨진다.
    """
    if not MAILCOW_API_KEY:
        return False
    email = f"{username}@{MAILCOW_DOMAIN}"
    if _is_shared_mailbox(email):
        logger.warning(
            "Mailcow 비밀번호 동기화 차단 — %s 는 공유 업무메일함입니다 (ERP 사용자: %s)",
            email, username,
        )
        return False
    try:
        r = requests.post(
            f"{MAILCOW_URL}/api/v1/edit/mailbox",
            headers=_headers(),
            json={"items": [email], "attr": {"password": password, "password2": password}},
            verify=False,
            timeout=5,
        )
        result = r.json()
        if isinstance(result, list) and result and result[0].get("type") == "success":
            return True
        logger.warning("Mailcow sync_password failed for %s: %s", email, result)
        return False
    except Exception:
        logger.exception("Mailcow sync_password error for %s", email)
        return False


def create_mailbox(username: str, full_name: str, password: str, quota: int = 3072) -> bool:
    """신규 사용자 승인 시 Mailcow 메일박스를 생성한다."""
    if not MAILCOW_API_KEY:
        return False
    try:
        r = requests.post(
            f"{MAILCOW_URL}/api/v1/add/mailbox",
            headers=_headers(),
            json={
                "local_part": username,
                "domain": MAILCOW_DOMAIN,
                "name": full_name or username,
                "password": password,
                "password2": password,
                "quota": str(quota),
                "active": "1",
            },
            verify=False,
            timeout=5,
        )
        result = r.json()
        if isinstance(result, list) and result and result[-1].get("type") == "success":
            return True
        logger.warning("Mailcow create_mailbox failed for %s: %s", username, result)
        return False
    except Exception:
        logger.exception("Mailcow create_mailbox error for %s", username)
        return False


def deactivate_mailbox(username: str) -> bool:
    """사용자 비활성화 시 Mailcow 메일박스도 비활성화한다."""
    if not MAILCOW_API_KEY:
        return False
    email = f"{username}@{MAILCOW_DOMAIN}"
    try:
        r = requests.post(
            f"{MAILCOW_URL}/api/v1/edit/mailbox",
            headers=_headers(),
            json={"items": [email], "attr": {"active": "0"}},
            verify=False,
            timeout=5,
        )
        result = r.json()
        if isinstance(result, list) and result and result[0].get("type") == "success":
            return True
        return False
    except Exception:
        logger.exception("Mailcow deactivate_mailbox error for %s", email)
        return False
