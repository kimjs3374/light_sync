#!/bin/bash
# Light-Sync ERP Channel 전용 Claude Code 세션
# systemd에서 screen을 통해 실행

SESSION_NAME="lightsync-channel"
WORK_DIR="/web/light_sync"

# 이미 실행 중이면 종료
screen -S "$SESSION_NAME" -X quit 2>/dev/null
sleep 1

# screen detached 모드로 Claude Code 실행
cd "$WORK_DIR"
exec screen -DmS "$SESSION_NAME" \
  /home/magnatech/.local/bin/claude \
  --dangerously-skip-permissions \
  --dangerously-load-development-channels server:lightsync-erp-chat
