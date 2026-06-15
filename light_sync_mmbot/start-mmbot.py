#!/usr/bin/env python3
"""Light-Sync Mattermost 봇 Claude Code 세션 런처.

- .env에서 MM_BOT_TOKEN 등 읽음
- mcp-mmbot.json을 임시파일로 복제하면서 env에 토큰 주입 (template + secret)
- Claude Code TUI 2단계(bypass, dev-channel) 자동 승인 후 포그라운드 유지
"""
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

import pexpect
from dotenv import load_dotenv

ROOT = Path("/web/light_sync")
TEMPLATE = ROOT / "light_sync_mmbot" / "mcp-mmbot.json"
SYSTEM_PROMPT = ROOT / "light_sync_mmbot" / "system-prompt.md"
CLAUDE = "/home/magnatech/.local/bin/claude"
BASE_PORT = 8788  # worker 1 → 8789, worker 2 → 8790 ...


def build_mcp_config(worker_id: int, port: int) -> str:
    """토큰 + worker별 port 주입한 임시 MCP config 파일 경로 반환."""
    load_dotenv(ROOT / ".env")

    token = os.environ.get("MM_BOT_TOKEN", "").strip()
    user_id = os.environ.get("MM_BOT_USER_ID", "").strip()
    base_url = os.environ.get("MM_BASE_URL", "https://team.mgnt.kr").strip()
    if not token:
        sys.stderr.write("[mmbot-launcher] FATAL: MM_BOT_TOKEN missing in .env\n")
        sys.exit(2)
    if not user_id:
        sys.stderr.write("[mmbot-launcher] FATAL: MM_BOT_USER_ID missing in .env\n")
        sys.exit(2)

    cfg = json.loads(TEMPLATE.read_text())
    server_env = cfg["mcpServers"]["lightsync-erp-mmbot"].setdefault("env", {})
    server_env["MM_BOT_TOKEN"] = token
    server_env["MM_BOT_USER_ID"] = user_id
    server_env["MM_BASE_URL"] = base_url
    server_env["MMBOT_PORT"] = str(port)
    server_env["MMBOT_WORKER_ID"] = str(worker_id)
    # HEADLESS 우회 활성화 (dev-channel inject 우회). 끄려면 .env 에 MMBOT_USE_HEADLESS=0
    server_env["MMBOT_USE_HEADLESS"] = os.environ.get("MMBOT_USE_HEADLESS", "1")

    fd, path = tempfile.mkstemp(prefix=f"mcp-mmbot-w{worker_id}-", suffix=".json")
    with os.fdopen(fd, "w") as fp:
        json.dump(cfg, fp)
    os.chmod(path, 0o600)
    sys.stderr.write(f"[mmbot-launcher] worker={worker_id} port={port} mcp config: {path}\n")
    return path


def select_down_enter(child, label):
    child.send("\x1b[B")
    time.sleep(0.3)
    child.send("\r")
    sys.stderr.write(f"[mmbot-launcher] {label}: selected option 2\n")
    sys.stderr.flush()


def main():
    os.chdir(ROOT)
    # argv[1] = worker_id (1, 2, 3, ...). 생략 시 1.
    try:
        worker_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    except ValueError:
        sys.stderr.write(f"[mmbot-launcher] FATAL: worker_id must be int, got {sys.argv[1]!r}\n")
        sys.exit(2)
    if worker_id < 1:
        sys.stderr.write("[mmbot-launcher] FATAL: worker_id must be >= 1\n")
        sys.exit(2)
    port = BASE_PORT + worker_id
    cfg_path = build_mcp_config(worker_id, port)

    args = [
        "--dangerously-skip-permissions",
        "--dangerously-load-development-channels",
        "server:lightsync-erp-mmbot",
        "--mcp-config", cfg_path,
        "--strict-mcp-config",
        "--model", "haiku",
        "--effort", "low",
        "--system-prompt-file", str(SYSTEM_PROMPT),
    ]
    sys.stderr.write(f"[mmbot-launcher] spawn: {CLAUDE} {' '.join(args)}\n")
    sys.stderr.flush()

    child = pexpect.spawn(
        CLAUDE, args, encoding="utf-8", timeout=30, dimensions=(24, 120)
    )
    child.logfile_read = sys.stderr

    # 1단계: Bypass Permissions 경고
    try:
        child.expect(r"No,\s*exit", timeout=15)
        select_down_enter(child, "bypass-permissions")
    except (pexpect.TIMEOUT, pexpect.EOF):
        sys.stderr.write("[mmbot-launcher] bypass prompt not found (skipped)\n")

    # 2단계: Development Channel 경고
    try:
        child.expect(r"local development|Exit", timeout=15)
        time.sleep(0.3)
        child.send("\r")
        sys.stderr.write("[mmbot-launcher] dev-channel: confirmed\n")
        sys.stderr.flush()
    except (pexpect.TIMEOUT, pexpect.EOF):
        sys.stderr.write("[mmbot-launcher] dev-channel prompt not found (skipped)\n")

    def forward_signal(signum, frame):
        try:
            child.kill(signum)
        except Exception:
            pass
        try:
            os.unlink(cfg_path)
        except Exception:
            pass

    signal.signal(signal.SIGTERM, forward_signal)
    signal.signal(signal.SIGINT, forward_signal)

    sys.stderr.write("[mmbot-launcher] Claude Code mmbot session running\n")
    sys.stderr.flush()

    try:
        child.expect(pexpect.EOF, timeout=None)
    except Exception:
        pass
    child.close()
    try:
        os.unlink(cfg_path)
    except Exception:
        pass
    sys.exit(child.exitstatus or 0)


if __name__ == "__main__":
    main()
