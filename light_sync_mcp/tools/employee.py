"""직원/근무인원 조회 Tools"""
import json
import datetime
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s


def register(mcp: FastMCP):

    @mcp.tool()
    def get_employees(
        department: Optional[str] = None,
        search: Optional[str] = None,
    ) -> str:
        """직원 목록 조회. 전체 인원수와 부서별 인원을 반환합니다.
        ★ '직원 몇 명', '우리 회사 인원' 등의 질문에 사용.
        department: 부서(그룹) 필터 (예: 영업부, 생산부, 관리부)
        search: 이름 검색
        """
        from modules.models.entities import User
        from sqlalchemy import func
        session = get_session()
        try:
            q = session.query(User).filter(User.role != 'pending')
            if department:
                q = q.filter(User.user_group.ilike(f"%{department}%"))
            if search:
                q = q.filter(User.full_name.ilike(f"%{search}%"))

            users = q.order_by(User.user_group, User.full_name).all()

            # 부서별 그룹핑
            dept_counts = {}
            user_list = []
            for u in users:
                dept = _s(u.user_group) or '미배정'
                dept_counts[dept] = dept_counts.get(dept, 0) + 1
                user_list.append({
                    "name": _s(u.full_name),
                    "position": _s(u.position),
                    "department": dept,
                    "phone": _s(u.phone_number),
                    "email": _s(u.email),
                })

            return json.dumps({
                "total": len(users),
                "by_department": dept_counts,
                "employees": user_list,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_today_attendance(
        target_date: Optional[str] = None,
    ) -> str:
        """오늘(또는 지정 날짜)의 근무인원 조회.
        전자결재 휴가신청서(승인 또는 부서장 선효력) 기준으로 연차/반차를 반영합니다.
        ★ '오늘 근무 몇 명', '누가 연차야', '출근 인원' 등의 질문에 사용.
        target_date: YYYY-MM-DD (생략 시 오늘)
        """
        from modules.models.entities import User
        from modules.services.approval_service import get_approved_leaves_for_date
        session = get_session()
        try:
            # 날짜 파싱
            if target_date:
                dt = datetime.date.fromisoformat(target_date)
            else:
                dt = datetime.date.today()

            # 전체 직원 (pending 제외)
            all_users = session.query(User).filter(User.role != 'pending').all()
            total = len(all_users)

            # 전자결재 휴가 문서 (승인 완료 또는 부서장 결재로 선효력 발생)
            # ERP 달력과 동일한 정본 로직 재사용
            events = get_approved_leaves_for_date(session, dt)

            full_leave = []   # 종일 휴가
            half_leave = []   # 반차

            for ev in events:
                entry = {
                    "name": _s(ev.get('name')),
                    "department": _s(ev.get('dept')),
                    "position": _s(ev.get('position')),
                    "type": _s(ev.get('disp_type')),
                    "leave_type": _s(ev.get('leave_type')),
                }
                if '반차' in _s(ev.get('disp_type')):
                    half_leave.append(entry)
                else:
                    full_leave.append(entry)

            working_count = total - len(full_leave)  # 반차는 출근으로 계산

            # 요일
            weekday_names = ['월', '화', '수', '목', '금', '토', '일']
            weekday = weekday_names[dt.weekday()]
            is_weekend = dt.weekday() >= 5

            return json.dumps({
                "date": dt.isoformat(),
                "weekday": weekday,
                "is_weekend": is_weekend,
                "total_employees": total,
                "working_count": int(working_count),
                "full_leave_count": len(full_leave),
                "half_leave_count": len(half_leave),
                "full_leave": full_leave,
                "half_leave": half_leave,
                "summary": f"{dt.month}/{dt.day}({weekday}) 전체 {total}명 중 근무 {int(working_count)}명"
                           + (f", 연차 {len(full_leave)}명" if full_leave else "")
                           + (f", 반차 {len(half_leave)}명" if half_leave else ""),
            }, ensure_ascii=False)
        finally:
            session.close()
