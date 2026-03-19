"""
G2B Contract Match - DB Migration
Contract 테이블에 g2b_contract_no 컬럼 추가
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.models.db import engine
from sqlalchemy import text, inspect

def migrate():
    insp = inspect(engine)
    columns = [c['name'] for c in insp.get_columns('contracts')]

    with engine.begin() as conn:
        if 'g2b_contract_no' not in columns:
            conn.execute(text("ALTER TABLE contracts ADD COLUMN g2b_contract_no VARCHAR(30) NULL"))
            print("[OK] contracts.g2b_contract_no added")
        else:
            print("[SKIP] contracts.g2b_contract_no already exists")

if __name__ == '__main__':
    migrate()
