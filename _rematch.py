"""
as.db A/S 이력 ↔ warranty 매칭
archive_matching_spec.md 4단계 로직 적용:
  1. 건명 추출
  2. SequenceMatcher 유사도 (임계값 0.5)
  3. 포함관계 매칭 (3글자 이상)
  4. 키워드 교집합 (임계값 0.3)
"""
import sys, io, sqlite3, json, re
from difflib import SequenceMatcher
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from modules.db_context import get_db
from modules.models.entities import Warranty, Contract

# 보존할 매칭계약
with open('aslist.md', 'r', encoding='utf-8') as f:
    old = f.read()
preserve = {}
for m in re.finditer(r'### \d+\.\s+\[(\d{4}-\d{2}-\d{2})\]\s+(.+?)[\n].*?\*\*매칭계약\*\*\s*[:：]\s*(.*)', old):
    key = f'{m.group(1)}|{m.group(2).strip()[:20]}'
    preserve[key] = m.group(3).strip()
print(f'보존 매칭계약: {len(preserve)}건')

# as.db
conn = sqlite3.connect('as.db')
rows = conn.execute('SELECT id, author, content_text, created_at, raw_json FROM posts ORDER BY created_at').fetchall()
conn.close()

as_items = []
for pid, author, content, created, raw_json in rows:
    if not content or not content.strip():
        continue
    rj = json.loads(raw_json)
    children_texts = []
    for child in rj.get('children', []):
        ct = child.get('content', {})
        if isinstance(ct, dict):
            for block in ct.get('content', []):
                for item in block.get('content', []):
                    if item.get('type') == 'text':
                        children_texts.append(item.get('text', ''))
    full_text = content + '\n' + '\n'.join(children_texts)

    # 건명 추출 (archive_matching_spec 2-1 로직)
    candidates = []
    for pat in [r'현장명\s*[:：]\s*(.+?)(?:\n|$)',
                r'(?:계약명|건명|건 명)\s*[:：]\s*(.+?)(?:\n|$)',
                r'현장\s*[:：]\s*(.+?)(?:\n|$)']:
        m = re.search(pat, content)
        if m:
            candidates.append(m.group(1).strip()[:80])
    if not candidates:
        first = content.strip().split('\n')[0].strip('* ').strip()[:80]
        if len(first) >= 3:
            candidates.append(first)

    m3 = re.search(r'(?:품목|품명|설치품목|설치사양|납품품목|적용품명|적용제품)\s*[:：]\s*(.+?)(?:\n|$)', full_text)
    item_text = m3.group(1).strip()[:50] if m3 else ''
    name = candidates[0] if candidates else content.strip().split('\n')[0][:60]

    as_items.append({
        'pid': pid, 'date': created[:10], 'author': author,
        'name': name, 'item': item_text,
        'candidates': candidates,
        'full_text': full_text,
        'children_count': rj.get('children_count', 0),
    })

# warranty
with get_db() as db:
    w_all = []
    for w in db.query(Warranty).all():
        w_all.append({
            'id': w.id,
            'contract_name': w.contract_name or '',
            'model': w.model_name or '',
            'year': str(w.warranty_start.year) if w.warranty_start else '',
            'start': str(w.warranty_start) if w.warranty_start else '',
        })

