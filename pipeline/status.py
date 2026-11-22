"""오늘 기준 공고 상태(접수 중/마감 임박/마감 등)와 D-day 표기."""
from __future__ import annotations

from datetime import date

STATUS_LABELS = {
    "closing": "마감 임박",
    "open": "접수 중",
    "upcoming": "접수 예정",
    "always": "상시 접수",
    "unknown": "기간 확인",
    "closed": "마감",
}
# 목록 정렬 우선순위 (작을수록 위)
STATUS_ORDER = {"closing": 0, "open": 1, "unknown": 2, "always": 3, "upcoming": 4, "closed": 9}


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def notice_status(n: dict, today: date, closing_days: int) -> dict:
    start, end = _d(n.get("start_date")), _d(n.get("end_date"))

    def result(status: str, label: str, days_left: int | None) -> dict:
        return {"status": status, "status_label": STATUS_LABELS[status], "dday_label": label, "days_left": days_left}

    if start and start > today:
        return result("upcoming", f"{(start - today).days}일 후 시작", (end - today).days if end else None)
    if end:
        left = (end - today).days
        if left < 0:
            return result("closed", "마감", left)
        if left == 0:
            return result("closing", "오늘 마감", 0)
        return result("closing" if left <= closing_days else "open", f"D-{left}", left)
    if n.get("period_kind") == "always":
        return result("always", "상시", None)
    return result("unknown", "기간 확인", None)


def sort_key(n: dict) -> tuple:
    return (STATUS_ORDER[n["status"]], n.get("end_date") or "9999-12-31", n.get("start_date") or "", n["title"])
