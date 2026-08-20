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


def mm_enabled() -> bool:
    """Mattermost 봇/알림 킬스위치 (.env: MM_ENABLED).

    False면 DM·채널알림·슬래시·버튼콜백을 전부 차단한다.
    계정 생성/비밀번호 동기화(sync_password, deactivate_user)는 이 플래그의 대상이 아니다 —
    MM을 다시 켤 때 계정 상태가 어긋나지 않도록 계속 유지한다.
    매 호출 시 env를 읽으므로 값만 되돌리고 재시작하면 즉시 복구된다.
    """
    return os.environ.get("MM_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


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


def send_dm(username: str, message: str, attachments: list | None = None) -> bool:
    """username 사용자에게 Mattermost 1:1 DM 발송.

    발신자: 전자결재 전용 봇(MM_APPROVAL_BOT_TOKEN). 미설정 시 admin 계정 폴백.
    direct 채널 생성(admin 토큰)은 멱등, 게시는 발신자 토큰으로 → 작성자=봇.
    attachments: 인터랙티브 버튼(props.attachments) — 승인/반려 버튼 등. None이면 순수 텍스트.
    실패해도 예외 없이 False 반환.
    """
    if not mm_enabled():
        return False
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
        post_body: dict = {'channel_id': channel_id, 'message': message}
        if attachments:
            post_body['props'] = {'attachments': attachments}
        r2 = requests.post(
            f"{MM_URL}/api/v4/posts",
            headers={"Authorization": f"Bearer {sender_token}", "Content-Type": "application/json"},
            json=post_body, timeout=5,
        )
        return r2.status_code in (200, 201)
    except Exception:
        logger.exception("Mattermost send_dm error for %s", username)
        return False


def send_dm_with_ref(username: str, message: str, attachments: list | None = None):
    """send_dm와 동일하나 게시된 post 참조를 반환. 성공 시 {'channel_id','post_id'} / 실패 None.

    처리 시 메시지 수정(버튼 제거)을 위해 post_id가 필요한 결재 알림용.
    """
    if not mm_enabled():
        return None
    if not MM_ADMIN_TOKEN or not username:
        return None
    try:
        target = _get_user_by_username(username)
        if not target:
            return None
        bot_token = _approval_bot_token()
        sender_token = bot_token or MM_ADMIN_TOKEN
        sender_id = _whoami_id(sender_token)
        if not sender_id:
            return None
        r = requests.post(
            f"{MM_URL}/api/v4/channels/direct",
            headers=_headers(), json=[sender_id, target['id']], timeout=5,
        )
        if r.status_code not in (200, 201):
            return None
        channel_id = r.json().get('id')
        post_body: dict = {'channel_id': channel_id, 'message': message}
        if attachments:
            post_body['props'] = {'attachments': attachments}
        r2 = requests.post(
            f"{MM_URL}/api/v4/posts",
            headers={"Authorization": f"Bearer {sender_token}", "Content-Type": "application/json"},
            json=post_body, timeout=5,
        )
        if r2.status_code in (200, 201):
            return {'channel_id': channel_id, 'post_id': r2.json().get('id')}
        return None
    except Exception:
        logger.exception("Mattermost send_dm_with_ref error for %s", username)
        return None


def update_approval_post(post_id: str, message: str) -> bool:
    """결재봇이 쓴 post를 수정(버튼 제거 + 처리완료 표시). 작성자=결재봇 토큰으로 PUT.

    일반봇 토큰으로는 결재봇 글을 수정할 수 없어 403 → 반드시 작성자 토큰 사용.
    """
    if not mm_enabled():
        return False
    if not post_id:
        return False
    token = _approval_bot_token() or MM_ADMIN_TOKEN
    if not token:
        return False
    try:
        r = requests.put(
            f"{MM_URL}/api/v4/posts/{post_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={'id': post_id, 'message': message, 'props': {}}, timeout=5,
        )
        if r.status_code not in (200, 201):
            logger.warning("MM 결재 post 수정 실패: %s %s", r.status_code, r.text[:150])
        return r.status_code in (200, 201)
    except Exception:
        logger.exception("update_approval_post error")
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
