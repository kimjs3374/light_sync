#!/bin/bash
# NAS 폴더 → ERP 동기화 (Python 실행 래퍼)
# cron 등록: bash /scripts/nas_folder_sync.sh > /dev/null 2>&1
python3 /scripts/nas_folder_sync.py
