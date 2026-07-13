#!/usr/bin/env python3
"""Light-Sync Channel 전용 Claude Code 세션 런처 (멀티워커).

argv[1] = worker_id (1, 2, 3, ...). 생략 시 1.
worker별로 CHANNEL_PORT = BASE_PORT + worker_id (worker1 → 8789, worker2 → 8790 ...).
mcp-channel.json을 템플릿으로 임시 config를 만들며 CHANNEL_PORT를 주입한다.

두 개의 TUI 경고 화면을 자동 수락 후 Claude Code를 포그라운드로 유지한다.
1) Bypass Permissions 경고 → "Yes, I accept"
2) Development Channel 경고 → "I am using this for local development"
"""
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

import pexpect

ROOT = Path("/web/light_sync")
CLAUDE = "/home/magnatech/.local/bin/claude"
TEMPLATE = ROOT / "light_sync_channel" / "mcp-channel.json"
SYSTEM_PROMPT = ROOT / "light_sync_channel" / "system-prompt.md"
BASE_PORT = 8800  # worker 1 → 8801, worker 2 → 8802 ... (mmbot 8789~8791 회피)


def build_mcp_config(worker_id: int, port: int) -> str:
    """worker별 CHANNEL_PORT를 주입한 임시 MCP config 파일 경로 반환."""
    cfg = json.loads(TEMPLATE.read_text())
    server_env = cfg["mcpServers"]["lightsync-erp-chat"].setdefault("env", {})
    server_env["CHANNEL_PORT"] = str(port)
    # FLASK_PORT는 템플릿 값 유지 (없으면 8501)
    server_env.setdefault("FLASK_PORT", "8501")

    fd, path = tempfile.mkstemp(prefix=f"mcp-channel-w{worker_id}-", suffix=".json")
    with os.fdopen(fd, "w") as fp:
        json.dump(cfg, fp)
    os.chmod(path, 0o600)
    sys.stderr.write(f"[channel-launcher] worker={worker_id} port={port} mcp config: {path}\n")
    sys.stderr.flush()
    return path


def select_down_enter(child, label):
    """TUI 메뉴에서 아래 화살표 + Enter로 두 번째 옵션 선택."""
    child.send("\x1b[B")  # Down arrow
    time.sleep(0.3)
    child.send("\r")      # Enter
    sys.stderr.write(f"[channel-launcher] {label}: selected option 2\n")
    sys.stderr.flush()


def main():
    os.chdir("/web/light_sync")
    # argv[1] = worker_id (1, 2, 3, ...). 생략 시 1.
    try:
        worker_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    except ValueError:
        sys.stderr.write(f"[channel-launcher] FATAL: worker_id must be int, got {sys.argv[1]!r}\n")
        sys.exit(2)
    if worker_id < 1:
        sys.stderr.write("[channel-launcher] FATAL: worker_id must be >= 1\n")
        sys.exit(2)

    port = BASE_PORT + worker_id
    os.environ.setdefault("FLASK_PORT", "8501")
    cfg_path = build_mcp_config(worker_id, port)

    args = [
        "--dangerously-skip-permissions",
        "--dangerously-load-development-channels",
        "server:lightsync-erp-chat",
        "--mcp-config", cfg_path,
        "--strict-mcp-config",
        "--model", "sonnet",
        "--effort", "low",
        "--system-prompt-file", str(SYSTEM_PROMPT),
    ]

    child = pexpect.spawn(CLAUDE, args, encoding="utf-8", timeout=30,
                          dimensions=(24, 120))
    child.logfile_read = sys.stderr

    # 1단계: Bypass Permissions 경고 → "Yes, I accept"
    try:
        child.expect(r"No,\s*exit", timeout=15)
        select_down_enter(child, "bypass-permissions")
    except (pexpect.TIMEOUT, pexpect.EOF):
        sys.stderr.write("[channel-launcher] bypass prompt not found\n")

    # 2단계: Development Channel 경고 → "I am using this for local development"
    try:
        child.expect(r"local development|Exit", timeout=15)
        # 이미 option 1 (local development)이 선택된 상태 → Enter만
        time.sleep(0.3)
        child.send("\r")
        sys.stderr.write("[channel-launcher] dev-channel: confirmed\n")
        sys.stderr.flush()
    except (pexpect.TIMEOUT, pexpect.EOF):
        sys.stderr.write("[channel-launcher] dev-channel prompt not found\n")

    # 시그널 전달 + 임시 config 정리
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

    sys.stderr.write(f"[channel-launcher] Claude Code channel session running (worker={worker_id}, port={port})\n")
    sys.stderr.flush()

    # Claude Code 프로세스가 끝날 때까지 대기
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
