import os
from pathlib import Path

from .constants import DETAIL_ITEM_ALIASES, DETAIL_ITEM_OPTIONS


def normalize_detail_item(value, default=None):
    raw = (value or '').strip()
    if not raw:
        return default
    normalized = DETAIL_ITEM_ALIASES.get(raw, raw)
    return normalized if normalized in DETAIL_ITEM_OPTIONS else default

BASE_DIR = str(Path(__file__).resolve().parents[2])
DB_DIR = os.path.join(BASE_DIR, 'DB')
DB_PATH = os.path.join(DB_DIR, 'light_sync.db')


def _read_env_value(key, default=None):
    value = os.getenv(key)
    if value:
        return value
    for env_file in [Path(BASE_DIR) / '.env', Path(BASE_DIR) / 'supabase' / '.env']:
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
