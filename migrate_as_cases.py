"""
as.db A/S 이력 → WarrantyCase + WarrantyCaseLog 마이그레이션
총 133건 (as.db posts 133건)
"""
import sqlite3
import json
import re
import sys
import os
from datetime import datetime, date

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('FLASK_ENV', 'production')

from modules.db_context import get_db
from modules.models.misc_entities import Warranty, WarrantyCase, WarrantyCaseLog


# ============================================================
# 1) as.db 원문 → warranty_id 매핑 (asmatched.md + aslist.md 파싱)
# ============================================================

def parse_asmatched():
    """asmatched.md → { (date, content_prefix): warranty_id }"""
    with open('asmatched.md', 'r', encoding='utf-8') as f:
        text = f.read()
    blocks = re.split(r'(?=### \d+\. \[)', text)
    blocks = [b for b in blocks if b.strip().startswith('###')]
    entries = []
    for b in blocks:
        hdr = re.search(r'### (\d+)\. \[(\d{4}-\d{2}-\d{2})\] (.+)', b)
        if not hdr:
            continue
        wid = re.search(r'warranty (\d+):', b)
        mc = re.search(r'매칭계약.*?:\s*(.+)', b)
        entries.append({
            'num': int(hdr.group(1)),
            'date': hdr.group(2),
            'title': hdr.group(3).strip(),
            'warranty_id': int(wid.group(1)) if wid else None,
            'search_contract': mc.group(1).strip() if (mc and not wid) else None,
        })
    return entries


def parse_aslist():
    """aslist.md → list of dict with search_contract"""
    with open('aslist.md', 'r', encoding='utf-8') as f:
        text = f.read()
    blocks = re.split(r'(?=### \d+\. \[)', text)
    blocks = [b for b in blocks if b.strip().startswith('###')]
    entries = []
    for b in blocks:
        hdr = re.search(r'### (\d+)\. \[(\d{4}-\d{2}-\d{2})\] (.+)', b)
        if not hdr:
            continue
        mc = re.search(r'수동매칭\s*[:：]\s*(.+)', b)
        entries.append({
            'num': int(hdr.group(1)),
            'date': hdr.group(2),
            'title': hdr.group(3).strip(),
            'warranty_id': None,
            'search_contract': mc.group(1).strip() if mc else None,
        })
    return entries


def build_post_warranty_map(posts_data):
    """
    Build mapping: post_id → { warranty_id, search_contract }
    Strategy: match md entries to posts by date + content text overlap
    """
    matched_entries = parse_asmatched()
    manual_entries = parse_aslist()

    # Build date → posts index
    posts_by_date = {}
    for p in posts_data:
        d = p['created_at'][:10]
        posts_by_date.setdefault(d, []).append(p)

    mapping = {}  # post_id → { warranty_id, search_contract }
    used_post_ids = set()

    # Match asmatched entries first (they have warranty_id)
    for entry in matched_entries:
        candidates = posts_by_date.get(entry['date'], [])
        # If only one candidate for this date, it's a direct match
        available = [p for p in candidates if p['id'] not in used_post_ids]
        if len(available) == 1:
            pid = available[0]['id']
            mapping[pid] = {
                'warranty_id': entry['warranty_id'],
                'search_contract': entry.get('search_contract'),
            }
            used_post_ids.add(pid)
        elif len(available) > 1:
            # Multiple posts on same date — match by content overlap
            best = None
            best_score = -1
            title_lower = entry['title'].lower()
            for p in available:
                ct = (p['content_text'] or '').lower()
                # Score: count matching chars from title in content
                title_words = set(re.findall(r'[\w가-힣]+', title_lower))
                ct_words = set(re.findall(r'[\w가-힣]+', ct[:300]))
                overlap = len(title_words & ct_words)
                if overlap > best_score:
                    best_score = overlap
                    best = p
            if best:
                mapping[best['id']] = {
                    'warranty_id': entry['warranty_id'],
                    'search_contract': entry.get('search_contract'),
                }
                used_post_ids.add(best['id'])

    # Match aslist entries (manual matching with search_contract)
    for entry in manual_entries:
        candidates = posts_by_date.get(entry['date'], [])
        available = [p for p in candidates if p['id'] not in used_post_ids]
        if len(available) == 1:
            pid = available[0]['id']
            mapping[pid] = {
                'warranty_id': None,
                'search_contract': entry.get('search_contract'),
            }
            used_post_ids.add(pid)
        elif len(available) > 1:
            title_lower = entry['title'].lower()
            best = None
            best_score = -1
            for p in available:
                ct = (p['content_text'] or '').lower()
                title_words = set(re.findall(r'[\w가-힣]+', title_lower))
                ct_words = set(re.findall(r'[\w가-힣]+', ct[:300]))
                overlap = len(title_words & ct_words)
                if overlap > best_score:
                    best_score = overlap
                    best = p
            if best:
                mapping[best['id']] = {
                    'warranty_id': None,
                    'search_contract': entry.get('search_contract'),
                }
                used_post_ids.add(best['id'])

    # Remaining unmatched posts → no warranty info
    return mapping, used_post_ids


