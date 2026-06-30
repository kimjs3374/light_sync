"""카카오워크 전자결재 백업 열람 (public.approval_documents).

본문(body.html)·첨부는 Supabase Storage `approval/{doc_id}/` 에 저장됨.
이 모듈은 목록/상세 조회 + 본문 재구성(읽기 전용).

본문 주의: Storage의 body.html은 카카오워크 Vue 에디터 템플릿(외부 CDN+부모
postMessage 의존)이라 그대로는 렌더 불가. 대신 그 안에 임베드된 `let data = {...}`
에서 editor(리치텍스트)+content/contents(구조화 필드)를 추출해 자체 HTML로 재구성한다.
(외부 의존 없음 → 카카오워크 유료화/종료에도 영구 열람 가능)
"""
import os
import re
import json
import html as _html
import urllib.request

from sqlalchemy import text
from modules.db_context import get_db

try:
    import nh3
except ImportError:
    nh3 = None

PAGE_SIZE = 30

_SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
_BUCKET = 'company-files'

# 결재선 유형 코드 → 한글
_APPR_TYPE = {'DR': '기안', 'AP': '결재', 'AG': '합의', 'RV': '검토',
              'CC': '참조', 'PA': '전결', 'RT': '대결'}
# 의견 처리 코드 → 한글
_OPINION_TYPE = {'AC': '승인', 'RJ': '반려', 'RT': '회수', 'AG': '합의'}


def _public_url(key):
    return f'{_SUPABASE_URL}/storage/v1/object/public/{_BUCKET}/{key}' if _SUPABASE_URL else None


def body_url(doc_id):
    """문서 본문 body.html 공개 URL (원본 — Vue 템플릿)."""
    return _public_url(f'approval/{doc_id}/body.html')


# ─────────────────────────────────────────── 본문 재구성 (data 추출 → 자체 HTML)

_ALLOWED_TAGS = {
    'p', 'br', 'span', 'div', 'b', 'strong', 'i', 'em', 'u', 's', 'strike',
    'sub', 'sup', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre',
    'code', 'hr', 'ul', 'ol', 'li', 'a', 'img', 'figure', 'figcaption',
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th', 'colgroup', 'col', 'caption',
}
_ALLOWED_ATTRS = {
    '*': {'style', 'class', 'align', 'valign', 'width', 'height'},
    'a': {'href', 'title', 'target'},
    'img': {'src', 'alt', 'width', 'height', 'style'},
    'td': {'colspan', 'rowspan', 'style', 'align', 'valign', 'width'},
    'th': {'colspan', 'rowspan', 'style', 'align', 'valign', 'width'},
    'table': {'border', 'cellpadding', 'cellspacing', 'style', 'width'},
    'col': {'span', 'style', 'width'},
}
_URL_SCHEMES = {'http', 'https', 'data', 'mailto'}

# 구조화 필드 한글 라벨
_LABELS = {
    'date': '일자', 'item': '항목', 'cost': '금액', 'usage': '용도',
    'applyItem': '품목', 'standard': '규격', 'unit': '단위', 'quantity': '수량',
    'remark': '비고', 'startDate': '시작일', 'endDate': '종료일',
    'startTime': '시작시간', 'endTime': '종료시간', 'visitPlace': '방문지',
    'visitPurpose': '방문목적', 'issue': '내용',
}
# 내부/노이즈 키 제외
_SKIP_KEYS = {'isError', 'forKey', 'holidayList', 'empId', 'empNo', 'deptId',
              'deptCode', 'deptPathId', 'apprPassword', 'email', 'accountId',
              'officeLocation'}


def _sanitize(html_str):
    if not html_str:
        return ''
    if nh3:
        return nh3.clean(html_str, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS,
                         url_schemes=_URL_SCHEMES)
    s = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', '', html_str)
    return re.sub(r'(?i)\son\w+\s*=\s*"[^"]*"', '', s)


def _decode_editor(editor):
    """editor 본문 HTML 디코드.

    카카오워크 editor는 이중 HTML 인코딩(예: `&nbsp;`가 `&amp;amp;nbsp;`)이라
    1회 unescape로 태그(`&lt;`→`<`)를 복원한 뒤, **엔티티만 한 단계 더** 복원한다.
    (`&amp;nbsp;`→`&nbsp;`). 텍스트의 `<`,`>` 손상을 막기 위해 일반 unescape 2회는 쓰지 않음.
    """
    h = _html.unescape(editor)
    h = re.sub(r'&amp;(#?[0-9A-Za-z]+;)', r'&\1', h)
    return h


