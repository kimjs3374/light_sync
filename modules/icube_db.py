"""
iCUBE ERP (DZICUBE) SQL Server 읽기 전용 연결 모듈.

- pyodbc 사용, Trusted_Connection (Windows 인증)
- 모든 쿼리에 CO_CD='1000' 필터 적용 필요 (호출 측 책임)
- 절대 INSERT/UPDATE/DELETE 실행 금지
"""

import os
import logging
import pyodbc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 환경변수
# ---------------------------------------------------------------------------
ICUBE_DB_SERVER = os.environ.get('ICUBE_DB_SERVER', r'localhost\SQLEXPRESS')
ICUBE_DB_NAME = os.environ.get('ICUBE_DB_NAME', 'DZICUBE')

_CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={ICUBE_DB_SERVER};"
    f"DATABASE={ICUBE_DB_NAME};"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)


# ---------------------------------------------------------------------------
# 연결 생성
# ---------------------------------------------------------------------------
def get_icube_connection():
    """pyodbc 연결을 반환한다. 읽기 전용이므로 autocommit=True."""
    try:
        conn = pyodbc.connect(_CONN_STR, autocommit=True, timeout=10)
        return conn
    except pyodbc.Error as e:
        logger.error("iCUBE DB 연결 실패: %s", e)
        raise


# ---------------------------------------------------------------------------
# 쿼리 실행 헬퍼
# ---------------------------------------------------------------------------
def execute_query(sql, params=None):
    """
    SELECT 쿼리를 실행하고 list[dict]를 반환한다.

    Args:
        sql: SQL 쿼리 문자열 (파라미터는 ? 플레이스홀더)
        params: 파라미터 튜플/리스트 (optional)

    Returns:
        list[dict] - 각 행을 컬럼명:값 딕셔너리로 변환
    """
    conn = None
    try:
        conn = get_icube_connection()
        cursor = conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)

        if not cursor.description:
            return []

        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    except pyodbc.Error as e:
        logger.error("iCUBE 쿼리 오류: %s | SQL: %s", e, sql[:200])
        raise
    finally:
        if conn:
            conn.close()


def execute_scalar(sql, params=None):
    """단일 값(첫 행 첫 컬럼)을 반환한다. 결과 없으면 None."""
    conn = None
    try:
        conn = get_icube_connection()
        cursor = conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        row = cursor.fetchone()
        return row[0] if row else None
    except pyodbc.Error as e:
        logger.error("iCUBE scalar 오류: %s | SQL: %s", e, sql[:200])
        raise
    finally:
        if conn:
            conn.close()


def test_connection():
    """연결 테스트. 성공 시 True, 실패 시 False."""
    try:
        result = execute_scalar("SELECT 1")
        return result == 1
    except Exception:
        return False
