import json
import os
from typing import List, Optional, Tuple
from urllib.parse import quote

import requests


def _read_env_value(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(key, default)


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


def upload_bytes(object_path: str, content: bytes, content_type: str = "application/octet-stream", upsert: bool = True, cache_control: str = "no-cache, max-age=0") -> Tuple[bool, str]:
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
        "cache-control": cache_control,
    }
    resp = requests.post(url, headers=headers, data=content, timeout=120)
    if resp.status_code in (200, 201):
        return True, "ok"
    return False, f"{resp.status_code} {resp.text[:300]}"


def exists(object_path: str) -> bool:
    """파일 존재 여부만 확인 (HEAD 요청, 다운로드 안 함)."""
    cfg = get_storage_config()
    if not cfg["enabled"]:
        return False
    obj = quote(_normalize_path(object_path), safe="/")
    url = f"{cfg['url']}/storage/v1/object/{cfg['bucket']}/{obj}"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
    }
    try:
        resp = requests.head(url, headers=headers, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


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


def move_object(src_path: str, dst_path: str) -> Tuple[bool, str]:
    """버킷 안에서 파일을 옮긴다 (서버쪽에서 처리 — 내려받았다 다시 올리지 않는다).

    대용량 첨부는 임시 위치에 먼저 올려두고 발송이 확정될 때 옮기므로,
    GB 단위 파일을 다시 왕복시키면 안 된다.
    """
    cfg = get_storage_config()
    if not cfg["enabled"]:
        return False, "supabase storage 설정이 없습니다"

    url = f"{cfg['url']}/storage/v1/object/move"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "bucketId": cfg["bucket"],
        "sourceKey": _normalize_path(src_path),
        "destinationKey": _normalize_path(dst_path),
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
    except Exception as e:
        return False, f"이동 요청 실패: {e}"
    if resp.status_code in (200, 201):
        return True, "ok"
    return False, f"{resp.status_code} {resp.text[:300]}"


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
