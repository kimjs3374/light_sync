"""새 메일이 **오는 즉시** 자동처리 — IMAP IDLE 감시자.

crontab 으로 1분마다 돌리면 최악 1분이 밀린다. 수신차단해 둔 주소의 메일이
1분 동안 받은편지함에 앉아 있고, 자동전달도 그만큼 늦는다.
IMAP 에는 "새 메일 생기면 알려줘"(IDLE)가 있으므로 그걸 쓴다.

구조
  계정 하나당 스레드 하나가 INBOX 에 IDLE 로 붙어 있는다.
  새 메일 신호가 오면 **곧바로** 자동처리를 한 번 돌린다.
  처리 자체는 run_mail_automation() 한 곳에서 한다 — 즉시 처리든 crontab 안전망이든
  같은 코드를 지나야, 한쪽만 고쳐져서 결과가 갈리는 일이 없다.

지켜야 할 것
  - **IDLE 은 29분 안에 한 번은 끊었다 다시 걸어야 한다.** RFC 가 그렇게 정하고,
    중간 장비들이 그보다 일찍 조용한 연결을 끊는다. 여기선 4분마다 되건다.
  - 신호가 몰아쳐도 처리는 **한 번으로 묶는다**(3초 디바운스). 메일 10통이
    한꺼번에 들어오면 10번 돌 이유가 없다.
  - 자동처리 설정이 **있는 계정만** 붙는다. 전 직원 계정에 상시 연결을 걸어 둘 수는 없다.
  - 연결이 끊기면 조용히 늘려 가며 다시 붙는다(30초 → 최대 10분).
  - 이 감시자가 죽어도 crontab 안전망이 5분마다 훑는다. 둘 다 같은 일을 하므로
    겹쳐도 결과가 달라지지 않는다.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

IDLE_RENEW_SEC = 240        # IDLE 다시 걸기 (RFC 29분 제한보다 넉넉히 짧게)
DEBOUNCE_SEC = 3            # 신호가 몰리면 한 번으로 묶는다
RESCAN_ACCOUNTS_SEC = 300   # 감시할 계정 목록 다시 보기
BACKOFF_START, BACKOFF_MAX = 30, 600


def _accounts_to_watch(app):
    """자동처리 설정이 하나라도 있는 계정만 — 그 외에는 붙어 있을 이유가 없다."""
    from modules.db_context import get_db
    from modules.models.mail_entities import (
        MailAccount, MailRule, MailAutoReply, MailAutoForward, MailBlocklist,
    )
    with app.app_context():
        with get_db() as db:
            ids = set()
            ids |= {r.account_id for r in db.query(MailRule).filter_by(is_active=True).all()}
            ids |= {r.account_id for r in db.query(MailAutoReply).filter_by(is_active=True).all()}
            ids |= {r.account_id for r in db.query(MailAutoForward).filter_by(is_active=True).all()}
            ids |= {r.account_id for r in db.query(MailBlocklist).filter_by(kind='block').all()}
            if not ids:
                return []
            rows = db.query(MailAccount).filter(
                MailAccount.id.in_(ids), MailAccount.is_active == True).all()
            return [{
                'id': a.id, 'email': a.email, 'username': a.username,
                'imap_host': a.imap_host, 'imap_port': a.imap_port,
                'use_ssl': a.use_ssl, 'password': a.password_encrypted,
            } for a in rows]


class _Runner:
    """자동처리 실행기 — 신호를 묶어서 한 번만 돌린다."""

    def __init__(self, app):
        self.app = app
        self._lock = threading.Lock()
        self._pending = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name='mail-automation', daemon=True)
        self._thread.start()

    def trigger(self, why=''):
        logger.info("[watch] 새 메일 신호 — %s", why)
        self._pending.set()

    def stop(self):
        self._stop.set()
        self._pending.set()

    def _loop(self):
        from modules.scheduler import run_mail_automation
        while not self._stop.is_set():
            self._pending.wait()
            if self._stop.is_set():
                return
            time.sleep(DEBOUNCE_SEC)       # 몰려 오는 신호를 한 번으로 묶는다
            self._pending.clear()
            try:
                with self._lock:
                    r = run_mail_automation(self.app)
                if r['blocked'] or r['classified']:
                    logger.info("[watch] 처리: 차단 %s건 · 분류 %s건", r['blocked'], r['classified'])
            except Exception as e:
                logger.error("[watch] 자동처리 실패: %s", e)


class _AccountWatcher(threading.Thread):
    """계정 하나의 INBOX 에 IDLE 로 붙어 있는 스레드."""

    def __init__(self, account, runner):
        super().__init__(name=f"idle-{account['email']}", daemon=True)
        self.account = account
        self.runner = runner
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        import ssl as _ssl
        from imapclient import IMAPClient
        from modules.services.mail_client import decrypt_password

        backoff = BACKOFF_START
        while not self._stop.is_set():
            imap = None
            try:
                pw = decrypt_password(self.account['password'])
                # 사내 메일서버는 IP 로 붙어 인증서 이름이 안 맞는다 —
                # MailClient 와 **같은 잣대**로 검증을 끈다(verify_cert=False 기본).
                # 여기만 엄격하게 두면 사내 계정은 감시가 아예 안 붙는다.
                ctx = _ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = _ssl.CERT_NONE
                imap = IMAPClient(self.account['imap_host'], port=self.account['imap_port'],
                                  ssl=bool(self.account['use_ssl']), ssl_context=ctx, timeout=60)
                if not self.account['use_ssl']:
                    try:
                        imap.starttls()
                    except Exception:
                        pass
                imap.login(self.account['username'], pw)
                imap.select_folder('INBOX')
                logger.info("[watch] 붙었습니다: %s", self.account['email'])
                backoff = BACKOFF_START

                while not self._stop.is_set():
                    imap.idle()
                    try:
                        responses = imap.idle_check(timeout=IDLE_RENEW_SEC)
                    finally:
                        # idle_done() 을 빠뜨리면 연결이 IDLE 에 갇혀 다음 명령이 안 먹는다
                        imap.idle_done()
                    if self._stop.is_set():
                        break
                    if any(b'EXISTS' in str(r).encode() or b'RECENT' in str(r).encode()
                           for r in (responses or [])):
                        self.runner.trigger(self.account['email'])
                    # 신호가 없으면 그냥 IDLE 을 다시 건다 (연결 유지)
            except Exception as e:
                if self._stop.is_set():
                    break
                logger.warning("[watch] %s 연결 끊김: %s (%s초 뒤 다시)",
                               self.account['email'], e, backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
            finally:
                try:
                    if imap:
                        imap.logout()
                except Exception:
                    pass


def watch_forever(app):
    """감시 시작 — systemd 서비스가 이 함수를 붙들고 돈다."""
    runner = _Runner(app)
    watchers = {}

    # 뜨자마자 한 번은 훑는다 — 꺼져 있는 동안 들어온 메일이 있다
    runner.trigger('기동')

    try:
        while True:
            try:
                accounts = _accounts_to_watch(app)
            except Exception as e:
                logger.error("[watch] 계정 목록 조회 실패: %s", e)
                accounts = []

            want = {a['id']: a for a in accounts}
            for aid in list(watchers):
                if aid not in want:                     # 설정이 지워진 계정은 떼어 낸다
                    watchers.pop(aid).stop()
                    logger.info("[watch] 감시 중지: %s", aid)
            for aid, acc in want.items():
                if aid not in watchers or not watchers[aid].is_alive():
                    w = _AccountWatcher(acc, runner)
                    watchers[aid] = w
                    w.start()

            if not want:
                logger.info("[watch] 감시할 계정이 없습니다 (자동처리 설정이 있는 계정만 붙습니다)")
            time.sleep(RESCAN_ACCOUNTS_SEC)
    except KeyboardInterrupt:
        pass
    finally:
        for w in watchers.values():
            w.stop()
        runner.stop()
