import json
import os
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote

import requests


BASE_DIR = Path(__file__).resolve().parents[1]


def _read_env_value(key: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(key)
    if value:
        return value

    for env_file in [BASE_DIR / ".env", BASE_DIR / "supabase" / ".env", BASE_DIR / "storage" / ".env"]:
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip()

    return default


def _normalize_path(path: str) -> str:
    return (path or "").replace("\\", "/").lstrip("/")


def get_storage_config():
    url = _read_env_value("SUPABASE_URL")
    key = _read_env_value("SUPABASE_SERVICE_ROLE_KEY") or _read_env_value("SERVICE_ROLE_KEY")
    bucket = _read_env_value("SUPABASE_STORAGE_BUCKET", "company-files")
    enabled = bool(url and key)
    return {
        "enabled": enabled,
        "url": (url or "").rstrip("/"),
        "key": key or "",
        "bucket": bucket,
    }


def is_storage_enabled() -> bool:
    return bool(get_storage_config()["enabled"])


def upload_bytes(object_path: str, content: bytes, content_type: str = "application/octet-stream", upsert: bool = True) -> Tuple[bool, str]:
    cfg = get_storage_config()
    if not cfg["enabled"]:
        return False, "supabase storage 설정이 없습니다"

    obj = quote(_normalize_path(object_path), safe="/")
    url = f"{cfg['url']}/storage/v1/object/{cfg['bucket']}/{obj}"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": content_type,
        "x-upsert": "true" if upsert else "false",
    }
    resp = requests.post(url, headers=headers, data=content, timeout=120)
    if resp.status_code in (200, 201):
        return True, "ok"
    return False, f"{resp.status_code} {resp.text[:300]}"


def download_bytes(object_path: str) -> Optional[bytes]:
    cfg = get_storage_config()
    if not cfg["enabled"]:
        return None

    obj = quote(_normalize_path(object_path), safe="/")
    url = f"{cfg['url']}/storage/v1/object/{cfg['bucket']}/{obj}"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
    }
    resp = requests.get(url, headers=headers, timeout=60)
    if resp.status_code == 200:
        return resp.content
    return None


def delete_object(object_path: str) -> bool:
    cfg = get_storage_config()
    if not cfg["enabled"]:
        return False

    obj = quote(_normalize_path(object_path), safe="/")
    url = f"{cfg['url']}/storage/v1/object/{cfg['bucket']}/{obj}"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
    }
    resp = requests.delete(url, headers=headers, timeout=30)
    return resp.status_code in (200, 204)


def _list_prefix(prefix: str) -> List[dict]:
    cfg = get_storage_config()
    if not cfg["enabled"]:
        return []
    url = f"{cfg['url']}/storage/v1/object/list/{cfg['bucket']}"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "prefix": _normalize_path(prefix),
        "limit": 1000,
        "offset": 0,
        "sortBy": {"column": "name", "order": "asc"},
    }
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
    if resp.status_code != 200:
        return []
    return resp.json() if isinstance(resp.json(), list) else []


def delete_prefix(prefix: str) -> int:
    cfg = get_storage_config()
    if not cfg["enabled"]:
        return 0

    queue = [_normalize_path(prefix).rstrip("/") + "/"]
    removed = 0
    while queue:
        pfx = queue.pop(0)
        items = _list_prefix(pfx)
        for item in items:
            name = item.get("name")
            if not name:
                continue
            is_dir = item.get("id") is None and not item.get("metadata")
            full = f"{pfx}{name}"
            if is_dir:
                queue.append(full.rstrip("/") + "/")
            else:
                if delete_object(full):
                    removed += 1
    return removed
