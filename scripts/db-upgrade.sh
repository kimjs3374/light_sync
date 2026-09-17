#!/usr/bin/env bash
#
# DB 스키마를 코드에 맞춘다. **설치할 때도, 올릴 때도 이것 하나만 부른다.**
#
#   처음 까는 곳  : 표를 만들고(create_all) 지금 자리를 말뚝으로 박는다
#   이미 돌던 곳  : 밀린 마이그레이션만 순서대로 올린다
#
# 올리기 전에 스키마를 덤프해 둔다. **이미지는 이전 버전으로 되돌릴 수 있어도
# 스키마는 되돌리기 어렵다** — 덤프가 유일한 안전줄이다.
#
#   사용법:  ./scripts/db-upgrade.sh            (덤프 뜨고 올린다)
#            ./scripts/db-upgrade.sh --dry-run  (뭘 할지 SQL 로 보여만 준다)
#            ./scripts/db-upgrade.sh --no-dump  (덤프 건너뛴다)
set -euo pipefail
cd "$(dirname "$0")/.."

PY=./venv/bin/python
ALEMBIC=./venv/bin/alembic
SCHEMA="${DB_SCHEMA:-light_sync}"
DUMP=1
DRY=0
for a in "$@"; do
  case "$a" in
    --no-dump) DUMP=0 ;;
    --dry-run) DRY=1; DUMP=0 ;;
    *) echo "모르는 옵션: $a" >&2; exit 2 ;;
  esac
done

# 이 스키마에 이력표가 있는가 = 이미 한 번이라도 올린 적이 있는가
HAS=$("$PY" - <<'PYEOF'
import os
from sqlalchemy import create_engine, text
from modules.models.helpers import _read_env_value
url = _read_env_value('DATABASE_URL') or _read_env_value('SUPABASE_DB_DSN')
schema = os.environ.get('DB_SCHEMA') or _read_env_value('DB_SCHEMA', 'light_sync')
e = create_engine(url)
with e.connect() as c:
    got = c.execute(text(
        "select 1 from information_schema.tables "
        "where table_schema=:s and table_name='alembic_version'"), {'s': schema}).first()
print('yes' if got else 'no')
PYEOF
)

if [ "$DRY" = "1" ]; then
  echo "[미리보기] 올릴 SQL 만 뽑습니다 (DB 는 건드리지 않습니다)"
  DB_SCHEMA="$SCHEMA" "$ALEMBIC" upgrade head --sql
  exit 0
fi

if [ "$HAS" = "no" ]; then
  echo "[설치] 처음입니다 — 표를 만들고 지금 자리를 표시합니다 (스키마: $SCHEMA)"
  DB_SCHEMA="$SCHEMA" "$PY" - <<'PYEOF'
import os
from sqlalchemy import create_engine, text
from modules.models.helpers import _read_env_value
from modules.models import Base
import modules.models.entities, modules.models.mail_entities            # noqa: F401
try:
    import modules.models.procurement_entities, modules.models.auth_entities  # noqa: F401
except Exception:
    pass
url = _read_env_value('DATABASE_URL') or _read_env_value('SUPABASE_DB_DSN')
schema = os.environ.get('DB_SCHEMA', 'light_sync')
e = create_engine(url)
with e.connect() as c:
    c.execute(text(f'CREATE SCHEMA IF NOT EXISTS {schema}'))
    c.execute(text(f'SET search_path TO {schema}, public'))
    Base.metadata.create_all(bind=c)
    c.commit()
    n = c.execute(text("select count(*) from information_schema.tables where table_schema=:s"),
                  {'s': schema}).scalar()
print(f'  표 {n}개 준비됨')
PYEOF
  DB_SCHEMA="$SCHEMA" "$ALEMBIC" stamp head
  echo "[설치] 끝났습니다."
  exit 0
fi

if [ "$DUMP" = "1" ] && command -v pg_dump >/dev/null 2>&1; then
  mkdir -p backups
  OUT="backups/schema-$(date +%Y%m%d-%H%M%S).sql"
  URL=$("$PY" -c "from modules.models.helpers import _read_env_value; print(_read_env_value('DATABASE_URL') or _read_env_value('SUPABASE_DB_DSN'))")
  echo "[백업] $OUT"
  pg_dump --schema-only --schema="$SCHEMA" "$URL" > "$OUT" || {
    echo "[백업] 실패했습니다. 덤프 없이 올리려면 --no-dump 를 주십시오." >&2; exit 1; }
fi

echo "[올리기] 밀린 것만 올립니다 (스키마: $SCHEMA)"
DB_SCHEMA="$SCHEMA" "$ALEMBIC" upgrade head
DB_SCHEMA="$SCHEMA" "$ALEMBIC" current
