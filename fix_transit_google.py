# -*- coding: utf-8 -*-
"""
用 Google Routes API (Compute Routes, TRANSIT) 重算 UNRELIABLE_TRANSIT 名单的 32 对通勤。
出发时间 = 下一个工作日 08:30 (新加坡时区), 与 OneMap 口径一致。
结果覆盖 commute_faculty.csv 里这 32 行: mode=transit_google。
用法: .venv/Scripts/python.exe fix_transit_google.py
"""
import csv
import json
import math
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import env
from faculties import FACULTIES

BASE = Path(__file__).parent
CSV_PATH = BASE / "commute_faculty.csv"
UNRELIABLE = ["24611200", "24666342"]
V2 = Path(r"C:\Users\23305\Desktop\nus\DSS5105\group project\DSS5105\output-final-delivery\rental_data_v2.csv")
URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def transit_minutes(key, sla, slo, ela, elo, departure_iso):
    body = {
        "origin": {"location": {"latLng": {"latitude": sla, "longitude": slo}}},
        "destination": {"location": {"latLng": {"latitude": ela, "longitude": elo}}},
        "travelMode": "TRANSIT",
        "departureTime": departure_iso,  # 顶层字段, RFC3339
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Goog-Api-Key": key,
                 "X-Goog-FieldMask": "routes.duration,routes.distanceMeters"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    routes = d.get("routes") or []
    if not routes or "duration" not in routes[0]:
        return None
    return math.ceil(float(routes[0]["duration"].rstrip("s")) / 60)


def transit_minutes_address(key, origin_addr, ela, elo, departure_iso):
    body = {
        "origin": {"address": origin_addr},
        "destination": {"location": {"latLng": {"latitude": ela, "longitude": elo}}},
        "travelMode": "TRANSIT",
        "departureTime": departure_iso,  # 顶层字段, RFC3339
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Goog-Api-Key": key,
                 "X-Goog-FieldMask": "routes.duration,routes.distanceMeters"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    routes = d.get("routes") or []
    if not routes or "duration" not in routes[0]:
        return None
    return math.ceil(float(routes[0]["duration"].rstrip("s")) / 60)


def main():
    key = env("GOOGLE_MAPS_API_KEY")
    v2 = {r["listing_id"]: r for r in csv.DictReader(open(V2, encoding="utf-8-sig"))}

    # 下一个工作日 08:30 新加坡时间 (UTC+8), RFC3339
    day = datetime.now(timezone.utc) + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    dep = datetime(day.year, day.month, day.day, 8, 30, tzinfo=timezone(timedelta(hours=8)))
    departure_iso = dep.isoformat()
    print(f"出发时间: {departure_iso}", flush=True)

    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8-sig")))
    fac_names = [f["name"] for f in FACULTIES]
    n = 0
    for r in rows:
        if r["listing_id"] not in UNRELIABLE:
            continue
        # 2026-10: OneMap 给这两盘的坐标点在 AYE 高道南侧, 步行接驳绕路;
        # 改用地址文本作起点, Google 解析到小区正确位置 (App 同款 20 分钟)
        origin_addr = f"{v2[r['listing_id']]['address'].split(',')[0]}, Singapore"
        for di, fname in enumerate(fac_names):
            if r["faculty"] != fname:
                continue
            f = FACULTIES[di]
            try:
                v = transit_minutes_address(key, origin_addr, f["latitude"], f["longitude"], departure_iso)
            except Exception as e:
                print(f"  {r['listing_id']} -> {fname[:30]}: 出错 {e}", flush=True)
                time.sleep(2)
                continue
            if v is not None:
                r["minutes"], r["mode"] = str(v), "transit_google"
                n += 1
                print(f"  {r['listing_id']} -> {fname[:32]}: {v} 分钟", flush=True)
            else:
                print(f"  {r['listing_id']} -> {fname[:30]}: 无公交方案", flush=True)
            time.sleep(0.3)

    tmp = CSV_PATH.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    tmp.replace(CSV_PATH)
    print(f"写回 {n} 行 (mode=transit_google)", flush=True)


if __name__ == "__main__":
    main()
