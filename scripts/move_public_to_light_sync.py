import argparse
import importlib.util
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _read_env_value(key, default=None):
    import os

    value = os.getenv(key)
    if value:
        return value

    for env_file in [PROJECT_ROOT / '.env', PROJECT_ROOT / 'supabase' / '.env']:
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            if k.strip() == key:
                return v.strip()
    return default


def quote_ident(identifier):
    value = (identifier or '').strip()
    if not value:
        raise ValueError('identifier가 비어 있습니다.')
    return '"' + value.replace('"', '""') + '"'


DEFAULT_SCHEMA = _read_env_value('DB_SCHEMA', 'light_sync')
DEFAULT_DSN = _read_env_value('DATABASE_URL') or _read_env_value('SUPABASE_DB_DSN')
PIP_INSTALL_HINT = f'"{sys.executable}" -m pip install psycopg2-binary'


def qi(identifier: str) -> str:
    return quote_ident(identifier)


def fetch_public_tables(conn):
    rows = conn.execute(
        text(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename NOT LIKE 'pg_%'
            ORDER BY tablename
            """
        )
    )
    return [row[0] for row in rows]


def fetch_public_sequences(conn):
    rows = conn.execute(
        text(
            """
            SELECT sequence_name
            FROM information_schema.sequences
            WHERE sequence_schema = 'public'
            ORDER BY sequence_name
            """
        )
    )
    return [row[0] for row in rows]


def fetch_public_views(conn):
    rows = conn.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.views
            WHERE table_schema = 'public'
            ORDER BY table_name
            """
        )
    )
    return [row[0] for row in rows]


def grant_schema_usage(conn, schema_name: str):
    schema_ident = qi(schema_name)
    conn.execute(text(f"GRANT USAGE ON SCHEMA {schema_ident} TO anon, authenticated, service_role"))
    conn.execute(text(f"GRANT ALL ON ALL TABLES IN SCHEMA {schema_ident} TO service_role"))
    conn.execute(text(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA {schema_ident} TO service_role"))
    conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema_ident} TO authenticated"))
    conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema_ident} TO anon"))
    conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema_ident} TO authenticated"))
    conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema_ident} TO anon"))


def main():
    parser = argparse.ArgumentParser(description='Supabase public 스키마 객체를 light_sync 스키마로 이동')
    parser.add_argument('--dsn', default=DEFAULT_DSN)
    parser.add_argument('--target-schema', default=DEFAULT_SCHEMA)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--include-views', action='store_true')
    args = parser.parse_args()

    if not args.dsn:
        raise SystemExit('[ERROR] DATABASE_URL 또는 SUPABASE_DB_DSN 값이 필요합니다.')

    if importlib.util.find_spec('psycopg2') is None and importlib.util.find_spec('psycopg') is None:
        print('[ERROR] PostgreSQL 드라이버가 설치되어 있지 않습니다.')
        print('[INFO] 다음 명령으로 설치 후 다시 실행하세요:')
        print(f'       {PIP_INSTALL_HINT}')
        raise SystemExit(1)

    try:
        engine = create_engine(args.dsn)
    except ModuleNotFoundError as e:
        if e.name in {'psycopg2', 'psycopg'}:
            print('[ERROR] PostgreSQL 드라이버 로딩에 실패했습니다.')
            print('[INFO] 다음 명령으로 설치 후 다시 실행하세요:')
            print(f'       {PIP_INSTALL_HINT}')
            raise SystemExit(1)
        raise

    insp = inspect(engine)
    if engine.dialect.name != 'postgresql':
        raise SystemExit('[ERROR] 이 스크립트는 PostgreSQL/Supabase 전용입니다.')

    with engine.begin() as conn:
        schema_ident = qi(args.target_schema)
        public_tables = fetch_public_tables(conn)
        public_sequences = fetch_public_sequences(conn)
        public_views = fetch_public_views(conn) if args.include_views else []

        print(f'[INFO] target schema: {args.target_schema}')
        print(f'[INFO] public tables   : {len(public_tables)}')
        print(f'[INFO] public sequences: {len(public_sequences)}')
        print(f'[INFO] public views    : {len(public_views)}')

        if args.dry_run:
            for name in public_tables:
                print(f'[DRY-RUN] ALTER TABLE public.{name} SET SCHEMA {args.target_schema};')
            for name in public_sequences:
                print(f'[DRY-RUN] ALTER SEQUENCE public.{name} SET SCHEMA {args.target_schema};')
            for name in public_views:
                print(f'[DRY-RUN] ALTER VIEW public.{name} SET SCHEMA {args.target_schema};')
            print(f'[DRY-RUN] ALTER ROLE postgres IN DATABASE postgres SET search_path TO {args.target_schema}, public;')
            return

        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS {schema_ident}'))

        for table_name in public_tables:
            conn.execute(text(f'ALTER TABLE public.{qi(table_name)} SET SCHEMA {schema_ident}'))

        for sequence_name in public_sequences:
            conn.execute(text(f'ALTER SEQUENCE public.{qi(sequence_name)} SET SCHEMA {schema_ident}'))

        for view_name in public_views:
            conn.execute(text(f'ALTER VIEW public.{qi(view_name)} SET SCHEMA {schema_ident}'))

        grant_schema_usage(conn, args.target_schema)
        conn.execute(text(f'SET search_path TO {schema_ident}, public'))

    print('[INFO] 스키마 이동이 완료되었습니다.')
    print('[INFO] 앱 환경변수 DB_SCHEMA=light_sync 설정을 확인하세요.')
    print(f'[INFO] 현재 DB의 테이블 스키마 목록: {insp.get_schema_names()}')


if __name__ == '__main__':
    main()