# ============================================================
# 2) Utility functions
# ============================================================

def extract_text_from_content(node):
    """카카오워크 content JSON에서 텍스트 추출"""
    if node is None:
        return ''
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        texts = []
        if 'text' in node:
            texts.append(node['text'])
        if 'content' in node and isinstance(node['content'], list):
            for item in node['content']:
                texts.append(extract_text_from_content(item))
        return ''.join(texts)
    if isinstance(node, list):
        return ''.join(extract_text_from_content(x) for x in node)
    return ''


def determine_defect_type(text):
    t = (text or '').upper()
    tl = text or ''
    if 'SMPS' in t or '안정기' in tl or '안전기' in tl:
        return 'SMPS'
    if any(w in tl for w in ['미점등', '소등', '반불', '깜빡', '깜박', '점등불가', '점등 불가',
                              '안들어옴', '안 들어옴', '안켜', '불량', '부점등', '미 점등', '점멸']):
        return 'LED_MODULE'
    if any(w in tl for w in ['결로', '침수', '습기']):
        return 'MOISTURE'
    if any(w in tl for w in ['디밍', '제어', '통신']):
        return 'CONTROL'
    if any(w in tl for w in ['렌즈', '유리', '눈부심']):
        return 'LENS'
    if any(w in tl for w in ['방열', '과열', '불탔']):
        return 'HEAT'
    if any(w in tl for w in ['배선', '전선', '결선', '오결선']):
        return 'WIRING'
    if any(w in tl for w in ['녹', '도장', '페인트', '녹이']):
        return 'PAINT'
    if any(w in tl for w in ['센서']):
        return 'SENSOR'
    if any(w in tl for w in ['외함', '본체']):
        return 'BODY'
    return 'OTHER'


def extract_symptom(text):
    if not text:
        return ''
    t = re.sub(r'^[\*\s]+', '', text)
    for kw in ['내용 :', '내용:', '하자요청내용 :', '하장요청내용 :', '민원내용 :',
                '민원내용:', '하자요청내용:', '하장요청내용:', '점검요청사항 :',
                '내용  :', '점검요청내용 :']:
        idx = t.find(kw)
        if idx >= 0:
            snippet = t[idx + len(kw):].strip()
            end = min(len(snippet), 200)
            for marker in [' - ', '\n- ', '- 요청자', '- 담당자', '상기', '\n*', '\n**']:
                mi = snippet.find(marker)
                if 0 < mi < end:
                    end = mi
            return snippet[:end].strip()
    return t[:150].strip()


def extract_customer(text):
    name, phone = '', ''
    if not text:
        return name, phone
    pm = re.search(r'(010[-\s]?\d{4}[-\s]?\d{4})', text)
    if pm:
        phone = pm.group(1).replace(' ', '').replace('-', '-')
    if not pm:
        pm = re.search(r'(0\d{1,2}[-)\s]\s*\d{3,4}[-\s]\d{4})', text)
        if pm:
            phone = pm.group(1)
    for pat in [r'요청자\s*[(:：]\s*([^\n\-]{2,20})',
                r'담당[자]?\s*[(:：]\s*([^\n\-]{2,20})',
                r'(\S{2,4}\s*(?:주무관|대리|팀장|대표|과장|사원|매니저|주사))']:
        nm = re.search(pat, text)
        if nm:
            name = nm.group(1).strip()[:50]
            break
    return name, phone


