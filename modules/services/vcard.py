"""vCard(.vcf)·CSV 주소록 읽기와 쓰기 — 가져오기/내보내기 공용.

다음·네이버·구글·아웃룩·시놀로지가 내주는 주소록 파일을 그대로 받아
우리 주소록 한 줄(이름·메일·회사·전화·메모) 모양으로 바꾼다.

**파서는 여기 한 벌뿐이다.** 화면의 [가져오기] 버튼(routes/mail.py)과
일회성 스크립트(scripts/import_synology_contacts.py)가 같은 것을 쓴다 —
둘이 갈리면 "스크립트로는 들어왔는데 화면으로는 안 들어온다" 가 된다.

vCard 는 규격이 느슨해서 서비스마다 다르게 내준다. 실제로 걸렸던 것들:
  - 줄 접힘(folding): 이어지는 줄이 공백·탭으로 시작한다
  - QUOTED-PRINTABLE: 아웃룩 2.1 판은 한글을 =EC=9D=B4 로 내주고,
    줄 끝의 `=` 는 "다음 줄에 이어짐" 이다 (이 이어지는 줄은 들여쓰기가 없다)
  - 속성 파라미터: EMAIL;TYPE=* Other:a@b.c — 값은 첫 콜론 뒤부터다
  - 값 이스케이프: \\, \\; \\n
  - 다음(Daum)은 그룹 이름을 ORG 에 `_1` 로 넣는다 — 회사가 아니다
"""

import csv
import io
import quopri
import re

__all__ = ['parse_contacts_file', 'parse_vcards', 'parse_csv_contacts', 'build_vcf', 'decode_bytes']

# 다음이 그룹을 ORG 로 흘려보낸 자리(_1, _2 …). 회사란에 넣으면 쓰레기가 된다.
_GROUP_ORG_RE = re.compile(r'^_\d+$')
_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
_HANGUL_RE = re.compile(r'[가-힣]')


def decode_bytes(raw):
    """업로드된 파일 바이트 → 문자열. 한글 주소록은 UTF-8 아니면 CP949 다."""
    if isinstance(raw, str):
        return raw
    for enc in ('utf-8-sig', 'utf-8', 'cp949', 'euc-kr'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def _unfold(text):
    """접힌 줄을 편다. vCard 는 두 가지로 접는다 — 공백 들여쓰기와 QP 의 `=` 꼬리."""
    out = []
    for raw_line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if out and raw_line[:1] in (' ', '\t'):
            out[-1] += raw_line[1:]                       # 규격대로 접힌 줄
        elif out and out[-1].endswith('=') and '=' in out[-1]:
            out[-1] = out[-1][:-1] + raw_line.strip()     # QUOTED-PRINTABLE 소프트 줄바꿈
        else:
            out.append(raw_line)
    return out


def _split_prop(line):
    """'EMAIL;TYPE=WORK:a@b.c' → ('EMAIL', {'TYPE': 'WORK'}, 'a@b.c')"""
    if ':' not in line:
        return None
    head, value = line.split(':', 1)
    parts = head.split(';')
    name = parts[0].strip().upper()
    # 구글은 item1.EMAIL 처럼 그룹 접두사를 붙인다
    if '.' in name:
        name = name.split('.', 1)[1]
    params = {}
    for p in parts[1:]:
        if '=' in p:
            k, v = p.split('=', 1)
            params[k.strip().upper()] = v.strip()
        else:
            params[p.strip().upper()] = ''
    return name, params, value


def _decode_value(value, params):
    enc = params.get('ENCODING', '').upper()
    if 'QUOTED-PRINTABLE' in enc:
        charset = params.get('CHARSET', 'utf-8')
        try:
            value = quopri.decodestring(value.encode('ascii', 'ignore')).decode(charset, errors='replace')
        except (LookupError, ValueError):
            pass
    # 이스케이프 풀기 — 순서가 중요하다(\\ 를 마지막에 풀면 \\n 이 깨진다)
    return (value.replace('\\n', '\n').replace('\\N', '\n')
                 .replace('\\,', ',').replace('\\;', ';').replace('\\\\', '\\')).strip()


def _name_from_n(value):
    """N: 성;이름;… → 사람 이름. 한글은 붙여 쓰고 로마자는 이름 성 순으로 둔다."""
    parts = [p.strip() for p in value.split(';')]
    family, given = (parts + ['', ''])[:2]
    if not family and not given:
        return ''
    if _HANGUL_RE.search(family + given):
        return f'{family}{given}'
    return ' '.join(p for p in (given, family) if p)


def parse_vcards(text):
    """vCard 여러 장이 이어 붙은 파일 → [{name, emails, company, tel, memo}]"""
    cards = []
    cur = None

    for line in _unfold(text):
        line = line.strip()
        upper = line.upper()

        if upper == 'BEGIN:VCARD':
            cur = {'name': '', 'n_name': '', 'emails': [], 'company': '', 'tels': [], 'memo': ''}
            continue
        if upper == 'END:VCARD':
            if cur:
                cards.append(cur)
            cur = None
            continue
        if cur is None or not line:
            continue

        prop = _split_prop(line)
        if not prop:
            continue
        name, params, raw = prop
        value = _decode_value(raw, params)
        if not value:
            continue

        if name == 'FN':
            cur['name'] = value
        elif name == 'N':
            cur['n_name'] = _name_from_n(value)
        elif name == 'EMAIL':
            for addr in re.split(r'[,;\s]+', value):
                addr = addr.strip().strip('<>')
                if addr and addr not in cur['emails']:
                    cur['emails'].append(addr)
        elif name == 'ORG':
            org = value.split(';')[0].strip()
            if org and not _GROUP_ORG_RE.match(org):
                cur['company'] = org
        elif name == 'TEL':
            if value not in cur['tels']:
                cur['tels'].append(value)
        elif name == 'NOTE':
            cur['memo'] = value

    # FN 이 없으면 N 으로 채운다
    for c in cards:
        if not c['name']:
            c['name'] = c.pop('n_name', '')
        else:
            c.pop('n_name', None)
    return cards


# CSV 머리글 — 서비스마다 말이 다르다. 우리가 내보낸 파일도 그대로 되읽힌다.
_CSV_KEYS = {
    'name': ['이름', '성명', 'name', 'full name', 'display name', '표시 이름', '닉네임'],
    'email': ['이메일', '메일', '메일주소', '이메일주소', 'email', 'e-mail', 'email address',
              'e-mail address', 'email 1 - value', 'primary email'],
    'company': ['회사', '회사명', '소속', '조직', 'company', 'organization', 'organization 1 - name'],
    'phone': ['전화', '전화번호', '휴대폰', '연락처', 'phone', 'tel', 'mobile',
              'phone 1 - value', 'primary phone'],
    'memo': ['메모', '비고', 'memo', 'note', 'notes'],
}


def parse_csv_contacts(text):
    """CSV 주소록 → [{name, emails, company, tel, memo}]. 머리글 이름으로 칸을 찾는다."""
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any((c or '').strip() for c in r)]
    if not rows:
        return []

    header = [(c or '').strip().lower() for c in rows[0]]
    idx = {}
    for key, names in _CSV_KEYS.items():
        for i, col in enumerate(header):
            if col in names:
                idx[key] = i
                break

    # 머리글을 못 찾으면 첫 줄부터 데이터로 본다 — 이름,이메일 두 칸짜리 파일이 흔하다
    if 'email' not in idx:
        idx = {'name': 0, 'email': 1} if len(header) > 1 else {'email': 0}
        body = rows
    else:
        body = rows[1:]

    def cell(row, key):
        i = idx.get(key)
        return (row[i].strip() if i is not None and i < len(row) else '')

    out = []
    for row in body:
        email = cell(row, 'email')
        if not email:
            continue
        out.append({
            'name': cell(row, 'name'),
            'emails': [email],
            'company': cell(row, 'company'),
            'tels': [cell(row, 'phone')] if cell(row, 'phone') else [],
            'memo': cell(row, 'memo'),
        })
    return out


