import argparse
import datetime as dt
import json
import mimetypes
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests
from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def now_str() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def ensure_bucket(base_url: str, service_role_key: str, bucket: str, report: dict, dry_run: bool = False):
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
    }
    list_url = f"{base_url.rstrip('/')}/storage/v1/bucket"
    resp = requests.get(list_url, headers=headers, timeout=30)
    resp.raise_for_status()
    buckets = resp.json() if isinstance(resp.json(), list) else []
    exists = any((b.get("id") == bucket or b.get("name") == bucket) for b in buckets)
    if exists:
        report["storage"]["bucket"] = {"name": bucket, "created": False, "already_exists": True}
        return

    if dry_run:
        report["storage"]["bucket"] = {"name": bucket, "created": False, "dry_run": True}
        return

    create_url = f"{base_url.rstrip('/')}/storage/v1/bucket"
    payload = {"id": bucket, "name": bucket, "public": True}
    create_resp = requests.post(create_url, headers=headers, data=json.dumps(payload), timeout=30)
    create_resp.raise_for_status()
    report["storage"]["bucket"] = {"name": bucket, "created": True, "public": True}


def upload_storage_files(
    base_url: str,
    service_role_key: str,
    bucket: str,
    storage_root: Path,
    report: dict,
    dry_run: bool = False,
):
    headers_base = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "x-upsert": "true",
    }

    files = [p for p in storage_root.rglob("*") if p.is_file()]
    report["storage"]["local_file_count"] = len(files)

    if dry_run:
        report["storage"].update(
            {
                "uploaded": 0,
                "failed": 0,
                "failed_files": [],
                "dry_run": True,
            }
        )
        return

    uploaded = 0
    failed = []

    for fp in files:
        rel = fp.relative_to(storage_root).as_posix()
        object_path = quote(rel, safe="/")
        upload_url = f"{base_url.rstrip('/')}/storage/v1/object/{bucket}/{object_path}"
        content_type = mimetypes.guess_type(fp.name)[0] or "application/octet-stream"
        headers = {**headers_base, "Content-Type": content_type}
        try:
            with fp.open("rb") as f:
                resp = requests.post(upload_url, headers=headers, data=f.read(), timeout=120)
            if resp.status_code not in (200, 201):
                failed.append({"path": rel, "status": resp.status_code, "body": resp.text[:500]})
            else:
                uploaded += 1
        except Exception as e:  # noqa: BLE001
            failed.append({"path": rel, "error": str(e)})

    report["storage"].update(
        {
            "uploaded": uploaded,
            "failed": len(failed),
            "failed_files": failed[:200],
        }
    )


def create_target_schema(target_engine, report: dict, dry_run: bool = False):
    if dry_run:
        report["db"]["schema"] = {"created": False, "dry_run": True}
        return

    from modules.models import Base  # 프로젝트 메타데이터 재사용

    Base.metadata.create_all(target_engine)
    report["db"]["schema"] = {"created": True}


def truncate_target_tables(target_engine, target_meta: MetaData):
    if not target_meta.sorted_tables:
        return
    with target_engine.begin() as conn:
        names = ", ".join(qi(t.name) for t in reversed(target_meta.sorted_tables))
        conn.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))


def migrate_data(source_engine, target_engine, batch_size: int, truncate_target: bool, report: dict, dry_run: bool = False):
    source_meta = MetaData()
    source_meta.reflect(bind=source_engine)

    target_meta = MetaData()
    target_meta.reflect(bind=target_engine)

    source_tables = source_meta.tables

    if truncate_target and not dry_run:
        truncate_target_tables(target_engine, target_meta)

    table_reports = []

    with source_engine.connect() as src_conn:
        # FK 순서를 target(Postgres) 기준으로 맞춰서 적재 (부모 -> 자식)
        for tgt_table in target_meta.sorted_tables:
            table_name = tgt_table.name
            if table_name not in source_tables:
                table_reports.append(
                    {
                        "table": table_name,
                        "status": "skipped",
                        "reason": "missing_in_source",
                        "source_count": None,
                        "target_count": None,
                    }
                )
                continue

            src_table = source_tables[table_name]

            source_count = src_conn.execute(select(text("count(1)")).select_from(src_table)).scalar_one()

            if dry_run:
                table_reports.append(
                    {
                        "table": table_name,
                        "status": "dry_run",
                        "source_count": int(source_count),
                        "target_count": None,
                    }
                )
                continue

            inserted = 0
            try:
                with target_engine.begin() as tgt_conn:
                    result = src_conn.execute(select(src_table))
                    while True:
                        chunk = result.fetchmany(batch_size)
                        if not chunk:
                            break
                        rows = [dict(r._mapping) for r in chunk]
                        tgt_conn.execute(tgt_table.insert(), rows)
                        inserted += len(rows)

                    target_count = tgt_conn.execute(select(text("count(1)")).select_from(tgt_table)).scalar_one()

                table_reports.append(
                    {
                        "table": table_name,
                        "status": "ok",
                        "source_count": int(source_count),
                        "inserted": int(inserted),
                        "target_count": int(target_count),
                    }
                )
            except SQLAlchemyError as e:
                table_reports.append(
                    {
                        "table": table_name,
                        "status": "error",
                        "source_count": int(source_count),
                        "inserted": int(inserted),
                        "error": str(e),
                    }
                )

    report["db"]["tables"] = table_reports

    if not dry_run:
        reset_sequences(target_engine, report)


