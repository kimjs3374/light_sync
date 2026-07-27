"""G2B 원본 ↔ ERP 대조 감사 (읽기 전용, 보고 전용)

배경:
  G2B → ERP 자동생성 경로는 "동기화"가 아니라 "생성 시 1회 복사"다.
  auto_create_contracts / sync_g2b_to_contracts 모두 기존 g2b_contract_no 는 skip 하므로,
  계약 생성 시점에 베껴온 필드는 원본이 바뀌어도 영원히 스냅샷으로 남는다.
  그래서 납품기한(2026-04), 수량(2026-07)처럼 필드 하나씩 뒤늦게 터져왔다.

이 모듈은 어긋난 필드를 전수 대조해서 보고만 한다.
  - 수정하지 않는다. 자동반영은 g2b_procurement_sync 쪽 sync_* 함수 담당.
  - 알림을 보내지 않는다. 로그/CLI 출력으로만 확인한다.
"""
import logging

from modules.models import Contract, ContractItem, Project, normalize_org_name
from modules.services.g2b_procurement_sync import _final_g2b_items, _match_g2b_items

logger = logging.getLogger(__name__)

# 완료 계약은 대조 대상이 아니다 (contract_filters.DONE_STATUSES 와 동일 기준)
from modules.contract_filters import DONE_STATUSES


def _norm(value):
    return (value or '').strip()


def audit_g2b_drift(db):
    """활성 G2B 계약 전건을 원본과 대조한다.

    Returns:
        dict: {total, findings: {category: [ {...}, ... ]}}
    """
    contracts = db.query(Contract).filter(
        Contract.g2b_contract_no.isnot(None),
        Contract.g2b_contract_no != '',
        Contract.payment_status.notin_(DONE_STATUSES),
        Contract.is_excluded.isnot(True),
    ).order_by(Contract.id).all()

    findings = {}

    def add(category, contract, detail):
        findings.setdefault(category, []).append({
            'contract_id': contract.id,
            'project_id': contract.project_id,
            'g2b_no': contract.g2b_contract_no,
            'contract_name': contract.contract_name,
            'detail': detail,
        })

    for contract in contracts:
        g2b_rows = _final_g2b_items(db, contract.g2b_contract_no)
        if not g2b_rows:
            add('G2B원본없음', contract, '조달내역에 해당 계약번호 행이 없음')
            continue

        rep = g2b_rows[0]
        max_chg = max((r.cntrct_dlvr_req_chg_ord or '00').strip() for r in g2b_rows)

        # ── 변경차수 반영 여부 ──
        erp_chg = _norm(contract.g2b_change_ord) or '00'
        if erp_chg != max_chg:
            add('변경차수미반영', contract, f'ERP {erp_chg}차 vs G2B {max_chg}차')

        # ── 납품기한 ──
        g2b_due = max((r.dlvr_tmlmt_date for r in g2b_rows if r.dlvr_tmlmt_date), default=None)
        if g2b_due and contract.delivery_due_date != g2b_due:
            add('납품기한', contract, f'ERP {contract.delivery_due_date} vs G2B {g2b_due}')

        # ── 계약일 (원계약 한정) ──
        # 변경계약이 나면 G2B 행의 cntrct_dlvr_req_date 가 변경일로 갱신되는데,
        # ERP 는 원계약일을 유지하는 게 맞으므로 00차만 비교한다.
        if max_chg == '00' and rep.cntrct_dlvr_req_date \
                and contract.contract_date != rep.cntrct_dlvr_req_date:
            add('계약일', contract,
                f'ERP {contract.contract_date} vs G2B {rep.cntrct_dlvr_req_date}')

        # ── 계약명 (사용자 수정 가능 필드 — 보고만) ──
        g2b_name = _norm(rep.cntrct_dlvr_req_nm)
        if g2b_name and _norm(contract.contract_name) != g2b_name:
            add('계약명', contract,
                f"ERP '{_norm(contract.contract_name)[:40]}' vs G2B '{g2b_name[:40]}'")

        # ── 품목: 수량 / 구성 ──
        contract_items = db.query(ContractItem).filter(
            ContractItem.contract_id == contract.id
        ).order_by(ContractItem.id).all()

        if not contract_items:
            add('품목없음', contract, 'ERP 계약품목 0건')
        elif all((r.prdct_qty or 0) == 0 and (r.prdct_amt or 0) == 0 for r in g2b_rows):
            add('계약취소의심', contract, '전 품목 수량 0 / 금액 0 — 계약 취소 처리 필요')
        else:
            pairs, method = _match_g2b_items(g2b_rows, contract_items)
            if pairs is None:
                g2b_models = ', '.join(_norm(r.prdct_idnt_no_nm)[:30] for r in g2b_rows)
                erp_models = ', '.join(_norm(ci.model_name)[:30] for ci in contract_items)
                add('품목구성', contract,
                    f'G2B {len(g2b_rows)}종 [{g2b_models}] vs ERP {len(contract_items)}종 [{erp_models}]')
            else:
                diffs = [
                    f"{_norm(ci.model_name) or ci.category} {ci.quantity or 0}→{g.prdct_qty or 0}"
                    for g, ci in pairs if (ci.quantity or 0) != (g.prdct_qty or 0)
                ]
                if diffs:
                    add('수량', contract, f"({method}매칭) " + ', '.join(diffs))

        # ── 현장 필드 (사용자 수정 가능 — 보고만) ──
        project = db.query(Project).get(contract.project_id) if contract.project_id else None
        if project:
            g2b_org = _norm(rep.dminstt_nm)
            erp_org = _norm(project.short_name)
            if g2b_org and normalize_org_name(erp_org) != normalize_org_name(g2b_org)[:50]:
                add('수요기관명', contract, f"현장 '{erp_org}' vs G2B '{g2b_org}'")
            elif erp_org and erp_org != normalize_org_name(erp_org):
                add('수요기관명_구표기', contract,
                    f"'{erp_org}' → '{normalize_org_name(erp_org)}' (전남광주 통합 표기 미적용)")

            g2b_place = _norm(rep.dlvr_plce_nm)
            if g2b_place and _norm(project.site_address) != g2b_place:
                add('납품장소', contract,
                    f"현장 '{_norm(project.site_address)[:35]}' vs G2B '{g2b_place[:35]}'")

    total_findings = sum(len(v) for v in findings.values())
    logger.info(
        '[G2B감사] 활성 계약 %d건 대조 — 불일치 %d건 (%s)',
        len(contracts), total_findings,
        ', '.join(f'{k} {len(v)}' for k, v in sorted(findings.items())) or '없음',
    )

    return {'total': len(contracts), 'findings': findings}


