"""aslist.md 형식으로 A/S 아카이브 매칭 결과 생성 → aslist2.md"""
import sqlite3
import json
import re
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from sqlalchemy import create_engine, text

engine = create_engine('postgresql://postgres:blues55088--@192.168.0.110:5433/postgres')


def extract_text(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, dict):
        return ''
    parts = []
    for node in content.get('content', []):
        for child in node.get('content', []):
            if child.get('type') == 'text':
                parts.append(child.get('text', ''))
    return ' '.join(parts).strip()


# 계약+보증 로딩
with engine.connect() as conn:
    rows = conn.execute(text(
        'SELECT c.id, c.contract_name, c.g2b_contract_no, '
        'w.id as wid, w.warranty_start, w.warranty_type '
        'FROM light_sync.contracts c '
        'LEFT JOIN light_sync.warranties w ON w.contract_id = c.id'
    )).fetchall()

contract_list = []
for r in rows:
    contract_list.append({
        'id': r.id,
        'name': r.contract_name or '',
        'g2b': r.g2b_contract_no or '',
        'wid': r.wid,
        'wstart': r.warranty_start,
        'wtype': r.warranty_type,
    })

# A/S 게시글
sq = sqlite3.connect('as.db')
sq.row_factory = sqlite3.Row
posts = sq.execute('SELECT * FROM posts ORDER BY created_at ASC').fetchall()


def find_best(ct):
    lines = [l.strip() for l in ct.split('\n') if l.strip()]
    candidates = []
    for line in lines[:10]:
        for prefix in ['계약명', '현장명', '현장', '건명', '건 명']:
            if prefix in line and ':' in line:
                val = line.split(':', 1)[1].strip()
                if val and len(val) >= 2:
                    candidates.append(val)
    if not candidates and lines:
        candidates.append(lines[0][:80])

    best_score = 0
    best = None
    best_reasons = []

    for cand in candidates:
        for c in contract_list:
            cname = c['name']
            parts = []
            total = 0

            cand_words = re.findall(r'[가-힣]{2,}', cand)
            for w in cand_words:
                if w in cname:
                    parts.append('현장명[%s]⊂계약명' % w)
                    total += 5

            cname_words = re.findall(r'[가-힣]{2,}', cname)
            for w in cname_words:
                if w in ct[:500]:
                    parts.append('계약명[%s]⊂본문' % w)
                    total += 5

            models = re.findall(r'[A-Z]{2,}[\-]?\d{2,}[A-Z]?', ct[:300])
            for m in models:
                if m in cname:
                    parts.append('모델[%s]일치' % m)
                    total += 3

            years_in_text = re.findall(r'20[12]\d', ct[:200])
            if c['wstart']:
                wy = str(c['wstart'])[:4]
                if wy in years_in_text:
                    parts.append('연도일치')
                    total += 3

            if total > best_score:
                best_score = total
                best = c
                best_reasons = parts[:6]

    return best_score, best, best_reasons


exact = []
weak = []
nomatch = []
idx = 0

for p in posts:
    ct = (p['content_text'] or '').strip()
    raw = json.loads(p['raw_json']) if p['raw_json'] else {}

    comments = []
    for c in raw.get('children', []):
        txt = extract_text(c.get('content', ''))
        if txt:
            comments.append(txt[:80])

    site_name = ''
    model_info = ''
    for line in ct.split('\n')[:10]:
        line = line.strip()
        for prefix in ['현장명', '계약명', '현장', '건명']:
            if prefix in line and ':' in line:
                site_name = line.split(':', 1)[1].strip()
                break
        if site_name:
            break
    for line in ct.split('\n')[:10]:
        line = line.strip()
        for prefix in ['품목', '품 목', '설치사양', '설치품목', '적용품명', '모델명', '납품품목']:
            if prefix in line and ':' in line:
                model_info = line.split(':', 1)[1].strip()[:60]
                break
        if model_info:
            break
    if not site_name:
        site_name = ct.split('\n')[0].strip()[:60] if ct else '(빈글)'

    score, matched, reasons = find_best(ct) if ct else (0, None, [])
    date_str = (p['created_at'] or '')[:10]
    idx += 1

    entry = {
        'idx': idx,
        'date': date_str,
        'site': site_name,
        'author': p['author'],
        'model': model_info,
        'children': p['children_count'],
        'original': ct.replace('\n', '  ')[:250],
        'score': score,
        'matched': matched,
        'reasons': reasons,
        'pid': p['id'],
    }

    if score >= 10:
        exact.append(entry)
    elif score >= 3:
        weak.append(entry)
    else:
        nomatch.append(entry)

