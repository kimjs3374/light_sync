"""공통 헬퍼 함수"""


def _s(val, default=""):
    """Safe string: None → default"""
    return val if val is not None else default


def _sn(val, default=0.0):
    """Safe number: None → default"""
    return float(val) if val is not None else default


def _sd(val):
    """Safe date: None → empty string, otherwise isoformat"""
    return val.isoformat() if val else ""
