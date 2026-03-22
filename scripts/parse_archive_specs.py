"""
워크보드 현장관리 → 협의 스펙 자동 파싱 스크립트

archive_posts(contract_id 매칭 완료) 본문에서
품목별 협의 스펙을 추출하여 contract_items.item_spec에 반영합니다.

사용법:
  py -3 scripts/parse_archive_specs.py          # dry-run (변경 안 함)
  py -3 scripts/parse_archive_specs.py --apply   # 실제 반영
"""
import re
import sys
import json
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import text
from modules.db_context import get_db


# ── 스펙 추출 정규식 ──────────────────────────────────
def parse_spec_from_text(content):
    """본문에서 품목별 스펙을 추출. [{model_hint, specs}, ...] 반환."""
    if not content:
        return []

    results = []

    # 품목 블록 분리: "1) ...", "2) ..." 또는 "- 품명 :", "품명 :" 패턴
    # 먼저 번호로 나뉜 품목들을 찾기
    blocks = re.split(r'\n\s*\d+\)\s*', content)
    if len(blocks) <= 1:
        # 번호 분리 안 되면 전체를 하나의 블록으로
        blocks = [content]

    for block in blocks:
        if not block.strip():
            continue

        spec = {}
        model_hint = ''

        # 모델명 추출 (MT-SLC-125, STA-1000, MTPS-105-9-2, MTPF-201-5, MTT24A, ARENA-400 등)
        model_match = re.search(
            r'(MT-?SL[AC][\w()\-]*\d+|STA[X()\-]*-?\d+|MTPS-?\d[\w\-]*|MTPF-?\d[\w\-]*|'
            r'MTT-?\d+\w*|ARENA[\w()\-\s]*\d+|SLA-?\d+|LED-?\d+|MTSOLAR[\w\-]*|MTSA[\w\-]*\d+)',
            block, re.IGNORECASE
        )
        if model_match:
            model_hint = model_match.group(0).strip()

        # ── SMPS 타입 (외장형/분리형/일체형 + 전주부착형 패턴) ──
        smps_match = re.search(r'SMPS\s*(외장|분리|일체)', block)
        if not smps_match:
            smps_match = re.search(r'(외장|분리|일체)\s*형', block)
        if not smps_match:
            # "전주부착형(SMPS외장형)" 패턴
            smps_match = re.search(r'전주부착형.*SMPS\s*(외장|분리|일체)', block)
        if smps_match:
            smps_type = smps_match.group(1)
            spec['is_integrated'] = (smps_type == '일체')
            spec['body_type'] = '일체형' if smps_type == '일체' else '분리형'

        # ── 케이블 이격거리 (다양한 패턴) ──
        cable_patterns = [
            r'케이블\s*(?:이격|길이)?\s*[:(（]?\s*(\d+)\s*[Mm]',  # 케이블 12M, 케이블길이(3m연장)
            r'케이블\s*(?:이격|길이)?\s*[:(（]?\s*(\d+)\s*[Mm]?\s*연장',  # 케이블길이(10m연장)
            r'이격\s*(?:거리)?\s*[:(]?\s*(\d+)\s*[Mm]',  # 이격 24M
        ]
        for pat in cable_patterns:
            cable_match = re.search(pat, block)
            if cable_match:
                spec['spacing_distance'] = cable_match.group(1) + 'M'
                break

        # ── 렌즈각도 ──
        lens_match = re.search(r'렌즈\s*(?:각도)?\s*[:(]?\s*(\d+)\s*[도°]?', block)
        if lens_match:
            spec['lens_angle'] = lens_match.group(1) + '도'
        else:
            # "35도: 2개, 55도: 1개" 패턴
            angle_matches = re.findall(r'(\d+)\s*도\s*[:：]\s*\d+\s*개', block)
            if angle_matches:
                spec['lens_angle'] = ', '.join(a + '도' for a in angle_matches)
            else:
                angle_match = re.search(r'(\d+)°', block)
                if angle_match:
                    spec['lens_angle'] = angle_match.group(1) + '도'

        # ── 배광 (WIDE/MEDIUM/NARROW, 광각/중각/협각) ──
        beam_match = re.search(r'(WIDE|MEDIUM|NARROW|광각|중각|협각)(?:\s*\(?\s*(\d+)\s*도?\)?)?', block, re.IGNORECASE)
        if beam_match and 'lens_angle' not in spec:
            beam_type = beam_match.group(1)
            beam_angle = beam_match.group(2)
            if beam_angle:
                spec['lens_angle'] = f"{beam_type}({beam_angle}도)"
            else:
                spec['lens_angle'] = beam_type

        # ── 암대 규격 (60.5mm, 76mm 등) ──
        arm_match = re.search(r'암대\s*[:(（]?\s*([\d.]+)\s*(?:mm|Ø|파이)?', block)
        if arm_match:
            spec['arm_type'] = arm_match.group(1) + 'mm'
        else:
            # "내경 60.5mm" 패턴
            inner_match = re.search(r'내경\s*[:(]?\s*([\d.]+)\s*(?:mm|Ø)?', block)
            if inner_match:
                spec['arm_type'] = inner_match.group(1) + 'mm'

        # ── 등주 타입 (기본형, B타입, 크로스암, 전주부착형 등) ──
        pole_type_match = re.search(r'타입\s*[:：]\s*(기본형|[A-C]\s*타입|크로스암|전주부착형|원[12]단형)', block)
        if pole_type_match:
            pt = pole_type_match.group(1).strip()
            if 'arm_type' not in spec:
                spec['arm_type'] = pt

        # ── 도장 여부 ──
        if re.search(r'도장\s*[Xx×]|도장없|도장\s*안함|도장\s*무', block):
            spec['is_painted'] = False
        elif re.search(r'지정\s*(?:색)?\s*도장|도장\s*색|도장\s*[:：]|도장\s*진행|도장\s*O', block):
            spec['is_painted'] = True
            color_match = re.search(r'도장\s*(?:색)?\s*[:：(（]?\s*([가-힣]{2,6})', block)
            if color_match:
                spec['paint_color'] = color_match.group(1)

        # ── 광택/도장 마감 (스텐 등주) ──
        if re.search(r'광택\s*처리|광택\)', block):
            spec['stainless_finish_type'] = '광택'
            spec['is_painted'] = False
        elif re.search(r'도장\s*처리|지정.*도장', block) and 'stainless_finish_type' not in spec:
            spec['stainless_finish_type'] = '도장'

        # ── 교체/신설 ──
        replace_match = re.search(r'(교체|신설|신규)\s*(?:공사|설치)?', block)
        if replace_match:
            val = replace_match.group(1)
            spec['replace_or_new'] = '교체' if val == '교체' else '신설'

        # ── 기초앙카/베이스 간격 ──
        anchor_match = re.search(
            r'(?:기초|앙카|앵커|베이스)\s*(?:간격|규격)?\s*[:：(（]?\s*(\d+)\s*[*×xX]\s*(\d+)',
            block
        )
        if anchor_match:
            spec['anchor_spacing'] = f"{anchor_match.group(1)}x{anchor_match.group(2)}"

        # ── 조명타워 높이 (MTT24A → 24M, MTT15B → 15M) ──
        height_match = re.search(r'MTT\s*-?\s*(\d+)', block, re.IGNORECASE)
        if height_match:
            spec['tower_height'] = height_match.group(1) + 'M'

        # ── 등기구 수 (N등용, 상부/하부 N등, 플랫폼 구성) ──
        lamp_match = re.search(r'(\d+)\s*등용', block)
        if lamp_match:
            spec['lamp_count'] = int(lamp_match.group(1))
        else:
            upper = re.search(r'상부\s*(\d+)\s*등', block)
            lower = re.search(r'하부\s*(\d+)\s*등', block)
            if upper or lower:
                total = (int(upper.group(1)) if upper else 0) + (int(lower.group(1)) if lower else 0)
                if total > 0:
                    spec['lamp_count'] = total

        # ── 안정기함/분전함 ──
        if re.search(r'안정기함|분전함|개별분전', block):
            spec['has_stabilizer_box'] = True

        # ── SMPS 모델명 (HLG-320H-36A, SPLW-50-36 등) ──
        smps_model = re.search(r'(HLG-[\w\-]+|SPLW-[\w\-]+|UPF-[\w\-]+|ELG-[\w\-]+|XLG-[\w\-]+)', block)
        if smps_model:
            spec['smps_model'] = smps_model.group(1)

        if spec and model_hint:
            results.append({'model_hint': model_hint, 'specs': spec})

    return results


