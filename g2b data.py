import argparse
import re
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import requests


BASE_URL = "http://apis.data.go.kr/1230000/ao/CntrctInfoService"
LIST_OPERATION = "getCntrctInfoListThng"
DETAIL_OPERATION = "getCntrctInfoListThngDetail"

TARGET_BIZNO_PLAIN = "4088168519"
TARGET_BIZNO_DASHED = "408-81-68519"
DEFAULT_SERVICE_KEY = "hUjO2bxNqI9pTqp31m1LrbGNNcfASAihCmyPL4A8CGcihiOgJhLhH4WvC2r6Xr9FnNVl2ob9EhsTdF3GjdqXDg%3D%3D"


def _safe_get_items(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    response = data.get("response", {})
    header = response.get("header", {})
    result_code = str(header.get("resultCode", ""))
    result_msg = header.get("resultMsg", "")

    if result_code and result_code != "00":
        raise RuntimeError(f"API 오류: resultCode={result_code}, resultMsg={result_msg}")

    body = response.get("body", {})
    items_obj = body.get("items", {})
    items = items_obj.get("item") if isinstance(items_obj, dict) else items_obj

    if items is None:
        return []
    if isinstance(items, list):
        return items
    if isinstance(items, dict):
        return [items]
    return []


def _to_number(value: Any) -> float:
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return value
    text = str(value).replace(",", "").strip()
    if not text:
        return 0
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return 0


def _extract_biznos_from_corp_list(corp_list: Any) -> List[str]:
    """corpList 문자열에서 사업자번호(10자리) 후보 추출"""
    if corp_list is None:
        return []
    text = str(corp_list).replace("-", "")
    return re.findall(r"(?<!\d)\d{10}(?!\d)", text)


def _has_target_bizno(corp_list: Any) -> bool:
    if corp_list is None:
        return False
    biznos = _extract_biznos_from_corp_list(corp_list)
    return TARGET_BIZNO_PLAIN in biznos


def _request_json(url: str, params: Dict[str, str]) -> Dict[str, Any]:
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _normalize_service_key(service_key: str) -> str:
    """인코딩/디코딩 키 모두 허용 (인코딩 키는 1회 decode 후 사용)."""
    if "%" in service_key:
        return unquote(service_key)
    return service_key


def _month_ranges(year: int) -> List[tuple[str, str, str]]:
    """year 기준 월별 [시작일시, 종료일시, 라벨] 반환 (YYYYMMDDHHMM)"""
    ranges: List[tuple[str, str, str]] = []
    for month in range(1, 13):
        start = datetime(year, month, 1, 0, 0)
        if month == 12:
            next_month = datetime(year + 1, 1, 1)
        else:
            next_month = datetime(year, month + 1, 1)
        end = next_month - timedelta(minutes=1)
        ranges.append((start.strftime("%Y%m%d%H%M"), end.strftime("%Y%m%d%H%M"), f"{year}-{month:02d}"))
    return ranges


def fetch_contract_list(service_key: str, begin_dt: str, end_dt: str, rows_per_page: int = 100) -> List[Dict[str, Any]]:
    """물품 계약현황 조회(등록일시 기준). inqryBgnDt/inqryEndDt 포맷: YYYYMMDDHHMM"""
    url = f"{BASE_URL}/{LIST_OPERATION}"
    all_items: List[Dict[str, Any]] = []
    page_no = 1

    while True:
        params = {
            "ServiceKey": service_key,
            "type": "json",
            "numOfRows": str(rows_per_page),
            "pageNo": str(page_no),
            "inqryDiv": "1",
            "inqryBgnDt": begin_dt,
            "inqryEndDt": end_dt,
        }
        data = _request_json(url, params)
        items = _safe_get_items(data)
        if not items:
            break

        all_items.extend(items)
        body = data.get("response", {}).get("body", {})
        total_count = int(body.get("totalCount", 0) or 0)

        if total_count and len(all_items) >= total_count:
            break
        if len(items) < rows_per_page:
            break
        page_no += 1

    return all_items


def fetch_contract_details(service_key: str, unty_cntrct_no: str, rows_per_page: int = 100) -> List[Dict[str, Any]]:
    """통합계약번호 기준 물품세부조회"""
    url = f"{BASE_URL}/{DETAIL_OPERATION}"
    all_items: List[Dict[str, Any]] = []
    page_no = 1

    while True:
        params = {
            "ServiceKey": service_key,
            "type": "json",
            "numOfRows": str(rows_per_page),
            "pageNo": str(page_no),
            "inqryDiv": "2",
            "untyCntrctNo": unty_cntrct_no,
        }
        data = _request_json(url, params)
        items = _safe_get_items(data)
        if not items:
            break

        all_items.extend(items)
        body = data.get("response", {}).get("body", {})
        total_count = int(body.get("totalCount", 0) or 0)

        if total_count and len(all_items) >= total_count:
            break
        if len(items) < rows_per_page:
            break
        page_no += 1

    return all_items


def build_rows(service_key: str, begin_dt: str, end_dt: str) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    base_items = fetch_contract_list(service_key, begin_dt, end_dt)

    target_contracts: List[Dict[str, Any]] = []
    for item in base_items:
        corp_list = item.get("corpList")
        biznos = _extract_biznos_from_corp_list(corp_list)
        if TARGET_BIZNO_PLAIN in biznos:
            target_contracts.append(item)

    print(f"[구간 {begin_dt}~{end_dt}] 전체 {len(base_items)}건, 매그나텍 후보 {len(target_contracts)}건")

    candidate_rows: List[Dict[str, Any]] = []
    for i, item in enumerate(target_contracts, start=1):
        candidate_rows.append(
            {
                "순번": i,
                "통합계약번호": item.get("untyCntrctNo", ""),
                "계약명": item.get("cntrctNm", "-"),
                "계약일자": item.get("cntrctDate", item.get("cntrctCnclsDate", "-")),
                "계약기관": item.get("cntrctInsttNm", "-"),
                "업체목록원문": item.get("corpList", "-"),
                "추출사업자번호": ",".join(_extract_biznos_from_corp_list(item.get("corpList"))),
            }
        )

    rows: List[Dict[str, Any]] = []
    seq = 1

    for contract in target_contracts:
        unty_cntrct_no = str(contract.get("untyCntrctNo", "")).strip()
        contract_name = contract.get("cntrctNm", "-")
        contract_date = contract.get("cntrctDate", contract.get("cntrctCnclsDate", "-"))

        if not unty_cntrct_no:
            continue

        detail_items = fetch_contract_details(service_key, unty_cntrct_no)
        if not detail_items:
            rows.append(
                {
                    "순번": seq,
                    "계약명": contract_name,
                    "계약일자": contract_date,
                    "납품기일": "-",
                    "물품분류": "-",
                    "모델명": "-",
                    "수량": 0,
                    "단가": 0,
                    "금액": 0,
                }
            )
            seq += 1
            continue

        for d in detail_items:
            rows.append(
                {
                    "순번": seq,
                    "계약명": contract_name,
                    "계약일자": contract_date,
                    "납품기일": d.get("dlvrTmlmt", "-"),
                    "물품분류": d.get("prdctClsfcNoNm", "-"),
                    "모델명": d.get("krnPrdctNm", "-"),
                    "수량": _to_number(d.get("prdctQty", 0)),
                    "단가": _to_number(d.get("qtyUprcAmt", 0)),
                    "금액": _to_number(d.get("prdctAmt", 0)),
                }
            )
            seq += 1

    monthly_stats = [
        {
            "조회시작": begin_dt,
            "조회종료": end_dt,
            "목록건수": len(base_items),
            "매그나텍후보건수": len(target_contracts),
            "최종상세행수": len(rows),
        }
    ]
    return rows, candidate_rows, monthly_stats


def build_rows_by_year(service_key: str, year: int) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    all_rows: List[Dict[str, Any]] = []
    all_candidates: List[Dict[str, Any]] = []
    all_stats: List[Dict[str, Any]] = []

    for begin_dt, end_dt, label in _month_ranges(year):
        print(f"\n=== {label} 조회 시작 ===")
        rows, candidates, stats = build_rows(service_key, begin_dt, end_dt)
        all_rows.extend(rows)
        all_candidates.extend(candidates)
        all_stats.extend(stats)

    # 순번 재정렬
    for i, row in enumerate(all_rows, start=1):
        row["순번"] = i
    for i, row in enumerate(all_candidates, start=1):
        row["순번"] = i

    return all_rows, all_candidates, all_stats


def save_to_excel(rows: List[Dict[str, Any]], output_path: str) -> None:
    from openpyxl import Workbook

    headers = ["순번", "계약명", "계약일자", "납품기일", "물품분류", "모델명", "수량", "단가", "금액"]
    wb = Workbook()
    ws = wb.active
    ws.title = "매그나텍_계약현황"
    ws.append(headers)

    for row in rows:
        ws.append([row.get(h, "") for h in headers])

    wb.save(output_path)


def save_dict_rows_to_excel(rows: List[Dict[str, Any]], headers: List[str], output_path: str, title: str) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h, "") for h in headers])
    wb.save(output_path)


