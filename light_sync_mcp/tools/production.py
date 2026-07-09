"""FR-05: 생산 도메인 Tools (3개)

production_processes 실제 컬럼: process_code, process_name, step_order, status,
progress_qty, progress_percent, started_at, completed_at.
(stage / worker_name / item_name / quantity 컬럼은 존재하지 않는다 — 참조 금지)
"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s


def _process_row(pr):
    """공정 1건 → 공통 dict (실제 스키마 기준)."""
    return {
        "process_code": _s(pr.process_code),
        "process_name": _s(pr.process_name),
        "step_order": pr.step_order,
        "status": _s(pr.status),
        "progress_qty": int(pr.progress_qty or 0),
        "progress_percent": int(pr.progress_percent or 0),
        "started_at": pr.started_at.strftime('%Y-%m-%d') if pr.started_at else "",
        "completed_at": pr.completed_at.strftime('%Y-%m-%d') if pr.completed_at else "",
    }


def register(mcp: FastMCP):

    @mcp.tool()
    def get_production_status(
        project_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """생산 현황 조회. 현장별 공정 진행 상태를 반환합니다.
        status: 대기 / 진행중 / 완료
        """
        from modules.models.entities import ProductionProcess, Project
        session = get_session()
        try:
            q = session.query(ProductionProcess)
            if project_id:
                q = q.filter(ProductionProcess.project_id == project_id)
            if status:
                q = q.filter(ProductionProcess.status.ilike(f"%{status}%"))
            total = q.count()
            processes = q.order_by(ProductionProcess.id.desc()).limit(limit).all()

            result = []
            for pr in processes:
                proj = session.get(Project, pr.project_id) if pr.project_id else None
                result.append({
                    "id": pr.id,
                    "project_id": pr.project_id,
                    "project_name": _s(proj.temp_name) if proj else "",
                    **_process_row(pr),
                })
            return json.dumps({
                "total": total,
                "returned": len(result),
                "truncated": total > len(result),
                "items": result,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_production_by_site(search: Optional[str] = None, limit: int = 30) -> str:
        """현장별 생산 카드 목록. 현장별로 그룹핑된 생산 공정을 반환합니다.

        ⚠️ 전체 1,200개 현장이 넘습니다. 특정 현장은 search 로 좁히세요.

        Args:
            search: 현장명 검색
            limit: 최대 현장 수 (기본 30, 최근 현장순)
        """
        from modules.models.entities import ProductionProcess, Project
        session = get_session()
        try:
            # 대상 현장 먼저 확정 (공정이 있는 현장 중 최근순)
            pid_q = (session.query(ProductionProcess.project_id)
                     .filter(ProductionProcess.project_id.isnot(None))
                     .distinct())
            if search:
                pid_q = pid_q.join(Project, Project.id == ProductionProcess.project_id) \
                             .filter(Project.temp_name.ilike(f"%{search}%"))
            all_pids = [r[0] for r in pid_q.all()]
            total_sites = len(all_pids)
            pids = sorted(all_pids, reverse=True)[:limit]

            processes = (session.query(ProductionProcess)
                         .filter(ProductionProcess.project_id.in_(pids)).all()
                         if pids else [])

            by_project = {}
            for pr in processes:
                pid = pr.project_id or 0
                if pid not in by_project:
                    proj = session.get(Project, pid) if pid else None
                    by_project[pid] = {
                        "project_id": pid,
                        "project_name": _s(proj.temp_name) if proj else "미연결",
                        "processes": [],
                    }
                by_project[pid]["processes"].append({"id": pr.id, **_process_row(pr)})

            for card in by_project.values():
                card["processes"].sort(key=lambda p: (p["step_order"] or 0))
                done = sum(1 for p in card["processes"] if p["status"] == '완료')
                card["process_count"] = len(card["processes"])
                card["done_count"] = done
                card["progress_percent"] = round(done * 100 / len(card["processes"])) \
                    if card["processes"] else 0

            items = sorted(by_project.values(), key=lambda x: x["project_id"], reverse=True)
            return json.dumps({
                "total": total_sites,
                "returned": len(items),
                "truncated": total_sites > len(items),
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_work_logs(
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        worker: Optional[str] = None,
        project_search: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """일일 작업일지 — 누가 언제 어느 공정을 얼마나 작업했는지.
        ★ '누가 뭐 작업했어', '오늘 생산 실적', '작업일지' 질문에 사용.

        Args:
            date_from: 시작일 YYYY-MM-DD (생략 시 최근 30일)
            date_to: 종료일 YYYY-MM-DD
            worker: 작업자(기록자) 이름
            project_search: 현장명 검색
            limit: 최대 건수 (기본 50, 최신순)
        """
        import datetime
        from modules.models.entities import ProductionProcess, Project
        from modules.models.production_entities import ProductionDailyLog
        session = get_session()
        try:
            q = (session.query(ProductionDailyLog, ProductionProcess, Project)
                 .join(ProductionProcess,
                       ProductionProcess.id == ProductionDailyLog.production_process_id)
                 .outerjoin(Project, Project.id == ProductionProcess.project_id))

            if date_from:
                q = q.filter(ProductionDailyLog.work_date >= datetime.date.fromisoformat(date_from))
            elif not date_to:
                q = q.filter(ProductionDailyLog.work_date
                             >= datetime.date.today() - datetime.timedelta(days=30))
            if date_to:
                q = q.filter(ProductionDailyLog.work_date <= datetime.date.fromisoformat(date_to))
            if worker:
                q = q.filter(ProductionDailyLog.created_by.ilike(f"%{worker}%"))
            if project_search:
                q = q.filter(Project.temp_name.ilike(f"%{project_search}%"))

            total = q.count()
            rows = q.order_by(ProductionDailyLog.work_date.desc(),
                              ProductionDailyLog.id.desc()).limit(limit).all()

            items = []
            by_worker = {}
            for log, pr, proj in rows:
                name = _s(log.created_by) or "미기록"
                qty = int(log.daily_qty or 0)
                by_worker[name] = by_worker.get(name, 0) + qty
                items.append({
                    "work_date": log.work_date.isoformat() if log.work_date else "",
                    "worker": name,
                    "project_name": _s(proj.temp_name) if proj else "",
                    "process_name": _s(pr.process_name),
                    "process_code": _s(pr.process_code),
                    "daily_qty": qty,
                    "memo": _s(log.memo),
                })

            return json.dumps({
                "total": total,
                "returned": len(items),
                "truncated": total > len(items),
                "qty_by_worker": by_worker,
                "basis": "production_daily_logs (작업자 = 기록자 created_by). "
                         "생산공정 테이블에는 담당자 컬럼이 없습니다.",
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_process_summary(project_search: Optional[str] = None) -> str:
        """공정 단계별 진행 집계 — 어느 단계에서 얼마나 밀려 있는지.
        ★ '공정별 현황', '어느 단계가 막혔어', '생산 단계 요약' 질문에 사용.

        Args:
            project_search: 현장명 검색 (생략 시 전사)
        """
        from modules.models.entities import ProductionProcess, Project
        from sqlalchemy import func
        session = get_session()
        try:
            q = session.query(
                ProductionProcess.process_code,
                ProductionProcess.process_name,
                ProductionProcess.status,
                func.count(ProductionProcess.id),
            )
            if project_search:
                q = (q.join(Project, Project.id == ProductionProcess.project_id)
                      .filter(Project.temp_name.ilike(f"%{project_search}%")))
            rows = q.group_by(ProductionProcess.process_code,
                              ProductionProcess.process_name,
                              ProductionProcess.status).all()

            by_code = {}
            for code, pname, status, cnt in rows:
                key = _s(code)
                slot = by_code.setdefault(key, {
                    "process_code": key,
                    "process_names": set(),
                    "대기": 0, "진행중": 0, "완료": 0, "total": 0,
                })
                slot["process_names"].add(_s(pname))
                slot[_s(status)] = slot.get(_s(status), 0) + cnt
                slot["total"] += cnt

            items = []
            for slot in sorted(by_code.values(), key=lambda x: x["process_code"]):
                names = sorted(n for n in slot.pop("process_names") if n)
                slot["process_names"] = names[:5]
                slot["progress_percent"] = round(slot["완료"] * 100 / slot["total"]) \
                    if slot["total"] else 0
                items.append(slot)

            return json.dumps({
                "project_search": project_search,
                "process_count": len(items),
                "total_processes": sum(i["total"] for i in items),
                "basis": "production_processes 를 process_code 별로 상태 집계 (대기/진행중/완료)",
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()
