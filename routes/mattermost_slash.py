"""Mattermost Slash Commands endpoint.

슬래시 명령어 목록:
    /오늘        — ERP 전체 현황 요약 (대시보드)
    /현장 [키워드] — 현장 검색
    /미청구       — 납품완료 후 미청구 건 목록
    /지연         — 납기 초과 현장 목록
    /납품 [날짜]  — 납품 일정 (기본: 오늘, 형식 YYYY-MM-DD 또는 M/D)

보안:
    MM_SLASH_TOKEN 환경변수가 설정된 경우 token 필드로 검증.
    미설정 시 검증 스킵 (개발 편의).

응답:
    즉시 "조회 중..." 반환 후 background thread에서 response_url로 실제 결과 POST.
    모든 응답은 ephemeral (요청자만 보임).
"""
from __future__ import annotations

import datetime
import logging
import os
import threading
from typing import Any, Dict, List, Optional

import requests
from flask import Blueprint, jsonify, request
from sqlalchemy import func

from modules.db_context import get_db

logger = logging.getLogger(__name__)

mattermost_slash_bp = Blueprint("mattermost_slash_bp", __name__)

MM_SLASH_TOKEN = os.environ.get("MM_SLASH_TOKEN", "")
ERP_BASE_URL = os.environ.get("ERP_BASE_URL", "https://work.mgnt.kr").rstrip("/")


def _erp_url(path: str) -> str:
    if not path:
        return ERP_BASE_URL
    return ERP_BASE_URL + (path if path.startswith("/") else "/" + path)


# ──────────────────────────────────────────────────────────────
# 공통 response_url 전송
# ──────────────────────────────────────────────────────────────

def _post_delayed(response_url: str, text: str, attachments: Optional[List] = None) -> None:
    """background thread에서 Mattermost response_url로 최종 결과 발송."""
    if not response_url:
        return
    payload: Dict[str, Any] = {
        "response_type": "ephemeral",
        "text": text,
    }
    if attachments:
        payload["attachments"] = attachments
    logger.info("[slash] → response_url POST: %s", response_url[:80] if response_url else "(empty)")
    try:
        r = requests.post(response_url, json=payload, timeout=10)
        logger.info("[slash] ← response_url 응답: %d %s", r.status_code, r.text[:100])
        if r.status_code >= 400:
            logger.warning("[slash] response_url POST 실패: %d %s", r.status_code, r.text[:200])
    except Exception as e:
        logger.warning("[slash] response_url POST 예외: %s", e)


# ──────────────────────────────────────────────────────────────
# 명령어 핸들러
# ──────────────────────────────────────────────────────────────

def _cmd_today(response_url: str) -> None:
    """/오늘 — ERP 전체 현황 요약"""
    from modules.models.entities import Project, Contract, Delivery, DeliverySplit
    from modules.models.inventory_entities import Item

    try:
        today = datetime.date.today()
        with get_db() as db:
            active = db.query(func.count(Project.id)).filter(
                Project.status.in_(["계약", "생산", "납품중"])
            ).scalar() or 0
            design = db.query(func.count(Project.id)).filter(
                Project.status == "설계/영업"
            ).scalar() or 0

            today_splits = db.query(DeliverySplit).filter(
                DeliverySplit.scheduled_date == today,
                DeliverySplit.status != "완료",
            ).all()
            today_cnt = len(today_splits)

            overdue_cnt = (
                db.query(func.count(func.distinct(Contract.project_id)))
                .filter(
                    Contract.delivery_due_date < today,
                    Contract.delivery_due_date.isnot(None),
                )
                .join(Project, Contract.project_id == Project.id)
                .filter(~Project.status.in_(["납품완료", "완료", "취소"]))
                .scalar() or 0
            )

            try:
                unbilled_cnt = (
                    db.query(func.count(Contract.id))
                    .join(Delivery, Delivery.contract_id == Contract.id)
                    .filter(
                        Contract.is_excluded.isnot(True),
                        Delivery.delivery_status == "done",
                        Contract.payment_status == "미청구",
                    )
                    .scalar() or 0
                )
            except Exception:
                unbilled_cnt = 0

            low_stock = db.query(func.count(Item.id)).filter(
                Item.is_active == True,
                Item.safety_stock > 0,
                Item.stock_qty < Item.safety_stock,
            ).scalar() or 0

            lines = [
                f"📅 **{today.strftime('%Y-%m-%d')} ERP 현황**",
                "",
                f"**진행 현장** {active}건 (설계/영업 {design}건)",
            ]
            if today_cnt:
                # split에서 contract_name 조회
                split_names = []
                for s in today_splits[:3]:
                    try:
                        d = db.get(Delivery, s.delivery_id)
                        c = db.get(Contract, d.contract_id) if d else None
                        split_names.append((c.contract_name or "-")[:12] if c else "-")
                    except Exception:
                        split_names.append("-")
                names = ", ".join(dict.fromkeys(split_names))  # 중복 제거 순서 유지
                lines.append(f"**오늘 납품** {today_cnt}건 — {names}{'...' if today_cnt > 3 else ''}")
            else:
                lines.append("**오늘 납품** 예정 없음")

            if overdue_cnt:
                lines.append(f"**납기 초과** ⚠️ {overdue_cnt}건")
            if unbilled_cnt:
                lines.append(f"**미청구** 💳 {unbilled_cnt}건")
            if low_stock:
                lines.append(f"**재고 부족** 📦 {low_stock}품목")

            lines += ["", f"🔗 {_erp_url('/dashboard')}"]
        _post_delayed(response_url, "\n".join(lines))
    except Exception as e:
        logger.exception("[slash /오늘] 오류")
        _post_delayed(response_url, f"❌ 오류: {e}")


