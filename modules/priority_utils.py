from modules.models import GLOBAL_PRIORITY_SETTINGS, PRIORITY_BADGE_STYLES


PRIORITY_REASON_RANK = {
    "manual_top": -10,
    "urgent": 0,
    "overdue": 1,
    "production_warning": 1,
    "delivery_unassigned": 2,
    "delivery_today": 3,
    "inspection": 4,
    "due_soon": 5,
    "sales_pending": 6,
    "material_pending": 7,
}

PRIORITY_TONE_RANK = {
    "manual": 0,
    "danger": 1,
    "warning": 2,
    "info": 3,
    "muted": 4,
}

PRIORITY_TONE_BY_REASON = {
    "manual_top": "manual",
    "urgent": "danger",
    "overdue": "danger",
    "production_warning": "danger",
    "due_soon": "warning",
    "delivery_today": "warning",
    "inspection": "info",
    "sales_pending": "muted",
    "material_pending": "muted",
    "delivery_unassigned": "muted",
}


def get_priority_due_warning_days(scope: str) -> int:
    shared = GLOBAL_PRIORITY_SETTINGS.get("shared", {})
    scoped = GLOBAL_PRIORITY_SETTINGS.get(scope, {})
    return int(scoped.get("due_warning_days", shared.get("due_warning_days", 7)))


def make_priority_reason(code: str, detail: str | None = None, label: str | None = None) -> dict:
    spec = PRIORITY_BADGE_STYLES.get(code, {})
    return {
        "code": code,
        "label": label or spec.get("label") or code,
        "css_class": spec.get("css_class") or "bg-secondary",
        "detail": detail or "",
        "rank": PRIORITY_REASON_RANK.get(code, 99),
    }


def get_active_priority_override(project_obj):
    override = getattr(project_obj, "priority_override", None)
    if override and getattr(override, "is_active", False):
        return override
    return None


def append_priority_reason(reasons: list, code: str, detail: str | None = None, label: str | None = None) -> None:
    if any(reason.get("code") == code for reason in reasons):
        return
    reasons.append(make_priority_reason(code, detail=detail, label=label))


def append_manual_priority_reason(reasons: list, project_obj):
    override = get_active_priority_override(project_obj)
    if not override:
        return None

    detail = (getattr(override, "note", "") or "").strip()
    append_priority_reason(reasons, "manual_top", detail=detail or None)
    return override


def append_due_priority_reason(reasons: list, dday: int | None, scope: str) -> None:
    if dday is None:
        return
    if dday < 0:
        append_priority_reason(reasons, "overdue", f"D+{-dday}")
        return
    if dday <= get_priority_due_warning_days(scope):
        append_priority_reason(reasons, "due_soon", "D-Day" if dday == 0 else f"D-{dday}")


def derive_priority_tone(reasons: list) -> str:
    tone = "muted"
    best_rank = PRIORITY_TONE_RANK[tone]
    for reason in reasons or []:
        current = PRIORITY_TONE_BY_REASON.get(reason.get("code"), "muted")
        current_rank = PRIORITY_TONE_RANK.get(current, 99)
        if current_rank < best_rank:
            tone = current
            best_rank = current_rank
    return tone


def make_priority_entry(
    *,
    project_id: int,
    project_no: str,
    title: str,
    detail_url: str,
    reasons: list,
    subtitle: str = "",
    meta_lines: list | None = None,
    dday: int | None = None,
    override_note: str = "",
):
    tone = derive_priority_tone(reasons)
    return {
        "project_id": project_id,
        "project_no": project_no or "-",
        "title": title or "-",
        "detail_url": detail_url,
        "reasons": reasons,
        "subtitle": subtitle or "",
        "meta_lines": meta_lines or [],
        "dday": dday,
        "override_note": override_note or "",
        "tone": tone,
    }


def sort_priority_entries(entries: list) -> list:
    def _sort_key(entry: dict):
        reasons = entry.get("reasons") or []
        min_rank = min((reason.get("rank", 99) for reason in reasons), default=99)
        dday = entry.get("dday")
        dday_sort = 99999 if dday is None else dday
        return (min_rank, dday_sort, entry.get("project_no") or "", entry.get("title") or "")

    return sorted(entries, key=_sort_key)