def _tidy(html_str):
    """연속된 빈 문단(<p><br></p>, <p> </p> 등)을 하나로 축약."""
    return re.sub(
        r'(?:<p>(?:\s|&nbsp;|<br\s*/?>)*</p>\s*){2,}',
        '<p><br></p>',
        html_str,
    )


def _extract_data(raw):
    """body.html의 `let data = {...}` JSON 추출 (중괄호 매칭)."""
    i = raw.find('let data = ')
    if i < 0:
        return None
    j = raw.find('{', i)
    if j < 0:
        return None
    depth = 0
    instr = False
    esc = False
    q = ''
    for k in range(j, len(raw)):
        c = raw[k]
        if instr:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == q:
                instr = False
        else:
            if c in '"\'':
                instr = True
                q = c
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[j:k + 1])
                    except Exception:
                        return None
    return None


def _fmt_val(v):
    if isinstance(v, dict):
        if 'hour' in v and 'min' in v:
            ap = '오전' if v.get('type') == 'AM' else '오후'
            return f"{ap} {v.get('hour', '')}:{v.get('min', '')}"
        return ', '.join(f'{k}: {x}' for k, x in v.items() if x not in (None, ''))
    if isinstance(v, (int, float)):
        return f'{v:,}'
    return str(v) if v is not None else ''


