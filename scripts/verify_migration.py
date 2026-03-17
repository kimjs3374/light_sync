import argparse
import json
from pathlib import Path

import requests
from sqlalchemy import MetaData, create_engine, select, text


def list_storage_objects(base_url: str, service_role_key: str, bucket: str, prefix: str = ""):
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
    }
    url = f"{base_url.rstrip('/')}/storage/v1/object/list/{bucket}"
    payload = {"prefix": prefix, "limit": 1000, "offset": 0, "sortBy": {"column": "name", "order": "asc"}}
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
    resp.raise_for_status()
    items = resp.json() if isinstance(resp.json(), list) else []
    files = [x for x in items if x.get("id") is not None or x.get("metadata")]
    dirs = [x for x in items if x.get("id") is None and not x.get("metadata")]
    return files, dirs


def count_db_rows(engine):
    meta = MetaData()
    meta.reflect(bind=engine)
    counts = {}
    with engine.connect() as conn:
        for t in meta.sorted_tables:
            cnt = conn.execute(select(text("count(1)")).select_from(t)).scalar_one()
            counts[t.name] = int(cnt)
    return counts


def main():
    parser = argparse.ArgumentParser(description="Verify SQLite -> Supabase migration result")
    parser.add_argument("--source-sqlite", default=None)
    parser.add_argument("--target-dsn", required=True)
    parser.add_argument("--supabase-url", required=True)
    parser.add_argument("--service-role-key", required=True)
    parser.add_argument("--bucket", default="company-files")
    parser.add_argument("--storage-root", default="storage")
    parser.add_argument("--skip-db", action="store_true")
    parser.add_argument("--skip-storage", action="store_true")
    parser.add_argument("--report", default="migration_verify_report.json")
    args = parser.parse_args()

    target_engine = create_engine(args.target_dsn)

    report = {"db": {}, "storage": {}}

    if args.skip_db:
        report["db"] = {"skipped": True}
    else:
        if not args.source_sqlite:
            raise SystemExit("[ERROR] DB 비교에는 --source-sqlite 경로가 필요합니다.")
        source_sqlite = Path(args.source_sqlite)
        if not source_sqlite.exists():
            raise SystemExit(f"[ERROR] 소스 DB 파일이 없습니다: {source_sqlite}")

        source_engine = create_engine(f"sqlite:///{source_sqlite.as_posix()}")
        source_counts = count_db_rows(source_engine)
        target_counts = count_db_rows(target_engine)

        compare = {}
        all_tables = sorted(set(source_counts) | set(target_counts))
        ok = True
        for t in all_tables:
            s = source_counts.get(t)
            p = target_counts.get(t)
            matched = s == p
            if not matched:
                ok = False
            compare[t] = {"source": s, "target": p, "matched": matched}

        report["db"] = {
            "all_matched": ok,
            "tables": compare,
        }

    if args.skip_storage:
        report["storage"] = {"skipped": True}
    else:
        local_files = [p for p in Path(args.storage_root).rglob("*") if p.is_file()]
        root_files, root_dirs = list_storage_objects(args.supabase_url, args.service_role_key, args.bucket)
        report["storage"] = {
            "local_file_count": len(local_files),
            "bucket_root_file_count": len(root_files),
            "bucket_root_dir_count": len(root_dirs),
        }

    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
