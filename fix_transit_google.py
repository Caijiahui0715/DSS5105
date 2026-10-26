# -*- coding: utf-8 -*-
"""
Recompute the 32 commutes of the UNRELIABLE_TRANSIT listings with the Google Routes API (Compute Routes, TRANSIT).
Departure = the next weekday at 08:30 (Singapore time), as for OneMap.
The results replace these 32 rows in commute_faculty.csv, with mode=transit_google.
Usage: .venv/Scripts/python.exe fix_transit_google.py
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
        "departureTime": departure_iso,  # a top-level field, RFC3339
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
        "departureTime": departure_iso,  # a top-level field, RFC3339
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

    # The next weekday at 08:30 Singapore time (UTC+8), RFC3339
    day = datetime.now(timezone.utc) + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    dep = datetime(day.year, day.month, day.day, 8, 30, tzinfo=timezone(timedelta(hours=8)))
    departure_iso = dep.isoformat()
    print(f"Departure: {departure_iso}", flush=True)

    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8-sig")))
    fac_names = [f["name"] for f in FACULTIES]
    n = 0
    for r in rows:
        if r["listing_id"] not in UNRELIABLE:
            continue
        # 2026-10: OneMap puts these two developments' coordinates south of the AYE expressway, so the walk
        # to transit takes a long detour; the address text as the start lets Google place them correctly (20 min, as in its app)
        origin_addr = f"{v2[r['listing_id']]['address'].split(',')[0]}, Singapore"
        for di, fname in enumerate(fac_names):
            if r["faculty"] != fname:
                continue
            f = FACULTIES[di]
            try:
                v = transit_minutes_address(key, origin_addr, f["latitude"], f["longitude"], departure_iso)
            except Exception as e:
                print(f"  {r['listing_id']} -> {fname[:30]}: failed {e}", flush=True)
                time.sleep(2)
                continue
            if v is not None:
                r["minutes"], r["mode"] = str(v), "transit_google"
                n += 1
                print(f"  {r['listing_id']} -> {fname[:32]}: {v} min", flush=True)
            else:
                print(f"  {r['listing_id']} -> {fname[:30]}: no public transport route", flush=True)
            time.sleep(0.3)

    tmp = CSV_PATH.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    tmp.replace(CSV_PATH)
    print(f"Wrote back {n} rows (mode=transit_google)", flush=True)


if __name__ == "__main__":
    main()
