"""
분할납품요구서 PDF 파싱 모듈.

나라장터(KONEPS) 표준 양식에서 API 미제공 필드를 추출한다.
- 계약체결번호, 계약체결일자
- 수수료, 합계금액
- 하자담보책임기간
- 검사기관, 검수기관
"""

import io
import re
import logging
from datetime import date

logger = logging.getLogger(__name__)


def req_no_candidates(req_no):
    """납품요구번호에서 조회에 쓸 후보를 우선순위대로 만든다.

    나라장터는 양식에 따라 변경차수를 다르게 붙인다.
    - 분할납품요구서: `R25TA00498993-00` (하이픈)
    - 물품계약서(최종): `R26TA0208569400` (하이픈 없이 뒤에 2자리)

    하이픈 없는 형태는 잘라낸 쪽이 맞을 때가 많지만, 번호 자체가 00으로
    끝나는 경우도 있어 단정하면 안 된다. 원본 → 절단본 순서로 후보를 주고
    호출부에서 실제로 매칭되는 것을 쓰게 한다.
    """
    if not req_no:
        return []
    no = re.sub(r'-\d{2}$', '', str(req_no).strip())
    cands = [no]
    if len(no) > 12 and no.endswith('00'):
        cands.append(no[:-2])
    return cands


def parse_contract_pdf(file_bytes):
    """
    분할납품요구서 PDF 바이트에서 핵심 필드를 추출한다.

    Returns:
        dict with keys:
            delivery_req_no: 납품요구번호
            contract_no: 계약체결번호
            contract_date: 계약체결일자 (date)
            req_date: 납품요구일자 (date)
            demand_org: 수요기관명
            demand_org_no: 수요기관번호
            business_name: 사업명
            supply_amount: 품대계
            fee: 수수료
            total_amount: 합계금액
            warranty_period: 하자담보책임기간
            inspection_org: 검사기관
            acceptance_org: 검수기관
            items: list of dicts (품목별 정보)
    """
    import pdfplumber

    text = ''
    fields = {}
    columns = {}
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + '\n'
            for name, value in _extract_form_fields(page).items():
                fields.setdefault(name, value)
            for name, value in _extract_summary_orgs(page).items():
                columns.setdefault(name, value)

    if not text.strip():
        raise ValueError("PDF에서 텍스트를 추출할 수 없습니다.")

    result = {}

    # 물품계약서(최종) 양식 판별
    is_contract_form = '물품계약서' in text and '계약일자' in text

    if is_contract_form:
        _parse_contract_form(text, result, fields)
    else:
        _parse_delivery_req_form(text, result, columns)

    # --- 품목 정보 (양식별) ---
    result['items'] = _parse_contract_items(text) if is_contract_form else _parse_items(text)

    logger.info("PDF 파싱 결과: 납품요구번호=%s, 계약번호=%s, 수수료=%s",
                result.get('delivery_req_no'), result.get('contract_no'), result.get('fee'))

    return result


# ── 좌표 기반 폼 필드 추출 ──
#
# 물품계약서(최종)는 괘선 없는 2단 폼이라 pdfplumber가 표로 인식하지 못한다.
# 게다가 셀 값이 두 줄로 접히면 텍스트 추출 시 `값1행 / 라벨행 / 값2행` 순서로
# 흩어져 나와, 라벨 뒤를 정규식으로 긁는 방식은 뒷조각만 잡는다.
# (실제로 `검수기관`이 "구" 한 글자로 저장된 사고가 있었다.)
# 그래서 단어 좌표로 라벨의 값 영역을 잡고, 접힌 줄을 다시 이어붙인다.

_LABEL_RUN_MAX_CHARS = 3     # 라벨은 "검 사 기 관:" 처럼 낱글자로 흩어진다
_LABEL_RUN_MAX_GAP = 15.0    # 낱글자 사이 간격(pt). 이보다 벌어지면 다른 칸
_LINE_TOL = 3.0              # 같은 줄로 볼 top 오차(pt)
_WRAP_MAX_DIST = 14.0        # 라벨줄에 붙일 수 있는 접힌 줄의 최대 거리(pt)


def _group_lines(words):
    """단어를 top 좌표 기준으로 줄 단위 묶는다."""
    lines = []
    for w in sorted(words, key=lambda x: (x['top'], x['x0'])):
        for ln in lines:
            if abs(ln['top'] - w['top']) <= _LINE_TOL:
                ln['words'].append(w)
                ln['top'] = min(ln['top'], w['top'])
                break
        else:
            lines.append({'top': w['top'], 'words': [w]})
    for ln in lines:
        ln['words'].sort(key=lambda x: x['x0'])
    lines.sort(key=lambda l: l['top'])
    return lines