def save_error_excel(output_path: str, error_message: str) -> None:
    """API 오류가 있어도 결과 파일이 생성되도록 오류 안내용 엑셀 생성"""
    row = {
        "순번": 1,
        "계약명": f"오류: {error_message}",
        "계약일자": "-",
        "납품기일": "-",
        "물품분류": "-",
        "모델명": "-",
        "수량": 0,
        "단가": 0,
        "금액": 0,
    }
    save_to_excel([row], output_path)


def _default_period() -> tuple[str, str]:
    """기본 조회기간: 최근 30일 (등록일시 기준, HHMM 포함)"""
    end = datetime.now()
    begin = end - timedelta(days=30)
    return begin.strftime("%Y%m%d0000"), end.strftime("%Y%m%d2359")


def main() -> None:
    parser = argparse.ArgumentParser(description="나라장터 계약정보서비스에서 매그나텍 계약내역을 엑셀로 저장")
    parser.add_argument(
        "--service-key",
        default=DEFAULT_SERVICE_KEY,
        help="공공데이터포털 서비스키(인코딩/디코딩 모두 가능, 미입력 시 기본값 사용)",
    )
    parser.add_argument("--begin-dt", help="조회 시작일시(YYYYMMDDHHMM)")
    parser.add_argument("--end-dt", help="조회 종료일시(YYYYMMDDHHMM)")
    parser.add_argument("--year", type=int, help="연도 기준 월별 조회 (예: 2025)")
    parser.add_argument("--output", default="매그나텍_계약현황.xlsx", help="출력 엑셀 파일 경로")
    parser.add_argument("--debug-output", help="필터 검증용 후보계약 엑셀 파일 경로")
    parser.add_argument("--stats-output", help="월별 통계 엑셀 파일 경로")
    args = parser.parse_args()

    begin_dt = args.begin_dt
    end_dt = args.end_dt
    if not begin_dt or not end_dt:
        begin_dt, end_dt = _default_period()

    try:
        service_key = _normalize_service_key(args.service_key)
        if args.year:
            rows, candidate_rows, stats_rows = build_rows_by_year(service_key, args.year)
        else:
            rows, candidate_rows, stats_rows = build_rows(service_key, begin_dt, end_dt)

        debug_output = args.debug_output or (
            f"매그나텍_후보계약_{args.year}.xlsx" if args.year else "매그나텍_후보계약.xlsx"
        )
        stats_output = args.stats_output or (
            f"매그나텍_월별통계_{args.year}.xlsx" if args.year else "매그나텍_월별통계.xlsx"
        )

        if candidate_rows:
            save_dict_rows_to_excel(
                rows=candidate_rows,
                headers=["순번", "통합계약번호", "계약명", "계약일자", "계약기관", "추출사업자번호", "업체목록원문"],
                output_path=debug_output,
                title="매그나텍_후보계약",
            )
        if stats_rows:
            save_dict_rows_to_excel(
                rows=stats_rows,
                headers=["조회시작", "조회종료", "목록건수", "매그나텍후보건수", "최종상세행수"],
                output_path=stats_output,
                title="월별통계",
            )

        if not rows:
            save_error_excel(
                args.output,
                "매그나텍(408-81-68519) 계약 데이터가 없거나 서비스키 권한 범위에서 조회되지 않음",
            )
            print(f"조회 결과가 없어도 파일은 생성했습니다: {args.output}")
            if candidate_rows:
                print(f"후보계약 검증 파일: {debug_output}")
            if stats_rows:
                print(f"월별통계 파일: {stats_output}")
            return

        save_to_excel(rows, args.output)
        print(f"완료: {len(rows)}건 저장 -> {args.output}")
        print(f"후보계약 검증 파일: {debug_output}")
        print(f"월별통계 파일: {stats_output}")

    except requests.HTTPError as e:
        save_error_excel(args.output, f"HTTP 오류({e})")
        print(f"HTTP 오류로 실제 데이터 조회 실패. 대신 오류 안내 파일 생성: {args.output}")
        sys.exit(0)
    except requests.RequestException as e:
        save_error_excel(args.output, f"요청 오류({e})")
        print(f"요청 오류로 실제 데이터 조회 실패. 대신 오류 안내 파일 생성: {args.output}")
        sys.exit(0)
    except ImportError:
        print("openpyxl 미설치: python -m pip install openpyxl")
        sys.exit(1)
    except Exception as e:
        print(f"실행 중 오류: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