def reset_sequences(target_engine, report: dict):
    insp = inspect(target_engine)
    reset = []
    with target_engine.begin() as conn:
        for table_name in insp.get_table_names():
            pk = insp.get_pk_constraint(table_name)
            cols = (pk or {}).get("constrained_columns") or []
            if len(cols) != 1:
                continue
            col = cols[0]
            table_q = qi(table_name)
            col_q = qi(col)
            try:
                sql = text(
                    f"SELECT setval(pg_get_serial_sequence('{table_name}','{col}'), "
                    f"COALESCE((SELECT MAX({col_q}) FROM {table_q}), 1), true)"
                )
                conn.execute(sql)
                reset.append({"table": table_name, "column": col, "status": "ok"})
            except Exception as e:  # noqa: BLE001
                reset.append({"table": table_name, "column": col, "status": "skipped", "reason": str(e)})
    report["db"]["sequence_reset"] = reset


def main():
    parser = argparse.ArgumentParser(description="SQLite -> Supabase(Postgres+Storage) migration")
    parser.add_argument("--source-sqlite", default=None)
    parser.add_argument("--target-dsn", default=os.getenv("SUPABASE_DB_DSN"))
    parser.add_argument("--supabase-url", default=os.getenv("SUPABASE_URL"))
    parser.add_argument("--service-role-key", default=os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    parser.add_argument("--bucket", default="company-files")
    parser.add_argument("--storage-root", default="storage")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--truncate-target", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-db", action="store_true")
    parser.add_argument("--skip-storage", action="store_true")
    parser.add_argument("--report", default=f"migration_report_{now_str()}.json")
    args = parser.parse_args()

    if not args.target_dsn:
        raise SystemExit("[ERROR] SUPABASE_DB_DSN(또는 --target-dsn) 값이 필요합니다.")
    if not args.supabase_url:
        raise SystemExit("[ERROR] SUPABASE_URL(또는 --supabase-url) 값이 필요합니다.")
    if not args.service_role_key:
        raise SystemExit("[ERROR] SUPABASE_SERVICE_ROLE_KEY(또는 --service-role-key) 값이 필요합니다.")

    source_sqlite = Path(args.source_sqlite) if args.source_sqlite else None
    if not args.skip_db:
        if not source_sqlite:
            raise SystemExit("[ERROR] DB 마이그레이션에는 --source-sqlite 경로가 필요합니다.")
        if not source_sqlite.exists():
            raise SystemExit(f"[ERROR] 소스 DB 파일이 없습니다: {source_sqlite}")

    storage_root = Path(args.storage_root)
    if not storage_root.exists():
        raise SystemExit(f"[ERROR] 스토리지 소스 경로가 없습니다: {storage_root}")

    report = {
        "started_at": dt.datetime.now().isoformat(),
        "dry_run": args.dry_run,
        "config": {
            "source_sqlite": str(source_sqlite) if source_sqlite else None,
            "target_dsn": args.target_dsn.split("@")[-1],
            "supabase_url": args.supabase_url,
            "bucket": args.bucket,
            "storage_root": str(storage_root),
            "batch_size": args.batch_size,
            "truncate_target": args.truncate_target,
            "skip_db": args.skip_db,
            "skip_storage": args.skip_storage,
        },
        "db": {},
        "storage": {},
        "errors": [],
    }

    source_engine = create_engine(f"sqlite:///{source_sqlite.as_posix()}") if source_sqlite else None
    target_engine = create_engine(args.target_dsn)

    try:
        if not args.skip_db:
            create_target_schema(target_engine, report, dry_run=args.dry_run)
            migrate_data(
                source_engine,
                target_engine,
                batch_size=args.batch_size,
                truncate_target=args.truncate_target,
                report=report,
                dry_run=args.dry_run,
            )
        else:
            report["db"]["skipped"] = True

        if not args.skip_storage:
            ensure_bucket(args.supabase_url, args.service_role_key, args.bucket, report, dry_run=args.dry_run)
            upload_storage_files(
                args.supabase_url,
                args.service_role_key,
                args.bucket,
                storage_root,
                report,
                dry_run=args.dry_run,
            )
        else:
            report["storage"]["skipped"] = True
    except Exception as e:  # noqa: BLE001
        report["errors"].append(str(e))
        raise
    finally:
        report["finished_at"] = dt.datetime.now().isoformat()
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[INFO] migration report written: {args.report}")


if __name__ == "__main__":
    main()