def _find_labels(line):
    """한 줄에서 `계 약 번 호:` 같은 라벨 그룹을 찾아 이름과 x 범위를 돌려준다."""
    labels = []
    run = []
    for w in line['words']:
        t = w['text']
        if run and w['x0'] - run[-1]['x1'] > _LABEL_RUN_MAX_GAP:
            run = []
        if t.endswith(':'):
            name = ''.join(p['text'] for p in run + [w]).rstrip(':').strip()
            if name:
                labels.append({
                    'name': name,
                    'x0': (run[0] if run else w)['x0'],
                    'x1': w['x1'],
                })
            run = []
        elif len(t) <= _LABEL_RUN_MAX_CHARS:
            run.append(w)
        else:
            run = []
    return labels


def _extract_form_fields(page):
    """페이지의 `라벨: 값` 쌍을 좌표로 읽어 {라벨명: 값} 으로 돌려준다."""
    try:
        words = page.extract_words()
    except Exception:  # pragma: no cover - pdfplumber 내부 오류 방어
        logger.warning("단어 좌표 추출 실패 — 정규식 파싱만 사용합니다.", exc_info=True)
        return {}

    lines = _group_lines(words)
    for ln in lines:
        ln['labels'] = _find_labels(ln)

    label_lines = [ln for ln in lines if ln['labels']]
    if not label_lines:
        return {}

    # 접힌 값 줄(라벨 없는 줄)을 가장 가까운 라벨줄에 붙인다
    for ln in label_lines:
        ln['extra'] = []
    for ln in lines:
        if ln['labels']:
            continue
        nearest = min(label_lines, key=lambda t: abs(t['top'] - ln['top']))
        if abs(nearest['top'] - ln['top']) <= _WRAP_MAX_DIST:
            nearest['extra'].append(ln)

    fields = {}
    for ln in label_lines:
        for idx, label in enumerate(ln['labels']):
            # 값 영역 = 라벨 오른쪽 ~ 같은 줄 다음 라벨 왼쪽
            right = ln['labels'][idx + 1]['x0'] if idx + 1 < len(ln['labels']) else page.width

            def in_region(w):
                return w['x0'] >= label['x1'] - 1 and w['x0'] < right - 1

            # 라벨 그룹 자체를 값으로 오인하지 않도록 제외
            same_line = [w for w in ln['words'] if in_region(w)
                         and not any(l['x0'] <= w['x0'] < l['x1'] for l in ln['labels'])]

            parts = []
            for extra in sorted(ln['extra'], key=lambda t: t['top']):
                if extra['top'] < ln['top']:
                    parts.append([w for w in extra['words'] if in_region(w)])
            parts.append(same_line)
            for extra in sorted(ln['extra'], key=lambda t: t['top']):
                if extra['top'] >= ln['top']:
                    parts.append([w for w in extra['words'] if in_region(w)])

            # 같은 줄 안은 공백으로, 접힌 줄 사이는 붙여서 이어야 원래 값이 된다
            value = ''.join(' '.join(w['text'] for w in p) for p in parts if p).strip()
            if value and label['name'] not in fields:
                fields[label['name']] = re.sub(r'\s+', ' ', value)

    return fields


_SUMMARY_HEADERS = ['품대계', '수수료', '합계금액', '분할납품', '검사', '검수']
_SUMMARY_COL_GAP = 15.0      # 헤더 낱글자를 칸으로 묶는 간격(pt)


