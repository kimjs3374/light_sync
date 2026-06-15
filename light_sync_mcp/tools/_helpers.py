"""공통 헬퍼 함수"""
import os

ERP_BASE_URL = os.environ.get("ERP_BASE_URL", "https://work.mgnt.kr").rstrip("/")


def _s(val, default=""):
    """Safe string: None → default"""
    return val if val is not None else default


def _sn(val, default=0.0):
    """Safe number: None → default"""
    return float(val) if val is not None else default


def _sd(val):
    """Safe date: None → empty string, otherwise isoformat"""
    return val.isoformat() if val else ""


def _erp_url(path: str) -> str:
    """ERP 절대 URL 생성. path는 슬래시로 시작.

    예: _erp_url(f"/contract_detail/{pid}")
        → 'https://work.mgnt.kr/contract_detail/123'
    """
    if not path:
        return ERP_BASE_URL
    if not path.startswith("/"):
        path = "/" + path
    return ERP_BASE_URL + path
