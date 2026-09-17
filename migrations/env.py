"""Alembic 실행 환경.

여기서 정하는 것 셋:
  ① 어디에 붙나      — DATABASE_URL (alembic.ini 에 비밀번호를 적지 않는다)
  ② 어느 스키마인가  — DB_SCHEMA(기본 light_sync). 연결마다 search_path 를 맞춘다
  ③ 무엇과 비교하나  — 앱의 모델(Base.metadata)

**이력표(alembic_version)도 그 스키마 안에 둔다.** public 에 두면 한 DB 에 두 벌을
올릴 때 서로 덮어쓴다.
"""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 앱의 모델을 전부 불러와야 metadata 가 채워진다 (이게 비교 대상이다)
from modules.models import Base  # noqa: E402
import modules.models.entities  # noqa: E402,F401
import modules.models.mail_entities  # noqa: E402,F401

try:                     # 회사마다 안 쓰는 묶음이 있을 수 있다 — 없으면 건너뛴다
    import modules.models.procurement_entities  # noqa: E402,F401
except Exception:        # pragma: no cover
    pass
try:
    import modules.models.auth_entities  # noqa: E402,F401
except Exception:        # pragma: no cover
    pass

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 앱과 **같은 방식**으로 읽는다 — 환경변수가 먼저, 없으면 .env.
# 두 곳이 갈리면 "앱은 되는데 마이그레이션만 다른 DB 를 보는" 사고가 난다.
from modules.models.helpers import _read_env_value  # noqa: E402

DB_URL = _read_env_value('DATABASE_URL') or _read_env_value('SUPABASE_DB_DSN')
DB_SCHEMA = os.environ.get('DB_SCHEMA') or _read_env_value('DB_SCHEMA', 'light_sync')
if not DB_URL:
    raise RuntimeError('DATABASE_URL 이 없습니다. .env 를 확인하십시오.')
config.set_main_option('sqlalchemy.url', DB_URL)

target_metadata = Base.metadata


def _opts(**extra):
    return dict(
        target_metadata=target_metadata,
        version_table='alembic_version',
        version_table_schema=DB_SCHEMA,
        include_schemas=False,        # search_path 로 이미 그 스키마를 본다
        compare_type=True,
        compare_server_default=True,
        **extra,
    )


def run_migrations_offline():
    """SQL 만 뽑아 본다 (`alembic upgrade head --sql`). 남의 DB 를 고치기 전에 읽어볼 때."""
    context.configure(url=DB_URL, literal_binds=True,
                      dialect_opts={'paramstyle': 'named'}, **_opts())
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix='sqlalchemy.', poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA}'))
        connection.execute(text(f'SET search_path TO {DB_SCHEMA}, public'))
        connection.commit()
        context.configure(connection=connection, **_opts())
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
