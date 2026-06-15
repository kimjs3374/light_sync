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


def sync_password(username: str, password: str) -> bool:
    """ERP 로그인 시 Mailcow 비밀번호를 동기화한다."""
    if not MAILCOW_API_KEY:
        return False
    email = f"{username}@{MAILCOW_DOMAIN}"
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
