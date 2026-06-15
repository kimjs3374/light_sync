#!/usr/bin/env python3
"""Light-Sync Channel 전용 Claude Code 세션 런처.

두 개의 TUI 경고 화면을 자동 수락 후 Claude Code를 포그라운드로 유지한다.
1) Bypass Permissions 경고 → "Yes, I accept"
2) Development Channel 경고 → "I am using this for local development"
"""
import os
import signal
import sys
import time
import pexpect

CLAUDE = "/home/magnatech/.local/bin/claude"
ARGS = [
    "--dangerously-skip-permissions",
    "--dangerously-load-development-channels",
    "server:lightsync-erp-chat",
    "--mcp-config",
    "/web/light_sync/light_sync_channel/mcp-channel.json",
    "--strict-mcp-config",
    "--model", "sonnet",
    "--effort", "low",
    "--system-prompt-file",
    "/web/light_sync/light_sync_channel/system-prompt.md",
]


def select_down_enter(child, label):
    """TUI 메뉴에서 아래 화살표 + Enter로 두 번째 옵션 선택."""
    child.send("\x1b[B")  # Down arrow
    time.sleep(0.3)
    child.send("\r")      # Enter
    sys.stderr.write(f"[channel-launcher] {label}: selected option 2\n")
    sys.stderr.flush()


def main():
    os.chdir("/web/light_sync")
    os.environ.setdefault("CHANNEL_PORT", "8788")
    os.environ.setdefault("FLASK_PORT", "8501")

    child = pexpect.spawn(CLAUDE, ARGS, encoding="utf-8", timeout=30,
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

    # 시그널 전달
    def forward_signal(signum, frame):
        try:
            child.kill(signum)
        except Exception:
            pass
    signal.signal(signal.SIGTERM, forward_signal)
    signal.signal(signal.SIGINT, forward_signal)

    sys.stderr.write("[channel-launcher] Claude Code channel session running\n")
    sys.stderr.flush()

    # Claude Code 프로세스가 끝날 때까지 대기
    try:
        child.expect(pexpect.EOF, timeout=None)
    except Exception:
        pass
    child.close()
    sys.exit(child.exitstatus or 0)


if __name__ == "__main__":
    main()
