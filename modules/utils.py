import datetime


def parse_date(value):
    """날짜 문자열 -> date 객체 변환"""
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'):
        try:
            return datetime.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def safe_int(value, default=0):
    """안전한 정수 변환"""
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def date_to_dt_start(d):
    """date -> datetime(00:00) 변환. None이면 None 반환."""
    if not d:
        return None
    return datetime.datetime.combine(d, datetime.time.min)


def is_true_value(value):
    """폼 데이터의 truthy 체크"""
    return str(value).lower() in ('1', 'true', 'on', 'yes') if value else False


ALLOWED_EXTENSIONS = {'pdf', 'dwg', 'png', 'jpg', 'jpeg', 'gif', 'xls', 'xlsx', 'docx'}


def validate_upload(file):
    """업로드 파일 검증 (확장자)"""
    if not file or not file.filename:
        return False, "파일이 선택되지 않았습니다."
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"허용되지 않는 파일 형식입니다: .{ext}"
    return True, "ok"
