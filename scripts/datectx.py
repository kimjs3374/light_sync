# -*- coding: utf-8 -*-
"""날짜 컨텍스트 생성기 - LLM에 주입할 날짜를 코드로 미리 계산"""
from datetime import date, timedelta
import calendar

WD = ["월", "화", "수", "목", "금", "토", "일"]

def month_range(y, m):
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])

def build(today: date) -> str:
    L = []
    A = L.append
    A(f"오늘: {today} ({WD[today.weekday()]})")

    # 주 (월요일 시작)
    mon = today - timedelta(days=today.weekday())
    A(f"이번주: {mon} ~ {mon + timedelta(days=6)}")
    A(f"지난주: {mon - timedelta(days=7)} ~ {mon - timedelta(days=1)}")
    A(f"다음주: {mon + timedelta(days=7)} ~ {mon + timedelta(days=13)}")

    # 다음주/지난주 각 요일
    nxt = ", ".join(f"{WD[i]}={mon + timedelta(days=7+i)}" for i in range(7))
    A(f"다음주 요일별: {nxt}")
    prv = ", ".join(f"{WD[i]}={mon - timedelta(days=7-i)}" for i in range(7))
    A(f"지난주 요일별: {prv}")

    # 월
    s, e = month_range(today.year, today.month)
    A(f"이번달: {s} ~ {e}")
    pm_y, pm_m = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    s, e = month_range(pm_y, pm_m)
    A(f"지난달: {s} ~ {e}")
    nm_y, nm_m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    s, e = month_range(nm_y, nm_m)
    A(f"다음달: {s} ~ {e}")

    # 분기
    q = (today.month - 1) // 3 + 1
    qs = date(today.year, 3 * q - 2, 1)
    qe = date(today.year, 3 * q, calendar.monthrange(today.year, 3 * q)[1])
    A(f"이번분기(={today.year}년 {q}분기): {qs} ~ {qe}")
    pq_y, pq = (today.year - 1, 4) if q == 1 else (today.year, q - 1)
    pqs = date(pq_y, 3 * pq - 2, 1)
    pqe = date(pq_y, 3 * pq, calendar.monthrange(pq_y, 3 * pq)[1])
    A(f"지난분기(={pq_y}년 {pq}분기): {pqs} ~ {pqe}")

    # year/month 정수 인자를 받는 도구용 (중요)
    A("")
    A("[year/month 정수 인자를 받는 도구는 아래 값을 쓸 것]")
    A(f"이번달 = year:{today.year}, month:{today.month}")
    A(f"지난달 = year:{pm_y}, month:{pm_m}")
    A(f"다음달 = year:{nm_y}, month:{nm_m}")
    A(f"올해 = year:{today.year} / 작년 = year:{today.year-1}")
    A("")

    # 연
    A(f"올해: {today.year}-01-01 ~ {today.year}-12-31")
    A(f"작년: {today.year-1}-01-01 ~ {today.year-1}-12-31")
    return "\n".join(L)

def today_context() -> str:
    """오늘 기준 날짜 컨텍스트. 봇 시스템 프롬프트에 붙여 쓴다."""
    return build(date.today())


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print(today_context())