# MD 출력
out = []
out.append('# A/S 이력 매칭 결과')
out.append('')
out.append('as.db %d건 (현장명⊂계약명 직접매칭 + 연도검증 + 모델매칭)' % len(posts))
out.append('- 정확 매칭: %d건 (score >= 10)' % len(exact))
out.append('- 약한 매칭: %d건 (score 3~9, 검토 필요)' % len(weak))
out.append('- 미매칭: %d건' % len(nomatch))
out.append('- **매칭률: %d%%**' % round((len(exact)+len(weak))/len(posts)*100))
out.append('')
out.append('---')
out.append('')

out.append('## 정확 매칭 (%d건)' % len(exact))
out.append('')
for e in exact:
    m = e['matched']
    child_str = ' (댓글 %d건)' % e['children'] if e['children'] else ''
    out.append('### %d. [%s] %s' % (e['idx'], e['date'], e['site']))
    out.append('- 작성자: %s / 품목: %s%s' % (e['author'], e['model'] or '-', child_str))
    out.append('- **[as.db 원문]** %s' % e['original'])
    if m:
        out.append('- **[매칭 결과]** contract %d: %s' % (m['id'], m['name'][:70]))
        wy = str(m['wstart'])[:4] if m['wstart'] else '-'
        out.append('- **[보증 정보]** 보증시작:%s / 유형:%s' % (wy, m['wtype'] or '-'))
    out.append('- **[매칭 근거]** score %d: %s' % (e['score'], ' / '.join(e['reasons'])))
    out.append('')

out.append('## 약한 매칭 (%d건, 검토 필요)' % len(weak))
out.append('')
for e in weak:
    m = e['matched']
    child_str = ' (댓글 %d건)' % e['children'] if e['children'] else ''
    out.append('### %d. [%s] %s' % (e['idx'], e['date'], e['site']))
    out.append('- 작성자: %s / 품목: %s%s' % (e['author'], e['model'] or '-', child_str))
    out.append('- **[as.db 원문]** %s' % e['original'])
    if m:
        out.append('- **[매칭 결과]** contract %d: %s' % (m['id'], m['name'][:70]))
    out.append('- **[매칭 근거]** score %d: %s' % (e['score'], ' / '.join(e['reasons'])))
    out.append('')

out.append('## 미매칭 (%d건)' % len(nomatch))
out.append('')
for e in nomatch:
    child_str = ' (댓글 %d건)' % e['children'] if e['children'] else ''
    out.append('### %d. [%s] %s' % (e['idx'], e['date'], e['site']))
    out.append('- 작성자: %s / 품목: %s%s' % (e['author'], e['model'] or '-', child_str))
    out.append('- **[as.db 원문]** %s' % e['original'])
    if e['matched']:
        out.append('- **[최근접]** contract %d: %s (score %d)' % (e['matched']['id'], e['matched']['name'][:50], e['score']))
    out.append('')

with open('aslist2.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))

print('정확: %d / 약한: %d / 미매칭: %d / 전체: %d' % (len(exact), len(weak), len(nomatch), len(posts)))
print('매칭률: %d%%' % round((len(exact)+len(weak))/len(posts)*100))
print('aslist2.md 저장 완료')

sq.close()