def _active_project_ids(db):
    """활성 계약을 하나라도 가진 현장 id 집합"""
    return {
        pid for (pid,) in db.query(Contract.project_id).filter(
            Contract.project_id.isnot(None),
            Contract.payment_status.notin_(DONE_STATUSES),
            Contract.is_excluded.isnot(True),
        ).distinct().all()
    }


def normalize_project_org_names(db, dry_run=True):
    """현장 수요기관명(projects.short_name)에 전남광주 통합 표기를 적용한다.

    G2B 값으로 덮어쓰지 않는다 — short_name 은 사용자가 직접 수정하는 필드라
    기존 값에 normalize_org_name() 만 적용해서 담당자 수정분을 보존한다.

    히스토리 로그는 활성 현장에만 남긴다. 2013~2014년 완료 현장까지 시스템 로그를
    쌓으면 히스토리 보드(환자차트)가 통째로 묻힌다.

    Returns:
        dict: {fixed, logged, changes[]}
    """
    from modules.history_board import append_history_log

    rows = db.query(Project).filter(
        Project.short_name.isnot(None),
        Project.short_name != '',
    ).all()
    active_ids = _active_project_ids(db)

    changes, logged = [], 0
    for project in rows:
        old = _norm(project.short_name)
        new = normalize_org_name(old)
        if not new or new == old:
            continue
        is_active = project.id in active_ids
        changes.append({'project_id': project.id, 'project_no': project.project_no,
                        'old': old, 'new': new, 'active': is_active})
        if not dry_run:
            project.short_name = new
            if is_active:
                append_history_log(
                    db,
                    project_id=project.id,
                    user_name='시스템',
                    content=f'수요기관명 전남광주 통합 표기 적용 — {old} → {new}',
                    scope='common',
                    kind='system',
                )
                logged += 1
        elif is_active:
            logged += 1

    logger.info('[G2B감사] 수요기관명 정규화 %s: %d건 (히스토리 기록 %d건)',
                '미리보기' if dry_run else '반영', len(changes), logged)
    return {'fixed': len(changes), 'logged': logged, 'changes': changes}
