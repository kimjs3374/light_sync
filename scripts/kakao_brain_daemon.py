#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""카카오워크 ERP 두뇌 — 상주(warm) 워커 풀 데몬.

문제: 메시지마다 `claude` CLI를 새로 띄우면 콜드스타트가 ~7~12초. 대부분이 두뇌 응답 지연.
해결: **사용자별 warm 워커**(claude stream-json 상주 프로세스)를 풀에 유지.
  - 같은 사용자의 이어지는 메시지는 워커를 재사용 → 콜드스타트 생략(실측 12s→2.4s).
  - 워커 = 사용자 1명의 세션(프로세스가 곧 세션이라 맥락 유지). 사용자끼리 완전 격리.
  - 각 워커는 그 사용자의 KAKAO_ERP_USER 를 주입한 MCP 설정으로 기동 → 휴가 상신 신원안전 유지.

프로토콜(유닉스 소켓, 한 줄 JSON):
  요청: {"uid": "<kakao_user_id>", "text": "<사용자 메시지>"}
  응답: {"reply": "...", "erp_user": "..."} | {"error": "...", "reply": null}

kakao_brain.py(클라이언트)가 이 소켓으로 포워딩하고, 데몬이 없으면 스스로 기동(단발 콜드 폴백).
"""
import os
import sys
import json
import time
import uuid
import atexit
import select
import signal
import socket
import threading
import subprocess

APP_ROOT = "/web/light_sync"
sys.path.insert(0, APP_ROOT)
os.chdir(APP_ROOT)

# kakao_brain 의 공용 로직 재사용(단일 출처): 신원 게이트/시스템프롬프트/MCP설정/모델/FAST_ENV.
from kakao_brain import (  # noqa: E402
    resolve, SYSTEM_PROMPT, FAST_ENV, CLAUDE_MODEL, BOT_CONFIG_DIR, _build_mcp_config,
)

SOCK_PATH = os.path.join(APP_ROOT, "scripts", "kakao_brain.sock")
LOG_PATH = os.path.join(APP_ROOT, "scripts", "kakao_daemon.log")
PID_PATH = os.path.join(APP_ROOT, "scripts", "kakao_daemon.pid")

MAX_WORKERS = int(os.environ.get("KAKAO_MAX_WORKERS", "3"))       # 동시 warm 워커 상한(서버 RAM 빠듯 → 보수적)
IDLE_TTL = int(os.environ.get("KAKAO_WORKER_IDLE_TTL", "360"))    # 유휴 6분 → 워커 종료(메모리 회수)
WORKER_TTL = int(os.environ.get("KAKAO_WORKER_TTL", "7200"))      # 워커 최대수명 2시간
WORKER_MAX_TURNS = int(os.environ.get("KAKAO_WORKER_MAX_TURNS", "40"))
ASK_TIMEOUT = int(os.environ.get("KAKAO_ASK_TIMEOUT", "150"))     # 한 턴 응답 대기 상한

_logf = open(LOG_PATH, "a", encoding="utf-8", buffering=1)


def log(msg):
    _logf.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")


class Worker:
    """사용자 1명 전용 claude stream-json 상주 프로세스."""

    def __init__(self, erp_user):
        self.erp_user = erp_user
        self.mcp_path = _build_mcp_config(erp_user)
        self.session_id = str(uuid.uuid4())
        self.turns = 0
        self.created = time.time()
        self.last_used = time.time()
        self.lock = threading.Lock()      # 같은 워커 동시 접근 방지(1턴씩 직렬)
        sysprompt = SYSTEM_PROMPT + (
            f"\n[현재 사용자 ERP 계정: {erp_user}] 이 사용자 본인의 정보/휴가만 처리한다."
        )
        cmd = ["claude", "-p",
               "--input-format", "stream-json",
               "--output-format", "stream-json", "--verbose",
               "--model", CLAUDE_MODEL,
               "--mcp-config", self.mcp_path,
               "--dangerously-skip-permissions",
               "--append-system-prompt", sysprompt,
               "--session-id", self.session_id]
        env = {**os.environ, **FAST_ENV,
               "CLAUDE_CONFIG_DIR": BOT_CONFIG_DIR, "KAKAO_ERP_USER": erp_user}
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=_logf,
            text=True, encoding="utf-8", errors="replace", bufsize=1, cwd=APP_ROOT, env=env)
        log(f"[worker+] uid_user={erp_user} pid={self.proc.pid} sid={self.session_id[:8]}")

    def alive(self):
        return self.proc.poll() is None

    def expired(self):
        return (time.time() - self.created > WORKER_TTL) or (self.turns >= WORKER_MAX_TURNS)

    def ask(self, text):
        """한 턴 질의 → 최종 응답 텍스트. 실패 시 예외."""
        if not self.alive():
            raise RuntimeError("worker_dead")
        # 입력 전 잔여 stdout 비우기(이전 턴 이후 남은 이벤트 제거 — 보통 없음)
        self._drain()
        msg = {"type": "user",
               "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
        try:
            self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise RuntimeError(f"worker_pipe:{e}")
        reply = self._read_result()
        self.turns += 1
        self.last_used = time.time()
        return reply

    def _drain(self):
        while True:
            r, _, _ = select.select([self.proc.stdout], [], [], 0)
            if not r:
                return
            if not self.proc.stdout.readline():
                return

    def _read_result(self):
        t0 = time.time()
        while True:
            remaining = ASK_TIMEOUT - (time.time() - t0)
            if remaining <= 0:
                raise RuntimeError("ask_timeout")
            r, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if not r:
                raise RuntimeError("ask_timeout")
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    raise RuntimeError("worker_died_midturn")
                continue
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("type") == "result":
                if ev.get("subtype") != "success" or ev.get("is_error"):
                    raise RuntimeError("claude_error:" + str(ev.get("result") or ev.get("subtype"))[:120])
                reply = (ev.get("result") or "").strip()
                if not reply:
                    raise RuntimeError("empty_reply")
                return reply

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass
        try:
            os.unlink(self.mcp_path)
        except OSError:
            pass
        log(f"[worker-] uid_user={self.erp_user} pid={self.proc.pid} turns={self.turns}")


class Pool:
    def __init__(self):
        self.workers = {}          # kakao_uid -> Worker
        self.glock = threading.Lock()

    def _evict_if_needed(self):
        if len(self.workers) < MAX_WORKERS:
            return
        # LRU 축출
        old_uid = min(self.workers, key=lambda k: self.workers[k].last_used)
        self.workers.pop(old_uid).close()

    def get(self, uid, erp_user):
        with self.glock:
            w = self.workers.get(uid)
            if w and w.alive() and not w.expired():
                return w
            if w:
                w.close()
                self.workers.pop(uid, None)
            self._evict_if_needed()
            w = Worker(erp_user)
            self.workers[uid] = w
            return w

    def drop(self, uid):
        with self.glock:
            w = self.workers.pop(uid, None)
        if w:
            w.close()

    def reap(self):
        while True:
            time.sleep(30)
            now = time.time()
            with self.glock:
                dead = [u for u, w in self.workers.items()
                        if (not w.alive()) or (now - w.last_used > IDLE_TTL) or w.expired()]
                for u in dead:
                    self.workers.pop(u).close()

    def close_all(self):
        with self.glock:
            for u in list(self.workers):
                try:
                    self.workers.pop(u).close()
                except Exception:
                    pass


POOL = Pool()


def handle(uid, text):
    """resolve 게이트 후 워커 배정·질의. kakao_brain.main 과 동일 정책."""
    erp_user, allowed, channel_enabled = resolve(uid)
    if not erp_user:
        return {"error": "unmapped", "reply": None, "kakao_user_id": uid}
    ignore_gate = os.environ.get("KAKAO_IGNORE_CHANNEL_GATE", "0").strip() in ("1", "true", "True")
    if not channel_enabled and not ignore_gate:
        return {"error": "channel_disabled", "reply": None, "erp_user": erp_user}
    if not allowed:
        return {"error": "no_allowed_tools", "reply": None, "erp_user": erp_user}

    for attempt in range(2):   # 워커가 죽어 있으면 1회 재생성 후 재시도
        w = POOL.get(uid, erp_user)
        try:
            reply = w.ask(text)
            return {"reply": reply, "erp_user": erp_user}
        except RuntimeError as e:
            reason = str(e)
            log(f"[ask-fail] uid={uid} attempt={attempt} {reason}")
            POOL.drop(uid)
            if attempt == 1 or reason.startswith("ask_timeout") or reason.startswith("claude_error"):
                return {"error": f"brain:{reason[:80]}", "reply": None, "erp_user": erp_user}
    return {"error": "brain:unknown", "reply": None, "erp_user": erp_user}


def serve_conn(conn):
    try:
        conn.settimeout(ASK_TIMEOUT + 30)
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(65536)
            if not chunk:
                return
            buf += chunk
        req = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
        uid = str(req.get("uid") or "")
        text = req.get("text") or ""
        if not uid or not text:
            resp = {"error": "bad_request", "reply": None}
        else:
            resp = handle(uid, text)
        conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
    except Exception as e:
        try:
            conn.sendall((json.dumps({"error": f"daemon:{str(e)[:80]}", "reply": None},
                                     ensure_ascii=False) + "\n").encode("utf-8"))
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    # 단일 인스턴스: 소켓 bind 실패면 이미 실행 중 → 종료.
    if os.path.exists(SOCK_PATH):
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.settimeout(1)
            probe.connect(SOCK_PATH)
            probe.close()
            log("[daemon] 이미 실행 중 — 종료")
            return
        except OSError:
            os.unlink(SOCK_PATH)   # 죽은 소켓 파일 제거

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK_PATH)
    os.chmod(SOCK_PATH, 0o660)
    srv.listen(64)
    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))
    log(f"[daemon] 기동 pid={os.getpid()} sock={SOCK_PATH} max_workers={MAX_WORKERS}")

    # 종료 시 자식 claude 워커를 반드시 정리(고아 프로세스=메모리 누수 방지).
    def _shutdown(*_a):
        log("[daemon] 종료 — 워커 정리")
        POOL.close_all()
        try:
            srv.close(); os.unlink(SOCK_PATH)
        except Exception:
            pass
        os._exit(0)
    atexit.register(POOL.close_all)
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    threading.Thread(target=POOL.reap, daemon=True).start()
    try:
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=serve_conn, args=(conn,), daemon=True).start()
    finally:
        POOL.close_all()
        try:
            srv.close()
            os.unlink(SOCK_PATH)
        except Exception:
            pass


if __name__ == "__main__":
    main()
