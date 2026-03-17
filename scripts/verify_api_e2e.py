import datetime as dt
import json
import re
from pathlib import Path
from urllib.parse import quote

import requests


def load_service_key() -> str:
    for env_path in [Path("storage/.env"), Path("supabase/.env")]:
        if env_path.exists():
            txt = env_path.read_text(encoding="utf-8")
            m = re.search(r"^SERVICE_ROLE_KEY=(.+)$", txt, flags=re.M)
            if m:
                return m.group(1).strip()
    raise RuntimeError("SERVICE_ROLE_KEY를 storage/.env 또는 supabase/.env 에서 찾지 못했습니다.")


def now_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


class E2ERunner:
    def __init__(self, base_url: str, service_role_key: str, bucket: str = "company-files"):
        self.base_url = base_url.rstrip("/")
        self.key = service_role_key
        self.bucket = bucket
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
        }
        self.steps = []
        self.created_db_id = None
        self.created_storage_path = None

    def add_step(self, name: str, ok: bool, detail: str):
        self.steps.append({"name": name, "ok": ok, "detail": detail})

    def rest_get(self, table: str, query: str):
        url = f"{self.base_url}/rest/v1/{table}?{query}"
        h = {**self.headers}
        r = requests.get(url, headers=h, timeout=30)
        return r

    def rest_insert(self, table: str, payload: dict):
        url = f"{self.base_url}/rest/v1/{table}"
        h = {**self.headers, "Content-Type": "application/json", "Prefer": "return=representation"}
        r = requests.post(url, headers=h, data=json.dumps(payload, ensure_ascii=False), timeout=30)
        return r

    def rest_delete(self, table: str, query: str):
        url = f"{self.base_url}/rest/v1/{table}?{query}"
        h = {**self.headers, "Prefer": "return=representation"}
        r = requests.delete(url, headers=h, timeout=30)
        return r

    def storage_list(self, prefix: str = ""):
        url = f"{self.base_url}/storage/v1/object/list/{self.bucket}"
        h = {**self.headers, "Content-Type": "application/json"}
        payload = {
            "prefix": prefix,
            "limit": 1000,
            "offset": 0,
            "sortBy": {"column": "name", "order": "asc"},
        }
        r = requests.post(url, headers=h, data=json.dumps(payload), timeout=30)
        return r

    def storage_upload_text(self, object_path: str, content: str):
        encoded = quote(object_path, safe="/")
        url = f"{self.base_url}/storage/v1/object/{self.bucket}/{encoded}"
        h = {**self.headers, "x-upsert": "true", "Content-Type": "text/plain; charset=utf-8"}
        r = requests.post(url, headers=h, data=content.encode("utf-8"), timeout=30)
        return r

    def storage_download(self, object_path: str):
        encoded = quote(object_path, safe="/")
        url = f"{self.base_url}/storage/v1/object/{self.bucket}/{encoded}"
        r = requests.get(url, headers=self.headers, timeout=30)
        return r

    def storage_delete(self, object_path: str):
        encoded = quote(object_path, safe="/")
        url = f"{self.base_url}/storage/v1/object/{self.bucket}/{encoded}"
        r = requests.delete(url, headers=self.headers, timeout=30)
        return r

    def list_files_recursive(self):
        files = []
        queue = [""]
        while queue:
            prefix = queue.pop(0)
            r = self.storage_list(prefix)
            if r.status_code != 200:
                return None, f"storage list 실패: {r.status_code} {r.text[:300]}"
            items = r.json() if isinstance(r.json(), list) else []
            for item in items:
                name = item.get("name")
                is_dir = item.get("id") is None and not item.get("metadata")
                if is_dir:
                    child_prefix = f"{prefix}{name}/" if prefix else f"{name}/"
                    queue.append(child_prefix)
                else:
                    full = f"{prefix}{name}" if prefix else name
                    files.append(full)
        return files, None

    def run(self):
        # 0) Storage 버킷/파일 존재 확인 (3,4단계 완료 확인)
        bucket_resp = requests.get(f"{self.base_url}/storage/v1/bucket", headers=self.headers, timeout=30)
        if bucket_resp.status_code != 200:
            self.add_step("Storage 인증 및 버킷 조회", False, f"{bucket_resp.status_code} {bucket_resp.text[:250]}")
            return
        buckets = bucket_resp.json() if isinstance(bucket_resp.json(), list) else []
        has_bucket = any((b.get("id") == self.bucket or b.get("name") == self.bucket) for b in buckets)
        self.add_step("Storage 버킷(company-files) 존재 확인", has_bucket, f"buckets={len(buckets)}")

        all_files, err = self.list_files_recursive()
        if err:
            self.add_step("Storage 파일 재귀 조회(Read)", False, err)
        else:
            self.add_step("Storage 파일 재귀 조회(Read)", len(all_files) > 0, f"file_count={len(all_files)}")

        # 1) 기존 DB 읽기 테스트
        read_resp = self.rest_get("production_processes", "select=id,project_id,contract_id,contract_item_id,process_code,process_name,status&limit=5")
        if read_resp.status_code != 200:
            self.add_step("DB 기존 데이터 조회(Read 5)", False, f"{read_resp.status_code} {read_resp.text[:250]}")
            return
        rows = read_resp.json() if isinstance(read_resp.json(), list) else []
        self.add_step("DB 기존 데이터 조회(Read 5)", len(rows) > 0, f"row_count={len(rows)}")
        if not rows:
            return

        sample = rows[0]

        # 2) DB 쓰기
        test_code = f"E2E_{now_id()}"
        insert_payload = {
            "project_id": sample["project_id"],
            "contract_id": sample["contract_id"],
            "contract_item_id": sample["contract_item_id"],
            "process_code": test_code,
            "process_name": "E2E API 테스트 공정",
            "step_order": 999,
            "status": "대기",
            "progress_qty": 0,
            "progress_percent": 0,
            "is_optional": False,
            "is_forced": True,
        }
        ins_resp = self.rest_insert("production_processes", insert_payload)
        if ins_resp.status_code not in (200, 201):
            self.add_step("DB 테스트 데이터 INSERT", False, f"{ins_resp.status_code} {ins_resp.text[:300]}")
            return

        ins_rows = ins_resp.json() if isinstance(ins_resp.json(), list) else []
        self.created_db_id = ins_rows[0]["id"] if ins_rows else None
        self.add_step("DB 테스트 데이터 INSERT", self.created_db_id is not None, f"inserted_id={self.created_db_id}")

        # 3) Storage 쓰기
        self.created_storage_path = f"e2e/test_drawing_verify_{now_id()}.txt"
        up_resp = self.storage_upload_text(self.created_storage_path, "Light-Sync E2E storage write test")
        if up_resp.status_code not in (200, 201):
            self.add_step("Storage 테스트 파일 업로드", False, f"{up_resp.status_code} {up_resp.text[:250]}")
            self.cleanup()
            return
        self.add_step("Storage 테스트 파일 업로드", True, self.created_storage_path)

        # 4) DB 읽기 검증
        vr_resp = self.rest_get(
            "production_processes",
            f"select=id,process_code,process_name&process_code=eq.{test_code}&limit=1",
        )
        if vr_resp.status_code == 200 and isinstance(vr_resp.json(), list) and len(vr_resp.json()) == 1:
            self.add_step("DB 테스트 데이터 재조회(Read)", True, f"process_code={test_code}")
        else:
            self.add_step("DB 테스트 데이터 재조회(Read)", False, f"{vr_resp.status_code} {vr_resp.text[:250]}")

        # 5) Storage 읽기/다운로드 검증
        dl_resp = self.storage_download(self.created_storage_path)
        if dl_resp.status_code == 200 and b"Light-Sync E2E storage write test" in dl_resp.content:
            self.add_step("Storage 테스트 파일 다운로드(Read)", True, f"bytes={len(dl_resp.content)}")
        else:
            self.add_step("Storage 테스트 파일 다운로드(Read)", False, f"{dl_resp.status_code} {dl_resp.text[:200]}")

        # 6) Clean-up
        self.cleanup()

    def cleanup(self):
        db_ok = True
        storage_ok = True

        if self.created_db_id is not None:
            del_resp = self.rest_delete("production_processes", f"id=eq.{self.created_db_id}")
            db_ok = del_resp.status_code in (200, 204)

        if self.created_storage_path is not None:
            sdel_resp = self.storage_delete(self.created_storage_path)
            storage_ok = sdel_resp.status_code in (200, 204)

        self.add_step("Clean-up(DB 테스트 데이터 삭제)", db_ok, f"id={self.created_db_id}")
        self.add_step("Clean-up(Storage 테스트 파일 삭제)", storage_ok, f"path={self.created_storage_path}")

    def markdown_report(self) -> str:
        total = len(self.steps)
        passed = sum(1 for s in self.steps if s["ok"])
        header = [
            "# Light-Sync Supabase API E2E Test Report",
            "",
            f"- Timestamp: {dt.datetime.now().isoformat()}",
            f"- Base URL: {self.base_url}",
            f"- Bucket: {self.bucket}",
            f"- Result: **{passed}/{total} PASS**",
            "",
            "| Step | Status | Detail |",
            "|---|---|---|",
        ]
        rows = [
            f"| {s['name']} | {'✅ PASS' if s['ok'] else '❌ FAIL'} | {str(s['detail']).replace('|', '/')} |"
            for s in self.steps
        ]
        return "\n".join(header + rows) + "\n"


def main():
    base_url = "https://api.mgnt.kr"
    key = load_service_key()
    runner = E2ERunner(base_url=base_url, service_role_key=key, bucket="company-files")
    runner.run()
    md = runner.markdown_report()
    print(md)
    report_path = Path(f"e2e_api_report_{now_id()}.md")
    report_path.write_text(md, encoding="utf-8")
    print(f"[INFO] saved: {report_path}")


if __name__ == "__main__":
    main()