def _render_structured(td):
    parts = []
    contents = td.get('contents')
    if isinstance(contents, list) and contents:
        keys = []
        for row in contents:
            if isinstance(row, dict):
                for k in row:
                    if k not in _SKIP_KEYS and k not in keys:
                        keys.append(k)
        if keys:
            head = ''.join(f'<th>{_html.escape(_LABELS.get(k, k))}</th>' for k in keys)
            body = ''
            for row in contents:
                if not isinstance(row, dict):
                    continue
                tds = ''.join(f'<td>{_html.escape(_fmt_val(row.get(k, "")))}</td>' for k in keys)
                body += f'<tr>{tds}</tr>'
            parts.append(f'<div class="sec"><h4>상세 내역</h4>'
                         f'<table class="kv"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
    content = td.get('content')
    if isinstance(content, dict):
        rows = ''
        for k, v in content.items():
            if k in _SKIP_KEYS:
                continue
            val = _fmt_val(v)
            if not val or val in ('None', '0'):
                continue
            rows += f'<tr><th>{_html.escape(_LABELS.get(k, k))}</th><td>{_html.escape(val)}</td></tr>'
        if rows:
            parts.append(f'<div class="sec"><h4>내용</h4><table class="kv">{rows}</table></div>')
    return ''.join(parts)


_PAGE_CSS = """
  body{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;font-size:14px;
    color:#222;line-height:1.65;padding:18px;margin:0;}
  img{max-width:100%;height:auto;}
  table{border-collapse:collapse;margin:6px 0;max-width:100%;}
  td,th{border:1px solid #d3d6db;padding:6px 9px;font-size:13px;vertical-align:top;word-break:break-word;}
  th{background:#f5f6f8;}
  table.kv th{text-align:left;white-space:nowrap;}
  .sec{margin:18px 0;}
  .sec h4{font-size:14px;margin:0 0 8px;color:#333;border-left:3px solid #3457d5;padding-left:8px;}
  .editor>*:first-child{margin-top:0;}
"""


def build_body_html(doc_id):
    """body.html 원본에서 본문을 추출·sanitize해 자체 HTML 문서로 반환.

    iframe(sandbox)에서 그대로 렌더. 추출 실패 시 None.
    """
    src = body_url(doc_id)
    if not src:
        return None
    try:
        with urllib.request.urlopen(src, timeout=20) as r:
            raw = r.read().decode('utf-8', 'replace')
    except Exception:
        return None

    data = _extract_data(raw)
    inner = ''
    if isinstance(data, dict):
        td = data.get('templateData')
        if isinstance(td, dict):
            editor = td.get('editor')
            if editor:
                inner += f'<div class="editor">{_tidy(_sanitize(_decode_editor(editor)))}</div>'
            inner += _render_structured(td)

    if not inner.strip():
        inner = ('<p style="color:#999">본문 내용을 추출할 수 없습니다. '
                 '원본은 백업에 보존되어 있습니다.</p>')

    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<style>{_PAGE_CSS}</style></head><body>{inner}</body></html>')


def _fmt_size(n):
    n = n or 0
    if n < 1024:
        return f'{n}B'
    if n < 1024 * 1024:
        return f'{n/1024:.1f}KB'
    return f'{n/1024/1024:.2f}MB'


def list_docs(page, q, form):
    """문서대장 목록 (기안일 최신순)."""
    offset = (page - 1) * PAGE_SIZE
    wheres, params = [], {}
    if q:
        wheres.append("(doc_no ILIKE :q "
                      "OR detail_json->'info'->>'docSubject' ILIKE :q "
                      "OR list_json->>'draftEmpName' ILIKE :q)")
        params['q'] = f'%{q}%'
    if form:
        wheres.append("list_json->>'formName' = :form")
        params['form'] = form
    where_sql = ('WHERE ' + ' AND '.join(wheres)) if wheres else ''

    with get_db() as db:
        forms = [r[0] for r in db.execute(text("""
            SELECT DISTINCT list_json->>'formName' AS f
            FROM public.approval_documents
            WHERE list_json->>'formName' IS NOT NULL
            ORDER BY f
        """)).fetchall()]

        total = db.execute(text(
            f"SELECT COUNT(*) FROM public.approval_documents {where_sql}"
        ), params).fetchone()[0]

        rows = db.execute(text(f"""
            SELECT id, doc_no,
                   list_json->>'formName',     list_json->>'docSubject',
                   list_json->>'draftEmpName',  list_json->>'draftDeptName',
                   list_json->>'draftPositionName',
                   list_json->>'draftDate',     list_json->>'completeDate',
                   jsonb_array_length(COALESCE(detail_json->'attach','[]'))
            FROM public.approval_documents
            {where_sql}
            ORDER BY (list_json->>'draftDate') DESC NULLS LAST, id DESC
            LIMIT :lim OFFSET :off
        """), {**params, 'lim': PAGE_SIZE, 'off': offset}).fetchall()

    docs = []
    for r in rows:
        docs.append({
            'id': r[0], 'doc_no': r[1] or '',
            'form_name': r[2] or '', 'subject': r[3] or '(제목 없음)',
            'drafter': r[4] or '', 'dept': r[5] or '', 'position': r[6] or '',
            'draft_date': r[7] or '', 'complete_date': r[8] or '',
            'attach_count': r[9] or 0,
        })
    return docs, total, forms


def load_doc(doc_id):
    """문서 상세 (본문 iframe용 메타 + 결재선/의견/첨부)."""
    with get_db() as db:
        r = db.execute(text("""
            SELECT id, doc_no, list_json, detail_json
            FROM public.approval_documents WHERE id = :id
        """), {'id': doc_id}).fetchone()
    if not r:
        return None

    lj = r[2] or {}
    dj = r[3] or {}
    info = dj.get('info', {}) or {}

    appr_line = []
    for a in sorted(dj.get('apprLine', []) or [], key=lambda x: x.get('apprOrder') or 0):
        appr_line.append({
            'order': a.get('apprOrder') or 0,
            'name': a.get('empName', ''),
            'dept': a.get('deptName') or '',
            'position': a.get('positionName') or a.get('dutyName') or '',
            'type': _APPR_TYPE.get(a.get('apprType'), a.get('apprType') or ''),
            'at': a.get('apprAt') or '',
        })

    opinions = []
    for o in dj.get('opinion', []) or []:
        opinions.append({
            'name': o.get('empName', ''),
            'dept': o.get('deptName') or '',
            'position': o.get('positionName') or '',
            'opinion': o.get('apprOpinion') or '',
            'type': _OPINION_TYPE.get(o.get('opinionType'), ''),
            'at': o.get('apprAt') or '',
        })

    attachments = []
    for at in dj.get('attach', []) or []:
        fid = at.get('fileId')
        ftype = (at.get('fileType') or '').lower()
        key = f'approval/{doc_id}/{fid}.{ftype}' if ftype else f'approval/{doc_id}/{fid}'
        attachments.append({
            'name': at.get('orgFileName') or at.get('fileName') or str(fid),
            'size_fmt': _fmt_size(at.get('fileSize')),
            'ext': ftype,
            'url': _public_url(key),
        })

    references = [rf.get('empName') or rf.get('deptName') or ''
                 for rf in (dj.get('reference', []) or [])]

    return {
        'id': r[0],
        'doc_no': r[1] or info.get('docNo') or '',
        'subject': info.get('docSubject') or lj.get('docSubject') or '(제목 없음)',
        'form_name': info.get('formName') or lj.get('formName') or '',
        'drafter': lj.get('draftEmpName') or info.get('draftEmpName') or '',
        'dept': lj.get('draftDeptName') or info.get('draftDeptName') or '',
        'position': lj.get('draftPositionName') or info.get('draftPositionName') or '',
        'draft_date': lj.get('draftDate') or '',
        'complete_date': lj.get('completeDate') or '',
        'keep_year': info.get('keepYear'),
        'appr_line': appr_line,
        'opinions': opinions,
        'attachments': attachments,
        'references': [x for x in references if x],
    }