def _extract_summary_orgs(page):
    """분할납품요구서 요약표에서 검사기관 / 검수기관을 칸 좌표로 읽는다.

    이 표도 값이 두 줄로 접힌다. 게다가 검사·검수 칸의 글자가 붙어 있으면
    pdfplumber가 `한국화학융합시험연구전라남도신안군보건` 처럼 두 칸을 한 단어로
    합쳐버려 단어 단위로는 절대 못 나눈다. 그래서 글자(char) 좌표로 칸을 가른다.

    금액 칸은 오른쪽 정렬이라 헤더 기준으로 자르면 끝자리가 옆 칸으로 넘어간다.
    금액은 기존 정규식이 이미 정확하므로 여기서는 기관명만 다룬다.
    """
    try:
        chars = [c for c in page.chars if (c.get('text') or '').strip()]
    except Exception:  # pragma: no cover - pdfplumber 내부 오류 방어
        logger.warning("글자 좌표 추출 실패 — 정규식 파싱만 사용합니다.", exc_info=True)
        return {}

    lines = _group_lines(chars)
    header = next((i for i, ln in enumerate(lines)
                   if ''.join(w['text'] for w in ln['words']) == ''.join(_SUMMARY_HEADERS)), None)
    if header is None:
        return {}

    # 헤더 낱글자 → 칸 묶음
    groups = []
    for w in lines[header]['words']:
        if groups and w['x0'] - groups[-1][-1]['x1'] <= _SUMMARY_COL_GAP:
            groups[-1].append(w)
        else:
            groups.append([w])
    if [''.join(c['text'] for c in g) for g in groups] != _SUMMARY_HEADERS:
        return {}

    value_lines = []
    for ln in lines[header + 1:header + 6]:
        if '사업명' in ''.join(w['text'] for w in ln['words']):
            break
        value_lines.append(ln)
    if not value_lines:
        return {}

    # 기관명은 칸 안에서 가운데 정렬이라 헤더보다 넓게 퍼진다.
    # 검사 칸의 왼쪽 경계는 헤더가 아니라 분할납품 값(가능/불가능) 끝을 기준 삼는다.
    left = groups[3][-1]['x1']
    for ln in value_lines:
        chars = ln['words']
        joined = ''.join(c['text'] for c in chars)
        pos = joined.find('가능')
        if pos >= 0:
            left = max(left, chars[pos + 1]['x1'])
    # 검사 / 검수는 서로 맞닿아 있어 헤더 중간점이 곧 칸 경계다
    mid = (groups[4][-1]['x1'] + groups[5][0]['x0']) / 2

    orgs = {'검사': [], '검수': []}
    for ln in value_lines:
        for name, (lo, hi) in (('검사', (left, mid)), ('검수', (mid, page.width))):
            seg = ''.join(c['text'] for c in ln['words']
                          if lo <= (c['x0'] + c['x1']) / 2 < hi)
            if seg:
                orgs[name].append(seg)

    return {name: ''.join(parts) for name, parts in orgs.items() if parts}


def _field(fields, *names):
    """여러 표기 중 먼저 잡히는 값을 돌려준다."""
    for n in names:
        v = (fields.get(n) or '').strip()
        if v:
            return v
    return ''


def _parse_date(s):
    """날짜 문자열 → date 객체. 2026/04/01, 2026.04.01 등 지원."""
    if not s:
        return None
    s = s.replace('/', '.').replace('-', '.')
    parts = s.split('.')
    if len(parts) == 3:
        try:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            pass
    return None


