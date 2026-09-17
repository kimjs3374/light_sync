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


def upload_stream(object_path: str, chunks, total_size: int,
                  content_type: str = "application/octet-stream",
                  progress=None, chunk_size: int = 8 * 1024 * 1024) -> Tuple[bool, str]:
    """큰 파일을 **메모리에 다 올리지 않고** Storage 로 흘려보낸다 (TUS 재개 업로드).

    왜 TUS 인가: 단일 PUT 은 앞단(Cloudflare 등)이 100MB 에서 막고, 무엇보다
    바이트를 통째로 들고 있어야 한다. 30GB 짜리를 그렇게 올리면 서버가 죽는다.
    TUS 는 조각으로 나눠 보내므로 **한 번에 손에 드는 것은 조각 하나(8MB)뿐**이다.

    chunks: 바이트를 조금씩 내주는 반복자(예: requests 의 iter_content)
    progress: 올린 누적 바이트를 받는 함수 — 화면 진행률이 여기서 나온다

    서버에서 부르므로 service 키를 그대로 쓴다(브라우저에는 절대 안 준다).
    """
    cfg = get_storage_config()
    if not cfg["enabled"]:
        return False, "supabase storage 설정이 없습니다"

    import base64
    import os as _os

    base = _os.environ.get("MAIL_STORAGE_LAN_URL", "").rstrip("/") or cfg["url"]
    endpoint = f"{base}/storage/v1/upload/resumable"
    obj = _normalize_path(object_path)

    # TUS 는 메타데이터를 base64 로 싣는다.
    # 한 쌍 안은 공백(키 값), **쌍과 쌍 사이는 쉼표**다. 공백으로 이으면
    # Supabase 가 400 Invalid upload-metadata 로 거절한다.
    meta = ",".join(
        f"{k} {base64.b64encode(v.encode()).decode()}"
        for k, v in (
            ("bucketName", cfg["bucket"]),
            ("objectName", obj),
            ("contentType", content_type),
            ("cacheControl", "3600"),
        )
    )
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Tus-Resumable": "1.0.0",
        "Upload-Length": str(total_size),
        "Upload-Metadata": meta,
        "x-upsert": "true",
    }
    try:
        resp = requests.post(endpoint, headers=headers, timeout=60)
    except Exception as e:
        return False, f"업로드를 시작하지 못했습니다: {e}"
    if resp.status_code not in (200, 201):
        return False, f"업로드 시작 실패 {resp.status_code} {resp.text[:200]}"

    location = resp.headers.get("Location") or ""
    if not location:
        return False, "업로드 주소를 받지 못했습니다"
    # TUS 가 주는 주소는 저장소 **내부 주소**(127.0.0.1:8000)를 가리킬 수 있다.
    # 경로만 떼어 우리가 쓰는 주소에 붙인다 — 안 그러면 다음 조각이 갈 곳이 없다.
    if location.startswith("http"):
        from urllib.parse import urlparse
        p = urlparse(location)
        location = f"{base}{p.path}" + (f"?{p.query}" if p.query else "")

    offset = 0
    buf = bytearray()

    def _patch(payload: bytes) -> Tuple[bool, str]:
        nonlocal offset
        r = requests.patch(
            location,
            headers={
                "apikey": cfg["key"],
                "Authorization": f"Bearer {cfg['key']}",
                "Tus-Resumable": "1.0.0",
                "Content-Type": "application/offset+octet-stream",
                "Upload-Offset": str(offset),
            },
            data=payload, timeout=(10, 600),
        )
        if r.status_code not in (200, 204):
            return False, f"조각 전송 실패 {r.status_code} {r.text[:200]}"
        offset = int(r.headers.get("Upload-Offset") or (offset + len(payload)))
        if progress:
            progress(offset)
        return True, "ok"

    try:
        for piece in chunks:
            if not piece:
                continue
            buf.extend(piece)
            while len(buf) >= chunk_size:
                ok, msg = _patch(bytes(buf[:chunk_size]))
                if not ok:
                    return False, msg
                del buf[:chunk_size]
        if buf:
            ok, msg = _patch(bytes(buf))
            if not ok:
                return False, msg
    except Exception as e:
        return False, f"업로드 중 끊겼습니다: {e}"

    if offset != total_size:
        return False, f"크기가 맞지 않습니다 (보낸 {offset} / 전체 {total_size})"
    return True, "ok"