def normalize_model(name):
    """모델명 비교용 정규화."""
    if not name:
        return ''
    return re.sub(r'[\s\-_()]+', '', name).upper()


def main():
    apply = '--apply' in sys.argv
    active_only = '--active' in sys.argv
    print(f"{'=' * 60}")
    mode_label = '적용 모드' if apply else '미리보기'
    scope_label = '활성 계약만' if active_only else '전체'
    print(f"워크보드 → 협의 스펙 자동 파싱 ({mode_label}, {scope_label})")
    print(f"{'=' * 60}\n")

    updated = 0
    skipped = 0
    errors = 0

    with get_db() as db:
        # 활성 계약 필터
        if active_only:
            active_cids = {r[0] for r in db.execute(text("""
                SELECT DISTINCT c.id
                FROM light_sync.projects p
                JOIN light_sync.contracts c ON c.project_id = p.id
                WHERE p.is_contracted = true
                  AND c.payment_status NOT IN ('입금완료', '변경완료', '취소')
            """)).fetchall()}
        else:
            active_cids = None

        # 계약별 텍스트 수집 (본문 + 댓글)
        archives = db.execute(text("""
            SELECT p.id, p.content_text, p.contract_id,
                   c.contract_name, c.id as cid
            FROM light_sync.archive_posts p
            JOIN light_sync.contracts c ON c.id = p.contract_id
            WHERE p.board_type = 'site'
              AND p.contract_id IS NOT NULL
              AND p.content_text IS NOT NULL
              AND p.content_text != ''
            ORDER BY p.created_at ASC
        """)).fetchall()

        comments = db.execute(text("""
            SELECT ac.content_text, ap.contract_id
            FROM light_sync.archive_comments ac
            JOIN light_sync.archive_posts ap ON ap.id = ac.post_id
            WHERE ap.board_type = 'site'
              AND ap.contract_id IS NOT NULL
              AND ac.content_text IS NOT NULL
            ORDER BY ac.created_at ASC
        """)).fetchall()

        # 계약별 텍스트 합치기
        contract_texts = {}
        for row in archives:
            cid = row.contract_id
            if active_cids is not None and cid not in active_cids:
                continue
            if cid not in contract_texts:
                contract_texts[cid] = {'name': row.contract_name, 'cid': row.cid, 'texts': []}
            contract_texts[cid]['texts'].append(row.content_text)

        for c in comments:
            cid = c.contract_id
            if cid in contract_texts:
                contract_texts[cid]['texts'].append(c.content_text)

        print(f"대상 계약: {len(contract_texts)}건 (본문+댓글 합산 파싱)\n")

        for cid, data in contract_texts.items():
            combined = '\n---\n'.join(data['texts'])
            parsed = parse_spec_from_text(combined)
            if not parsed:
                continue

            items = db.execute(text("""
                SELECT ci.id, ci.model_name, ci.category, ci.item_spec_json, ci.status_sales
                FROM light_sync.contract_items ci
                WHERE ci.contract_id = :cid
            """), {'cid': data['cid']}).fetchall()

            if not items:
                continue

            for spec_data in parsed:
                hint_norm = normalize_model(spec_data['model_hint'])

                # 모델명으로 매칭
                matched_item = None
                if hint_norm:
                    for item in items:
                        item_norm = normalize_model(item.model_name)
                        if not item_norm:
                            continue
                        if hint_norm in item_norm or item_norm in hint_norm:
                            matched_item = item
                            break

                # 매칭 안 되고 품목이 1개면 그 품목에 할당
                if not matched_item and len(items) == 1:
                    matched_item = items[0]

                if not matched_item:
                    continue

                # 기존 스펙과 병합 (기존 값 우선 유지)
                existing_spec = {}
                if matched_item.item_spec_json:
                    if isinstance(matched_item.item_spec_json, str):
                        try:
                            existing_spec = json.loads(matched_item.item_spec_json)
                        except Exception:
                            existing_spec = {}
                    else:
                        existing_spec = dict(matched_item.item_spec_json)

                new_fields = {}
                for k, v in spec_data['specs'].items():
                    if k not in existing_spec or not existing_spec[k]:
                        new_fields[k] = v

                if not new_fields:
                    skipped += 1
                    continue

                merged = dict(existing_spec)
                merged.update(new_fields)

                print(f"[{row.contract_name[:30]}]")
                print(f"  품목: {matched_item.model_name} (id={matched_item.id})")
                print(f"  추출: {spec_data['specs']}")
                print(f"  신규: {new_fields}")
                print(f"  기존상태: {matched_item.status_sales or '계약확인'}")
                print()

                if apply:
                    try:
                        db.execute(text("""
                            UPDATE light_sync.contract_items
                            SET item_spec_json = :spec
                            WHERE id = :id
                        """), {'spec': json.dumps(merged, ensure_ascii=False), 'id': matched_item.id})
                        updated += 1
                    except Exception as e:
                        print(f"  ERROR: {e}")
                        errors += 1
                else:
                    updated += 1

        if apply:
            db.commit()

    print(f"\n{'=' * 60}")
    print(f"결과: 반영 {updated}건 / 스킵(이미입력) {skipped}건 / 에러 {errors}건")
    if not apply:
        print("※ 미리보기 모드입니다. --apply 옵션으로 실제 반영하세요.")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