def _parse_contract_form(text, result, fields=None):
    """물품계약서(최종) 양식 파싱.

    fields: 좌표 기반으로 읽은 {라벨: 값}. 두 줄로 접힌 칸까지 복원되므로
            기관명처럼 잘려나가기 쉬운 항목은 이쪽을 우선 쓴다.
    """
    fields = fields or {}

    # --- 계약번호 (R26TA..., R25TB... 등) ---
    m = re.search(r'계\s*약\s*번\s*호\s*:?\s*([A-Za-z0-9]+)', text)
    if m:
        result['delivery_req_no'] = m.group(1).strip()
        result['contract_no'] = m.group(1).strip()

    # --- 계약일자 ---
    m = re.search(r'계약일자\s*:?\s*(\d{4}/\d{2}/\d{2})', text)
    if m:
        result['contract_date'] = _parse_date(m.group(1))

    # --- 계약건명 ---
    m = re.search(r'계\s*약\s*건\s*명\s*:?\s*(.+?)(?:\n|$)', text)
    if m:
        result['business_name'] = re.sub(r'\s+', ' ', m.group(1)).strip()

    # --- 계약금액 ---
    m = re.search(r'계\s*약\s*금\s*액\s*:?\s*([\d,]+)\s*원', text)
    if m:
        result['supply_amount'] = int(m.group(1).replace(',', ''))

    # --- 수수료 ---
    m = re.search(r'수\s*수\s*료\s*:?\s*([\d,]+)\s*원', text)
    if m:
        result['fee'] = int(m.group(1).replace(',', ''))

    # --- 합계금액 (계약금액 + 수수료) ---
    if result.get('supply_amount') and result.get('fee'):
        result['total_amount'] = result['supply_amount'] + result['fee']

    # --- 납품기한 ---
    m = re.search(r'납\s*품\s*기\s*한\s*:?\s*(\d{4}/\d{2}/\d{2})', text)
    if m:
        result['delivery_due'] = _parse_date(m.group(1))

    # --- 수요기관명 / 검사기관 / 검수기관 ---
    # 접힘 복원이 되는 좌표 결과를 우선. 없을 때만 정규식 폴백.
    demand_org = _field(fields, '수요기관명')
    if not demand_org:
        m = re.search(r'수\s*요\s*기\s*관\s*명\s*:?\s*(.+?)(?:\s{2,}|분)', text)
        demand_org = m.group(1).strip() if m else ''
    if demand_org:
        result['demand_org'] = demand_org

    inspection = _field(fields, '검사기관')
    if not inspection:
        m = re.search(r'검\s*사\s*기\s*관\s*:?\s*(.+?)(?:\s{2,}|검\s*수)', text)
        inspection = m.group(1).strip() if m else ''
    if inspection:
        result['inspection_org'] = inspection

    acceptance = _field(fields, '검수기관')
    if not acceptance:
        m = re.search(r'검\s*수\s*기\s*관\s*:?\s*(.+?)(?:\n|$)', text)
        acceptance = m.group(1).strip() if m else ''
    if acceptance:
        result['acceptance_org'] = acceptance

    # --- 하자담보책임기간 ---
    m = re.search(r'하자담보책임기간\s*:?\s*(\d+)\s*년', text)
    if m:
        result['warranty_period'] = f"{m.group(1)}년"

    # --- 지체상금률 ---
    m = re.search(r'지\s*체\s*상\s*금\s*률\s*:?\s*([\d.]+)\s*%', text)
    if m:
        result['penalty_rate'] = m.group(1)

    # --- 하자보수보증금률 ---
    m = re.search(r'하자보수보증금률\s*:?\s*([\d.]+)\s*%', text)
    if m:
        result['warranty_bond_rate'] = m.group(1)

    # --- 품명, 수량 ---
    m = re.search(r'품\s*명\s*:?\s*(.+?)\s+수\s*량\s*:?\s*(\d+)', text)
    if m:
        result['product_name'] = m.group(1).strip()
        result['quantity'] = int(m.group(2))


def _parse_delivery_req_form(text, result, columns=None):
    """분할납품요구서 양식 파싱.

    columns: 요약표를 칸 좌표로 읽은 결과. 접힌 기관명이 복원되므로 우선 사용한다.
    """
    # --- 납품요구번호 ---
    m = re.search(r'납\s*품\s*요\s*구\s*번\s*호\s*:?\s*([A-Za-z0-9\-]+)', text)
    if m:
        result['delivery_req_no'] = m.group(1).strip()

    # --- 계약번호 + 계약일자 ---
    m = re.search(r'계약번호\s*제\s*([A-Za-z0-9\-]+)\s*호\s*\(\s*(\d{4}[./]\d{2}[./]\d{2})\s*\)', text)
    if m:
        result['contract_no'] = m.group(1).strip()
        result['contract_date'] = _parse_date(m.group(2))

    # --- 납품요구일자 ---
    m = re.search(r'납\s*품\s*요\s*구\s*일\s*자\s*:?\s*(\d{4}[./]\d{2}[./]\d{2})', text)
    if m:
        result['req_date'] = _parse_date(m.group(1))

    # --- 수요기관 ---
    m = re.search(r'수\s*요\s*기\s*관\s*:?\s*([^\s계나사문하][\w\s]*?)(?:\s{2,}|계)', text)
    if m:
        result['demand_org'] = m.group(1).strip()

    # --- 수요기관번호 ---
    m = re.search(r'수\s*요\s*기\s*관\s*번\s*호\s*:?\s*(\d+)', text)
    if m:
        result['demand_org_no'] = m.group(1).strip()

    # --- 하자담보책임기간 ---
    m = re.search(r'하자담보책임기간\s*:?\s*(\d+)\s*년', text)
    if m:
        result['warranty_period'] = f"{m.group(1)}년"

    # --- 품대계, 수수료, 합계금액, 분할납품, 검사, 검수 ---
    _parse_summary_table(text, result, columns)

    # --- 사업명 ---
    m = re.search(r'사\s*업\s*명\s*:\s*(.+?)(?:\n|순)', text)
    if m:
        result['business_name'] = re.sub(r'\s+', ' ', m.group(1)).strip()


