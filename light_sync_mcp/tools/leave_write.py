"""휴가 상신 MCP 도구 (preview + confirm) — 카카오워크 봇/웹챗 공용.

write_ops.py 에서 휴가 상신을 분리한 모듈. READONLY 봇도 '휴가 전용' 쓰기 경로만
열 수 있도록(LIGHT_SYNC_MCP_WRITE_LEAVE_ONLY=1) 별도 등록한다.

신원은 서버가 환경변수 KAKAO_ERP_USER 로 주입한다(봇이 요청마다 임시 mcp-config 에 삽입).
주입값이 있으면 requester/clicker 를 그 값으로 강제해 남의 명의 상신을 원천 차단한다.
"""
import os
import json
import datetime

from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s
from .write_ops import _parse_date, _store_session, LEAVE_TYPES, LEAVE_PERIODS

# 반차 기본 시간대 — ERP 기안 폼(templates/approval_form.html)과 동일.
# 오전 09:00~12:00 / 오후 13:00~18:00 (12~13 점심시간 제외)
HALF_TIMES = {'오전반차': ('09:00', '12:00'), '오후반차': ('13:00', '18:00')}


def register(mcp: FastMCP):

    @mcp.tool()
    def write_preview_leave_request(
        requester_username: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        leave_type: Optional[str] = None,
        period: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> str:
        """휴가 상신 preview — 확인 시 전자결재 휴가신청서가 상신됩니다.

        결재선은 ERP와 동일하게 자동 구성됩니다 (부서장 → 임원진).
        승인되면 연차가 자동 차감됩니다.

        ★ 반차도 이 도구로 처리: period="오후반차"/"오전반차", 사용일수 자동 0.5일.
        ★ 이 도구는 preview 만 만든다. 반환된 fields 를 사용자에게 그대로 보여주고
          '상신할까요?' 라고 물은 뒤, 사용자가 동의하면 confirm_leave_request(session_token)
          을 호출해 실제 상신한다. 절대 같은 턴에 바로 confirm 하지 말 것.

        ★ 필수 필드:
          - requester_username: (서버가 자동 주입 — 본인 명의로만 상신) 비워도 됨
          - start_date: 시작일 (YYYY-MM-DD / M/D / 오늘 / 내일)
          - leave_type: 연차(기본) / 병가 / 경조사 / 공가 / 기타
          - period: 종일(기본) / 오전반차(09:00~12:00) / 오후반차(13:00~18:00)
          - end_date: 종료일 (생략 시 시작일과 동일)
          - reason: 사유
        """
        from modules.services import approval_service as svc

        # 신원 주입: 봇 채널은 서버가 KAKAO_ERP_USER 로 본인을 강제한다(위조 차단).
        forced = os.environ.get("KAKAO_ERP_USER", "").strip()
        if forced:
            requester_username = forced

        if not requester_username:
            return json.dumps({"status": "error",
                "message": "requester_username 이 필요합니다. 본인 명의로만 상신할 수 있습니다."},
                ensure_ascii=False)

        if not start_date:
            return json.dumps({"status": "needs_info", "intent": "write_preview_leave_request",
                "question": "휴가 시작일이 언제입니까?",
                "hint": "예: 내일, 2026-07-20, 7/20",
                "collected": {}}, ensure_ascii=False)

        parsed_start = _parse_date(start_date)
        if not parsed_start:
            return json.dumps({"status": "needs_info", "intent": "write_preview_leave_request",
                "question": f"'{start_date}' 날짜를 인식하지 못했습니다. 다시 입력해주세요.",
                "hint": "YYYY-MM-DD 또는 M/D",
                "collected": {}}, ensure_ascii=False)

        parsed_end = _parse_date(end_date) if end_date else parsed_start
        if not parsed_end:
            parsed_end = parsed_start
        if parsed_end < parsed_start:
            return json.dumps({"status": "error",
                "message": "종료일이 시작일보다 빠릅니다."}, ensure_ascii=False)

        ltype = (leave_type or '연차').strip()
        if ltype not in LEAVE_TYPES:
            return json.dumps({"status": "needs_info", "intent": "write_preview_leave_request",
                "question": f"'{ltype}' 휴가 종류를 인식하지 못했습니다.",
                "hint": " / ".join(LEAVE_TYPES),
                "collected": {"start_date": parsed_start.isoformat()}}, ensure_ascii=False)

        prd = (period or '종일').strip()
        if prd not in LEAVE_PERIODS:
            return json.dumps({"status": "needs_info", "intent": "write_preview_leave_request",
                "question": f"'{prd}' 기간 구분을 인식하지 못했습니다.",
                "hint": " / ".join(LEAVE_PERIODS),
                "collected": {"start_date": parsed_start.isoformat(), "leave_type": ltype}},
                ensure_ascii=False)

        if '반차' in prd:
            parsed_end = parsed_start  # 반차는 하루

        if not reason:
            return json.dumps({"status": "needs_info", "intent": "write_preview_leave_request",
                "question": "휴가 사유를 입력해주세요.",
                "hint": "예: 개인사유, 병원진료, 경조사",
                "collected": {"start_date": parsed_start.isoformat(),
                              "end_date": parsed_end.isoformat(),
                              "leave_type": ltype, "period": prd}}, ensure_ascii=False)

        session = get_session()
        try:
            from modules.models.entities import User
            drafter = (session.query(User).filter(User.username == requester_username).first()
                       or session.query(User)
                       .filter(User.email.ilike(f"{requester_username}@%")).first())
            if not drafter:
                return json.dumps({"status": "error",
                    "message": f"'{requester_username}' 사용자를 ERP에서 찾을 수 없습니다."},
                    ensure_ascii=False)

            # 사용일수 — ERP 상신과 동일한 산정식
            if '반차' in prd:
                days = 0.5
                half_st, half_et = HALF_TIMES.get(prd, ('', ''))
            else:
                from modules.services import holiday_service
                days = float(holiday_service.working_days(parsed_start, parsed_end))
                half_st, half_et = '', ''
            if days <= 0:
                return json.dumps({"status": "error",
                    "message": f"{parsed_start} ~ {parsed_end} 구간에 근무일이 없습니다 "
                               "(주말/공휴일). 날짜를 확인해주세요."}, ensure_ascii=False)

            # 결재선 미리 확인 (상신 시점에 다시 구성)
            line = svc.resolve_default_line(session, drafter, form_key='leave')
            line_label = " → ".join(f"{s['approver_name']} {s['approver_position'] or ''}".strip()
                                    for s in line) or "본인 전결 (상위 결재자 없음)"

            # 잔여 연차 확인 (연차만 차감)
            balance_note = ""
            if ltype == '연차':
                from modules.services import hr_service
                summary = hr_service.leave_summary(session, drafter)
                after = round(summary['remaining'] - days, 1)
                balance_note = f"잔여 {summary['remaining']}일 → 사용 후 {after}일"
                if after < 0:
                    balance_note += "  ⚠️ 잔여 연차 부족"

            position = (drafter.position or '').strip()
            drafter_name = _s(drafter.full_name)
            drafter_dept = _s(drafter.user_group)
            title = f"{drafter_dept} {drafter_name} {position} 휴가신청서".strip()
            title = " ".join(title.split())

            token = _store_session("confirm_leave_request", {
                "drafter_id": drafter.id,
                "title": title,
                "form_data": {
                    "leave_type": ltype,
                    "period": prd,
                    "start_date": parsed_start.isoformat(),
                    "end_date": parsed_end.isoformat(),
                    "start_time": half_st,
                    "end_time": half_et,
                    "days": str(days),
                    "reason": reason,
                    "emergency_contact": _s(drafter.phone_number),
                },
                "content": reason,
            }, user_name=drafter_name)
        finally:
            session.close()

        fields = {
            "기안자": " ".join(f"{drafter_dept} {drafter_name} {position}".split()),
            "휴가종류": ltype,
            "기간구분": prd,
            "기간": (parsed_start.isoformat() if parsed_start == parsed_end
                     else f"{parsed_start.isoformat()} ~ {parsed_end.isoformat()}"),
            "사용일수": f"{days}일",
            "사유": reason,
            "결재선": line_label,
        }
        if half_st:
            fields["휴가시간"] = f"{half_st} ~ {half_et}"
        if balance_note:
            fields["연차잔여"] = balance_note

        return json.dumps({
            "status": "preview",
            "action_type": "confirm_leave_request",
            "session_token": token,
            "summary": f"휴가 상신 — {ltype} {days}일",
            "fields": fields,
            "notice": "사용자가 동의하면 confirm_leave_request(session_token) 로 상신됩니다. "
                      "승인 완료(또는 부서장 선효력) 시 연차가 자동 차감됩니다.",
        }, ensure_ascii=False)

    @mcp.tool()
    def confirm_leave_request(session_token: str) -> str:
        """휴가 상신 확정 — write_preview_leave_request 의 preview 를 실제 전자결재로 상신.

        ★ 사용자가 미리보기를 보고 '네/응/그래/확인/상신해' 등으로 명확히 동의했을 때만
          호출한다. 본인 신원은 서버가 주입(KAKAO_ERP_USER)하며 preview 기안자와 대조해
          남의 명의 상신을 차단한다.

        Args:
            session_token: write_preview_leave_request 가 반환한 session_token
        """
        from modules.models.misc_entities import PendingWriteSession
        from modules.models.entities import User
        from modules.services import approval_service as svc

        forced = os.environ.get("KAKAO_ERP_USER", "").strip()
        if not forced:
            return json.dumps({"status": "error",
                "message": "확정 권한이 없습니다(신원 미주입)."}, ensure_ascii=False)
        if not session_token:
            return json.dumps({"status": "error",
                "message": "session_token 이 필요합니다. 먼저 휴가 미리보기를 만들어 주세요."},
                ensure_ascii=False)

        session = get_session()
        try:
            row = session.get(PendingWriteSession, session_token)
            if not row:
                return json.dumps({"status": "error",
                    "message": "세션을 찾을 수 없습니다(30분 만료됐을 수 있음). 다시 신청해주세요."},
                    ensure_ascii=False)
            if row.used:
                return json.dumps({"status": "error",
                    "message": "이미 상신 처리된 신청입니다."}, ensure_ascii=False)
            if row.expires_at < datetime.datetime.now():
                return json.dumps({"status": "error",
                    "message": "미리보기가 만료되었습니다(30분 초과). 다시 신청해주세요."},
                    ensure_ascii=False)
            if row.intent_type != "confirm_leave_request":
                return json.dumps({"status": "error",
                    "message": "휴가 상신 세션이 아닙니다."}, ensure_ascii=False)

            try:
                payload = json.loads(row.payload_json)
            except Exception:
                return json.dumps({"status": "error",
                    "message": "세션 payload 파싱 오류."}, ensure_ascii=False)

            clicker = (session.query(User).filter(User.username == forced).first()
                       or session.query(User).filter(User.email.ilike(f"{forced}@%")).first())
            result = svc.submit_leave_from_payload(session, payload, clicker)
            if not result.get("ok"):
                session.rollback()
                return json.dumps({"status": "error",
                    "message": result.get("msg", "상신 실패")}, ensure_ascii=False)
            row.used = True
            session.commit()
            return json.dumps({"status": "done",
                "doc_no": result.get("doc_no"),
                "message": result.get("label"),
                "detail": result.get("detail")}, ensure_ascii=False)
        except Exception as e:
            session.rollback()
            return json.dumps({"status": "error",
                "message": f"상신 중 오류: {str(e)[:150]}"}, ensure_ascii=False)
        finally:
            session.close()
