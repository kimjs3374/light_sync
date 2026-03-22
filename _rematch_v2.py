"""
as.db A/S 매칭 v2 — 지명 기반 심플 매칭
1. 건명/본문에서 지명 추출
2. 지명으로 warranty 필터
3. 필터 결과 중 시설명/모델명으로 1건 특정
4. 특정 안 되면 미매칭 (솔직하게 기록)
"""
import sys, io, sqlite3, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from difflib import SequenceMatcher
from modules.db_context import get_db
from modules.models.entities import Warranty, Contract, G2bProcurement

# 시설/일반 단어 (지명 추출 시 제외)
NOT_PLACE = {
    '종합운동장','공설운동장','테니스장','축구장','야구장','체육관','운동장',
    '체육공원','생활체육공원','실내체육관','다목적체육관','수영장','풋살장',
    '조명타워','가로등','보안등','투광등','태양광','조명','등기구',
    '관급자재','설치공사','전기공사','교체공사','구입','구매','조달',
    '하자점검','하자요청','점검요청','방문요청','현장점검','미점등',
    '반불','교체','불량','점등','깜빡','확인','처리','조치','방문',
    '담당','주무관','부탁','협의','진행','예정','완료','보고','접수',
    '하자','민원','공지','요청','현장','문의','상기','관련','내용',
    '공사','사업','관급','자재','조명기구','투광등기구','건립','전기',
    '보수','정비','개선','시설','설치','신규','상반기','하반기',
    '디밍','제어기','통신','불량','점검','통화','결과','이상',
    '도로조명','조도개선','야간조명','스포츠조명','LED',
    '초등학교','중학교','고등학교','태양광가로등',
}

# aslist.md 이미 매칭된 건
with open('aslist.md', 'r', encoding='utf-8') as f:
    old = f.read()
already = set()
for m in re.finditer(r'### \d+\. \[(\d{4}-\d{2}-\d{2})\] (.+?)\n', old):
    block = old[m.end():m.end()+500]
    if '매칭 결과' in block or '매칭계약' in block:
        already.add(f'{m.group(1)}|{m.group(2).strip()[:30]}')
print(f'이미 매칭: {len(already)}건')

# as.db
conn = sqlite3.connect('as.db')
rows = conn.execute('SELECT id, author, content_text, created_at, raw_json FROM posts ORDER BY created_at').fetchall()
conn.close()

items = []
for pid, author, content, created, raw_json in rows:
    if not content or not content.strip(): continue
    rj = json.loads(raw_json)
    ct = []
    for child in rj.get('children', []):
        c = child.get('content', {})
        if isinstance(c, dict):
            for b in c.get('content', []):
                for it in b.get('content', []):
                    if it.get('type') == 'text': ct.append(it.get('text', ''))
    full = content + '\n' + '\n'.join(ct)
    site = ''
    for pat in [r'현장명?\s*[:：]\s*(.+?)(?:\n|$|-\s|민원)',
                r'(?:계약명|건명)\s*[:：]\s*(.+?)(?:\n|$)',
                r'현장\s*[:：]\s*(.+?)(?:\n|$)']:
        mm = re.search(pat, content)
        if mm: site = mm.group(1).strip()[:80]; break
    if not site:
        site = content.strip().split('\n')[0].strip('* ')[:80]
    m3 = re.search(r'(?:품목|품명|설치품목|설치사양|납품품목|적용품명|적용제품)\s*[:：]\s*(.+?)(?:\n|$)', full)
    item = m3.group(1).strip()[:50] if m3 else ''
    key = f'{created[:10]}|{site[:30]}'
    if key in already: continue
    items.append({'pid':pid,'date':created[:10],'author':author,'site':site,'item':item,'full':full,'cc':rj.get('children_count',0)})

print(f'미매칭 게시글: {len(items)}건')

# 매칭
matched, unmatched = [], []