def _parse_summary_table(text, result, columns=None):
    """품대계 / 수수료 / 합계금액 / 분할납품 / 검사 / 검수 행을 파싱한다."""
    columns = columns or {}

    # 금액 행 패턴: 연속된 숫자,콤마 3개 + 가능/불가능 + 검사기관 + 검수기관
    # 예: 9,720,000 47,230 9,767,230 가능 전라남도 전라남도
    # 예: 4,650,000 25,110 4,675,110 가능 한국광기술원 전라남도
    pattern = (
        r'([\d,]+)\s+'           # 품대계
        r'([\d,]+)\s+'           # 수수료
        r'([\d,]+)\s+'           # 합계금액
        r'(가능|불가능)\s+'       # 분할납품
        r'(.+?)\s+'              # 검사기관
        r'(.+?)(?:\n|$)'         # 검수기관
    )
    m = re.search(pattern, text)
    if m:
        result['supply_amount'] = int(m.group(1).replace(',', ''))
        result['fee'] = int(m.group(2).replace(',', ''))
        result['total_amount'] = int(m.group(3).replace(',', ''))
        result['split_delivery'] = m.group(4).strip()
        result['inspection_org'] = m.group(5).strip()
        result['acceptance_org'] = m.group(6).strip()
    else:
        # 폴백: 개별 파싱
        amounts = re.findall(r'([\d,]{5,})', text[:text.find('사 업 명') if '사 업 명' in text else 2000])
        if len(amounts) >= 3:
            result['supply_amount'] = int(amounts[0].replace(',', ''))
            result['fee'] = int(amounts[1].replace(',', ''))
            result['total_amount'] = int(amounts[2].replace(',', ''))

    # 접힌 기관명은 정규식으로 복원할 수 없다 — 칸 좌표로 읽힌 값이 있으면 덮어쓴다
    if columns.get('검사'):
        result['inspection_org'] = columns['검사']
    if columns.get('검수'):
        result['acceptance_org'] = columns['검수']


def _parse_items(text):
    """품목 테이블에서 단가, 수량, 납품기한, 물품분류/식별번호를 추출한다.

    KONEPS 분할납품요구서는 텍스트 추출 시 `단가 수량 납품기한`이 먼저 나오고,
    바로 다음 줄에 `순번 + 물품분류번호(8) + 물품식별번호(8+)`가 이어진다.
    기존 정규식은 식별번호를 먼저 잡고 뒤쪽 단가/수량을 찾아 한 칸씩 밀려 매칭되고
    마지막 품목을 누락하는 버그가 있어, 실제 레이아웃 순서대로 다시 작성한다.
    """
    items = []

    item_pattern = re.findall(
        r'([\d,]+)(?:\.\d+)?\s+'      # 단가
        r'(\d+)\s+'                  # 수량
        r'(\d{4}/\d{2}/\d{2})\s*\n'  # 납품기한 + 줄바꿈
        r'\s*\d+\s+'                 # 순번
        r'(\d{8})(\d{8,})',          # 물품분류번호 + 물품식별번호
        text
    )

    for unit_price, qty_s, date_s, class_no, ident_no in item_pattern:
        item = {
            'product_class_no': class_no,
            'product_ident_no': ident_no,
            'unit_price': int(unit_price.replace(',', '')),
            'quantity': int(qty_s),
        }
        item['amount'] = item['unit_price'] * item['quantity']
        # 납품기한
        date_parts = date_s.split('/')
        if len(date_parts) == 3:
            try:
                item['delivery_date'] = date(int(date_parts[0]), int(date_parts[1]), int(date_parts[2]))
            except ValueError:
                pass
        items.append(item)

    return items


