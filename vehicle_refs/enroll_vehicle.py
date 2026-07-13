# -*- coding: utf-8 -*-
"""차량 계기판 참고사진 등록: enroll_vehicle.py "<차량명>" <이미지경로>"""
import sys, os, re, json, shutil

REF_DIR = "/web/light_sync/vehicle_refs"
REF_JSON = os.path.join(REF_DIR, "refs.json")

veh = sys.argv[1]
src = sys.argv[2]
os.makedirs(REF_DIR, exist_ok=True)
ext = os.path.splitext(src)[1] or ".jpg"
key = re.sub(r"[^0-9A-Za-z]+", "_", veh).strip("_") or "veh"
dst_name = f"{key}{ext}"
shutil.copy(src, os.path.join(REF_DIR, dst_name))

try:
    refs = json.load(open(REF_JSON, encoding="utf-8"))
except Exception:
    refs = {}
refs[veh] = dst_name
json.dump(refs, open(REF_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"등록 완료: '{veh}' -> {dst_name}")
print("현재 등록 차량:", list(refs.keys()))
