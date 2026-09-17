"""baseline — 여기까지가 지금 돌고 있는 스키마

이 리비전은 **아무것도 하지 않는다.** 시작점을 표시하는 말뚝이다.

왜 비어 있나: 이미 돌고 있는 DB 에 마이그레이션을 들이는 중이라, 지금 상태를
「0번」으로 선언하고 여기서부터 쌓는다. 이미 있는 테이블을 다시 만들려 들면
남의 데이터를 밟는다.

새로 까는 곳(고객사 첫 설치)은:
    ① 앱이 Base.metadata.create_all() 로 표를 만들고
    ② `alembic stamp head` 로 여기까지 온 것으로 표시한 뒤
    ③ 그 다음 리비전부터 순서대로 올라간다.
(scripts/db-upgrade.sh 가 이 셋을 알아서 한다)

Revision ID: 3b30ede0681b
Revises:
Create Date: 2026-09-17
"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision = '3b30ede0681b'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
