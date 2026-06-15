"""Mattermost API 연동 — 계정 자동 생성 + 비밀번호 동기화

ERP 로그인 시 호출되어 같은 username/password로 Mattermost 계정을 보장한다.
사용자는 ERP와 Mattermost 양쪽에 동일한 자격증명으로 접속.

REST API 사용 — Mattermost Team Edition 무료에서 동작.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

MM_URL = os.environ.get("MATTERMOST_URL", "http://127.0.0.1:8065")
MM_ADMIN_TOKEN = os.environ.get("MATTERMOST_ADMIN_TOKEN", "")
MM_DOMAIN = os.environ.get("MATTERMOST_EMAIL_DOMAIN", "mgnt.kr")
MM_DEFAULT_TEAM = os.environ.get("MATTERMOST_DEFAULT_TEAM", "magnatech")  # team URL slug


def _headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MM_ADMIN_TOKEN}",
    }


def _get_user_by_username(username: str):
    """존재하면 user dict, 없으면 None"""
    try:
        r = requests.get(
            f"{MM_URL}/api/v4/users/username/{username}",
            headers=_headers(),
            timeout=5,
        )
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        logger.exception("Mattermost get_user error for %s", username)
        return None


def _create_user(username: str, password: str, email: str, full_name: str | None,
                 position: str | None = None, department: str | None = None):
    """신규 사용자 생성. ERP의 이름·직책·부서를 MM 프로필에 반영.

    - first_name: 이름 (한글)
    - nickname: "이름 직책" (예: 김정수 차장) — 채팅 표시명
    - position: "부서 직책" (예: 영업부 차장) — 프로필 popover
    """
    try:
        name = full_name or username
        nick = f"{name} {position}".strip() if position else name
        position_field = f"{department or ''} {position or ''}".strip()
        r = requests.post(
            f"{MM_URL}/api/v4/users",
            headers=_headers(),
            json={
                "username": username,
                "password": password,
                "email": email,
                "first_name": name,
                "nickname": nick,
                "position": position_field,
            },
            timeout=5,
        )
        if r.status_code in (200, 201):
            return r.json()
        logger.warning("Mattermost create_user failed for %s: %s %s", username, r.status_code, r.text[:200])
        return None
    except Exception:
        logger.exception("Mattermost create_user error for %s", username)
        return None


def _patch_user_profile(user_id: str, full_name: str | None,
                       position: str | None, department: str | None) -> bool:
    """기존 MM 사용자의 이름/닉네임/직책을 ERP 기준으로 갱신."""
    name = full_name or ""
    if not name:
        return False
    nick = f"{name} {position}".strip() if position else name
    position_field = f"{department or ''} {position or ''}".strip()
    try:
        r = requests.put(
            f"{MM_URL}/api/v4/users/{user_id}/patch",
            headers=_headers(),
            json={"first_name": name, "nickname": nick, "position": position_field},
            timeout=5,
        )
        if r.status_code == 200:
            return True
        logger.warning("Mattermost patch_user_profile failed for %s: %s %s", user_id, r.status_code, r.text[:200])
        return False
    except Exception:
        logger.exception("Mattermost patch_user_profile error for %s", user_id)
        return False


def _update_password(user_id: str, new_password: str) -> bool:
    """관리자 권한으로 비밀번호 변경 (current_password 없이)"""
    try:
        r = requests.put(
            f"{MM_URL}/api/v4/users/{user_id}/password",
            headers=_headers(),
            json={"new_password": new_password},
            timeout=5,
        )
        if r.status_code == 200:
            return True
        logger.warning("Mattermost update_password failed for %s: %s %s", user_id, r.status_code, r.text[:200])
        return False
    except Exception:
        logger.exception("Mattermost update_password error for %s", user_id)
        return False


def _add_to_default_team(user_id: str) -> bool:
    """기본 팀에 자동 가입"""
    if not MM_DEFAULT_TEAM:
        return False
    try:
        # team id 조회
        r = requests.get(f"{MM_URL}/api/v4/teams/name/{MM_DEFAULT_TEAM}", headers=_headers(), timeout=5)
        if r.status_code != 200:
            return False
        team_id = r.json().get("id")
        # 멤버 추가
        r = requests.post(
            f"{MM_URL}/api/v4/teams/{team_id}/members",
            headers=_headers(),
            json={"team_id": team_id, "user_id": user_id},
            timeout=5,
        )
        return r.status_code in (200, 201)
    except Exception:
        logger.exception("Mattermost add_to_default_team error for %s", user_id)
        return False


def sync_password(username: str, password: str, email: str | None = None,
                  full_name: str | None = None,
                  position: str | None = None,
                  department: str | None = None) -> bool:
    """ERP 로그인 시 호출. 없으면 생성, 있으면 비번 갱신 + 이름/직책 동기화.

    실패해도 ERP 로그인은 계속되어야 하므로 절대 예외 던지지 않는다.
    """
    if not MM_ADMIN_TOKEN:
        return False

    target_email = email or f"{username}@{MM_DOMAIN}"

    user = _get_user_by_username(username)
    if user is None:
        # 신규 생성 + 기본 팀 가입
        created = _create_user(username, password, target_email, full_name,
                              position=position, department=department)
        if created:
            _add_to_default_team(created["id"])
            logger.info("Mattermost user created: %s", username)
            return True
        return False

    # 기존 사용자 → 비번 갱신 + 프로필 갱신 (직책/부서 변경 자동 반영)
    pw_ok = _update_password(user["id"], password)
    if full_name:
        _patch_user_profile(user["id"], full_name, position, department)
    return pw_ok


def deactivate_user(username: str) -> bool:
    """ERP 사용자 비활성화 시 Mattermost도 비활성화"""
    if not MM_ADMIN_TOKEN:
        return False
    user = _get_user_by_username(username)
    if not user:
        return True
    try:
        r = requests.delete(f"{MM_URL}/api/v4/users/{user['id']}", headers=_headers(), timeout=5)
        return r.status_code == 200
    except Exception:
        logger.exception("Mattermost deactivate_user error for %s", username)
        return False


_BOT_USER_ID_CACHE = {}

# 전자결재 전용 봇 토큰 (.env: MM_APPROVAL_BOT_TOKEN). 없으면 admin 계정으로 폴백.
APPROVAL_BOT_USERNAME = os.environ.get("MM_APPROVAL_BOT_USERNAME", "approval-bot")


def _approval_bot_token():
    return os.environ.get("MM_APPROVAL_BOT_TOKEN", "").strip()


def _whoami_id(token):
    """주어진 토큰 소유자의 user id (캐시)."""
    if token in _BOT_USER_ID_CACHE:
        return _BOT_USER_ID_CACHE[token]
    try:
        r = requests.get(f"{MM_URL}/api/v4/users/me",
                         headers={"Authorization": f"Bearer {token}"}, timeout=5)
        if r.status_code == 200:
            uid = r.json().get('id')
            _BOT_USER_ID_CACHE[token] = uid
            return uid
    except Exception:
        logger.exception("Mattermost whoami error")
    return None


def _get_token_owner_id():
    """admin 토큰 소유자 user id."""
    return _whoami_id(MM_ADMIN_TOKEN)


def send_dm(username: str, message: str) -> bool:
    """username 사용자에게 Mattermost 1:1 DM 발송.

    발신자: 전자결재 전용 봇(MM_APPROVAL_BOT_TOKEN). 미설정 시 admin 계정 폴백.
    direct 채널 생성(admin 토큰)은 멱등, 게시는 발신자 토큰으로 → 작성자=봇.
    실패해도 예외 없이 False 반환.
    """
    if not MM_ADMIN_TOKEN or not username:
        return False
    try:
        target = _get_user_by_username(username)
        if not target:
            return False

        bot_token = _approval_bot_token()
        sender_token = bot_token or MM_ADMIN_TOKEN
        sender_id = _whoami_id(sender_token)
        if not sender_id:
            return False

        # direct 채널 생성 (admin 토큰으로 — 멱등, 양쪽 멤버 보장)
        r = requests.post(
            f"{MM_URL}/api/v4/channels/direct",
            headers=_headers(), json=[sender_id, target['id']], timeout=5,
        )
        if r.status_code not in (200, 201):
            logger.warning("MM direct channel 생성 실패: %s %s", r.status_code, r.text[:150])
            return False
        channel_id = r.json().get('id')
        # 게시는 발신자(봇) 토큰으로 → 작성자가 봇으로 표시
        r2 = requests.post(
            f"{MM_URL}/api/v4/posts",
            headers={"Authorization": f"Bearer {sender_token}", "Content-Type": "application/json"},
            json={'channel_id': channel_id, 'message': message}, timeout=5,
        )
        return r2.status_code in (200, 201)
    except Exception:
        logger.exception("Mattermost send_dm error for %s", username)
        return False


# ────────────────────────────────────────────────────────
# 전자결재 봇 프로비저닝 (1회성 — admin 토큰 필요)
# ────────────────────────────────────────────────────────

def provision_approval_bot(display_name="전자결재", description="전자결재 알림 봇"):
    """결재 전용 봇 생성(멱등) + 기본팀 등록 + 액세스 토큰 발급.

    반환 (bot_user_id, token) / 실패 시 (None, None).
    token은 발급 시 1회만 노출되므로 호출측에서 .env에 저장해야 함.
    """
    if not MM_ADMIN_TOKEN:
        return None, None
    uname = APPROVAL_BOT_USERNAME
    bot_id = None
    # 기존 봇 조회
    try:
        r = requests.get(f"{MM_URL}/api/v4/bots?include_deleted=false&per_page=200",
                         headers=_headers(), timeout=5)
        if r.status_code == 200:
            for b in r.json():
                if b.get('username') == uname:
                    bot_id = b.get('user_id')
                    break
    except Exception:
        logger.exception("MM bots list error")
    # 없으면 생성
    if not bot_id:
        try:
            r = requests.post(f"{MM_URL}/api/v4/bots", headers=_headers(),
                              json={'username': uname, 'display_name': display_name,
                                    'description': description}, timeout=5)
            if r.status_code in (200, 201):
                bot_id = r.json().get('user_id')
            else:
                logger.warning("MM bot 생성 실패: %s %s", r.status_code, r.text[:200])
                return None, None
        except Exception:
            logger.exception("MM bot 생성 오류")
            return None, None
    # 기본 팀 등록 (멱등)
    try:
        _add_to_default_team(bot_id)
    except Exception:
        pass
    # 액세스 토큰 발급
    try:
        r = requests.post(f"{MM_URL}/api/v4/users/{bot_id}/tokens", headers=_headers(),
                          json={'description': 'ERP approval bot token'}, timeout=5)
        if r.status_code in (200, 201):
            return bot_id, r.json().get('token')
        logger.warning("MM bot 토큰 발급 실패: %s %s", r.status_code, r.text[:200])
    except Exception:
        logger.exception("MM bot 토큰 발급 오류")
    return bot_id, None