# 매칭 (archive_matching_spec 4단계)
def match_entry(entry, w_list):
    candidates = entry['candidates']
    full_text = entry['full_text'][:500]
    # 키워드는 건명(candidates)에서만 추출 — 본문 전체는 잡음이 많음
    cand_text = ' '.join(candidates)
    kw_text = set(re.findall(r'[가-힣]{2,}', cand_text))

    best_wid = None
    best_score = 0
    best_method = ''

    for w in w_list:
        wname = w['contract_name']
        if not wname:
            continue

        score = 0
        method = ''

        for cand in candidates:
            # 2-2. SequenceMatcher 유사도
            ratio = SequenceMatcher(None, cand, wname).ratio()
            if ratio > score:
                score = ratio
                method = f'유사도 {ratio:.2f}'

            # 2-3. 포함관계
            if len(cand) >= 3 and cand in wname:
                s = 0.9
                if s > score:
                    score = s
                    method = f'포함: [{cand}]⊂계약명'
            # 역방향: 계약명 핵심부분이 건명에 포함 (4글자 이상, 공통어 제외)
            wname_clean = re.sub(r'\(.*?\)', '', wname).strip()
            wname_parts = [p for p in re.split(r'[\s\-/,]+', wname_clean) if len(p) >= 4]
            common_facility = {'테니스장','축구장','운동장','체육관','체육공원','가로등','보안등',
                              '투광등','초등학교','중학교','고등학교','조명타워','태양광가로등',
                              '실내체육관','종합운동장','공설운동장'}
            for wp in wname_parts:
                if wp in cand and wp not in common_facility:
                    s = 0.85
                    if s > score:
                        score = s
                        method = f'역포함: [{wp}]⊂건명'

        # 2-4. 키워드 교집합 (정확일치 + 부분포함)
        wname_kw = set(re.findall(r'[가-힣]{2,}', wname))
        if kw_text and wname_kw:
            # 정확 일치
            inter = kw_text & wname_kw
            # 부분 포함: as.db 키워드가 warranty 키워드에 포함되거나 그 반대
            partial = set()
            for ak in kw_text:
                if len(ak) < 2: continue
                for wk in wname_kw:
                    if len(wk) < 2: continue
                    if ak in wk or wk in ak:
                        partial.add(ak)
            all_matches = inter | partial
            ratio_kw = len(all_matches) / max(len(kw_text), len(wname_kw))
            if ratio_kw > score:
                score = ratio_kw
                method = f'키워드교집합 {ratio_kw:.2f} ({",".join(list(all_matches)[:5])})'

        if score > best_score:
            best_score = score
            best_wid = w['id']
            best_method = method

    return best_wid, best_score, best_method

matched, unmatched = [], []
for entry in as_items:
    wid, score, method = match_entry(entry, w_all)

    pkey = f'{entry["date"]}|{entry["name"][:20]}'
    pval = preserve.get(pkey)
    content_summary = entry['full_text'].replace('\n', ' ').strip()[:250]

    w_detail = ''
    if wid:
        for w in w_all:
            if w['id'] == wid:
                w_detail = f'보증시작:{w["year"]} / 모델:{w["model"]}'
                break

    e = {
        'date': entry['date'], 'author': entry['author'],
        'name': entry['name'][:60], 'item': entry['item'][:40],
        'score': score, 'method': method,
        'preserved': pval, 'children': entry['children_count'],
        'content_summary': content_summary, 'w_detail': w_detail,
    }

    if wid and score >= 0.5:
        e['wid'] = wid
        for w in w_all:
            if w['id'] == wid:
                e['wname'] = w['contract_name'][:70]
                break
        matched.append(e)
    else:
        unmatched.append(e)

# 출력
total = len(matched) + len(unmatched)
lines = []
lines.append('# A/S 이력 매칭 결과')
lines.append('')
lines.append(f'as.db {total}건 (archive_matching_spec 4단계 로직: 유사도+포함관계+키워드교집합)')
lines.append(f'- 정확 매칭: {len(matched)}건 (score >= 0.5)')
lines.append(f'- 미매칭: {len(unmatched)}건')
lines.append(f'- **매칭률: {len(matched)*100//total}%**')
lines.append('')
lines.append('---')
lines.append('')

def write_e(ls, i, e, show_w=True):
    ls.append(f'### {i}. [{e["date"]}] {e["name"]}')
    extra = f' (댓글 {e["children"]}건)' if e['children'] else ''
    ls.append(f'- 작성자: {e["author"]} / 품목: {e["item"] or "-"}{extra}')
    ls.append(f'- **[as.db 원문]** {e["content_summary"]}')
    if show_w and 'wid' in e:
        ls.append(f'- **[매칭 결과]** warranty {e["wid"]}: {e["wname"]}')
        ls.append(f'- **[보증 정보]** {e["w_detail"]}')
        ls.append(f'- **[매칭 방법]** {e["method"]} (score {e["score"]:.2f})')
    if e.get('preserved') is not None:
        ls.append(f'- **매칭계약** : {e["preserved"]}')
    ls.append('')

lines.append(f'## 정확 매칭 ({len(matched)}건)')
lines.append('')
for i, e in enumerate(matched, 1): write_e(lines, i, e)
lines.append('---')
lines.append('')
lines.append(f'## 미매칭 ({len(unmatched)}건)')
lines.append('')
for i, e in enumerate(unmatched, 1): write_e(lines, i, e, show_w=False)

with open('aslist.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'완료: 정확 {len(matched)} / 미매칭 {len(unmatched)} / 매칭률 {len(matched)*100//total}%')