def parse_contacts_file(raw, filename=''):
    """업로드된 주소록 파일 → 저장할 수 있는 연락처 목록.

    메일 한 개당 한 줄로 편다(vCard 한 장에 주소가 여럿일 수 있다).
    반환: (contacts, stats) — stats 는 화면에 그대로 적을 숫자다.
    """
    text = decode_bytes(raw)
    is_csv = filename.lower().endswith('.csv') or 'BEGIN:VCARD' not in text.upper()
    cards = parse_csv_contacts(text) if is_csv else parse_vcards(text)

    contacts = []
    seen = set()
    no_email = 0
    bad_email = 0
    for c in cards:
        if not c['emails']:
            no_email += 1
            continue
        for email in c['emails']:
            email = email.strip()
            if not _EMAIL_RE.match(email):
                bad_email += 1
                continue
            key = email.lower()
            if key in seen:          # 파일 안에서의 중복은 여기서 접는다
                continue
            seen.add(key)
            contacts.append({
                'name': c['name'] or email.split('@')[0],
                'email': email,
                'company': c.get('company', ''),
                'phone': ', '.join(c.get('tels') or []),
                'memo': c.get('memo', ''),
            })

    return contacts, {
        'cards': len(cards),
        'contacts': len(contacts),
        'no_email': no_email,
        'bad_email': bad_email,
        'format': 'csv' if is_csv else 'vcf',
    }


def _esc(v):
    return (str(v or '').replace('\\', '\\\\').replace('\n', '\\n')
            .replace(',', '\\,').replace(';', '\\;'))


def build_vcf(contacts):
    """연락처 목록 → vCard 3.0 문자열. 다음·네이버·구글이 그대로 되읽는 형식이다."""
    out = []
    for c in contacts:
        name = c.get('name') or c.get('email', '')
        out += ['BEGIN:VCARD', 'VERSION:3.0', f'FN:{_esc(name)}', f'N:;{_esc(name)};;;']
        if c.get('email'):
            out.append(f'EMAIL;TYPE=INTERNET:{_esc(c["email"])}')
        if c.get('company'):
            out.append(f'ORG:{_esc(c["company"])}')
        if c.get('phone'):
            out.append(f'TEL;TYPE=WORK:{_esc(c["phone"])}')
        if c.get('memo'):
            out.append(f'NOTE:{_esc(c["memo"])}')
        out.append('END:VCARD')
    # vCard 는 CRLF 다 — 아웃룩은 LF 만 있으면 한 장으로 뭉쳐 읽는다
    return '\r\n'.join(out) + '\r\n'
