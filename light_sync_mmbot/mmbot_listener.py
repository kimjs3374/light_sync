#!/usr/bin/env python3
"""Mattermost WebSocket listener for Light-Sync ERP bot.

Connects to Mattermost WS, listens for `posted` events, filters mentions/DMs
targeting the bot, then forwards to mmbot.mjs HTTP (:8789) which triggers the
Claude Code MCP session.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import sys
import uuid
from typing import Any

import httpx
import websockets

# ── Config ───────────────────────────────────────────────────────────
MM_BASE_URL = os.environ.get("MM_BASE_URL", "https://team.mgnt.kr")
MM_WS_URL = MM_BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/v4/websocket"
MM_BOT_TOKEN = os.environ.get("MM_BOT_TOKEN", "")
MM_BOT_USER_ID = os.environ.get("MM_BOT_USER_ID", "")
# 워커풀: 콤마 구분 포트 목록. 기본 8789(워커1) ~ 8791(워커3).
_ports = [p.strip() for p in os.environ.get("MMBOT_WORKER_PORTS", "8789,8790,8791").split(",") if p.strip()]
WORKER_URLS = [f"http://127.0.0.1:{p}" for p in _ports]

# 채널별 페르소나 매트릭스 (channel name → persona)
# PoC: 매핑 없으면 default("ERP 비서", all tools)
PERSONAS: dict[str, dict[str, str]] = {
    # "영업": {"name": "영업 페르소나", "allowed_tools": "projects,contracts,quotations,revenue"},
    # "생산": {"name": "생산 페르소나", "allowed_tools": "production,material_orders,receiving,processing_orders"},
    # "관리": {"name": "관리 페르소나", "allowed_tools": "tax_invoices,unpaid_invoices,billing_status"},
}

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [mmbot-listener] %(levelname)s %(message)s",
    level=logging.INFO,
    stream=sys.stderr,
)
log = logging.getLogger("mmbot-listener")

if not MM_BOT_TOKEN:
    log.error("MM_BOT_TOKEN not set")
    sys.exit(1)
if not MM_BOT_USER_ID:
    log.error("MM_BOT_USER_ID not set")
    sys.exit(1)
if not WORKER_URLS:
    log.error("MMBOT_WORKER_PORTS empty — at least one worker required")
    sys.exit(1)
log.info(f"worker pool: {WORKER_URLS}")


# ── Channel info cache (id → {name, type}) ───────────────────────────
_channel_cache: dict[str, dict[str, str]] = {}


async def fetch_channel_info(client: httpx.AsyncClient, channel_id: str) -> dict[str, str]:
    if channel_id in _channel_cache:
        return _channel_cache[channel_id]
    try:
        r = await client.get(
            f"{MM_BASE_URL}/api/v4/channels/{channel_id}",
            headers={"Authorization": f"Bearer {MM_BOT_TOKEN}"},
            timeout=5.0,
        )
        r.raise_for_status()
        info = r.json()
        result = {
            "name": info.get("display_name") or info.get("name") or channel_id,
            "type": info.get("type", "O"),
        }
        _channel_cache[channel_id] = result
        return result
    except Exception as e:
        log.warning(f"channel info fetch failed {channel_id}: {e}")
        return {"name": channel_id, "type": "O"}


def is_addressed_to_bot(event_data: dict[str, Any], post: dict[str, Any]) -> bool:
    """봇에게 보낸 메시지인지 판단.

    - DM (channel_type == "D"): 봇이 참여한 DM이면 모두 응답
    - 채널: mentions에 봇 user_id 포함 시
    """
    channel_type = event_data.get("channel_type", "")
    if channel_type == "D":
        # 단, 봇 자신이 보낸 메시지는 무시
        return post.get("user_id") != MM_BOT_USER_ID
    mentions_raw = event_data.get("mentions", "[]")
    try:
        mentions = json.loads(mentions_raw) if isinstance(mentions_raw, str) else mentions_raw
    except Exception:
        mentions = []
    return MM_BOT_USER_ID in (mentions or [])


def strip_mention(text: str, bot_username: str = "erp_1") -> str:
    """`@erp_1 ...` 접두사 제거."""
    needle = f"@{bot_username}"
    if text.startswith(needle):
        return text[len(needle):].lstrip()
    return text


# 워커 round-robin 분산기 (동시 3-5명 처리)
_worker_cycle = itertools.cycle(WORKER_URLS)
_dispatch_lock = asyncio.Lock()


async def pick_worker() -> str:
    async with _dispatch_lock:
        return next(_worker_cycle)


async def forward_to_mmbot(client: httpx.AsyncClient, payload: dict[str, Any]) -> None:
    """워커풀 중 하나에 dispatch. 실패 시 다음 워커로 폴백."""
    candidates = list(WORKER_URLS)
    primary = await pick_worker()
    # primary 우선 + 실패 시 나머지 시도
    order = [primary] + [u for u in candidates if u != primary]
    for url in order:
        try:
            r = await client.post(url, json=payload, timeout=10.0)
            if r.status_code >= 400:
                log.error(f"worker {url} returned {r.status_code}: {r.text[:200]}")
                continue
            log.info(f"forwarded {payload['request_id']} → {url}")
            return
        except Exception as e:
            log.warning(f"worker {url} unreachable: {e}, fallback")
    log.error(f"all workers failed for request_id={payload['request_id']}")


async def handle_posted_event(client: httpx.AsyncClient, event: dict[str, Any]) -> None:
    data = event.get("data", {})
    broadcast = event.get("broadcast", {})

    post_raw = data.get("post")
    if not post_raw:
        return
    try:
        post = json.loads(post_raw) if isinstance(post_raw, str) else post_raw
    except Exception as e:
        log.warning(f"post parse failed: {e}")
        return

    # 봇 자신의 메시지는 무시
    if post.get("user_id") == MM_BOT_USER_ID:
        return

    # 시스템 메시지 무시
    if post.get("type"):
        return

    if not is_addressed_to_bot(data, post):
        return

    channel_id = post.get("channel_id") or broadcast.get("channel_id")
    if not channel_id:
        return

    channel_info = await fetch_channel_info(client, channel_id)
    channel_name = channel_info["name"]
    channel_type = channel_info["type"]

    # 페르소나 매핑 (DM은 default)
    persona = PERSONAS.get(channel_name) if channel_type != "D" else None

    text = strip_mention(post.get("message", "").strip())
    # MM 첨부파일 — post.file_ids 추출 (이메일 첨부 등 후속 도구가 사용)
    mm_file_ids = list(post.get("file_ids") or [])
    # 첨부만 있고 텍스트가 비어있어도 처리 (예: "이거 보내" 의도)
    if not text and not mm_file_ids:
        return

    request_id = uuid.uuid4().hex[:12]
    payload = {
        "request_id": request_id,
        "user": data.get("sender_name", "").lstrip("@") or post.get("user_id", ""),
        "channel_id": channel_id,
        "channel_name": channel_name,
        "channel_type": channel_type,
        "post_id": post.get("id", ""),
        "root_id": post.get("root_id", "") or post.get("id", ""),
        "text": text,
        "mm_file_ids": mm_file_ids,
        "allowed_tools": persona["allowed_tools"] if persona else "",
        "persona_name": persona["name"] if persona else "",
    }
    log.info(
        f"dispatch ch={channel_name} ({channel_type}) user={payload['user']}: {text[:60]}"
    )
    await forward_to_mmbot(client, payload)


async def ws_loop() -> None:
    seq = 1
    backoff = 2
    while True:
        try:
            log.info(f"connecting to {MM_WS_URL}")
            async with websockets.connect(MM_WS_URL, max_size=2**22) as ws:
                # 인증
                await ws.send(
                    json.dumps(
                        {
                            "seq": seq,
                            "action": "authentication_challenge",
                            "data": {"token": MM_BOT_TOKEN},
                        }
                    )
                )
                seq += 1
                log.info("authentication_challenge sent")
                backoff = 2
                async with httpx.AsyncClient() as client:
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        event_type = msg.get("event")
                        if event_type == "posted":
                            await handle_posted_event(client, msg)
                        elif event_type == "hello":
                            log.info(f"hello received: server={msg.get('data', {}).get('server_version', '?')}")
        except websockets.ConnectionClosed as e:
            log.warning(f"WS closed: {e}, reconnect in {backoff}s")
        except Exception as e:
            log.error(f"WS error: {e}, reconnect in {backoff}s")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)


def main() -> None:
    try:
        asyncio.run(ws_loop())
    except KeyboardInterrupt:
        log.info("stopped by user")


if __name__ == "__main__":
    main()
