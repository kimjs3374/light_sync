"""
IMAP/SMTP 메일 클라이언트 래퍼.

Phase 1: Synology IMAP (192.168.0.101:993)
Phase 2: Mailcow 전환 시 이 모듈만 수정
"""

import os
import logging
import smtplib
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.header import decode_header
from email.utils import parseaddr, formataddr, formatdate
from datetime import datetime

from imapclient import IMAPClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 비밀번호 암호화
# ---------------------------------------------------------------------------
_FERNET_KEY = os.environ.get('MAIL_ENCRYPT_KEY', '')


def encrypt_password(plain: str) -> str:
    from cryptography.fernet import Fernet
    f = Fernet(_FERNET_KEY.encode())
    return f.encrypt(plain.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    from cryptography.fernet import Fernet
    f = Fernet(_FERNET_KEY.encode())
    return f.decrypt(encrypted.encode()).decode()


# ---------------------------------------------------------------------------
# HTML Sanitizer
# ---------------------------------------------------------------------------
def sanitize_html(html_body: str) -> str:
    """메일 HTML 본문 XSS 방지."""
    import nh3
    return nh3.clean(
        html_body,
        tags={'p', 'br', 'div', 'span', 'a', 'img', 'table', 'tr', 'td', 'th',
              'thead', 'tbody', 'b', 'i', 'u', 'strong', 'em', 'ul', 'ol', 'li',
              'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre', 'code',
              'hr', 'font', 'center', 'sub', 'sup', 'small', 'big', 'dl', 'dt', 'dd'},
        attributes={
            'a': {'href', 'title', 'target'},
            'img': {'src', 'alt', 'width', 'height', 'style'},
            'font': {'color', 'size', 'face'},
            'td': {'style', 'width', 'height', 'colspan', 'rowspan', 'align', 'valign'},
            'th': {'style', 'width', 'height', 'colspan', 'rowspan', 'align', 'valign'},
            'table': {'style', 'width', 'border', 'cellpadding', 'cellspacing'},
            'tr': {'style'},
            'div': {'style', 'class'},
            'span': {'style', 'class'},
            'p': {'style', 'class'},
            '*': {'style'},
        },
        url_schemes={'http', 'https', 'cid', 'mailto', 'data'},
    )


# ---------------------------------------------------------------------------
# 헤더 디코딩 유틸리티
# ---------------------------------------------------------------------------
def _decode_header_value(value):
    """RFC2047 인코딩된 메일 헤더를 유니코드로 디코딩."""
    if not value:
        return ''
    parts = decode_header(value)
    result = []
    for data, charset in parts:
        if isinstance(data, bytes):
            result.append(data.decode(charset or 'utf-8', errors='replace'))
        else:
            result.append(data)
    return ''.join(result)


def _parse_address(addr_str):
    """메일 주소 파싱. 'Name <email>' → {'name': ..., 'email': ...}"""
    if not addr_str:
        return {'name': '', 'email': ''}
    # RFC2047 먼저 디코딩 후 파싱 (인코딩된 이름이 주소 파싱 방해 방지)
    decoded = _decode_header_value(addr_str)
    name, addr = parseaddr(decoded)
    return {'name': name, 'email': addr}


def _parse_address_list(addr_str):
    """콤마 구분 주소 리스트 파싱."""
    if not addr_str:
        return []
    import re as _re
    # 짝 안 맞는 꺾쇠괄호 제거 (예: 'user@example.com>' → 'user@example.com')
    cleaned = _re.sub(r'(?<!<)>', '', addr_str)  # < 없이 > 만 있는 경우 제거
    # RFC2047 먼저 디코딩 후 파싱 (인코딩된 이름이 주소 파싱 방해 방지)
    decoded = _decode_header_value(cleaned)
    from email.utils import getaddresses
    pairs = getaddresses([decoded])
    result = []
    for name, addr in pairs:
        if addr:
            result.append({'name': name, 'email': addr})
    # getaddresses 실패 시 직접 이메일 추출 풀백
    if not result:
        for m in _re.finditer(r'[\w.+-]+@[\w.-]+\.\w+', decoded):
            result.append({'name': '', 'email': m.group()})
    return result


# ---------------------------------------------------------------------------
# MailClient
# ---------------------------------------------------------------------------
class MailClient:
    """IMAP/SMTP 메일 클라이언트."""

    def __init__(self, imap_host, imap_port, smtp_host, smtp_port,
                 username, password, use_ssl=True, verify_cert=False):
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.verify_cert = verify_cert  # 외부 서버: True, 내부 자체인증서: False
        self._imap = None
        # 워커 내 IMAP 연결 풀 사용 여부 (sync 워커 환경)
        self.use_pool = False
        self._pool_key = None

    # ─── 워커별 IMAP 연결 풀 ───────────────────────────────────────────
    # 매 요청마다 connect+LOGIN+LOGOUT 하는 비용을 줄이기 위해
    # 같은 워커 메모리에 (username, imap_host) 키로 IMAP 연결을 캐싱한다.
    # gunicorn sync 워커는 워커당 single-thread 이므로 lock 불필요.
    _POOL: dict = {}
    _POOL_TTL = 90  # 초

    def _make_ssl_context(self):
        """SSL 컨텍스트 생성. 내부서버=인증서검증 안함, 외부서버=정상 검증."""
        import ssl as _ssl
        ssl_context = _ssl.create_default_context()
        if not self.verify_cert:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = _ssl.CERT_NONE
        return ssl_context

    def _connect_imap(self):
        """IMAP 연결 생성."""
        ssl_context = self._make_ssl_context()

        client = IMAPClient(self.imap_host, port=self.imap_port,
                            ssl=self.use_ssl, ssl_context=ssl_context, timeout=30)
        client.login(self.username, self.password)
        return client

    def __enter__(self):
        if self.use_pool:
            import time as _t
            key = (self.username, self.imap_host, self.imap_port)
            entry = MailClient._POOL.get(key)
            now = _t.time()
            if entry and entry['expires_at'] > now:
                try:
                    entry['imap'].noop()  # liveness 확인
                    entry['expires_at'] = now + MailClient._POOL_TTL
                    self._imap = entry['imap']
                    self._pool_key = key
                    return self
                except Exception:
                    # dead connection — 정리하고 새로
                    try:
                        entry['imap'].logout()
                    except Exception:
                        pass
                    MailClient._POOL.pop(key, None)
            # 새 연결
            self._imap = self._connect_imap()
            MailClient._POOL[key] = {'imap': self._imap, 'expires_at': now + MailClient._POOL_TTL}
            self._pool_key = key
            return self
        # 기본 경로 (풀 미사용)
        self._imap = self._connect_imap()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.use_pool:
            # 정상 종료시 풀에 보존. 예외 발생 시 안전을 위해 폐기.
            if exc_type is not None and self._pool_key is not None:
                try:
                    self._imap.logout()
                except Exception:
                    pass
                MailClient._POOL.pop(self._pool_key, None)
            self._imap = None
            self._pool_key = None
            return
        if self._imap:
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None

    # === 폴더 ===

    def inbox_unread_count(self):
        """INBOX 한 폴더만 UNSEEN 조회 — 뱃지/카운터용 가벼운 호출."""
        try:
            status = self._imap.folder_status('INBOX', ['UNSEEN'])
            return int(status.get(b'UNSEEN', 0) or 0)
        except Exception:
            return 0

    def list_folders(self, all_unread=False):
        """폴더 목록.

        INBOX 하나만 STATUS UNSEEN 조회한다. 그 외 폴더는 unread=0 으로 둔다.
        Dovecot STATUS 가 폴더당 0.3~0.6초 들고 폴더가 10개를 넘으면 4초가
        넘어가는 경우가 있어 INBOX 외에는 사이드바 카운트를 포기했다.
        all_unread=True 인 경우에만 모든 폴더 STATUS (관리용 옵션).
        """
        import time as _t
        import logging as _log
        _log_ = _log.getLogger(__name__)

        folders = []
        t_total = _t.perf_counter()
        raw = self._imap.list_folders()
        t_list = _t.perf_counter() - t_total
        n_status = 0
        t_status = 0.0
        for flags, delimiter, name in raw:
            flag_strs = [str(f) for f in flags]
            folder_info = {
                'name': name,
                'flags': flag_strs,
                'delimiter': delimiter.decode() if isinstance(delimiter, bytes) else delimiter,
                'unread': 0,
            }
            do_status = all_unread or (isinstance(name, str) and name.upper() == 'INBOX')
            if do_status:
                try:
                    t0 = _t.perf_counter()
                    status = self._imap.folder_status(name, ['UNSEEN'])
                    t_status += _t.perf_counter() - t0
                    n_status += 1
                    folder_info['unread'] = status.get(b'UNSEEN', 0)
                except Exception:
                    pass
            folders.append(folder_info)

        elapsed = _t.perf_counter() - t_total
        if elapsed >= 0.3:
            _log_.info(
                'list_folders user=%s elapsed=%.2fs list=%.2fs status_n=%d status_sum=%.2fs folders=%d',
                self.username, elapsed, t_list, n_status, t_status, len(folders),
            )
        return folders

    def create_folder(self, name):
        self._imap.create_folder(name)

    def delete_folder(self, name):
        self._imap.delete_folder(name)

    # === 메일 목록 ===

    def fetch_messages(self, folder='INBOX', page=1, per_page=30, search_criteria='ALL'):
        """메일 목록 조회 (페이징)."""
        self._imap.select_folder(folder, readonly=True)
        # IMAP SORT로 날짜 기준 최신순 정렬 (APPEND된 메일도 원래 날짜로 정렬)
        try:
            all_uids = self._imap.sort('REVERSE DATE', search_criteria)
        except Exception:
            # SORT 미지원 서버 fallback
            all_uids = self._imap.search(search_criteria)
            all_uids.sort(reverse=True)

        total = len(all_uids)
        pages = max(1, (total + per_page - 1) // per_page)
        start = (page - 1) * per_page
        end = start + per_page
        page_uids = all_uids[start:end]

        if not page_uids:
            return {'messages': [], 'total': total, 'page': page, 'pages': pages}

        # ENVELOPE + FLAGS만 가져오기 (BODYSTRUCTURE 제거 = 속도 대폭 개선)
        # To 헤더도 가져와서 ENVELOPE에 to가 없는 메일 대비
        raw = self._imap.fetch(page_uids, ['ENVELOPE', 'FLAGS', 'BODY.PEEK[HEADER.FIELDS (CONTENT-TYPE TO)]'])
        messages = []
        for uid in page_uids:
            if uid not in raw:
                continue
            data = raw[uid]
            env = data.get(b'ENVELOPE')
            flags = data.get(b'FLAGS', ())

            if not env:
                continue

            # 첨부파일 유무: Content-Type에 multipart/mixed가 있으면 첨부 가능성 높음
            header_bytes = data.get(b'BODY[HEADER.FIELDS (CONTENT-TYPE TO)]', b'').decode(errors='replace')
            has_attach = 'multipart/mixed' in header_bytes.lower()

            # ENVELOPE to가 없으면 헤더에서 직접 파싱
            to_list = self._parse_envelope_addrs(env.to)
            if not to_list:
                import re as _re
                to_match = _re.search(r'(?i)^To:\s*(.+?)(?:\r?\n(?!\s)|$)', header_bytes, _re.DOTALL)
                if to_match:
                    to_list = _parse_address_list(to_match.group(1).strip())

            msg = {
                'uid': uid,
                'subject': _decode_header_value(env.subject.decode('utf-8', errors='replace') if isinstance(env.subject, bytes) else (env.subject or '')),
                'from': self._parse_envelope_addr(env.from_),
                'to': to_list,
                'date': env.date.isoformat() if env.date else '',
                'flags': [str(f) for f in flags],
                'is_read': b'\\Seen' in flags,
                'is_flagged': b'\\Flagged' in flags,
                'has_attachment': has_attach,
                'size': 0,
            }
            messages.append(msg)

        return {'messages': messages, 'total': total, 'page': page, 'pages': pages}

    def fetch_by_uids(self, folder, uids):
        """UID 목록으로 메시지를 직접 조회 (검색 결과용)."""
        import logging as _log
        log = _log.getLogger(__name__)
        log.info("fetch_by_uids: folder=%s, uids=%s", folder, uids)
        self._imap.select_folder(folder, readonly=True)
        # UID 내림차순 = 최신순 근사치 (IMAP UID는 단조증가)
        sorted_uids = sorted(uids, reverse=True)

        if not sorted_uids:
            return {'messages': [], 'total': 0, 'page': 1, 'pages': 1}

        raw = self._imap.fetch(sorted_uids, ['ENVELOPE', 'FLAGS', 'BODY.PEEK[HEADER.FIELDS (CONTENT-TYPE TO)]'])
        messages = []
        for uid in sorted_uids:
            if uid not in raw:
                continue
            data = raw[uid]
            env = data.get(b'ENVELOPE')
            flags = data.get(b'FLAGS', ())
            if not env:
                continue
            header_bytes = data.get(b'BODY[HEADER.FIELDS (CONTENT-TYPE TO)]', b'').decode(errors='replace')
            has_attach = 'multipart/mixed' in header_bytes.lower()
            to_list = self._parse_envelope_addrs(env.to)
            if not to_list:
                import re as _re
                to_match = _re.search(r'(?i)^To:\s*(.+?)(?:\r?\n(?!\s)|$)', header_bytes, _re.DOTALL)
                if to_match:
                    to_list = _parse_address_list(to_match.group(1).strip())
            messages.append({
                'uid': uid,
                'subject': _decode_header_value(env.subject.decode('utf-8', errors='replace') if isinstance(env.subject, bytes) else (env.subject or '')),
                'from': self._parse_envelope_addr(env.from_),
                'to': to_list,
                'date': env.date.isoformat() if env.date else '',
                'flags': [str(f) for f in flags],
                'is_read': b'\\Seen' in flags,
                'is_flagged': b'\\Flagged' in flags,
                'has_attachment': has_attach,
                'size': 0,
            })
        log.info("fetch_by_uids: raw=%d fetched, messages=%d built, subjects=%s",
                 len(raw), len(messages), [m['subject'][:20] for m in messages])
        return {'messages': messages, 'total': len(messages), 'page': 1, 'pages': 1}

    def search_messages(self, query, folder='INBOX'):
        """IMAP SEARCH로 메일 검색. 서버 검색 실패 시 ENVELOPE 클라이언트 스캔 폴백."""
        import logging as _log
        log = _log.getLogger(__name__)
        self._imap.select_folder(folder, readonly=True)
        q_lower = query.lower()

        # 1단계: IMAP 서버 검색 시도
        uid_set = set()
        for criteria in (['SUBJECT', query], ['FROM', query], ['TEXT', query]):
            try:
                found = self._imap.search(criteria, charset='UTF-8')
                log.info("MAIL SEARCH [%s] %s → %d hits", criteria[0], query, len(found))
                uid_set.update(found)
            except Exception as e:
                log.warning("MAIL SEARCH [%s] %s → FAILED: %s", criteria[0], query, e)

        log.info("MAIL SEARCH total uid_set after server search: %d", len(uid_set))

        # 2단계: 최근 200개 ENVELOPE 제목/발신자 부분문자열 스캔 (항상 실행)
        # IMAP 서버가 단어 단위 처리 시 "설비" → "전등설비" 누락 보완
        try:
            try:
                all_uids = self._imap.sort('REVERSE DATE', 'ALL')
            except Exception:
                all_uids = sorted(self._imap.search('ALL'), reverse=True)
            scan_uids = all_uids[:200]
            if scan_uids:
                raw = self._imap.fetch(scan_uids, ['ENVELOPE'])
                matched = 0
                for uid, data in raw.items():
                    env = data.get(b'ENVELOPE')
                    if not env:
                        continue
                    subj_raw = env.subject or b''
                    subj = _decode_header_value(
                        subj_raw.decode('utf-8', errors='replace') if isinstance(subj_raw, bytes) else subj_raw
                    )
                    from_str = ''
                    if env.from_:
                        addr = env.from_[0]
                        name = (addr.name or b'').decode('utf-8', errors='replace') if isinstance(addr.name or b'', bytes) else (addr.name or '')
                        mailbox = (addr.mailbox or b'').decode(errors='replace') if isinstance(addr.mailbox or b'', bytes) else (addr.mailbox or '')
                        host = (addr.host or b'').decode(errors='replace') if isinstance(addr.host or b'', bytes) else (addr.host or '')
                        from_str = f'{name} {mailbox}@{host}'
                    if q_lower in subj.lower() or q_lower in from_str.lower():
                        uid_set.add(uid)
                        matched += 1
                log.info("MAIL SEARCH envelope-scan: %d matched from %d", matched, len(scan_uids))
        except Exception as e:
            log.error("MAIL SEARCH envelope-scan failed: %s", e, exc_info=True)

        uids = sorted(uid_set, reverse=True)
        return uids[:200]

    # === 메일 본문 ===

    def fetch_message(self, uid, folder='INBOX'):
        """메일 상세 조회."""
        self._imap.select_folder(folder, readonly=False)
        raw = self._imap.fetch([uid], ['RFC822', 'FLAGS'])
        if uid not in raw:
            return None

        # 읽음 표시
        self._imap.set_flags([uid], [b'\\Seen'])

        msg_bytes = raw[uid][b'RFC822']
        flags = raw[uid].get(b'FLAGS', ())
        msg = email.message_from_bytes(msg_bytes)

        # 본문 + 첨부파일 파싱
        html_body = ''
        text_body = ''
        attachments = []
        inline_images = {}

        dsn_parts = []  # 반송메일(DSN) delivery-status 파트
        is_report = msg.get_content_type() == 'multipart/report'

        for part_idx, part in enumerate(msg.walk()):
            content_type = part.get_content_type()
            disposition = str(part.get('Content-Disposition', ''))
            content_id = part.get('Content-ID', '')

            if 'attachment' in disposition:
                filename = part.get_filename()
                if filename:
                    filename = _decode_header_value(filename)
                    attachments.append({
                        'part_id': str(part_idx),
                        'filename': filename,
                        'size': len(part.get_payload(decode=True) or b''),
                        'content_type': content_type,
                    })
            elif content_type == 'text/html':
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or 'utf-8'
                html_body = payload.decode(charset, errors='replace') if payload else ''
            elif content_type == 'text/plain' and not html_body:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or 'utf-8'
                text_body = payload.decode(charset, errors='replace') if payload else ''
            elif content_type == 'message/delivery-status':
                # 반송메일 배달 상태 정보
                try:
                    payload = part.get_payload()
                    if isinstance(payload, list):
                        for sub in payload:
                            dsn_parts.append(str(sub))
                    elif isinstance(payload, str):
                        dsn_parts.append(payload)
                    else:
                        raw = part.get_payload(decode=True)
                        if raw:
                            dsn_parts.append(raw.decode('utf-8', errors='replace'))
                except Exception:
                    pass
            elif content_id and content_type.startswith('image/'):
                # 인라인 이미지
                cid = content_id.strip('<>')
                payload = part.get_payload(decode=True)
                if payload:
                    import base64
                    b64 = base64.b64encode(payload).decode()
                    inline_images[cid] = f'data:{content_type};base64,{b64}'

        # 반송메일인데 본문이 비어있으면 DSN 정보로 본문 구성
        if is_report and not html_body and not text_body and dsn_parts:
            text_body = '메일 전송 실패 (반송)\n' + '─' * 40 + '\n' + '\n'.join(dsn_parts)
        elif is_report and not html_body and dsn_parts:
            # text_body는 있지만 DSN 상세도 같이 보여줌
            text_body = text_body.rstrip() + '\n\n── 배달 상태 정보 ──\n' + '\n'.join(dsn_parts)

        # 인라인 이미지 치환
        if html_body and inline_images:
            for cid, data_uri in inline_images.items():
                html_body = html_body.replace(f'cid:{cid}', data_uri)

        # HTML sanitize
        safe_html = sanitize_html(html_body) if html_body else ''

        return {
            'uid': uid,
            'subject': _decode_header_value(msg.get('Subject', '')),
            'from': _parse_address(msg.get('From', '')),
            'to': _parse_address_list(msg.get('To', '')),
            'cc': _parse_address_list(msg.get('Cc', '')),
            'date': msg.get('Date', ''),
            'html_body': safe_html,
            'text_body': text_body,
            'attachments': attachments,
            'flags': [str(f) for f in flags],
            'is_read': b'\\Seen' in flags,
            'is_flagged': b'\\Flagged' in flags,
        }

    def fetch_attachment(self, uid, part_id, folder='INBOX'):
        """첨부파일 다운로드. Returns: (filename, content_type, bytes)"""
        self._imap.select_folder(folder, readonly=True)
        raw = self._imap.fetch([uid], ['RFC822'])
        if uid not in raw:
            return None, None, None

        msg = email.message_from_bytes(raw[uid][b'RFC822'])
        for idx, part in enumerate(msg.walk()):
            if str(idx) == part_id:
                filename = part.get_filename()
                if filename:
                    filename = _decode_header_value(filename)
                content_type = part.get_content_type()
                payload = part.get_payload(decode=True)
                return filename, content_type, payload

        return None, None, None

    def fetch_all_attachments(self, uid, folder='INBOX'):
        """메일의 모든 첨부파일을 한 번에 조회. Returns: [(filename, bytes), ...]"""
        self._imap.select_folder(folder, readonly=True)
        raw = self._imap.fetch([uid], ['RFC822'])
        if uid not in raw:
            return []

        msg = email.message_from_bytes(raw[uid][b'RFC822'])
        results = []
        for part in msg.walk():
            disposition = str(part.get('Content-Disposition', ''))
            if 'attachment' not in disposition:
                continue
            filename = part.get_filename()
            if not filename:
                continue
            filename = _decode_header_value(filename)
            payload = part.get_payload(decode=True)
            if payload:
                results.append((filename, payload))
        return results

    # === 플래그/이동 ===

    def set_flags(self, uids, flag, action='add', folder='INBOX'):
        """플래그 설정. flag: \\Seen, \\Flagged 등."""
        self._imap.select_folder(folder)
        flag_bytes = flag.encode() if isinstance(flag, str) else flag
        if action == 'add':
            self._imap.add_flags(uids, [flag_bytes])
        else:
            self._imap.remove_flags(uids, [flag_bytes])

    def move_messages(self, uids, dest_folder, src_folder='INBOX'):
        """메일 폴더 이동."""
        self._imap.select_folder(src_folder)
        self._imap.move(uids, dest_folder)

    def delete_messages(self, uids, folder='INBOX'):
        """휴지통으로 이동."""
        trash_names = ['Trash', 'INBOX.Trash', 'Deleted Items', 'Deleted Messages']
        trash_folder = None
        folders = self._imap.list_folders()
        for flags, delimiter, name in folders:
            if name in trash_names or b'\\Trash' in flags:
                trash_folder = name
                break
        if trash_folder:
            self.move_messages(uids, trash_folder, folder)
        else:
            # 휴지통 없으면 삭제 플래그 + expunge
            self._imap.select_folder(folder)
            self._imap.delete_messages(uids)
            self._imap.expunge()

    # === 발송 ===

    def send_message(self, from_addr, to, cc=None, bcc=None, subject='',
                     html_body='', text_body='', attachments=None,
                     from_name=None):
        """SMTP 발송."""
        msg = MIMEMultipart('mixed')

        if from_name:
            from email.header import Header
            msg['From'] = formataddr((str(Header(from_name, 'utf-8')), from_addr))
        else:
            msg['From'] = from_addr
        msg['To'] = ', '.join(to) if isinstance(to, list) else to
        if cc:
            msg['Cc'] = ', '.join(cc) if isinstance(cc, list) else cc
        msg['Subject'] = subject
        msg['Date'] = formatdate(localtime=True)
        from email.utils import make_msgid
        msg['Message-ID'] = make_msgid(domain=from_addr.split('@')[-1] if '@' in from_addr else 'mgnt.kr')
        msg['MIME-Version'] = '1.0'

        # 본문 (HTML 우선, text 폴백)
        alt = MIMEMultipart('alternative')
        if text_body:
            alt.attach(MIMEText(text_body, 'plain', 'utf-8'))
        if html_body:
            alt.attach(MIMEText(html_body, 'html', 'utf-8'))
        elif text_body:
            pass  # already attached
        msg.attach(alt)

        # 첨부파일
        if attachments:
            for filename, file_bytes in attachments:
                att = MIMEApplication(file_bytes)
                att.add_header('Content-Disposition', 'attachment', filename=filename)
                msg.attach(att)

        # 수신자 목록
        recipients = []
        if isinstance(to, list):
            recipients.extend(to)
        else:
            recipients.append(to)
        if cc:
            recipients.extend(cc if isinstance(cc, list) else [cc])
        if bcc:
            recipients.extend(bcc if isinstance(bcc, list) else [bcc])

        smtp_ctx = self._make_ssl_context()

        if self.smtp_port == 465:
            # Implicit SSL (SMTPS) — 외부 메일서버 (다음, 네이버 등)
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30, context=smtp_ctx) as server:
                if self.password:
                    server.login(self.username, self.password)
                server.sendmail(from_addr, recipients, msg.as_string())
        else:
            # STARTTLS (587) 또는 평문 (25)
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                try:
                    server.starttls(context=smtp_ctx)
                except smtplib.SMTPNotSupportedError:
                    pass
                if self.password:
                    server.login(self.username, self.password)
                server.sendmail(from_addr, recipients, msg.as_string())

        # 보낸편지함에 저장
        try:
            sent_folders = ['Sent', 'INBOX.Sent', 'Sent Items', 'Sent Messages']
            folders = self._imap.list_folders()
            sent_folder = None
            for flags, delimiter, name in folders:
                if name in sent_folders or b'\\Sent' in flags:
                    sent_folder = name
                    break
            if sent_folder:
                self._imap.append(sent_folder, msg.as_bytes())
        except Exception as e:
            logger.warning("보낸편지함 저장 실패: %s", e)

        return {'success': True, 'message': '메일 발송 완료'}

    def save_draft(self, from_addr, to, subject, html_body, attachments=None):
        """Draft 폴더에 저장."""
        msg = MIMEMultipart()
        msg['From'] = from_addr
        msg['To'] = ', '.join(to) if isinstance(to, list) else (to or '')
        msg['Subject'] = subject
        if html_body:
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        if attachments:
            for filename, file_bytes in attachments:
                att = MIMEApplication(file_bytes)
                att.add_header('Content-Disposition', 'attachment', filename=filename)
                msg.attach(att)

        draft_folders = ['Drafts', 'INBOX.Drafts', 'Draft']
        folders = self._imap.list_folders()
        draft_folder = None
        for flags, delimiter, name in folders:
            if name in draft_folders or b'\\Drafts' in flags:
                draft_folder = name
                break
        if draft_folder:
            self._imap.append(draft_folder, msg.as_bytes())
        return {'success': True}

    # === Private helpers ===

    @staticmethod
    def _parse_envelope_addr(addr_tuple):
        """ENVELOPE 주소 파싱 (단일)."""
        if not addr_tuple:
            return {'name': '', 'email': ''}
        a = addr_tuple[0]
        name = a.name.decode('utf-8', errors='replace') if a.name else ''
        mailbox = a.mailbox.decode('utf-8', errors='replace') if a.mailbox else ''
        host = a.host.decode('utf-8', errors='replace') if a.host else ''
        return {'name': _decode_header_value(name), 'email': f'{mailbox}@{host}' if mailbox else ''}

    @staticmethod
    def _parse_envelope_addrs(addr_tuple):
        """ENVELOPE 주소 리스트 파싱."""
        if not addr_tuple:
            return []
        result = []
        for a in addr_tuple:
            name = a.name.decode('utf-8', errors='replace') if a.name else ''
            mailbox = a.mailbox.decode('utf-8', errors='replace') if a.mailbox else ''
            host = a.host.decode('utf-8', errors='replace') if a.host else ''
            result.append({'name': _decode_header_value(name), 'email': f'{mailbox}@{host}' if mailbox else ''})
        return result

    @staticmethod
    def _has_attachment(body_structure):
        """BODYSTRUCTURE에서 첨부파일 유무 확인."""
        if not body_structure:
            return False
        # 간단한 휴리스틱: 문자열 표현에 'attachment' 포함 여부
        return 'attachment' in str(body_structure).lower()
