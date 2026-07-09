"""채팅→ERP 쓰기 작업 Preview 도구 (11종)

패턴:
  1. 필드 부족 → {"status":"needs_info", "question":"...", "hint":"..."}
  2. 모든 필드 확보 → {"status":"preview", ...fields..., "session_token":"uuid",
                        "action_type":"confirm_xxx"}
  3. 사용자가 확인 버튼 클릭 → Flask /mattermost/action → DB 실제 반영

history_logs.origin = 'chat_confirmed' 으로 기록됨 (KPI 추적).
"""
from __future__ import annotations

import datetime
import json
import uuid
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _erp_url

# ── 차량 선택지 (ERP와 동일) ──────────────────────────────
VEHICLE_CHOICES = ['쏘렌토 9539', '스타리아 3417', '포터 8804', '개인차량', '대중교통', '기타']

# ── 결함 유형 (한국어 → 코드) ─────────────────────────────
DEFECT_LABEL_MAP = {
    'LED모듈': 'LED_MODULE', 'LED 모듈': 'LED_MODULE', 'LED 모듈 불량': 'LED_MODULE',
    'SMPS': 'SMPS', 'SMPS 고장': 'SMPS',
    '방열': 'HEAT', '방열 이상': 'HEAT',
    '렌즈': 'LENS', '렌즈 손상': 'LENS', '리플렉터': 'LENS',
    '결로': 'MOISTURE', '침수': 'MOISTURE', '결로/침수': 'MOISTURE',
    '제어': 'CONTROL', '제어 불량': 'CONTROL', '제어기': 'CONTROL',
    '배선': 'WIRING', '커넥터': 'WIRING', '배선 불량': 'WIRING',
    '외관': 'BODY', '바디': 'BODY',
    '폴': 'POLE', '전주': 'POLE',
    '도색': 'PAINT', '도장': 'PAINT',
    '앙카': 'ANCHOR', '앵커': 'ANCHOR', '볼트': 'ANCHOR',
    '센서': 'SENSOR',
    '기타': 'OTHER',
}
DEFECT_TYPES_HINT = "LED모듈/SMPS/방열/렌즈/결로/제어/배선/외관/폴/도색/앙카/센서/기타"

# ── 발주 상태 ─────────────────────────────────────────────
PO_STATUS_FLOW = ['작성중', '발송완료', '입고대기', '입고완료', '취소']

# ── 휴가 양식 선택지 (approval_form_templates.field_schema 와 동일) ──
LEAVE_TYPES = ['연차', '병가', '경조사', '공가', '기타']
LEAVE_PERIODS = ['종일', '오전반차', '오후반차']


def _store_session(intent_type: str, payload: Dict[str, Any],
                   user_name: str = "", channel_id: str = "") -> str:
    """PendingWriteSession DB 저장 → token 반환"""
    from modules.models.misc_entities import PendingWriteSession
    token = str(uuid.uuid4())
    session = get_session()
    try:
        row = PendingWriteSession(
            token=token,
            intent_type=intent_type,
            payload_json=json.dumps(payload, ensure_ascii=False, default=str),
            user_name=user_name,
            channel_id=channel_id,
            expires_at=datetime.datetime.now() + datetime.timedelta(minutes=30),
            used=False,
        )
        session.add(row)
        session.commit()
    finally:
        session.close()
    return token