def _parse_contract_items(text):
    """물품계약서(최종) 뒤에 붙는 `계약물품명세서` 표에서 품목을 추출한다.

    표 레이아웃(텍스트 추출 순서):
        물품분류번호 물품식별번호 품명 규격 지역 단위
        인도조건 수량 단가 계약금액 수요기관 납품기한
    규격·수요기관이 길면 위아래 줄로 접혀 순번과 뒤섞이므로,
    번호쌍과 금액행을 각각 순서대로 뽑아 짝지운다.
    """
    # 본문 첫머리의 "별첨계약물품명세서,..." 문장이 아니라 독립된 표 제목을 찾는다
    m = re.search(r'\n\s*계약물품명세서\s*\n', text)
    if not m:
        return []
    section = text[m.end():]

    numbers = re.findall(r'(\d{8})\s+(\d{8,})\s', section)
    rows = re.findall(
        r'\s(\d+)\s+'                 # 수량
        r'([\d,]{3,})\s+'             # 단가
        r'([\d,]{3,})\s+'             # 계약금액
        r'(?:\S+\s+)?'                # 수요기관(같은 줄에 붙어 나올 때만)
        r'(\d{4}/\d{2}/\d{2})',       # 납품기한
        section
    )

    if len(numbers) != len(rows):
        logger.warning("계약물품명세서 파싱 불일치 — 번호 %d건 / 금액행 %d건. 품목 반영을 건너뜁니다.",
                       len(numbers), len(rows))
        return []

    items = []
    for (class_no, ident_no), (qty_s, uprc_s, amt_s, date_s) in zip(numbers, rows):
        qty = int(qty_s)
        unit_price = int(uprc_s.replace(',', ''))
        amount = int(amt_s.replace(',', ''))
        # 열이 밀려 엉뚱한 값을 잡으면 수량·단가가 그대로 조달내역에 덮여쓰인다.
        # 단가×수량=금액이 맞을 때만 신뢰한다.
        if unit_price * qty != amount:
            logger.warning("계약물품명세서 금액 불일치 — 식별번호 %s (%s x %s != %s). 품목 반영을 건너뜁니다.",
                           ident_no, uprc_s, qty_s, amt_s)
            return []
        item = {
            'product_class_no': class_no,
            'product_ident_no': ident_no,
            'unit_price': unit_price,
            'quantity': qty,
            'amount': amount,
        }
        parts = date_s.split('/')
        try:
            item['delivery_date'] = date(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            pass
        items.append(item)

    return items


def update_procurement_from_pdf(db_session, parsed_data):
    """
    파싱 결과를 g2b_procurements 테이블에 보완 저장한다.
    납품요구번호로 매칭하여 PDF 전용 필드를 업데이트한다.

    Returns:
        int: 업데이트된 레코드 수
    """
    from modules.models.misc_entities import G2bProcurement

    req_no_raw = parsed_data.get('delivery_req_no')
    if not req_no_raw:
        logger.warning("납품요구번호 없음 — PDF 파싱 결과를 저장할 수 없습니다.")
        return 0

    # 변경차수 suffix 제거 — 양식마다 `-00` / `00` 으로 달라 후보를 차례로 시도한다
    candidates = req_no_candidates(req_no_raw)
    records, req_no = [], (candidates[0] if candidates else req_no_raw)
    for cand in candidates:
        records = db_session.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == cand
        ).all()
        if records:
            req_no = cand
            break

    if not records:
        logger.warning("납품요구번호 %s에 해당하는 조달내역이 없습니다. (후보: %s)",
                       req_no_raw, ', '.join(candidates))
        return 0

    # 재업로드(변경계약 PDF) 대응 — 파싱된 값이 있으면 항상 덮어쓴다.
    updated = 0
    for rec in records:
        changed = False
        for src_key, attr in (
            ('contract_no', 'pdf_contract_no'),
            ('contract_date', 'pdf_contract_date'),
            ('fee', 'pdf_fee'),
            ('total_amount', 'pdf_total_amount'),
            ('warranty_period', 'pdf_warranty_period'),
            ('inspection_org', 'pdf_inspection_org'),
            ('acceptance_org', 'pdf_acceptance_org'),
        ):
            new_val = parsed_data.get(src_key)
            if new_val and getattr(rec, attr) != new_val:
                setattr(rec, attr, new_val)
                changed = True
        if changed:
            updated += 1

    # --- 품목별 수량/단가/금액 갱신 (계약서 PDF 기준, 물품식별번호 매칭) ---
    # 변경계약 PDF를 올리면 줄어든 수량/금액이 g2b_procurements 라인에 반영되도록 한다.
    by_ident = {
        str(it['product_ident_no']): it
        for it in (parsed_data.get('items') or [])
        if it.get('product_ident_no')
    }
    for rec in records:
        it = by_ident.get(str(rec.prdct_idnt_no))
        if not it:
            continue
        item_changed = False
        qty, uprc, amt = it.get('quantity'), it.get('unit_price'), it.get('amount')
        if qty is not None and rec.prdct_qty != qty:
            rec.prdct_qty = qty
            item_changed = True
        if uprc is not None and rec.prdct_uprc != uprc:
            rec.prdct_uprc = uprc
            item_changed = True
        if amt is not None and rec.prdct_amt != amt:
            rec.prdct_amt = amt
            item_changed = True
        if item_changed:
            updated += 1

    if updated:
        db_session.commit()
        logger.info("납품요구번호 %s: %d건 PDF 보완 필드 업데이트", req_no, updated)

    return updated
