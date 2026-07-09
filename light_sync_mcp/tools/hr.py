"""인사/연차 도메인 Tools (4개)

연차 산정은 modules/services/hr_service.py 로직을 그대로 재사용한다.
(입사일 기준 부여 → 전자결재 승인분 자동차감 + 수동 사용분 + 조정)
직접 계산하지 말 것 — ERP 화면과 숫자가 어긋난다.
"""
import datetime
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s


def _resolve_user(session, name):
    """실명 / username / 메일 아이디 → User."""
    from modules.models.entities import User
    if not name:
        return None
    u = session.query(User).filter(User.full_name == name).first()
    if not u:
        u = session.query(User).filter(User.username == name).first()
    if not u:
        u = session.query(User).filter(User.email.ilike(f"{name}@%")).first()
    if not u:
        u = session.query(User).filter(User.full_name.ilike(f"%{name}%")).first()
    return u


def register(mcp: FastMCP):

    @mcp.tool()
    def get_leave_balance(employee: Optional[str] = None) -> str:
        """연차 잔여일수 조회 (부여/사용/조정/잔여).
        ★ '연차 며칠 남았어', 'OOO 연차 잔여', '남은 휴가' 질문에 사용.

        employee 생략 시 전체 직원의 잔여 연차를 요약해 반환합니다.

        Args:
            employee: 직원 이름 (생략 시 전원)
        """
        from modules.models.entities import User
        from modules.services import hr_service
        session = get_session()
        try:
            if employee:
                user = _resolve_user(session, employee)
                if not user:
                    return json.dumps({"error": f"직원을 찾을 수 없습니다: {employee}"},
                                      ensure_ascii=False)
                users = [user]
            else:
                users = (session.query(User)
                         .filter(User.role != 'pending', User.hire_date.isnot(None))
                         .order_by(User.user_group, User.full_name).all())

            items = []
            for u in users:
                s = hr_service.leave_summary(session, u)
                row = {
                    "name": _s(u.full_name),
                    "position": _s(u.position),
                    "department": _s(u.user_group),
                    "hire_date": u.hire_date.isoformat() if u.hire_date else "",
                    "years": s.get("years"),
                    "granted": s["granted"],
                    "used": s["used"],
                    "adjust": s["adjust"],
                    "remaining": s["remaining"],
                    "leave_year": f"{s['year_start']} ~ {s['year_end']}",
                }
                if employee:
                    row["detail"] = [{
                        "doc_no": d.get("doc_no"),
                        "leave_type": d.get("leave_type"),
                        "start": d.get("start"),
                        "end": d.get("end"),
                        "days": d.get("days"),
                        "manual": d.get("manual"),
                    } for d in s["detail"]]
                items.append(row)

            return json.dumps({
                "count": len(items),
                "basis": "입사일 기준 연차연도. 부여 + 조정 − 사용(전자결재 승인분 + 수동등록분).",
                "items": items if employee else sorted(items, key=lambda x: x["remaining"], reverse=True),
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_leave_calendar(
        year: Optional[int] = None,
        month: Optional[int] = None,
        employee: Optional[str] = None,
    ) -> str:
        """기간별 휴가 일정 — 전자결재 승인(또는 선효력) 휴가신청서 기준.
        ★ '이번 달 누가 휴가야', '다음주 연차자', '휴가 일정' 질문에 사용.

        Args:
            year: 연도 (생략 시 올해)
            month: 월 (생략 시 이번 달)
            employee: 특정 직원만
        """
        from modules.services.approval_service import get_approved_leaves_for_month
        session = get_session()
        try:
            today = datetime.date.today()
            year = year or today.year
            month = month or today.month

            # ERP 휴가 달력과 동일한 정본 로직 재사용 (날짜별 전개)
            by_day = get_approved_leaves_for_month(session, year, month)

            days = []
            seen = {}
            for day in sorted(by_day):
                people = []
                for ev in by_day[day]:
                    if employee and employee not in _s(ev.get('name')):
                        continue
                    people.append({
                        "name": _s(ev.get('name')),
                        "department": _s(ev.get('dept')),
                        "position": _s(ev.get('position')),
                        "type": _s(ev.get('disp_type')),
                        "leave_type": _s(ev.get('leave_type')),
                    })
                    key = (_s(ev.get('name')), ev.get('doc_id'))
                    seen.setdefault(key, {
                        "name": _s(ev.get('name')),
                        "department": _s(ev.get('dept')),
                        "type": _s(ev.get('disp_type')),
                        "start": ev['start'].isoformat(),
                        "end": (ev['end'] - datetime.timedelta(days=1)).isoformat(),
                    })
                if people:
                    days.append({"date": day.isoformat(), "count": len(people), "people": people})

            return json.dumps({
                "year": year,
                "month": month,
                "day_count": len(days),
                "leave_doc_count": len(seen),
                "basis": "전자결재 휴가신청서 중 승인완료 또는 부서장 선효력 발생분 (ERP 달력과 동일)",
                "by_leave": sorted(seen.values(), key=lambda x: x["start"]),
                "by_date": days,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_leave_promotion_status(year: Optional[int] = None) -> str:
        """연차사용촉진제 진행 현황 (근로기준법 제61조).
        ★ '연차촉진 어디까지 갔어', '촉구 대상자', '2차 통보 필요한 사람' 질문에 사용.

        Args:
            year: 연차연도(입사기념 시작연도). 생략 시 전체 최근순.
        """
        from modules.models import LeavePromotion
        session = get_session()
        try:
            q = session.query(LeavePromotion)
            if year:
                q = q.filter(LeavePromotion.leave_year == year)
            rows = q.order_by(LeavePromotion.notified_at.desc()).limit(100).all()

            stage_ko = {'first': '1차 촉구', 'extra': '추가 촉구', 'second': '2차 회사지정'}
            status_ko = {
                'sent': '통보발송', 'designated': '직원지정완료',
                'admin_designated': '회사지정완료', 'completed': '완료', 'expired': '기한만료',
            }
            items = [{
                "name": _s(p.user.full_name) if p.user else "",
                "leave_year": p.leave_year,
                "emp_type": '1년이상' if p.emp_type == 'over1y' else '1년미만',
                "stage": stage_ko.get(p.stage, _s(p.stage)),
                "status": status_ko.get(p.status, _s(p.status)),
                "remaining_days": float(p.remaining_days) if p.remaining_days is not None else None,
                "notified_at": p.notified_at.strftime('%Y-%m-%d') if p.notified_at else "",
                "designate_due": p.designate_due.isoformat() if p.designate_due else "",
                "email_sent": bool(p.email_sent),
                "employee_dates": p.employee_dates or [],
                "admin_dates": p.admin_dates or [],
            } for p in rows]

            by_stage = {}
            for it in items:
                by_stage[it["stage"]] = by_stage.get(it["stage"], 0) + 1

            return json.dumps({
                "year": year,
                "count": len(items),
                "by_stage": by_stage,
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_employee_card(employee: str) -> str:
        """직원 인사카드 — 소속/직급/입사일/근속/연락처 + 연차 요약.
        ★ 'OOO 언제 입사했어', '근속 몇 년', 'OOO 인사정보' 질문에 사용.

        Args:
            employee: 직원 이름
        """
        from modules.services import hr_service
        session = get_session()
        try:
            u = _resolve_user(session, employee)
            if not u:
                return json.dumps({"error": f"직원을 찾을 수 없습니다: {employee}"},
                                  ensure_ascii=False)

            out = {
                "name": _s(u.full_name),
                "position": _s(u.position),
                "department": _s(u.user_group),
                "email": _s(u.email),
                "phone": _s(u.phone_number),
                "hire_date": u.hire_date.isoformat() if u.hire_date else "",
                "role": _s(u.role),
            }
            if u.hire_date:
                s = hr_service.leave_summary(session, u)
                out["years_of_service"] = s.get("years")
                out["leave"] = {
                    "granted": s["granted"], "used": s["used"],
                    "adjust": s["adjust"], "remaining": s["remaining"],
                    "leave_year": f"{s['year_start']} ~ {s['year_end']}",
                }
            return json.dumps(out, ensure_ascii=False)
        finally:
            session.close()
