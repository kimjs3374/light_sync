import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# ERP 루트를 sys.path에 추가 → modules/models/entities.py 재사용
_erp_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _erp_root not in sys.path:
    sys.path.insert(0, _erp_root)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL 환경변수가 설정되지 않았습니다.")

DB_SCHEMA = os.environ.get("DB_SCHEMA", "public")

engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    connect_args={"options": f"-csearch_path={DB_SCHEMA}"},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_session():
    """DB 세션 반환. 사용 후 반드시 close() 호출."""
    return SessionLocal()