with get_db() as db:
    # warranty + 발주처 + 현장명 로드
    raw_w = db.query(Warranty).all()
    all_w = []
    for w in raw_w:
        w.dminstt = ''
        w.project_name = ''
        if w.contract_id:
            c = db.query(Contract).get(w.contract_id)
            if c:
                if c.project:
                    w.project_name = c.project.temp_name or ''
                if c.g2b_contract_no:
                    g = db.query(G2bProcurement).filter(G2bProcurement.cntrct_dlvr_req_no == c.g2b_contract_no).first()
                    if g:
                        w.dminstt = g.dminstt_nm or ''
        all_w.append(w)
    print(f'warranty: {len(all_w)}건 (발주처/현장명 포함)')

    for entry in items:
        site = entry['site']
        full = entry['full'][:600]

        # Step 1: 지명 추출 (건명에서 NOT_PLACE 제외한 2글자+ 한글)
        words = [w for w in re.findall(r'[가-힣]{2,}', site) if w not in NOT_PLACE]

        # 본문에서도 지명 보충
        if not words or all(len(w) < 3 for w in words):
            body_words = [w for w in re.findall(r'[가-힣]{2,}', full[:200]) if w not in NOT_PLACE]
            words = words + body_words

        # 모델명 추출
        models = set(re.findall(r'(?:ARENA|STA|BATOO|MT-FL|MT-SLC|MT-SLA|MT-TL|MTSA|MTPF|MTT)-?\d+[A-Z]*', full, re.I))

        # Step 2: 지명으로 warranty 필터 (계약명 + 발주처 + 현장명)
        candidates = []
        tried = []

        for kw in sorted(words, key=len, reverse=True)[:5]:
            # 계약명에서 검색
            hits = [w for w in all_w if kw in (w.contract_name or '')]
            if 0 < len(hits) <= 50:
                tried.append(f'계약명"{kw}" → {len(hits)}건')
                candidates = hits
                break
            # 없으면 발주처(dminstt)에서 검색
            hits2 = [w for w in all_w if kw in (w.dminstt or '')]
            if 0 < len(hits2) <= 50:
                tried.append(f'발주처"{kw}" → {len(hits2)}건')
                candidates = hits2
                break
            # 없으면 현장명(project_name)에서 검색
            hits3 = [w for w in all_w if kw in (w.project_name or '')]
            if 0 < len(hits3) <= 50:
                tried.append(f'현장명"{kw}" → {len(hits3)}건')
                candidates = hits3
                break
            tried.append(f'"{kw}" → 계약{len(hits)}/발주처{len(hits2)}/현장{len(hits3)}건')

        # Step 3: 후보 중에서 시설명/모델로 특정
        best_w = None
        best_score = 0
        best_reason = ''

        if candidates:
            # 건명에서 시설명 추출 (NOT_PLACE에 있는 것 = 시설명)
            facility_words = [w for w in re.findall(r'[가-힣]{2,}', site) if w in NOT_PLACE and len(w) >= 3]
            # 본문 모델명
            models = set(re.findall(r'(?:ARENA|STA|BATOO|MT-FL|MT-SLC|MT-SLA|MT-TL|MTSA|MTPF|MTT)-?\d+[A-Z]*', full, re.I))

            for w in candidates:
                wn = w.contract_name or ''
                score = 0
                reason = ''

                # 1차: 유사도
                r = SequenceMatcher(None, site, wn).ratio()
                if r >= 0.5:
                    score = r
                    reason = f'유사도 {r:.2f}'

                # 2차: 시설명이 계약명에 포함되면 보너스
                fac_hits = [fw for fw in facility_words if fw in wn]
                if fac_hits:
                    s = 0.6 + len(fac_hits) * 0.1
                    if s > score:
                        score = s
                        reason = f'지명+시설[{",".join(fac_hits)}]'

                # 3차: 모델명 일치 보너스
                w_models = set(re.findall(r'(?:ARENA|STA|BATOO|MT-FL|MT-SLC|MT-SLA|MT-TL|MTSA|MTPF|MTT)-?\d+[A-Z]*', w.model_name or '', re.I))
                if models & w_models:
                    score += 0.15
                    reason += f' +모델[{list(models & w_models)[0]}]'

                if score > best_score:
                    best_score = score
                    best_w = w
                    best_reason = reason

        # 0.5 이상만 매칭
        cs = entry['full'].replace('\n',' ')[:250]
        e = {'date':entry['date'],'author':entry['author'],'site':entry['site'][:60],'item':entry['item'][:40],'cc':entry['cc'],'cs':cs}

        if best_w and best_score >= 0.5:
            e['wid'] = best_w.id
            e['wname'] = (best_w.contract_name or '')[:70]
            e['wd'] = f'보증시작:{best_w.warranty_start.year if best_w.warranty_start else "?"} / 모델:{best_w.model_name or "-"}'
            e['reason'] = best_reason
            e['score'] = best_score
            matched.append(e)
        else:
            e['tried'] = ' / '.join(tried[:4])
            if candidates:
                # 후보는 있었는데 특정 못 함
                top3 = sorted(candidates, key=lambda w: SequenceMatcher(None, site, w.contract_name or '').ratio(), reverse=True)[:3]
                e['tried'] += ' → 후보: ' + ', '.join([f'{w.id}:{(w.contract_name or "")[:30]}' for w in top3])
            unmatched.append(e)

# 출력
total = len(matched) + len(unmatched)
ls = ['# A/S 이력 매칭 v2 (지명 기반)','',
      f'aslist.md 매칭 {len(already)}건 제외, 나머지 {total}건',
      f'- 신규 매칭: {len(matched)}건',
      f'- 미매칭: {len(unmatched)}건',
      f'- 로직: 지명 추출 → warranty 필터 → 유사도 특정 → 확실한 것만','','---','']

ls.append(f'## 신규 매칭 ({len(matched)}건)')
ls.append('')
for i, e in enumerate(matched, 1):
    ls.append(f'### {i}. [{e["date"]}] {e["site"]}')
    x = f' (댓글 {e["cc"]}건)' if e['cc'] else ''
    ls.append(f'- 작성자: {e["author"]} / 품목: {e["item"] or "-"}{x}')
    ls.append(f'- **[as.db 원문]** {e["cs"]}')
    ls.append(f'- **[매칭 결과]** warranty {e["wid"]}: {e["wname"]}')
    ls.append(f'- **[보증 정보]** {e["wd"]}')
    ls.append(f'- **[매칭 근거]** {e["reason"]} (score {e["score"]:.2f})')
    ls.append('')

ls.append('---')
ls.append('')
ls.append(f'## 미매칭 ({len(unmatched)}건)')
ls.append('')
for i, e in enumerate(unmatched, 1):
    ls.append(f'### {i}. [{e["date"]}] {e["site"]}')
    x = f' (댓글 {e["cc"]}건)' if e['cc'] else ''
    ls.append(f'- 작성자: {e["author"]} / 품목: {e["item"] or "-"}{x}')
    ls.append(f'- **[as.db 원문]** {e["cs"]}')
    ls.append(f'- **[검색 시도]** {e["tried"]}')
    ls.append('')

with open('aslistv2.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(ls))
print(f'완료: 신규매칭 {len(matched)} / 미매칭 {len(unmatched)}')