def extract_site_name(text):
    """본문에서 현장명 추출"""
    if not text:
        return ''
    for kw in ['현장명 :', '현장명:', '현장 :', '현장:']:
        m = re.search(kw + r'\s*(.+?)(?:\n|-\s)', text)
        if m:
            return m.group(1).strip()[:100]
    return ''


def find_warranty(db, warranty_id=None, search_contract=None):
    """warranty 찾기"""
    if warranty_id:
        w = db.query(Warranty).filter(Warranty.id == warranty_id).first()
        if w:
            return w

    if not search_contract:
        return None

    # Skip known non-warranty entries
    if any(x in search_contract for x in ['민수공사', '민수', '조달건 아니고', '단순 A/S만']):
        return None

    # Exact match
    w = db.query(Warranty).filter(Warranty.contract_name == search_contract).first()
    if w:
        return w

    # LIKE match
    w = db.query(Warranty).filter(Warranty.contract_name.ilike(f'%{search_contract}%')).first()
    if w:
        return w

    # Try removing <...> annotations
    clean = re.sub(r'<[^>]+>', '', search_contract).strip()
    if clean != search_contract:
        w = db.query(Warranty).filter(Warranty.contract_name.ilike(f'%{clean}%')).first()
        if w:
            return w

    # Try main keywords
    keywords = re.findall(r'[\w가-힣]{2,}', search_contract)
    if len(keywords) >= 2:
        for kw in keywords[:3]:
            if len(kw) >= 3:
                results = db.query(Warranty).filter(Warranty.contract_name.ilike(f'%{kw}%')).all()
                if len(results) == 1:
                    return results[0]

    return None


# ============================================================
# 3) Load posts from as.db
# ============================================================

def load_posts():
    conn = sqlite3.connect('as.db')
    cur = conn.cursor()
    cur.execute('''
        SELECT id, author, content_text, created_at, raw_json
        FROM posts
        WHERE content_text IS NOT NULL AND content_text != ''
        ORDER BY created_at
    ''')
    posts = []
    for row in cur.fetchall():
        rj = json.loads(row[4])
        user = rj.get('user', {})
        author_name = user.get('display_name', '') or row[1] or '?'

        children = []
        for c in rj.get('children', []):
            c_user = c.get('user', {})
            c_author = c_user.get('display_name', '') or '?'
            c_content = extract_text_from_content(c.get('content', {}))
            c_created = c.get('created_at')
            if isinstance(c_created, (int, float)):
                c_dt = datetime.fromtimestamp(c_created)
            else:
                c_dt = datetime.now()
            if c_content.strip():
                children.append({
                    'author': c_author,
                    'content': c_content.strip(),
                    'created_at': c_dt,
                })

        posts.append({
            'id': row[0],
            'author': author_name,
            'content_text': row[2],
            'created_at': row[3],
            'children': children,
        })
    conn.close()
    return posts


# ============================================================
# 4) Main migration
# ============================================================