def register(mcp: FastMCP):

    # ══════════════════════════════════════════════════════
    # 1. 납품완료 처리
    # ══════════════════════════════════════════════════════
    @mcp.tool()
    def write_preview_delivery_complete(
        project_search: str,
        completed_date: Optional[str] = None,
    ) -> str:
        """납품완료 처리 preview.

        ★ 필수 필드:
          - project_search: 현장명/약칭 (예: "세종반다비")
          - completed_date: 납품완료일 (YYYY-MM-DD 또는 M/D, 생략 시 오늘)

        status=needs_info 이면 question 필드를 사용자에게 그대로 전달.
        status=preview 이면 summary와 fields를 보여주고 확인 버튼 제시.
        """
        from modules.models.entities import Project, Contract, Delivery, DeliverySplit

        # ── 납품완료일 파싱 ──────────────────────────────
        today = datetime.date.today()
        if not completed_date:
            return json.dumps({
                "status": "needs_info",
                "intent": "write_preview_delivery_complete",
                "question": f"납품완료일이 언제입니까? (오늘: {today.strftime('%Y-%m-%d')})",
                "hint": "예: 오늘, 2026-05-13, 5/13",
                "collected": {"project_search": project_search},
            }, ensure_ascii=False)

        parsed_date = _parse_date(completed_date)
        if not parsed_date:
            return json.dumps({
                "status": "needs_info",
                "intent": "write_preview_delivery_complete",
                "question": f"날짜를 인식하지 못했습니다. 다시 입력해주세요. (예: 2026-05-13, 5/13)",
                "hint": "YYYY-MM-DD 또는 M/D 형식",
                "collected": {"project_search": project_search},
            }, ensure_ascii=False)

        # ── 현장 검색 ────────────────────────────────────
        session = get_session()
        try:
            projects = session.query(Project).filter(
                Project.temp_name.ilike(f"%{project_search}%")
                | Project.short_name.ilike(f"%{project_search}%")
                | Project.project_no.ilike(f"%{project_search}%")
            ).filter(~Project.status.in_(["납품완료", "취소"])).limit(5).all()

            if not projects:
                return json.dumps({"status": "error", "message": f"'{project_search}' 현장을 찾을 수 없습니다."}, ensure_ascii=False)
            if len(projects) > 1:
                names = ", ".join(f"{p.temp_name or p.short_name}(id={p.id})" for p in projects[:5])
                return json.dumps({"status": "needs_info", "intent": "write_preview_delivery_complete",
                    "question": f"여러 현장이 검색됩니다. 더 정확한 이름을 입력해주세요.\n검색 결과: {names}",
                    "hint": "현장명을 더 구체적으로 입력하세요.",
                    "collected": {"project_search": project_search, "completed_date": completed_date},
                }, ensure_ascii=False)

            project = projects[0]

            # ── 예정 split 조회 ──────────────────────────
            splits = (
                session.query(DeliverySplit)
                .join(Delivery, DeliverySplit.delivery_id == Delivery.id)
                .filter(Delivery.project_id == project.id)
                .filter(DeliverySplit.status.in_(["예정", "진행중"]))
                .order_by(DeliverySplit.split_no.asc())
                .all()
            )

            if not splits:
                return json.dumps({"status": "error", "message": f"{project.temp_name}: 완료 처리할 납품 회차가 없습니다 (이미 완료됐거나 등록된 일정이 없음)."}, ensure_ascii=False)

            split_info = [{"id": s.id, "split_no": s.split_no, "quantity": s.quantity,
                           "scheduled_date": _s(s.scheduled_date)} for s in splits]
            total_qty = sum(s.quantity or 0 for s in splits)

            token = _store_session("confirm_delivery_complete", {
                "project_id": project.id,
                "split_ids": [s.id for s in splits],
                "completed_date": parsed_date.isoformat(),
            })

            return json.dumps({
                "status": "preview",
                "action_type": "confirm_delivery_complete",
                "session_token": token,
                "summary": f"납품완료 처리 — {project.temp_name or project.short_name}",
                "fields": {
                    "현장": _s(project.temp_name or project.short_name),
                    "납품완료일": parsed_date.isoformat(),
                    "처리 회차": f"{len(splits)}건",
                    "총 수량": f"{total_qty}EA",
                    "회차 목록": split_info,
                },
                "erp_url": _erp_url(f"/delivery_management/{project.id}"),
            }, ensure_ascii=False)
        finally:
            session.close()

    # ══════════════════════════════════════════════════════
    # 2. AS 접수
    # ══════════════════════════════════════════════════════
    @mcp.tool()
    def write_preview_as_register(
        project_search: str,
        defect_type: Optional[str] = None,
        symptom: Optional[str] = None,
        received_date: Optional[str] = None,
    ) -> str:
        """AS 접수 등록 preview.

        ★ 필수 필드:
          - project_search: 현장명
          - defect_type: 결함 유형 (LED모듈/SMPS/방열/렌즈/결로/제어/배선/외관/폴/도색/앙카/센서/기타)
          - symptom: 증상 설명
          - received_date: 접수일 (생략 시 오늘)
        """
        from modules.models.entities import Project, Warranty

        today = datetime.date.today()

        if not defect_type:
            return json.dumps({"status": "needs_info", "intent": "write_preview_as_register",
                "question": f"결함 유형이 무엇입니까?",
                "hint": DEFECT_TYPES_HINT,
                "collected": {"project_search": project_search},
            }, ensure_ascii=False)

        defect_code = _map_defect(defect_type)
        if not defect_code:
            return json.dumps({"status": "needs_info", "intent": "write_preview_as_register",
                "question": f"'{defect_type}'를 인식할 수 없습니다. 결함 유형을 다시 선택해주세요.",
                "hint": DEFECT_TYPES_HINT,
                "collected": {"project_search": project_search},
            }, ensure_ascii=False)

        if not symptom:
            return json.dumps({"status": "needs_info", "intent": "write_preview_as_register",
                "question": "증상을 설명해주세요. (예: 3번 가로등 점등 안 됨)",
                "hint": "구체적인 증상, 위치, 수량 등 포함",
                "collected": {"project_search": project_search, "defect_type": defect_type},
            }, ensure_ascii=False)

        parsed_date = _parse_date(received_date) if received_date else today

        session = get_session()
        try:
            projects = session.query(Project).filter(
                Project.temp_name.ilike(f"%{project_search}%")
                | Project.short_name.ilike(f"%{project_search}%")
            ).limit(5).all()

            if not projects:
                return json.dumps({"status": "error", "message": f"'{project_search}' 현장 없음"}, ensure_ascii=False)
            if len(projects) > 1:
                names = ", ".join(f"{p.temp_name or p.short_name}(id={p.id})" for p in projects[:5])
                return json.dumps({"status": "needs_info", "intent": "write_preview_as_register",
                    "question": f"여러 현장이 검색됩니다. 더 정확히 입력해주세요.\n결과: {names}",
                    "hint": "현장명을 더 구체적으로",
                    "collected": {"project_search": project_search, "defect_type": defect_type, "symptom": symptom},
                }, ensure_ascii=False)

            project = projects[0]
            warranty = session.query(Warranty).filter(Warranty.project_id == project.id).first()

            # case_no 자동 생성
            from modules.models.entities import WarrantyCase
            from sqlalchemy import func
            year = today.year
            cnt = session.query(func.count(WarrantyCase.id)).filter(
                WarrantyCase.case_no.ilike(f"WC{year}-%")
            ).scalar() or 0
            case_no = f"WC{year}-{cnt+1:03d}"

            defect_label = dict(DEFECT_LABEL_MAP).get(defect_type, defect_type)

            token = _store_session("confirm_as_register", {
                "project_id": project.id,
                "warranty_id": warranty.id if warranty else None,
                "case_no": case_no,
                "defect_code": defect_code,
                "defect_label": defect_type,
                "symptom": symptom,
                "received_date": (parsed_date or today).isoformat(),
                "manual_site_name": _s(project.temp_name or project.short_name),
            })

            return json.dumps({
                "status": "preview",
                "action_type": "confirm_as_register",
                "session_token": token,
                "summary": f"AS 접수 — {project.temp_name or project.short_name}",
                "fields": {
                    "현장": _s(project.temp_name or project.short_name),
                    "접수번호": case_no,
                    "결함유형": defect_type,
                    "증상": symptom,
                    "접수일": (parsed_date or today).isoformat(),
                },
                "erp_url": _erp_url(f"/warranty/{project.id}"),
            }, ensure_ascii=False)
        finally:
            session.close()

    # ══════════════════════════════════════════════════════
    # 3. 청구완료 처리
    # ══════════════════════════════════════════════════════
    @mcp.tool()
    def write_preview_billing_complete(
        project_search: str,
        invoice_date: Optional[str] = None,
    ) -> str:
        """청구완료 처리 preview. 납품완료 후 미청구 계약을 청구완료로 변경.

        ★ 필수 필드:
          - project_search: 현장명 또는 계약명
          - invoice_date: 세금계산서 발행일 (YYYY-MM-DD)
        """
        from modules.models.entities import Project, Contract, Delivery

        today = datetime.date.today()

        if not invoice_date:
            return json.dumps({"status": "needs_info", "intent": "write_preview_billing_complete",
                "question": f"세금계산서 발행일이 언제입니까? (오늘: {today.strftime('%Y-%m-%d')})",
                "hint": "예: 오늘, 2026-05-31, 5/31",
                "collected": {"project_search": project_search},
            }, ensure_ascii=False)

        parsed_date = _parse_date(invoice_date)
        if not parsed_date:
            return json.dumps({"status": "needs_info", "intent": "write_preview_billing_complete",
                "question": "날짜를 인식하지 못했습니다. 다시 입력해주세요.",
                "hint": "YYYY-MM-DD 또는 M/D",
                "collected": {"project_search": project_search},
            }, ensure_ascii=False)

        session = get_session()
        try:
            contracts = (
                session.query(Contract, Project)
                .join(Project, Contract.project_id == Project.id)
                .join(Delivery, Delivery.contract_id == Contract.id)
                .filter(
                    Contract.is_excluded.isnot(True),
                    Delivery.delivery_status == "done",
                    Contract.payment_status == "미청구",
                )
                .filter(
                    Project.temp_name.ilike(f"%{project_search}%")
                    | Project.short_name.ilike(f"%{project_search}%")
                    | Contract.contract_name.ilike(f"%{project_search}%")
                )
                .limit(5).all()
            )

            if not contracts:
                return json.dumps({"status": "error",
                    "message": f"'{project_search}' 해당 미청구 계약을 찾을 수 없습니다. (이미 청구됐거나 납품완료 전일 수 있음)"
                }, ensure_ascii=False)

            if len(contracts) > 1:
                names = ", ".join(f"{c.contract_name or p.temp_name}(id={c.id})" for c, p in contracts[:5])
                return json.dumps({"status": "needs_info", "intent": "write_preview_billing_complete",
                    "question": f"여러 계약이 검색됩니다. 더 정확한 이름으로 입력해주세요.\n결과: {names}",
                    "hint": "계약명을 더 구체적으로",
                    "collected": {"project_search": project_search, "invoice_date": invoice_date},
                }, ensure_ascii=False)

            contract, project = contracts[0]

            token = _store_session("confirm_billing_complete", {
                "contract_id": contract.id,
                "project_id": project.id,
                "invoice_date": parsed_date.isoformat(),
            })

            return json.dumps({
                "status": "preview",
                "action_type": "confirm_billing_complete",
                "session_token": token,
                "summary": f"청구완료 처리 — {contract.contract_name or project.temp_name}",
                "fields": {
                    "현장": _s(project.temp_name or project.short_name),
                    "계약명": _s(contract.contract_name),
                    "세금계산서 발행일": parsed_date.isoformat(),
                    "현재 상태": _s(contract.payment_status),
                    "변경 후": "청구완료",
                },
                "erp_url": _erp_url(f"/contract_detail/{project.id}"),
            }, ensure_ascii=False)
        finally:
            session.close()

    # ══════════════════════════════════════════════════════
    # 4. 운행일지 등록
    # ══════════════════════════════════════════════════════
    @mcp.tool()
    def write_preview_vehicle_log(
        destination: Optional[str] = None,
        distance_km: Optional[int] = None,
        purpose: Optional[str] = None,
        vehicle: Optional[str] = None,
        use_date: Optional[str] = None,
        driver_name: Optional[str] = None,
    ) -> str:
        """운행일지 등록 preview.

        ★ 필수 필드:
          - destination: 목적지 (예: 세종시청, 장흥현장)
          - distance_km: 운행거리 km (정수)
          - purpose: 운행목적 (예: 현장점검, AS처리)
          - vehicle: 차량 (쏘렌토 9539/스타리아 3417/포터 8804/개인차량/대중교통/기타)
          - driver_name: 운전자 이름
          - use_date: 운행일 (생략 시 오늘)
        """
        today = datetime.date.today()

        if not destination:
            return json.dumps({"status": "needs_info", "intent": "write_preview_vehicle_log",
                "question": "목적지가 어디입니까?",
                "hint": "예: 세종시청, 장흥현장, 본사",
                "collected": {},
            }, ensure_ascii=False)

        if distance_km is None:
            return json.dumps({"status": "needs_info", "intent": "write_preview_vehicle_log",
                "question": f"'{destination}' 운행 거리가 몇 km입니까?",
                "hint": "정수로 입력 (예: 185)",
                "collected": {"destination": destination},
            }, ensure_ascii=False)

        if not purpose:
            return json.dumps({"status": "needs_info", "intent": "write_preview_vehicle_log",
                "question": "운행 목적을 입력해주세요.",
                "hint": "예: 현장점검, AS처리, 자재운반, 계약미팅",
                "collected": {"destination": destination, "distance_km": distance_km},
            }, ensure_ascii=False)

        if not vehicle:
            choices_str = " / ".join(VEHICLE_CHOICES)
            return json.dumps({"status": "needs_info", "intent": "write_preview_vehicle_log",
                "question": "어떤 차량을 이용했습니까?",
                "hint": choices_str,
                "collected": {"destination": destination, "distance_km": distance_km, "purpose": purpose},
            }, ensure_ascii=False)

        matched_vehicle = _match_vehicle(vehicle)
        if not matched_vehicle:
            choices_str = " / ".join(VEHICLE_CHOICES)
            return json.dumps({"status": "needs_info", "intent": "write_preview_vehicle_log",
                "question": f"'{vehicle}' 차량을 인식하지 못했습니다. 다시 선택해주세요.",
                "hint": choices_str,
                "collected": {"destination": destination, "distance_km": distance_km, "purpose": purpose},
            }, ensure_ascii=False)

        if not driver_name:
            return json.dumps({"status": "needs_info", "intent": "write_preview_vehicle_log",
                "question": "운전자 이름을 입력해주세요.",
                "hint": "예: 김정수, 김선중",
                "collected": {"destination": destination, "distance_km": distance_km,
                              "purpose": purpose, "vehicle": vehicle},
            }, ensure_ascii=False)

        parsed_date = _parse_date(use_date) if use_date else today

        # ERP user 조회 (이름 기준)
        session = get_session()
        try:
            from modules.models.entities import User
            erp_user = session.query(User).filter(
                User.full_name == driver_name
            ).first()
            user_id = erp_user.id if erp_user else None
            dept = erp_user.user_group if erp_user else None
            position = erp_user.position if erp_user else None
        finally:
            session.close()

        token = _store_session("confirm_vehicle_log", {
            "vehicle": matched_vehicle,
            "destination": destination,
            "distance_km": int(distance_km),
            "purpose": purpose,
            "use_date": (parsed_date or today).isoformat(),
            "driver_name": driver_name,
            "user_id": user_id,
            "user_department": dept,
            "user_position": position,
            "origin": "출발지 미기재",
        })

        return json.dumps({
            "status": "preview",
            "action_type": "confirm_vehicle_log",
            "session_token": token,
            "summary": f"운행일지 등록 — {driver_name} / {matched_vehicle}",
            "fields": {
                "운전자": driver_name,
                "차량": matched_vehicle,
                "운행일": (parsed_date or today).isoformat(),
                "목적지": destination,
                "거리": f"{distance_km}km",
                "목적": purpose,
            },
        }, ensure_ascii=False)

    # ══════════════════════════════════════════════════════
    # 5. 출장 등록
    # ══════════════════════════════════════════════════════
    @mcp.tool()
    def write_preview_business_trip(
        destination: Optional[str] = None,
        departure_date: Optional[str] = None,
        departure_time: Optional[str] = None,
        travelers: Optional[str] = None,
        purpose: Optional[str] = None,
        vehicle: Optional[str] = None,
        return_date: Optional[str] = None,
        return_time: Optional[str] = None,
        requester_username: Optional[str] = None,
    ) -> str:
        """출장 등록 preview.

        ★ 필수 필드:
          - destination: 출장지
          - departure_date: 출발일 (YYYY-MM-DD 또는 M/D)
          - departure_time: 출발시각 (HH:MM, 예: 08:30)
          - travelers: 출장자 이름 (쉼표 구분, 예: 김정수, 김선중)
          - purpose: 출장 목적
          - vehicle: 이동수단 (쏘렌토 9539/스타리아 3417/포터 8804/개인차량/대중교통/기타)
          - return_date: 귀환일 (생략 시 당일)
          - return_time: 귀환예정시각 (HH:MM, 예: 18:00)

        ★ requester_username: 채널 태그의 user="..." 값을 그대로 전달.
          - travelers가 비어 있고 사용자가 1인칭(나/저/혼자/본인)을 썼거나 출장자를 명시하지 않은 경우,
            이 값으로 발신자 ERP 프로필을 자동 조회해 travelers를 채웁니다 (재질문 회피).
          - 명시적으로 다른 사람 이름을 받았다면 travelers를 그대로 두세요.
        """
        today = datetime.date.today()

        # ── 결정론적 자동 채움: travelers 미지정 + requester_username 있음 → 발신자로 채움 ──
        # mmbot은 channel 태그의 user="..." 를 항상 전달하므로 LLM이 1인칭 추출을 놓쳐도 여기서 복구.
        if (not travelers or not travelers.strip()) and requester_username:
            try:
                _s = get_session()
                try:
                    from modules.models.entities import User as _User
                    _u = _s.query(_User).filter(_User.username == requester_username).first()
                    if not _u:
                        _u = _s.query(_User).filter(_User.email.ilike(f"{requester_username}@%")).first()
                    if _u and _u.full_name:
                        travelers = _u.full_name
                finally:
                    _s.close()
            except Exception:
                pass  # 매핑 실패 시 기존 needs_info 흐름으로 자연 fallback

        if not destination:
            return json.dumps({"status": "needs_info", "intent": "write_preview_business_trip",
                "question": "출장지가 어디입니까?",
                "hint": "예: 세종시, 장흥군청, 본사",
                "collected": {},
            }, ensure_ascii=False)

        if not departure_date:
            return json.dumps({"status": "needs_info", "intent": "write_preview_business_trip",
                "question": f"출발일이 언제입니까? (오늘: {today.strftime('%Y-%m-%d')})",
                "hint": "예: 오늘, 내일, 2026-05-15, 5/15",
                "collected": {"destination": destination},
            }, ensure_ascii=False)

        parsed_depart = _parse_date(departure_date)
        if not parsed_depart:
            return json.dumps({"status": "needs_info", "intent": "write_preview_business_trip",
                "question": "출발일 날짜를 인식하지 못했습니다. 다시 입력해주세요.",
                "hint": "YYYY-MM-DD 또는 M/D",
                "collected": {"destination": destination},
            }, ensure_ascii=False)

        if not departure_time:
            return json.dumps({"status": "needs_info", "intent": "write_preview_business_trip",
                "question": "출발 시각이 몇 시입니까?",
                "hint": "예: 08:30, 9시, 오전 8시",
                "collected": {"destination": destination, "departure_date": departure_date},
            }, ensure_ascii=False)

        parsed_depart_time = _parse_time(departure_time)
        if not parsed_depart_time:
            return json.dumps({"status": "needs_info", "intent": "write_preview_business_trip",
                "question": f"'{departure_time}' 시각을 인식하지 못했습니다. 다시 입력해주세요.",
                "hint": "예: 08:30, 09:00",
                "collected": {"destination": destination, "departure_date": departure_date},
            }, ensure_ascii=False)

        if not travelers:
            return json.dumps({"status": "needs_info", "intent": "write_preview_business_trip",
                "question": "출장자 이름을 입력해주세요.",
                "hint": "여러 명이면 쉼표로 구분 (예: 김정수, 김선중)",
                "collected": {"destination": destination, "departure_date": departure_date,
                              "departure_time": departure_time},
            }, ensure_ascii=False)

        if not purpose:
            return json.dumps({"status": "needs_info", "intent": "write_preview_business_trip",
                "question": "출장 목적을 입력해주세요.",
                "hint": "예: 현장점검, 계약미팅, 납품확인",
                "collected": {"destination": destination, "departure_date": departure_date,
                              "departure_time": departure_time, "travelers": travelers},
            }, ensure_ascii=False)

        if not vehicle:
            choices_str = " / ".join(VEHICLE_CHOICES)
            return json.dumps({"status": "needs_info", "intent": "write_preview_business_trip",
                "question": "이동수단이 무엇입니까?",
                "hint": choices_str,
                "collected": {"destination": destination, "departure_date": departure_date,
                              "departure_time": departure_time, "travelers": travelers,
                              "purpose": purpose},
            }, ensure_ascii=False)

        matched_vehicle = _match_vehicle(vehicle)
        if not matched_vehicle:
            return json.dumps({"status": "needs_info", "intent": "write_preview_business_trip",
                "question": f"'{vehicle}' 이동수단을 인식하지 못했습니다.",
                "hint": " / ".join(VEHICLE_CHOICES),
                "collected": {"destination": destination, "departure_date": departure_date,
                              "departure_time": departure_time, "travelers": travelers,
                              "purpose": purpose},
            }, ensure_ascii=False)

        if not return_date:
            return json.dumps({"status": "needs_info", "intent": "write_preview_business_trip",
                "question": f"귀환 예정일이 언제입니까? (당일이면 {parsed_depart.strftime('%Y-%m-%d')} 입력)",
                "hint": "예: 오늘, 내일, 5/15",
                "collected": {"destination": destination, "departure_date": departure_date,
                              "departure_time": departure_time, "travelers": travelers,
                              "purpose": purpose, "vehicle": vehicle},
            }, ensure_ascii=False)

        parsed_return = _parse_date(return_date) or parsed_depart

        if not return_time:
            return json.dumps({"status": "needs_info", "intent": "write_preview_business_trip",
                "question": "귀환 예정 시각이 몇 시입니까?",
                "hint": "예: 18:00, 저녁 6시",
                "collected": {"destination": destination, "departure_date": departure_date,
                              "departure_time": departure_time, "travelers": travelers,
                              "purpose": purpose, "vehicle": vehicle, "return_date": return_date},
            }, ensure_ascii=False)

        parsed_return_time = _parse_time(return_time) or "18:00"

        traveler_list = [t.strip() for t in travelers.split(",") if t.strip()]

        session = get_session()
        try:
            from modules.models.entities import User
            first_user = session.query(User).filter(User.full_name == traveler_list[0]).first()
            created_by_id = first_user.id if first_user else None

            member_data = []
            for name in traveler_list:
                u = session.query(User).filter(User.full_name == name).first()
                member_data.append({
                    "user_name": name,
                    "user_id": u.id if u else None,
                    "position": u.position if u else None,
                    "department": u.user_group if u else None,
                })
        finally:
            session.close()

        if not created_by_id:
            return json.dumps({"status": "error",
                "message": f"'{traveler_list[0]}' 사용자를 ERP에서 찾을 수 없습니다. 정확한 이름으로 다시 입력해주세요."
            }, ensure_ascii=False)

        depart_dt = f"{parsed_depart.isoformat()}T{parsed_depart_time}:00"
        return_dt = f"{parsed_return.isoformat()}T{parsed_return_time}:00"

        token = _store_session("confirm_business_trip", {
            "title": f"{destination} 출장 — {purpose}",
            "destination": destination,
            "purpose": purpose,
            "vehicle": matched_vehicle,
            "departure_date": depart_dt,
            "return_date": return_dt,
            "created_by": created_by_id,
            "members": member_data,
        })

        return json.dumps({
            "status": "preview",
            "action_type": "confirm_business_trip",
            "session_token": token,
            "summary": f"출장 등록 — {destination}",
            "fields": {
                "출장지": destination,
                "이동수단": matched_vehicle,
                "출발": f"{parsed_depart.isoformat()} {parsed_depart_time}",
                "귀환예정": f"{parsed_return.isoformat()} {parsed_return_time}",
                "출장자": ", ".join(traveler_list),
                "목적": purpose,
            },
        }, ensure_ascii=False)

    # ══════════════════════════════════════════════════════
    # 6. 일일보고 등록
    # ══════════════════════════════════════════════════════
    @mcp.tool()
    def write_preview_daily_report(
        department: Optional[str] = None,
        items=None,
        report_date: Optional[str] = None,
        reporter_name: Optional[str] = None,
    ) -> str:
        """일일보고 등록 preview.

        ★ 필수 필드:
          - department: 부서명 (영업부/생산부/관리부)
          - items: 업무 항목들. 두 형식 허용:
              · 문자열: "항목1, 항목2" (쉼표/줄바꿈 구분)
              · 리스트: ["항목1","항목2"] 또는 [{"category":"계약","content":"세종현장 납품확인"}, ...]
          - reporter_name: 보고자 이름

        선택 필드:
          - report_date: 보고 날짜 (생략 시 오늘)
        """
        from modules.models.entities import DailyReport, User

        today = datetime.date.today()
        DEPTS = ["영업부", "생산부", "관리부"]

        if not department:
            return json.dumps({"status": "needs_info", "intent": "write_preview_daily_report",
                "question": "어느 부서 일일보고입니까?",
                "hint": " / ".join(DEPTS),
                "collected": {},
            }, ensure_ascii=False)

        dept = _match_dept(department)
        if not dept:
            return json.dumps({"status": "needs_info", "intent": "write_preview_daily_report",
                "question": f"'{department}' 부서를 인식하지 못했습니다.",
                "hint": " / ".join(DEPTS),
                "collected": {},
            }, ensure_ascii=False)

        if not items:
            return json.dumps({"status": "needs_info", "intent": "write_preview_daily_report",
                "question": f"{dept} 오늘 업무 내용을 입력해주세요.",
                "hint": "여러 항목은 쉼표나 줄바꿈으로 구분. 예: 세종현장 납품확인, PO발주 3건 처리",
                "collected": {"department": department},
            }, ensure_ascii=False)

        if not reporter_name:
            return json.dumps({"status": "needs_info", "intent": "write_preview_daily_report",
                "question": "보고자 이름을 입력해주세요.",
                "hint": "예: 김정수, 이지훈",
                "collected": {"department": department, "items": items},
            }, ensure_ascii=False)

        parsed_date = _parse_date(report_date) if report_date else today
        target_date = parsed_date or today

        session = get_session()
        try:
            reporter = session.query(User).filter(User.full_name == reporter_name).first()
            if not reporter:
                return json.dumps({"status": "error",
                    "message": f"'{reporter_name}' 사용자를 찾을 수 없습니다."
                }, ensure_ascii=False)

            # 기존 보고 중복 체크
            existing = session.query(DailyReport).filter(
                DailyReport.report_date == target_date,
                DailyReport.department == dept,
            ).first()

            # items 는 str 또는 list (LLM 이 list of dict/str 형태로 넘기는 케이스 허용)
            if isinstance(items, list):
                item_list = []
                for it in items:
                    if isinstance(it, dict):
                        cat = (it.get('category') or '').strip()
                        cnt = (it.get('content') or it.get('text') or '').strip()
                        item_list.append(f"{cat}: {cnt}" if cat and cnt else (cnt or cat))
                    else:
                        s = str(it).strip()
                        if s:
                            item_list.append(s)
            else:
                item_list = [x.strip() for x in str(items).replace("\n", ",").split(",") if x.strip()]

            token = _store_session("confirm_daily_report", {
                "report_date": target_date.isoformat(),
                "department": dept,
                "reporter_name": reporter_name,
                "reporter_id": reporter.id,
                "items": item_list,
                "existing_id": existing.id if existing else None,
            })

            warning = f"\n⚠️ {target_date} {dept} 보고가 이미 있습니다. 덮어씁니다." if existing else ""

            return json.dumps({
                "status": "preview",
                "action_type": "confirm_daily_report",
                "session_token": token,
                "summary": f"일일보고 등록 — {dept} ({target_date}){warning}",
                "fields": {
                    "부서": dept,
                    "날짜": target_date.isoformat(),
                    "보고자": reporter_name,
                    "업무항목": item_list,
                },
            }, ensure_ascii=False)
        finally:
            session.close()

    # ══════════════════════════════════════════════════════
    # 7. 발주 상태 변경
    # ══════════════════════════════════════════════════════
    @mcp.tool()
    def write_preview_po_status(
        po_search: Optional[str] = None,
        new_status: Optional[str] = None,
    ) -> str:
        """발주서 상태 변경 preview.

        ★ 필수 필드:
          - po_search: 발주번호 (PO2026-001) 또는 거래처명/품목명
          - new_status: 변경할 상태 (발송완료/입고대기/입고완료/취소)
        """
        from modules.models.entities import PurchaseOrder, Vendor

        if not po_search:
            return json.dumps({"status": "needs_info", "intent": "write_preview_po_status",
                "question": "발주번호 또는 거래처명을 입력해주세요.",
                "hint": "예: PO2026-001, 삼성전자, LED모듈",
                "collected": {},
            }, ensure_ascii=False)

        if not new_status:
            return json.dumps({"status": "needs_info", "intent": "write_preview_po_status",
                "question": f"'{po_search}' 발주를 어떤 상태로 변경할까요?",
                "hint": "발송완료 / 입고대기 / 입고완료 / 취소",
                "collected": {"po_search": po_search},
            }, ensure_ascii=False)

        matched_status = _match_po_status(new_status)
        if not matched_status:
            return json.dumps({"status": "needs_info", "intent": "write_preview_po_status",
                "question": f"'{new_status}' 상태를 인식하지 못했습니다.",
                "hint": "발송완료 / 입고대기 / 입고완료 / 취소",
                "collected": {"po_search": po_search},
            }, ensure_ascii=False)

        session = get_session()
        try:
            pos = (
                session.query(PurchaseOrder)
                .filter(
                    PurchaseOrder.po_no.ilike(f"%{po_search}%")
                    | PurchaseOrder.note.ilike(f"%{po_search}%")
                )
                .filter(~PurchaseOrder.status.in_(["입고완료", "취소"]))
                .order_by(PurchaseOrder.po_date.desc())
                .limit(5).all()
            )

            if not pos:
                # 거래처명으로 재시도
                pos = (
                    session.query(PurchaseOrder)
                    .join(Vendor, PurchaseOrder.vendor_id == Vendor.id)
                    .filter(Vendor.name.ilike(f"%{po_search}%"))
                    .filter(~PurchaseOrder.status.in_(["입고완료", "취소"]))
                    .order_by(PurchaseOrder.po_date.desc())
                    .limit(5).all()
                )

            if not pos:
                return json.dumps({"status": "error",
                    "message": f"'{po_search}' 발주서를 찾을 수 없습니다. (이미 완료됐거나 번호 오류)"
                }, ensure_ascii=False)

            if len(pos) > 1:
                names = ", ".join(f"{p.po_no}(상태:{p.status})" for p in pos[:5])
                return json.dumps({"status": "needs_info", "intent": "write_preview_po_status",
                    "question": f"여러 발주서가 검색됩니다. 발주번호를 정확히 입력해주세요.\n결과: {names}",
                    "hint": "발주번호 전체 입력",
                    "collected": {"new_status": new_status},
                }, ensure_ascii=False)

            po = pos[0]
            vendor = session.query(Vendor).get(po.vendor_id)

            token = _store_session("confirm_po_status", {
                "po_id": po.id,
                "po_no": po.po_no,
                "new_status": matched_status,
            })

            return json.dumps({
                "status": "preview",
                "action_type": "confirm_po_status",
                "session_token": token,
                "summary": f"발주 상태 변경 — {po.po_no}",
                "fields": {
                    "발주번호": po.po_no,
                    "거래처": _s(vendor.name) if vendor else "-",
                    "현재 상태": _s(po.status),
                    "변경 후": matched_status,
                    "발주일": _s(po.po_date),
                },
                "erp_url": _erp_url(f"/purchase_orders/{po.id}"),
            }, ensure_ascii=False)
        finally:
            session.close()

    # ── 8. 생산완료 처리 ───────────────────────────────────────
    @mcp.tool()
    def write_preview_production_complete(
        keyword: Optional[str] = None,
        process_id: Optional[int] = None,
        completed_date: Optional[str] = None,
    ) -> str:
        """생산공정 완료 처리 preview.

        Args:
            keyword: 현장명/모델명/공정명 검색어 (process_id 없을 때 사용)
            process_id: 생산공정 ID (직접 지정)
            completed_date: 완료일 (오늘/내일/YYYY-MM-DD, 기본=오늘)
        """
        from modules.models.production_entities import ProductionProcess
        from modules.models.entities import ContractItem, Contract, Project
        session = get_session()
        try:
            # 검색
            if not keyword and not process_id:
                return json.dumps({"status": "needs_info", "intent": "write_preview_production_complete",
                    "question": "어느 공정을 완료 처리할까요? 현장명·모델명·공정명으로 검색해주세요.",
                    "hint": "예: '세종현장 조립공정' 또는 '공정 ID 123'",
                }, ensure_ascii=False)

            target_date = _parse_date(completed_date) if completed_date else str(datetime.date.today())

            if process_id:
                proc = session.query(ProductionProcess).get(process_id)
                if not proc:
                    return json.dumps({"status": "error",
                        "message": f"생산공정 ID {process_id}를 찾을 수 없습니다."
                    }, ensure_ascii=False)
                candidates = [proc]
            else:
                # keyword로 검색: 공정명 or 현장명 (join)
                candidates = (
                    session.query(ProductionProcess)
                    .join(ContractItem, ProductionProcess.contract_item_id == ContractItem.id)
                    .join(Contract, ProductionProcess.contract_id == Contract.id)
                    .join(Project, ProductionProcess.project_id == Project.id)
                    .filter(
                        ProductionProcess.status.notin_(['완료', '스킵']),
                        (ProductionProcess.process_name.ilike(f'%{keyword}%')) |
                        (Project.temp_name.ilike(f'%{keyword}%')) |
                        (ContractItem.model_name.ilike(f'%{keyword}%'))
                    )
                    .order_by(ProductionProcess.step_order)
                    .limit(10)
                    .all()
                )

            if not candidates:
                return json.dumps({"status": "error",
                    "message": f"'{keyword}'에 해당하는 진행 중인 생산공정이 없습니다. (이미 완료됐거나 검색어 수정 필요)"
                }, ensure_ascii=False)

            if len(candidates) > 1:
                lines = []
                for c in candidates[:8]:
                    item = session.query(ContractItem).get(c.contract_item_id)
                    proj = session.query(Project).get(c.project_id)
                    lines.append(f"ID {c.id}: [{_s(proj.temp_name if proj else '-')}] {c.process_name} — 상태:{c.status}")
                return json.dumps({"status": "needs_info", "intent": "write_preview_production_complete",
                    "question": f"여러 공정이 검색됩니다. 공정 ID를 지정해주세요.\n" + "\n".join(lines),
                    "hint": "공정 ID 번호로 다시 요청해주세요",
                    "collected": {"keyword": keyword, "completed_date": target_date},
                }, ensure_ascii=False)

            proc = candidates[0]
            item = session.query(ContractItem).get(proc.contract_item_id)
            proj = session.query(Project).get(proc.project_id)
            contract = session.query(Contract).get(proc.contract_id)

            token = _store_session("confirm_production_complete", {
                "process_id": proc.id,
                "completed_date": target_date,
            })

            return json.dumps({
                "status": "preview",
                "action_type": "confirm_production_complete",
                "session_token": token,
                "summary": f"생산완료 — {proc.process_name}",
                "fields": {
                    "현장": _s(proj.temp_name) if proj else "-",
                    "모델": _s(item.model_name) if item else "-",
                    "공정": proc.process_name,
                    "현재상태": proc.status,
                    "완료처리일": target_date,
                    "공정ID": proc.id,
                },
                "erp_url": _erp_url(f"/production/{proc.project_id}"),
            }, ensure_ascii=False)
        finally:
            session.close()

    # ── 8-2. 생산완료 일괄 처리 (품목 전체 공정 + 수량 검증) ────────
    @mcp.tool()
    def write_preview_production_complete_all(
        keyword: Optional[str] = None,
        contract_item_id: Optional[int] = None,
        quantity: Optional[int] = None,
        completed_date: Optional[str] = None,
    ) -> str:
        """생산완료 일괄 처리 preview — 한 품목(ContractItem)의 전체 공정을
        step_order 순서로 모두 완료 처리합니다. 마지막 공정만 닫는 single-step
        도구와 달리 1단계부터 마지막 단계까지 한 번에 처리하며 수량 일치 검증을
        수행합니다.

        사용 시점: 사용자가 "전체완료", "다 끝났어", "1~7단계 다 완료", "통째로
        완료" 등 품목 전체의 생산 완료를 한 번에 등록하려 할 때.

        Args:
            keyword: 현장명/모델명 검색어 (contract_item_id 없을 때 사용)
            contract_item_id: ContractItem ID 직접 지정 (검색 생략)
            quantity: 완료 수량 — 미지정 시 ContractItem.quantity 와 일치 가정.
                      지정 시 일치하지 않으면 needs_info 로 재확인.
            completed_date: 완료일 (오늘/내일/YYYY-MM-DD, 기본=오늘)
        """
        from modules.models.production_entities import ProductionProcess
        from modules.models.entities import ContractItem, Contract, Project
        session = get_session()
        try:
            if not keyword and not contract_item_id:
                return json.dumps({"status": "needs_info",
                    "intent": "write_preview_production_complete_all",
                    "question": "어느 품목을 전체 완료 처리할까요? 현장명·모델명으로 검색해주세요.",
                    "hint": "예: '탄금축구장 조명' 또는 '5626 탄금'",
                }, ensure_ascii=False)

            target_date = _parse_date(completed_date) if completed_date else str(datetime.date.today())

            # ── 품목 후보 식별 ────────────────────────────────────────
            if contract_item_id:
                item = session.query(ContractItem).get(contract_item_id)
                if not item:
                    return json.dumps({"status": "error",
                        "message": f"ContractItem ID {contract_item_id} 없음"
                    }, ensure_ascii=False)
                items = [item]
            else:
                # keyword 매칭: 모델명 / 프로젝트(temp_name) 이 일치하는 품목 중
                # 생산공정이 등록돼 있고 아직 '생산완료' 가 아닌 것만.
                items = (
                    session.query(ContractItem)
                    .join(Contract, ContractItem.contract_id == Contract.id)
                    .join(Project, Contract.project_id == Project.id)
                    .filter(
                        (Project.temp_name.ilike(f'%{keyword}%')) |
                        (ContractItem.model_name.ilike(f'%{keyword}%'))
                    )
                    .filter(
                        (ContractItem.status_prod.is_(None)) |
                        (ContractItem.status_prod != '생산완료')
                    )
                    .order_by(ContractItem.id)
                    .limit(10)
                    .all()
                )
                # 공정 등록이 된 품목만
                items = [it for it in items if session.query(ProductionProcess)
                         .filter(ProductionProcess.contract_item_id == it.id).count() > 0]

            if not items:
                return json.dumps({"status": "error",
                    "message": f"'{keyword}' 매칭 + 공정 등록 + 미완료 품목 없음"
                }, ensure_ascii=False)

            if len(items) > 1:
                lines = []
                for it in items[:8]:
                    proj = (session.query(Project)
                            .join(Contract, Contract.project_id == Project.id)
                            .filter(Contract.id == it.contract_id).first())
                    lines.append(f"item_id {it.id}: [{_s(proj.temp_name if proj else '-')}] "
                                 f"{_s(it.model_name)} × {it.quantity}ea (status_prod={_s(it.status_prod)})")
                return json.dumps({"status": "needs_info",
                    "intent": "write_preview_production_complete_all",
                    "question": "여러 품목이 검색됩니다. contract_item_id 로 다시 호출해주세요.\n" + "\n".join(lines),
                    "hint": "contract_item_id 파라미터에 위의 item_id 번호 지정",
                    "collected": {"keyword": keyword, "completed_date": target_date,
                                  "quantity": quantity},
                }, ensure_ascii=False)

            item = items[0]
            proj = (session.query(Project)
                    .join(Contract, Contract.project_id == Project.id)
                    .filter(Contract.id == item.contract_id).first())
            planned_qty = int(item.quantity or 0)

            # ── 수량 검증 ────────────────────────────────────────────
            if quantity is None:
                # 수량 미지정 — 자동 검증 통과 의도지만 사용자에게 명시 확인 권고
                final_qty = planned_qty
            else:
                if int(quantity) != planned_qty:
                    return json.dumps({"status": "needs_info",
                        "intent": "write_preview_production_complete_all",
                        "question": (f"수량 불일치: 입력 {quantity}개 vs 계약수량 {planned_qty}개. "
                                     f"계약수량 {planned_qty}개로 일괄 완료할까요? "
                                     f"(다른 수량이면 PC에서 부분완료 입력 필요)"),
                        "hint": f"quantity={planned_qty} 로 다시 호출하거나 PC 접속",
                        "collected": {"contract_item_id": item.id,
                                      "completed_date": target_date,
                                      "planned_quantity": planned_qty},
                    }, ensure_ascii=False)
                final_qty = int(quantity)

            # ── 공정 목록 조회 (step_order 순) ────────────────────────
            procs = (session.query(ProductionProcess)
                     .filter(ProductionProcess.contract_item_id == item.id)
                     .order_by(ProductionProcess.step_order, ProductionProcess.id)
                     .all())
            if not procs:
                return json.dumps({"status": "error",
                    "message": f"품목 {item.id} 에 등록된 생산공정 없음"
                }, ensure_ascii=False)

            already_done = [p for p in procs if p.status in ('완료', '스킵')]
            todo = [p for p in procs if p.status not in ('완료', '스킵')]
            steps_preview = [
                f"{p.step_order}. {p.process_name} (현재:{p.status})"
                for p in procs
            ]

            token = _store_session("confirm_production_complete_all", {
                "contract_item_id": item.id,
                "process_ids": [p.id for p in procs],
                "quantity": final_qty,
                "completed_date": target_date,
            })

            return json.dumps({
                "status": "preview",
                "action_type": "confirm_production_complete_all",
                "session_token": token,
                "summary": f"전체 생산완료 — {_s(item.model_name)} × {final_qty}ea",
                "fields": {
                    "현장": _s(proj.temp_name) if proj else "-",
                    "모델": _s(item.model_name),
                    "계약수량": f"{planned_qty}ea",
                    "완료수량": f"{final_qty}ea",
                    "공정수": f"{len(procs)}개 (이미완료 {len(already_done)} / 처리대상 {len(todo)})",
                    "공정목록": " · ".join(steps_preview),
                    "완료처리일": target_date,
                    "ContractItemID": item.id,
                },
                "erp_url": _erp_url(f"/production/team2?site={item.contract.project_id}") if item.contract else "",
            }, ensure_ascii=False)
        finally:
            session.close()

    # ── 9. 이메일 발송 (Phase 2 WRITE) ────────────────────────────
    @mcp.tool()
    def write_preview_email_send(
        requester_username: str,
        to: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        account_id: Optional[int] = None,
        request_read_receipt: bool = True,
        large_file_ids=None,
        mm_file_ids=None,
    ) -> str:
        """이메일 발송 preview — SMTP 송신은 사용자 확인 버튼 후 실행됨.

        ⚠️ 권한 격리 (필독):
        - requester_username 필수. 식별 실패 시 error.
        - account_id 명시 안 하면 사용자 개인 계정 자동 선택.
        - 공유 계정 사용 시 mail_shared_access.can_send 권한 검증.
        - 다른 사람 계정으로 발송 절대 금지.
        - large_file_ids: 발신자 본인이 업로드한 파일만 첨부 가능 (admin 예외).
        - mm_file_ids: 챗봇 호출 컨텍스트 `[MM_첨부_파일_ID: ...]` 에 들어있는
          ID 만 전달하라. 임의의 ID 추측 금지.

        Args:
            requester_username: 챗봇 채널 발신자 username (필수)
            to: 받는 사람 (콤마 구분 다수 가능)
            subject: 제목
            body: 본문 (HTML 또는 plain text — plain 이면 자동 <br> 변환)
            cc / bcc: 참조/숨은참조 (선택)
            account_id: 발송할 메일 계정 ID (생략 시 개인 계정)
            request_read_receipt: 수신확인 트래킹 픽셀 삽입 (기본 True)
            large_file_ids: ERP 메일 화면에서 업로드한 파일의 file_id 배열
                            (mail_large_files). SMTP MIME 직접 첨부로 발송됨.
                            예: ["abc123def456", "xyz789..."] 또는 ["abc123,xyz789"]
            mm_file_ids: Mattermost 채팅창에 첨부된 파일의 MM file_id 배열.
                         확정 발송 시 봇이 MM API 로 바이트를 가져와 SMTP MIME
                         첨부로 붙입니다 (ERP 일반 메일과 동일 경로).
                         예: ["mmf_aaaa", "mmf_bbbb"]
        """
        from modules.models.entities import User
        from modules.models.mail_entities import MailAccount, MailSharedAccess, MailLargeFile
        import datetime as _dt
        session = get_session()
        try:
            # ── 사용자 식별 ──────────────────────────────────────
            if not requester_username:
                return json.dumps({"status": "error",
                    "message": "requester_username 이 필요합니다."
                }, ensure_ascii=False)
            user = session.query(User).filter(User.username == requester_username).first()
            if not user:
                user = session.query(User).filter(
                    User.email.ilike(f"{requester_username}@%")).first()
            if not user:
                return json.dumps({"status": "error",
                    "message": f"사용자 '{requester_username}' 식별 실패. 메일 발송 불가."
                }, ensure_ascii=False)

            # ── 발송 계정 결정 + 권한 검증 ──────────────────────
            account = None
            account_err = None
            if account_id:
                acc = session.get(MailAccount, account_id)
                if not acc or not acc.is_active:
                    account_err = f"mail_account_id={account_id} 없거나 비활성."
                elif acc.is_shared:
                    # 공유 계정 - shared_access 필수 + can_send 권한
                    access = session.query(MailSharedAccess).filter_by(
                        mail_account_id=acc.id, user_id=user.id).first()
                    if not access and (user.role or '').lower() != 'admin':
                        account_err = f"공유 계정 #{acc.id} 접근 권한 없음."
                    elif access and not access.can_send and (user.role or '').lower() != 'admin':
                        account_err = f"공유 계정 #{acc.id} 발송 권한(can_send) 없음."
                    else:
                        account = acc
                else:
                    # 개인 계정 - 본인 소유만
                    if acc.user_id != user.id:
                        account_err = f"다른 사용자의 개인 계정 #{acc.id} 발송 금지."
                    else:
                        account = acc
            else:
                # 기본: 본인 개인 계정 첫 번째
                account = session.query(MailAccount).filter_by(
                    user_id=user.id, is_shared=False, is_active=True).first()
                if not account:
                    account_err = f"사용자 '{user.username}' 의 개인 메일 계정 미설정."

            if account_err:
                return json.dumps({"status": "error",
                    "message": account_err}, ensure_ascii=False)

            # ── 필드 단계별 needs_info 흐름 ─────────────────────
            collected = {
                "from_account_id": account.id,
                "from_email": account.email,
                "from_display": account.display_name,
            }

            if not to or not to.strip():
                return json.dumps({"status": "needs_info",
                    "intent": "write_preview_email_send",
                    "question": "받는 사람 이메일을 입력해주세요.",
                    "hint": "예: 'partner@company.com' 또는 여러 명은 콤마로 구분 'a@x.com, b@y.com'",
                    "collected": collected,
                }, ensure_ascii=False)

            to_list = [a.strip() for a in str(to).split(',') if a.strip()]
            if not to_list:
                return json.dumps({"status": "needs_info",
                    "intent": "write_preview_email_send",
                    "question": "받는 사람 이메일 형식이 올바르지 않습니다.",
                    "hint": "예: 'partner@company.com'",
                    "collected": collected,
                }, ensure_ascii=False)
            # 이메일 형식 간단 검증
            invalid = [a for a in to_list if '@' not in a]
            if invalid:
                return json.dumps({"status": "needs_info",
                    "intent": "write_preview_email_send",
                    "question": f"이메일 주소 형식 오류: {invalid}",
                    "hint": "각 주소에 '@' 가 포함되어야 합니다.",
                    "collected": collected,
                }, ensure_ascii=False)
            collected["to"] = to

            cc_list = [a.strip() for a in str(cc or '').split(',') if a.strip()]
            bcc_list = [a.strip() for a in str(bcc or '').split(',') if a.strip()]

            if not subject or not subject.strip():
                return json.dumps({"status": "needs_info",
                    "intent": "write_preview_email_send",
                    "question": "메일 제목을 입력해주세요.",
                    "hint": "예: '[매그나텍] 가공발주 송부의건 26-0515'",
                    "collected": collected,
                }, ensure_ascii=False)

            if not body or not body.strip():
                return json.dumps({"status": "needs_info",
                    "intent": "write_preview_email_send",
                    "question": "메일 본문을 입력해주세요.",
                    "hint": "HTML 또는 일반 텍스트. 일반 텍스트는 자동으로 줄바꿈 처리됩니다.",
                    "collected": collected,
                }, ensure_ascii=False)

            # plain → HTML 자동 변환 (간단)
            body_str = str(body)
            is_html = '<' in body_str and '>' in body_str
            html_body = body_str if is_html else body_str.replace('\n', '<br>')

            # ── 첨부파일(대용량 file_id) 검증 ────────────────────
            file_ids_normalized = []
            attachment_summary = []
            if large_file_ids:
                # 입력 형태 정규화: list / 문자열(콤마구분) 모두 허용
                if isinstance(large_file_ids, str):
                    raw_ids = [x.strip() for x in large_file_ids.split(',') if x.strip()]
                elif isinstance(large_file_ids, (list, tuple)):
                    raw_ids = []
                    for x in large_file_ids:
                        if isinstance(x, str):
                            raw_ids.extend([y.strip() for y in x.split(',') if y.strip()])
                        else:
                            raw_ids.append(str(x).strip())
                else:
                    raw_ids = [str(large_file_ids).strip()]

                from datetime import timezone as _tz
                now = _dt.datetime.now(_tz.utc)
                is_admin = (user.role or '').lower() == 'admin'
                for fid in raw_ids:
                    rec = session.query(MailLargeFile).filter_by(file_id=fid).first()
                    if not rec or rec.is_deleted:
                        return json.dumps({"status": "error",
                            "message": f"file_id='{fid}' 파일 없음 또는 이미 삭제됨."
                        }, ensure_ascii=False)
                    # tz-aware/naive 호환 — expires_at 이 naive 면 UTC 로 간주
                    exp = rec.expires_at
                    if exp and exp.tzinfo is None:
                        exp = exp.replace(tzinfo=_tz.utc)
                    if exp and exp < now:
                        return json.dumps({"status": "error",
                            "message": f"file_id='{fid}' 만료됨 (expires_at={rec.expires_at.date()}). ERP에서 재업로드 필요."
                        }, ensure_ascii=False)
                    # 권한: 발신자가 본인 업로드 또는 admin
                    if rec.sender_user_id != user.id and not is_admin:
                        return json.dumps({"status": "error",
                            "message": f"file_id='{fid}' 는 다른 사용자가 업로드한 파일입니다. 본인 업로드 파일만 첨부 가능."
                        }, ensure_ascii=False)
                    file_ids_normalized.append(fid)
                    size_mb = (rec.file_size or 0) / (1024 * 1024)
                    attachment_summary.append({
                        "source": "erp",
                        "file_id": fid,
                        "filename": rec.original_filename,
                        "size_mb": round(size_mb, 2),
                        "expires_at": str(rec.expires_at.date()) if rec.expires_at else None,
                    })

            # ── MM 첨부 파일 검증 (Mattermost API 로 메타 조회) ──
            mm_file_ids_normalized = []
            if mm_file_ids:
                import os as _os
                import requests as _rq
                # 입력 정규화 (list / 콤마 문자열)
                if isinstance(mm_file_ids, str):
                    mm_raw = [x.strip() for x in mm_file_ids.split(',') if x.strip()]
                elif isinstance(mm_file_ids, (list, tuple)):
                    mm_raw = []
                    for x in mm_file_ids:
                        if isinstance(x, str):
                            mm_raw.extend([y.strip() for y in x.split(',') if y.strip()])
                        else:
                            mm_raw.append(str(x).strip())
                else:
                    mm_raw = [str(mm_file_ids).strip()]

                mm_base = _os.environ.get('MM_BASE_URL', 'https://team.mgnt.kr').rstrip('/')
                mm_tok = _os.environ.get('MM_BOT_TOKEN', '')
                if not mm_tok:
                    return json.dumps({"status": "error",
                        "message": "MM 첨부 발송 불가 — MM_BOT_TOKEN 환경변수 미설정."
                    }, ensure_ascii=False)

                for fid in mm_raw:
                    try:
                        r = _rq.get(
                            f"{mm_base}/api/v4/files/{fid}/info",
                            headers={"Authorization": f"Bearer {mm_tok}"},
                            timeout=10,
                        )
                    except Exception as e:
                        return json.dumps({"status": "error",
                            "message": f"MM 파일 메타 조회 실패 file_id='{fid}': {e!s:.100}"
                        }, ensure_ascii=False)
                    if r.status_code != 200:
                        return json.dumps({"status": "error",
                            "message": (f"MM 파일 메타 조회 실패 file_id='{fid}' "
                                        f"(HTTP {r.status_code}). 봇이 해당 채널/파일 접근 권한 없을 수 있음.")
                        }, ensure_ascii=False)
                    info = r.json()
                    fname = info.get('name') or f'mm-{fid}'
                    fsize = int(info.get('size') or 0)
                    fmime = info.get('mime_type') or 'application/octet-stream'
                    mm_file_ids_normalized.append(fid)
                    attachment_summary.append({
                        "source": "mm",
                        "file_id": fid,
                        "filename": fname,
                        "size_mb": round(fsize / (1024 * 1024), 2),
                        "mime": fmime,
                    })

            # ── preview 응답 ──────────────────────────────────
            token = _store_session("confirm_email_send", {
                "sender_user_id": user.id,
                "account_id": account.id,
                "to": to_list,
                "cc": cc_list,
                "bcc": bcc_list,
                "subject": subject.strip(),
                "html_body": html_body,
                "request_read_receipt": bool(request_read_receipt),
                "large_file_ids": file_ids_normalized,
                "mm_file_ids": mm_file_ids_normalized,
            })

            fields = {
                "발신": f"{account.display_name or ''} <{account.email}>",
                "받는사람": ', '.join(to_list),
                "참조": ', '.join(cc_list) if cc_list else "(없음)",
                "숨은참조": ', '.join(bcc_list) if bcc_list else "(없음)",
                "제목": subject.strip(),
                "본문_길이": f"{len(body_str)}자 ({'HTML' if is_html else 'plain→HTML 자동변환'})",
                "본문_미리보기": body_str[:200] + ('...' if len(body_str) > 200 else ''),
                "수신확인_트래킹": "사용" if request_read_receipt else "미사용",
            }
            if attachment_summary:
                def _fmt(a):
                    if a.get("source") == "mm":
                        return f"{a['filename']} ({a['size_mb']}MB, MM)"
                    return f"{a['filename']} ({a['size_mb']}MB, 만료 {a['expires_at']})"
                fields["첨부파일"] = " / ".join(_fmt(a) for a in attachment_summary)

            return json.dumps({
                "status": "preview",
                "action_type": "confirm_email_send",
                "session_token": token,
                "summary": f"메일 발송 — {subject[:40]}",
                "fields": fields,
                "attachments": attachment_summary,
                "notice": "확인 버튼을 누르면 즉시 SMTP 발송됩니다. 발송 후 취소 불가." +
                          (" 첨부 파일은 SMTP MIME 첨부로 직접 발송됩니다 (ERP 일반 메일과 동일)." if attachment_summary else ""),
            }, ensure_ascii=False)
        finally:
            session.close()

    # ══════════════════════════════════════════════════════
    # 11. 휴가 상신 (전자결재)
    # ══════════════════════════════════════════════════════
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

        ★ 필수 필드:
          - requester_username: 채널 태그의 user="..." 값 (기안자 = 본인만 가능)
          - start_date: 시작일 (YYYY-MM-DD / M/D / 오늘 / 내일)
          - leave_type: 연차(기본) / 병가 / 경조사 / 공가 / 기타
          - period: 종일(기본) / 오전반차 / 오후반차
          - end_date: 종료일 (생략 시 시작일과 동일)
          - reason: 사유
        """
        from modules.services import approval_service as svc

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
            else:
                from modules.services import holiday_service
                days = float(holiday_service.working_days(parsed_start, parsed_end))
            if days <= 0:
                return json.dumps({"status": "error",
                    "message": f"{parsed_start} ~ {parsed_end} 구간에 근무일이 없습니다 "
                               "(주말/공휴일). 날짜를 확인해주세요."}, ensure_ascii=False)

            # 결재선 미리 확인 (상신 시점에 다시 구성)
            line = svc.resolve_default_line(session, drafter)
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
                    "start_time": "",
                    "end_time": "",
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
        if balance_note:
            fields["연차잔여"] = balance_note

        return json.dumps({
            "status": "preview",
            "action_type": "confirm_leave_request",
            "session_token": token,
            "summary": f"휴가 상신 — {ltype} {days}일",
            "fields": fields,
            "notice": "확인 버튼을 누르면 전자결재로 상신됩니다. "
                      "승인 완료(또는 부서장 선효력) 시 연차가 자동 차감됩니다.",
        }, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────
# 내부 유틸
# ──────────────────────────────────────────────────────────────

def _parse_time(text: str) -> Optional[str]:
    """시각 파싱 → 'HH:MM' 문자열. 오전/오후, 숫자 단독, HH:MM 지원."""
    if not text:
        return None
    t = text.strip()
    # 오전/오후 처리
    pm = "오후" in t or "pm" in t.lower()
    am = "오전" in t or "am" in t.lower()
    t = t.replace("오전", "").replace("오후", "").replace("am", "").replace("pm", "").replace("시", ":").replace("분", "").strip()
    # HH:MM 형식
    if ":" in t:
        parts = t.split(":")
        try:
            h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            if pm and h < 12:
                h += 12
            if am and h == 12:
                h = 0
            return f"{h:02d}:{m:02d}"
        except ValueError:
            pass
    # 숫자만
    try:
        h = int(t)
        if pm and h < 12:
            h += 12
        if am and h == 12:
            h = 0
        return f"{h:02d}:00"
    except ValueError:
        pass
    return None


def _parse_date(text: str) -> Optional[datetime.date]:
    """자연어 날짜 파싱. '오늘', '내일', '어제', YYYY-MM-DD, M/D 지원."""
    if not text:
        return None
    t = text.strip().lower()
    today = datetime.date.today()
    if t in ("오늘", "today"):
        return today
    if t in ("내일", "tomorrow"):
        return today + datetime.timedelta(days=1)
    if t in ("모레",):
        return today + datetime.timedelta(days=2)
    if t in ("어제", "yesterday"):
        return today - datetime.timedelta(days=1)
    if t in ("글피",):
        return today + datetime.timedelta(days=3)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d", "%m-%d"):
        try:
            d = datetime.datetime.strptime(t, fmt)
            if fmt in ("%m/%d", "%m-%d"):
                d = d.replace(year=today.year)
            return d.date()
        except ValueError:
            continue
    return None


def _map_defect(label: str) -> Optional[str]:
    label = label.strip()
    if label in DEFECT_LABEL_MAP:
        return DEFECT_LABEL_MAP[label]
    for k, v in DEFECT_LABEL_MAP.items():
        if k.lower() in label.lower() or label.lower() in k.lower():
            return v
    # 직접 코드 입력 허용
    codes = set(DEFECT_LABEL_MAP.values())
    if label.upper() in codes:
        return label.upper()
    return None


def _match_vehicle(text: str) -> Optional[str]:
    text = text.strip()
    for v in VEHICLE_CHOICES:
        if text in v or v in text:
            return v
    tl = text.lower()
    for v in VEHICLE_CHOICES:
        if tl in v.lower():
            return v
    return None


def _match_dept(text: str) -> Optional[str]:
    text = text.strip()
    for dept in ["영업부", "생산부", "관리부"]:
        if dept in text or text in dept:
            return dept
    mapping = {"영업": "영업부", "생산": "생산부", "관리": "관리부", "총무": "관리부"}
    for k, v in mapping.items():
        if k in text:
            return v
    return None


def _match_po_status(text: str) -> Optional[str]:
    text = text.strip()
    for s in PO_STATUS_FLOW:
        if text == s or text in s:
            return s
    mapping = {"발송": "발송완료", "입고대기": "입고대기", "입고": "입고완료", "완료": "입고완료", "취소": "취소"}
    for k, v in mapping.items():
        if k in text:
            return v
    return None
