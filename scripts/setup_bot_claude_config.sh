#!/bin/bash
# 봇 전용 Claude Code config 디렉토리 구성 (bkit 플러그인/자동메모리 없음).
#   kakao_brain.py 가 CLAUDE_CONFIG_DIR=/web/light_sync/.claude_bot 로 claude 를 실행한다.
#   목적: 팀 dev용 ~/.claude(bkit 자동메모리)와 완전 분리 → 봇 사용자간 맥락 누수 차단.
#   OAuth 자격은 팀 것과 심볼릭 공유(토큰 회전 자동 동기, 분리 안 됨).
# 서버 재구축/디렉토리 유실 시 이 스크립트 1회 실행으로 복구.
set -e
BOTDIR=/web/light_sync/.claude_bot
mkdir -p "$BOTDIR"
# OAuth 자격 심볼릭(팀 것 공유 → 만료/회전 자동 반영)
ln -sf "$HOME/.claude/.credentials.json" "$BOTDIR/.credentials.json"
# 플러그인/마켓플레이스 비활성 = bkit 안 뜸(auto-memory OFF)
printf '%s\n' '{"enabledPlugins": {}, "extraKnownMarketplaces": {}}' > "$BOTDIR/settings.json"
# 워크스페이스 신뢰(권한 경고 억제). 이미 있으면 claude 가 관리하는 상태 보존.
[ -f "$BOTDIR/.claude.json" ] || printf '%s\n' '{"projects":{"/web/light_sync":{"hasTrustDialogAccepted":true}}}' > "$BOTDIR/.claude.json"
echo "봇 config 준비 완료: $BOTDIR"
ls -la "$BOTDIR"