def main():
    posts = load_posts()
    print(f'Loaded {len(posts)} posts from as.db')

    # Build warranty mapping
    mapping, used_ids = build_post_warranty_map(posts)
    print(f'Mapped {len(mapping)} posts to warranty info')

    unmatched = [p for p in posts if p['id'] not in used_ids]
    print(f'Unmatched posts (no md entry): {len(unmatched)}')
    for p in unmatched:
        print(f'  post {p["id"]} [{p["created_at"][:10]}] {p["content_text"][:60]}')

    with get_db() as db:
        # Get existing case numbers
        existing_cases = {c.case_no for c in db.query(WarrantyCase.case_no).all()}
        print(f'\nExisting cases in DB: {existing_cases}')

        # Sort posts by date
        posts.sort(key=lambda p: p['created_at'])

        # Track case_no per year
        year_seq = {}
        for cn in existing_cases:
            m = re.match(r'AS-(\d{4})-(\d{3})', cn)
            if m:
                y, s = int(m.group(1)), int(m.group(2))
                year_seq[y] = max(year_seq.get(y, 0), s)

        created_count = 0
        log_count = 0
        skipped = 0

        for post in posts:
            pid = post['id']
            entry_date = post['created_at'][:10]
            year = int(entry_date[:4])
            content = post['content_text'] or ''
            author = post['author']

            # Get warranty mapping info
            winfo = mapping.get(pid, {})
            warranty_id = winfo.get('warranty_id')
            search_contract = winfo.get('search_contract')

            # Find warranty
            warranty = find_warranty(db, warranty_id=warranty_id, search_contract=search_contract)

            # Generate case_no
            if year not in year_seq:
                year_seq[year] = 0
            year_seq[year] += 1
            case_no = f'AS-{year}-{year_seq[year]:03d}'

            if case_no in existing_cases:
                print(f'  SKIP: {case_no} already exists')
                skipped += 1
                continue

            # Extract fields
            defect_type = determine_defect_type(content)
            symptom = extract_symptom(content)
            customer_name, customer_phone = extract_customer(content)
            site_name = extract_site_name(content)
            reported_date = datetime.strptime(entry_date, '%Y-%m-%d').date()

            # Completed date: from last child comment or same day
            completed_date = reported_date
            if post['children']:
                last_dt = post['children'][-1]['created_at']
                if hasattr(last_dt, 'date'):
                    completed_date = last_dt.date()

            # Parse post created_at
            try:
                post_created = datetime.fromisoformat(post['created_at'].replace('Z', '+00:00')).replace(tzinfo=None)
            except:
                post_created = datetime.strptime(entry_date, '%Y-%m-%d')

            # Determine if chargeable (보증만료 여부)
            is_chargeable = False
            if warranty and warranty.warranty_end:
                if reported_date > warranty.warranty_end:
                    is_chargeable = True
            # Check content for 유상 keyword
            if '유상' in content:
                is_chargeable = True

            # Build WarrantyCase
            is_manual = (warranty is None)
            contract_name_val = warranty.contract_name if warranty else (search_contract or site_name or '')

            case = WarrantyCase(
                warranty_id=warranty.id if warranty else None,
                project_id=warranty.project_id if warranty else None,
                case_no=case_no,
                defect_type=defect_type,
                symptom=symptom[:500] if symptom else '',
                status='완료',
                reported_by=customer_name or author,
                reported_date=reported_date,
                completed_date=completed_date,
                assigned_to=author,
                is_chargeable=is_chargeable,
                request_channel='카카오',
                customer_name=customer_name,
                customer_phone=customer_phone,
                contract_name=contract_name_val[:200] if contract_name_val else None,
                item_group=warranty.item_group if warranty else None,
                model_name=warranty.model_name if warranty else None,
                created_by='시스템(as.db 마이그레이션)',
            )

            if is_manual:
                case.manual_site_name = site_name[:200] if site_name else None
                case.manual_contract_name = (search_contract or contract_name_val)[:200] if (search_contract or contract_name_val) else None

            db.add(case)
            db.flush()

            # Create logs
            # Main post → 접수 로그
            log_main = WarrantyCaseLog(
                case_id=case.id,
                log_type='note',
                content=f'[카카오워크 접수] {content}',
                created_by=f'{author} (카카오워크)',
                created_at=post_created,
            )
            db.add(log_main)
            log_count += 1

            # Children → 댓글 로그
            for child in post['children']:
                log_child = WarrantyCaseLog(
                    case_id=case.id,
                    log_type='note',
                    content=f'[댓글] {child["content"]}',
                    created_by=f'{child["author"]} (카카오워크)',
                    created_at=child['created_at'],
                )
                db.add(log_child)
                log_count += 1

            created_count += 1

            # Batch commit every 50
            if created_count % 50 == 0:
                db.commit()
                print(f'  Committed batch: {created_count} cases, {log_count} logs')

        # Final commit
        db.commit()
        print(f'\n=== Migration Complete ===')
        print(f'Cases created: {created_count}')
        print(f'Logs created: {log_count}')
        print(f'Skipped: {skipped}')

        # Verify totals
        total_cases = db.query(WarrantyCase).count()
        total_logs = db.query(WarrantyCaseLog).count()
        print(f'Total cases in DB: {total_cases}')
        print(f'Total logs in DB: {total_logs}')

        # Show year breakdown
        from sqlalchemy import func
        year_counts = db.query(
            func.substring(WarrantyCase.case_no, 4, 4),
            func.count()
        ).group_by(func.substring(WarrantyCase.case_no, 4, 4)).all()
        for y, c in sorted(year_counts):
            print(f'  {y}: {c} cases')


if __name__ == '__main__':
    main()