def _cmd_site(text: str, response_url: str) -> None:
    """/현장 [키워드] — 현장 검색"""
    from modules.models.entities import Project

    if not text:
        _post_delayed(response_url, "사용법: `/현장 세종` 처럼 키워드를 입력하세요.")
        return

    STATUS_EMOJI = {
        "계약": "📋", "생산": "🏭", "납품중": "🚚",
        "납품완료": "✅", "설계/영업": "📐", "취소": "❌",
    }

    try:
        with get_db() as db:
            projects = (
                db.query(Project)
                .filter(
                    Project.temp_name.ilike(f"%{text}%")
                    | Project.short_name.ilike(f"%{text}%")
                    | Project.site_address.ilike(f"%{text}%")
                    | Project.project_no.ilike(f"%{text}%")
                )
                .order_by(Project.created_at.desc())
                .limit(10)
                .all()
            )

            if not projects:
                _post_delayed(response_url, f"**'{text}'** 검색 결과 없음")
                return

            lines = [f"🔍 **'{text}'** 검색 결과 {len(projects)}건\n"]
            for p in projects:
                em = STATUS_EMOJI.get(p.status or "", "•")
                name = p.temp_name or p.short_name or f"현장#{p.id}"
                status = p.status or "-"
                url = _erp_url(f"/contract_detail/{p.id}")
                lines.append(f"{em} [{name}]({url}) — {status}")

        _post_delayed(response_url, "\n".join(lines))
    except Exception as e:
        logger.exception("[slash /현장] 오류")
        _post_delayed(response_url, f"❌ 오류: {e}")


def _cmd_unbilled(response_url: str) -> None:
    """/미청구 — 납품완료 후 미청구 건 목록"""
    from modules.models.entities import Contract, Project, Delivery
    from modules.models.misc_entities import G2bProcurement
    from sqlalchemy import func as sqlfunc

    try:
        with get_db() as db:
            rows = (
                db.query(Contract, Project)
                .join(Project, Contract.project_id == Project.id)
                .join(Delivery, Delivery.contract_id == Contract.id)
                .filter(
                    Contract.is_excluded.isnot(True),
                    Delivery.delivery_status == "done",
                    Contract.payment_status == "미청구",
                )
                .order_by(Delivery.id.asc())
                .limit(20)
                .all()
            )

            if not rows:
                _post_delayed(response_url, "✅ 미청구 건 없음")
                return

            # G2B 금액 조회 (계약번호 기준 합산)
            g2b_nos = [c.g2b_contract_no for c, _ in rows if c.g2b_contract_no]
            amt_map: dict = {}
            if g2b_nos:
                g2b_rows = (
                    db.query(
                        G2bProcurement.cntrct_dlvr_req_no,
                        sqlfunc.sum(G2bProcurement.prdct_amt),
                    )
                    .filter(G2bProcurement.cntrct_dlvr_req_no.in_(g2b_nos))
                    .group_by(G2bProcurement.cntrct_dlvr_req_no)
                    .all()
                )
                amt_map = {no: (amt or 0) for no, amt in g2b_rows}

            total_amt = sum(amt_map.get(c.g2b_contract_no, 0) for c, _ in rows)
            lines = [f"💳 **미청구 {len(rows)}건**" + (f" (합계 {total_amt:,}원)" if total_amt else "") + "\n"]
            for c, p in rows:
                name = c.contract_name or p.temp_name or f"계약#{c.id}"
                amt = amt_map.get(c.g2b_contract_no)
                amt_str = f" {amt:,}원" if amt else ""
                url = _erp_url(f"/contract_detail/{p.id}")
                lines.append(f"• [{name}]({url}){amt_str}")

            lines.append(f"\n🔗 {_erp_url('/billing')}")
        _post_delayed(response_url, "\n".join(lines))
    except Exception as e:
        logger.exception("[slash /미청구] 오류")
        _post_delayed(response_url, f"❌ 오류: {e}")


