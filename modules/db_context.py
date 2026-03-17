from contextlib import contextmanager
from modules.models import SessionLocal


@contextmanager
def get_db():
    """안전한 DB 세션 컨텍스트 매니저. 예외 시 자동 rollback, 항상 close."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
