#!/usr/bin/env python3
"""Light-Sync ERP 메일 신착 알림 데몬.

5분 폴링으로 각 활성 mail_account 의 INBOX 를 점검,
last_seen_uid 초과 신규 메일을 headless claude 로 요약 → MM DM 전송.

대상 사용자:
  - 개인계정 (is_shared=False): mail_accounts.user_id 의 MM DM
  - 공용계정 (is_shared=True) : mail_shared_access 에 등록된 사용자 전원 의 MM DM

첫 기동(또는 처음 보는 account) 폭주 방지:
  - mail_notify_state row 가 없으면 현재 INBOX max UID 로 워터마크 초기화
  - 과거 메일 재요약 금지

요약 실패 fallback:
  - claude --print 실패/타임아웃이어도 알림 자체는 발송
  - 본문 자리에 "(요약 실패)" 표시, 발신/제목/시각/링크는 유지

ENV (대부분 .env 자동 로드):
  DATABASE_URL, DB_SCHEMA=light_sync
  MM_BASE_URL, MM_BOT_TOKEN, MM_BOT_USER_ID
  MAIL_NOTIFY_POLL_SEC (default 300)
  MAIL_NOTIFY_CLAUDE_BIN (default /home/magnatech/.local/bin/claude)
  MAIL_NOTIFY_TIMEOUT_MS (default 60000)
  MAIL_NOTIFY_DRY_RUN=1   → DM 발송 없이 stdout 출력만 (테스트용)
  MAIL_NOTIFY_ONCE=1      → 한 번만 폴링하고 종료 (테스트용)
  MAIL_NOTIFY_MAX_PER_RUN (default 5) → 계정당 폴링 1회에 처리할 신규 메일 상한
  ERP_BASE_URL (default https://work.mgnt.kr) — 메일함 deep link 베이스
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Iterable, Optional

# ── ERP 경로 + DB 로드 ─────────────────────────────────────────────────
ROOT = "/web/light_sync"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
os.environ.setdefault("DB_SCHEMA", "light_sync")

from light_sync_mcp.db import get_session  # noqa: E402
from modules.models.entities import User  # noqa: E402
from modules.models.mail_entities import (  # noqa: E402
    MailAccount,
    MailSharedAccess,
    MailNotifyState,
)
from modules.services.mail_client import MailClient, decrypt_password  # noqa: E402

# ── Config ─────────────────────────────────────────────────────────────
MM_BASE_URL = os.environ.get("MM_BASE_URL", "https://team.mgnt.kr").rstrip("/")
# 메일 알림은 업무봇(`a.i`)이 아닌 별도 봇 계정(`mail_notify_bot`)으로 발송한다.
# MAIL_NOTIFY_MM_BOT_TOKEN / _USER_ID 가 설정돼 있으면 그쪽을 우선 사용,
# 미설정 시 호환성을 위해 기존 MM_BOT_* 로 폴백.
MM_BOT_TOKEN = (
    os.environ.get("MAIL_NOTIFY_MM_BOT_TOKEN")
    or os.environ.get("MM_BOT_TOKEN", "")
)
MM_BOT_USER_ID = (
    os.environ.get("MAIL_NOTIFY_MM_BOT_USER_ID")
    or os.environ.get("MM_BOT_USER_ID", "")
)
ERP_BASE_URL = os.environ.get("ERP_BASE_URL", "https://work.mgnt.kr").rstrip("/")

POLL_SEC = int(os.environ.get("MAIL_NOTIFY_POLL_SEC", "300"))
CLAUDE_BIN = os.environ.get(
    "MAIL_NOTIFY_CLAUDE_BIN", "/home/magnatech/.local/bin/claude"
)
SUMMARY_PROMPT = os.environ.get(
    "MAIL_NOTIFY_SUMMARY_PROMPT",
    "/web/light_sync/light_sync_mmbot/system-prompt-mail-summary.md",
)
HEADLESS_MCP_CFG = os.environ.get(
    "MAIL_NOTIFY_MCP_CFG",
    "/web/light_sync/light_sync_mmbot/mcp-headless.json",
)
TIMEOUT_MS = int(os.environ.get("MAIL_NOTIFY_TIMEOUT_MS", "60000"))
DRY_RUN = os.environ.get("MAIL_NOTIFY_DRY_RUN") == "1"
ONCE = os.environ.get("MAIL_NOTIFY_ONCE") == "1"
MAX_PER_RUN = int(os.environ.get("MAIL_NOTIFY_MAX_PER_RUN", "5"))

logging.basicConfig(
    format="%(asctime)s [mail-notifier] %(levelname)s %(message)s",
    level=logging.INFO,
    stream=sys.stderr,
)
log = logging.getLogger("mail-notifier")

if not MM_BOT_TOKEN or not MM_BOT_USER_ID:
    log.error("MAIL_NOTIFY_MM_BOT_TOKEN / MM_BOT_TOKEN 미설정")
    sys.exit(2)
log.info(
    f"using MM bot user_id={MM_BOT_USER_ID} "
    f"(separated={bool(os.environ.get('MAIL_NOTIFY_MM_BOT_TOKEN'))})"
)


# ── Mattermost REST helpers ────────────────────────────────────────────
def _mm_request(method: str, path: str, body=None) -> tuple[int, str]:
    url = f"{MM_BASE_URL}{path}"
    data = None
    headers = {"Authorization": f"Bearer {MM_BOT_TOKEN}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


_mm_user_cache: dict[str, Optional[str]] = {}
_dm_channel_cache: dict[str, Optional[str]] = {}


def mm_resolve_user_id(username: str) -> Optional[str]:
    """MM username → user_id. 캐시. 실패 시 None."""
    if not username:
        return None
    if username in _mm_user_cache:
        return _mm_user_cache[username]
    code, body = _mm_request(
        "GET", f"/api/v4/users/username/{urllib.parse.quote(username)}"
    )
    if code != 200:
        log.warning(f"MM user lookup 실패 username={username} code={code}")
        _mm_user_cache[username] = None
        return None
    try:
        uid = json.loads(body).get("id")
    except Exception:
        uid = None
    _mm_user_cache[username] = uid
    return uid


def mm_dm_channel(user_id: str) -> Optional[str]:
    """봇 ↔ user_id DM 채널 보장 후 channel_id 반환."""
    if not user_id:
        return None
    if user_id in _dm_channel_cache:
        return _dm_channel_cache[user_id]
    code, body = _mm_request(
        "POST", "/api/v4/channels/direct", [MM_BOT_USER_ID, user_id]
    )
    if code not in (200, 201):
        log.warning(f"MM DM 생성 실패 user_id={user_id} code={code} body={body[:120]}")
        _dm_channel_cache[user_id] = None
        return None
    try:
        cid = json.loads(body).get("id")
    except Exception:
        cid = None
    _dm_channel_cache[user_id] = cid
    return cid


def mm_post_message(channel_id: str, message: str) -> bool:
    code, body = _mm_request(
        "POST",
        "/api/v4/posts",
        {"channel_id": channel_id, "message": message},
    )
    if code not in (200, 201):
        log.warning(f"MM post 실패 channel={channel_id} code={code} body={body[:120]}")
        return False
    return True


# ── 메일 본문 요약 (headless claude) ───────────────────────────────────
def summarize_mail(meta: dict, body_excerpt: str) -> Optional[str]:
    """claude --print 헤드리스 호출. 실패 시 None."""
    prompt_lines = [
        f"[from] {meta.get('from_name', '')} <{meta.get('from_email', '')}>",
        f"[subject] {meta.get('subject', '')}",
        f"[date] {meta.get('date', '')}",
        "[body]",
        (body_excerpt or "(본문 없음)").strip()[:4000],
    ]
    prompt = "\n".join(prompt_lines)
    args = [
        CLAUDE_BIN,
        "--print",
        "--model", "haiku",
        "--mcp-config", HEADLESS_MCP_CFG,
        "--strict-mcp-config",
        "--system-prompt-file", SUMMARY_PROMPT,
        "--dangerously-skip-permissions",
        prompt,
    ]
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_MS / 1000.0,
            env={**os.environ, "CLAUDECODE": "1"},
        )
    except subprocess.TimeoutExpired:
        log.warning(f"summarize timeout uid={meta.get('uid')}")
        return None
    except Exception as e:
        log.warning(f"summarize spawn 실패 uid={meta.get('uid')}: {e!s:.120}")
        return None
    if result.returncode != 0:
        log.warning(
            f"summarize rc={result.returncode} stderr={result.stderr[:200]!r}"
        )
        return None
    text = (result.stdout or "").strip()
    if not text:
        return None
    return text[:800]  # 안전 상한


# ── 알림 메시지 빌드 + 분배 ────────────────────────────────────────────
def _erp_mail_link(account_id: int, uid: int) -> str:
    return f"{ERP_BASE_URL}/mail?account_id={account_id}&uid={uid}"


def build_notification_text(
    account: MailAccount,
    meta: dict,
    summary: Optional[str],
) -> str:
    account_label = account.email or account.username or f"계정#{account.id}"
    if account.is_shared:
        account_label = f"공용 {account_label}"
    from_disp = meta.get("from_name") or meta.get("from_email") or "(발신자 미상)"
    if meta.get("from_name") and meta.get("from_email"):
        from_disp = f"{meta['from_name']} <{meta['from_email']}>"
    subj = meta.get("subject") or "(제목 없음)"
    date_disp = meta.get("date") or ""
    link = _erp_mail_link(account.id, meta.get("uid") or 0)
    body = summary.strip() if summary else "_(요약 실패 — 원문 확인 필요)_"
    return (
        f"📧 **[{account_label}]** {from_disp}\n"
        f"**{subj}**  ·  {date_disp}\n"
        f"{body}\n"
        f"🔗 {link}"
    )


def resolve_recipients(session, account: MailAccount) -> list[User]:
    """계정 → 알림 받을 User 목록."""
    if not account.is_shared:
        # 개인계정: owner 1명
        if account.user_id:
            u = session.get(User, account.user_id)
            return [u] if u and u.is_active else []
        return []
    # 공용계정: mail_shared_access row 가 있는 모든 활성 user (read 권한 기준)
    rows = (
        session.query(MailSharedAccess)
        .filter(MailSharedAccess.mail_account_id == account.id)
        .all()
    )
    users = []
    for r in rows:
        u = session.get(User, r.user_id)
        if u and u.is_active:
            users.append(u)
    return users


def distribute_notification(session, account: MailAccount, text: str) -> int:
    """대상 user 들에게 DM 발송. 발송 성공 건수 반환."""
    recipients = resolve_recipients(session, account)
    if not recipients:
        log.info(
            f"account#{account.id} ({account.email}): 알림 대상 0명 — skip"
        )
        return 0
    sent = 0
    # 라이브 폴링에서도 분배 가시성 확보 — 각 user 단위로 post 직전 INFO 로그.
    log.info(
        f"account#{account.id} ({account.email}) 알림 분배 대상 "
        f"{len(recipients)}명: {[u.username for u in recipients]}"
    )
    for user in recipients:
        if DRY_RUN:
            log.info(
                f"[DRY] account#{account.id} → @{user.username} ({user.full_name})"
            )
            sent += 1
            continue
        uid = mm_resolve_user_id(user.username)
        if not uid:
            log.warning(
                f"account#{account.id} → @{user.username}: MM 사용자 매칭 실패"
            )
            continue
        channel = mm_dm_channel(uid)
        if not channel:
            continue
        log.info(
            f"account#{account.id} → @{user.username} ({user.full_name}) DM={channel} 전송 시도"
        )
        if mm_post_message(channel, text):
            sent += 1
            log.info(
                f"account#{account.id} → @{user.username} 발송 성공"
            )
    return sent


# ── IMAP 폴링 ──────────────────────────────────────────────────────────
def _parse_envelope_addr_short(env_addr) -> tuple[str, str]:
    """ENVELOPE from_ → (name, email)."""
    if not env_addr:
        return "", ""
    a = env_addr[0]
    try:
        name_raw = a.name.decode("utf-8", errors="replace") if a.name else ""
        # encoded-word 디코드
        from email.header import decode_header, make_header
        try:
            name = str(make_header(decode_header(name_raw)))
        except Exception:
            name = name_raw
    except Exception:
        name = ""
    try:
        mailbox = (a.mailbox or b"").decode("utf-8", errors="replace")
        host = (a.host or b"").decode("utf-8", errors="replace")
        email = f"{mailbox}@{host}" if mailbox and host else ""
    except Exception:
        email = ""
    return name, email


def _decode_subject(env_subj) -> str:
    if not env_subj:
        return ""
    if isinstance(env_subj, bytes):
        raw = env_subj.decode("utf-8", errors="replace")
    else:
        raw = str(env_subj)
    from email.header import decode_header, make_header
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def _extract_text_body(imap, uid: int, limit: int = 4000) -> str:
    """BODY.PEEK[TEXT] 가져와서 평문 추출."""
    try:
        raw = imap.fetch([uid], ["BODY.PEEK[TEXT]"])
    except Exception:
        return ""
    if uid not in raw:
        return ""
    body = raw[uid].get(b"BODY[TEXT]") or b""
    if not body:
        return ""
    # email 모듈로 multipart 디코드 시도 — TEXT 만 가져왔으니 plain best-effort
    text = body.decode("utf-8", errors="replace")
    return text[:limit]


def _initialize_watermark(imap, folder: str = "INBOX") -> tuple[int, int]:
    """folder select 후 (max_uid, uidvalidity) 반환. 비어있으면 (0, uidvalidity)."""
    info = imap.select_folder(folder, readonly=True)
    uidvalidity = int(info.get(b"UIDVALIDITY", 0) or 0)
    try:
        all_uids = imap.search(["ALL"])
    except Exception:
        all_uids = []
    max_uid = max(all_uids) if all_uids else 0
    return max_uid, uidvalidity


def _search_new_uids(imap, last_uid: int, folder: str = "INBOX") -> list[int]:
    """(last_uid, *] 신규 UID 정렬 리스트.

    IMAPClient.search 는 criteria 를 토큰 리스트로 받으므로
    ['UID', '7:*'] 형태가 정답이다 ('UID 7:*' 한 문자열로 주면 BAD).
    """
    imap.select_folder(folder, readonly=True)
    try:
        uids = imap.search(["UID", f"{last_uid + 1}:*"])
    except Exception as e:
        log.warning(f"UID search 실패: {e!s:.120}")
        return []
    # IMAP 'X:*' 에서 X 이상이 없어도 max UID 1건이 돌아오는 서버가 있어
    # 한 번 더 last_uid 보다 큰 것만 필터.
    return sorted(u for u in uids if u > last_uid)


def _fetch_envelope(imap, uid: int) -> Optional[dict]:
    try:
        raw = imap.fetch([uid], ["ENVELOPE"])
    except Exception:
        return None
    if uid not in raw:
        return None
    env = raw[uid].get(b"ENVELOPE")
    if not env:
        return None
    name, email_addr = _parse_envelope_addr_short(env.from_)
    return {
        "uid": uid,
        "from_name": name,
        "from_email": email_addr,
        "subject": _decode_subject(env.subject),
        "date": env.date.isoformat() if env.date else "",
    }


# ── 메인 폴링 사이클 ───────────────────────────────────────────────────
def ensure_state(session, account: MailAccount) -> MailNotifyState:
    st = session.get(MailNotifyState, account.id)
    if st:
        return st
    st = MailNotifyState(account_id=account.id, last_seen_uid=0, is_enabled=True)
    session.add(st)
    session.commit()
    return st


def poll_account(session, account: MailAccount) -> dict:
    """계정 1개 폴링 결과 dict (count_new, count_sent, error)."""
    out = {"account_id": account.id, "email": account.email, "count_new": 0, "count_sent": 0, "error": None}
    st = ensure_state(session, account)
    if not st.is_enabled:
        return out

    try:
        password = decrypt_password(account.password_encrypted)
    except Exception as e:
        out["error"] = f"비번 복호화 실패: {e!s:.80}"
        st.last_error = out["error"]
        st.last_polled_at = datetime.datetime.now()
        session.commit()
        return out

    client = MailClient(
        imap_host=account.imap_host, imap_port=account.imap_port,
        smtp_host=account.smtp_host, smtp_port=account.smtp_port,
        username=account.username, password=password,
        use_ssl=account.use_ssl,
    )

    try:
        with client as c:
            # 워터마크 초기화 — 부트스트랩 여부를 last_seen_uid 0 로 판단하면
            # "빈 메일함의 정상 상태" 와 "초기화 안 됨" 이 같은 값(0)을 갖게 되어,
            # 빈 메일함에 도착한 *첫 진짜 메일*을 다시 부트스트랩 분기에 흡수시켜
            # 알림 없이 워터마크만 전진시키는 버그가 난다.
            # → 부트스트랩 신호는 `last_polled_at is None` 또는 `uid_validity is None`
            #   (한 번이라도 정상 폴링이 끝났다면 둘 다 채워져 있다).
            max_uid, uidv = _initialize_watermark(c._imap)
            is_bootstrap = (st.last_polled_at is None) or (st.uid_validity is None)
            is_uidv_changed = bool(
                st.uid_validity and uidv and st.uid_validity != uidv
            )
            if is_bootstrap or is_uidv_changed:
                reason = "최초 기동" if is_bootstrap else "UIDVALIDITY 변경"
                log.info(
                    f"account#{account.id} ({account.email}) 워터마크 초기화({reason}): "
                    f"last_uid {st.last_seen_uid}→{max_uid}, uidv {st.uid_validity}→{uidv}"
                )
                st.last_seen_uid = max_uid
                st.uid_validity = uidv
                st.last_polled_at = datetime.datetime.now()
                st.last_error = None
                session.commit()
                return out

            new_uids = _search_new_uids(c._imap, st.last_seen_uid)
            out["count_new"] = len(new_uids)
            if not new_uids:
                st.last_polled_at = datetime.datetime.now()
                st.last_error = None
                if uidv and st.uid_validity != uidv:
                    st.uid_validity = uidv
                session.commit()
                return out

            # 상한
            process_uids = new_uids[:MAX_PER_RUN]
            if len(new_uids) > MAX_PER_RUN:
                log.info(
                    f"account#{account.id}: 신규 {len(new_uids)}건 중 {MAX_PER_RUN}건 처리, 나머지는 다음 사이클"
                )

            for uid in process_uids:
                meta = _fetch_envelope(c._imap, uid)
                if not meta:
                    log.warning(f"account#{account.id} uid={uid} ENVELOPE fetch 실패")
                    # 워터마크는 전진시켜 같은 uid 무한 재시도 방지
                    st.last_seen_uid = max(st.last_seen_uid, uid)
                    continue

                body_excerpt = _extract_text_body(c._imap, uid)
                summary = summarize_mail(meta, body_excerpt)

                text = build_notification_text(account, meta, summary)
                sent = distribute_notification(session, account, text)
                out["count_sent"] += sent

                st.last_seen_uid = max(st.last_seen_uid, uid)
                st.notify_count = (st.notify_count or 0) + 1
                session.commit()

            # 처리 안 한 잔여는 다음 cycle에서 자연 진행
            if process_uids:
                # 잔여 가장 큰 uid 까지 워터마크 일관성 유지: 처리한 마지막 uid 까지만 전진
                pass

            st.last_polled_at = datetime.datetime.now()
            st.last_error = None
            if uidv:
                st.uid_validity = uidv
            session.commit()

    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e!s:.120}"
        log.warning(f"account#{account.id} ({account.email}) 폴링 실패: {out['error']}")
        try:
            st.last_error = out["error"]
            st.last_polled_at = datetime.datetime.now()
            session.commit()
        except Exception:
            session.rollback()

    return out


def poll_all_once() -> dict:
    session = get_session()
    summary = {"accounts": 0, "new_total": 0, "sent_total": 0, "errors": 0}
    try:
        accounts = (
            session.query(MailAccount).filter(MailAccount.is_active.is_(True)).all()
        )
        summary["accounts"] = len(accounts)
        for a in accounts:
            r = poll_account(session, a)
            summary["new_total"] += r["count_new"]
            summary["sent_total"] += r["count_sent"]
            if r["error"]:
                summary["errors"] += 1
    finally:
        session.close()
    return summary


def main():
    log.info(
        f"start: poll={POLL_SEC}s dry_run={DRY_RUN} once={ONCE} max_per_run={MAX_PER_RUN}"
    )
    while True:
        t0 = time.time()
        try:
            s = poll_all_once()
            log.info(
                f"cycle done: accounts={s['accounts']} new={s['new_total']} "
                f"sent={s['sent_total']} errors={s['errors']} elapsed={time.time()-t0:.1f}s"
            )
        except Exception as e:
            log.exception(f"cycle 실패: {e!s:.120}")
        if ONCE:
            return
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
