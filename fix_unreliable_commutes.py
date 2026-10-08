# -*- coding: utf-8 -*-
"""
用 Google Routes API 步行矩阵重算 UNRELIABLE_TRANSIT 名单房源的通勤时间。
OneMap 步行路网在 Normanton Park 等封闭小区缺失, 给出 7km 级别的绕路;
Google 路网包含小区内部道路, 结果贴近真实。
结果写回 commute_faculty.csv: mode=walk_google。
用法: .venv/Scripts/python.exe fix_unreliable_commutes.py   (需 .env 里 GOOGLE_MAPS_API_KEY)
"""
import csv
import json
import math
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import env
from faculties import FACULTIES

BASE = Path(__file__).parent
CSV_PATH = BASE / "commute_faculty.csv"
UNRELIABLE = ["24611200", "24666342"]
V2 = Path(r"C:\Users\23305\Desktop\nus\DSS5105\group project\DSS5105\output-final-delivery\rental_data_v2.csv")


def google_walk_matrix(token, origins, destinations):
    """一次请求算 origins×destinations 的步行矩阵, 返回 {(oi, di): (minutes, meters)}"""
    body = {
        "origins": [{"waypoint": {"location": {"latLng": {"latitude": la, "longitude": lo}}}}
                    for la, lo in origins],
        "destinations": [{"waypoint": {"location": {"latLng": {"latitude": la, "longitude": lo}}}}
                         for la, lo in destinations],
        "travelMode": "WALK",
    }
    req = urllib.request.Request(
        "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "X-Goog-Api-Key": token,
                 "X-Goog-FieldMask": "originIndex,destinationIndex,distanceMeters,duration,status"})
    with urllib.request.urlopen(req, timeout=60) as r:
        elements = json.loads(r.read().decode())
    out = {}
    for e in elements:
        if e.get("status") or "duration" not in e:
            out[(e.get("originIndex"), e.get("destinationIndex"))] = None
        else:
            out[(e.get("originIndex"), e.get("destinationIndex"))] = (
                math.ceil(float(e["duration"].rstrip("s")) / 60), int(e["distanceMeters"]))
    return out


def main():
    key = env("GOOGLE_MAPS_API_KEY")
    if not key:
        raise SystemExit(".env 缺少 GOOGLE_MAPS_API_KEY")

    # 名单房源坐标
    v2 = {r["listing_id"]: r for r in csv.DictReader(open(V2, encoding="utf-8-sig"))}
    origins = []
    for lid in UNRELIABLE:
        r = v2[lid]
        origins.append((float(r["latitude"]), float(r["longitude"])))

    dests = [(f["latitude"], f["longitude"]) for f in FACULTIES]
    fac_names = [f["name"] for f in FACULTIES]

    print(f"请求 Google 步行矩阵: {len(origins)} 房源 x {len(dests)} 学院 ...", flush=True)
    matrix = google_walk_matrix(key, origins, dests)

    # 打印并校验
    for oi, lid in enumerate(UNRELIABLE):
        for di, fname in enumerate(fac_names):
            res = matrix.get((oi, di))
            if res:
                print(f"  {lid} -> {fname[:30]}: {res[0]} 分钟 ({res[1]} m)", flush=True)
            else:
                print(f"  {lid} -> {fname[:30]}: Google 也无路线", flush=True)

    # 写回 CSV
    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8-sig")))
    fn = list(rows[0].keys())
    if "mode" not in fn:
        fn.insert(3, "mode")
    today = f"{datetime.now():%Y-%m-%d}"
    n = 0
    for r in rows:
        r.setdefault("mode", "")
        if r["listing_id"] not in UNRELIABLE:
            continue
        oi = UNRELIABLE.index(r["listing_id"])
        di = fac_names.index(r["faculty"]) if r["faculty"] in fac_names else None
        res = matrix.get((oi, di)) if di is not None else None
        if res:
            r["minutes"], r["mode"] = str(res[0]), "walk_google"
            r["departure"] = today
            n += 1
    tmp = CSV_PATH.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fn, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    tmp.replace(CSV_PATH)
    print(f"写回 {n} 行 (mode=walk_google) -> {CSV_PATH.name}", flush=True)


if __name__ == "__main__":
    main()