def _cmd_overdue(response_url: str) -> None:
    """/지연 — 납기 초과 현장 목록"""
    from modules.models.entities import Project, Contract

    try:
        today = datetime.date.today()
        with get_db() as db:
            contracts = db.query(Contract).filter(
                Contract.delivery_due_date < today,
                Contract.delivery_due_date.isnot(None),
            ).all()

            result = []
            seen: set = set()
            for c in contracts:
                proj = db.get(Project, c.project_id) if c.project_id else None
                if not proj:
                    continue
                if proj.status in ("납품완료", "완료", "취소"):
                    continue
                if proj.id in seen:
                    continue
                seen.add(proj.id)
                days = (today - c.delivery_due_date).days
                result.append((days, proj.temp_name or proj.short_name or f"현장#{proj.id}",
                                proj.id, c.delivery_due_date))

            result.sort(key=lambda x: x[0], reverse=True)

            if not result:
                _post_delayed(response_url, "✅ 납기 초과 현장 없음")
                return

            lines = [f"⚠️ **납기 초과 {len(result)}건**\n"]
            for days, name, pid, due in result[:15]:
                url = _erp_url(f"/contract_detail/{pid}")
                lines.append(f"• [{name}]({url}) — D+{days}일 (기한: {due})")

            if len(result) > 15:
                lines.append(f"_(전체 {len(result)}건 중 15건 표시)_")

        _post_delayed(response_url, "\n".join(lines))
    except Exception as e:
        logger.exception("[slash /지연] 오류")
        _post_delayed(response_url, f"❌ 오류: {e}")


def _cmd_delivery(text: str, response_url: str) -> None:
    """/납품 [날짜] — 납품 일정. 날짜 생략 시 오늘."""
    from modules.models.entities import DeliverySplit, Delivery, Contract, Project

    # 날짜 파싱
    target: datetime.date = datetime.date.today()
    if text:
        cleaned = text.strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d", "%m-%d"):
            try:
                parsed = datetime.datetime.strptime(cleaned, fmt)
                if fmt in ("%m/%d", "%m-%d"):
                    parsed = parsed.replace(year=datetime.date.today().year)
                target = parsed.date()
                break
            except ValueError:
                continue
        else:
            _post_delayed(
                response_url,
                "날짜 형식 오류 — `YYYY-MM-DD` 또는 `M/D` 형식으로 입력하세요. (예: `/납품 5/15`)",
            )
            return

    STATUS_EMOJI = {"완료": "✅", "진행중": "🔄", "예정": "📋"}
    date_str = target.strftime("%Y-%m-%d")

    try:
        with get_db() as db:
            splits = (
                db.query(DeliverySplit)
                .join(Delivery, DeliverySplit.delivery_id == Delivery.id)
                .join(Contract, Delivery.contract_id == Contract.id)
                .join(Project, Contract.project_id == Project.id)
                .filter(DeliverySplit.scheduled_date == target)
                .order_by(DeliverySplit.id.asc())
                .all()
            )

            if not splits:
                _post_delayed(response_url, f"📅 **{date_str}** 납품 일정 없음")
                return

            lines = [f"🚚 **{date_str} 납품 일정 {len(splits)}건**\n"]
            for s in splits:
                delivery = db.get(Delivery, s.delivery_id)
                contract = db.get(Contract, delivery.contract_id) if delivery else None
                project = db.get(Project, contract.project_id) if contract else None

                name = (contract.contract_name if contract else None) or \
                       (project.temp_name if project else None) or f"납품#{s.id}"
                qty = f"{s.quantity:,}EA" if s.quantity else "-"
                status = s.status or "예정"
                em = STATUS_EMOJI.get(status, "•")
                url = _erp_url(f"/delivery_management/{project.id}") if project else _erp_url("/delivery_management")
                lines.append(f"{em} [{name}]({url}) {qty} — {status}")

        _post_delayed(response_url, "\n".join(lines))
    except Exception as e:
        logger.exception("[slash /납품] 오류")
        _post_delayed(response_url, f"❌ 오류: {e}")


# ──────────────────────────────────────────────────────────────
# Flask route
# ──────────────────────────────────────────────────────────────

@mattermost_slash_bp.route("/mattermost/slash", methods=["POST"])
def slash_handler():
    """Mattermost 슬래시 커맨드 수신 엔드포인트."""
    # token 검증
    token = request.form.get("token", "")
    if MM_SLASH_TOKEN and token != MM_SLASH_TOKEN:
        logger.warning("[slash] 토큰 불일치: %s", token[:10])
        return jsonify({"text": "❌ 인증 실패"}), 403

    command: str = request.form.get("command", "").lstrip("/").strip()
    text: str = request.form.get("text", "").strip()
    response_url: str = request.form.get("response_url", "")
    user_name: str = request.form.get("user_name", "")

    logger.info("[slash] @%s /%s '%s' response_url=%s", user_name, command, text, response_url[:80] if response_url else "(empty)")

    dispatch = {
        "오늘":  lambda: _cmd_today(response_url),
        "현장":  lambda: _cmd_site(text, response_url),
        "미청구": lambda: _cmd_unbilled(response_url),
        "지연":  lambda: _cmd_overdue(response_url),
        "납품":  lambda: _cmd_delivery(text, response_url),
    }

    handler = dispatch.get(command)
    if handler is None:
        return jsonify({
            "text": f"알 수 없는 명령어: `/{command}`\n사용 가능: /오늘, /현장, /미청구, /지연, /납품"
        }), 200

    threading.Thread(target=handler, daemon=True).start()

    return jsonify({
        "response_type": "ephemeral",
        "text": "⏳ 조회 중...",
    })
