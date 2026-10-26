# -*- coding: utf-8 -*-
"""
Recompute the commutes of the UNRELIABLE_TRANSIT listings with the Google Routes API walking matrix.
OneMap's walking network lacks the paths inside gated developments such as Normanton Park and gives
detours of around 7 km; Google's network has the internal roads, so its results are close to reality.
The results are written back to commute_faculty.csv with mode=walk_google.
Usage: .venv/Scripts/python.exe fix_unreliable_commutes.py   (needs GOOGLE_MAPS_API_KEY in .env)
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
    """The walking matrix of origins × destinations in one request: {(oi, di): (minutes, meters)}."""
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
        raise SystemExit(".env is missing GOOGLE_MAPS_API_KEY. Add it and run again.")

    # The listed listings' coordinates
    v2 = {r["listing_id"]: r for r in csv.DictReader(open(V2, encoding="utf-8-sig"))}
    origins = []
    for lid in UNRELIABLE:
        r = v2[lid]
        origins.append((float(r["latitude"]), float(r["longitude"])))

    dests = [(f["latitude"], f["longitude"]) for f in FACULTIES]
    fac_names = [f["name"] for f in FACULTIES]

    print(f"Asking Google for the walking matrix: {len(origins)} listings x {len(dests)} faculties ...", flush=True)
    matrix = google_walk_matrix(key, origins, dests)

    # Print and check
    for oi, lid in enumerate(UNRELIABLE):
        for di, fname in enumerate(fac_names):
            res = matrix.get((oi, di))
            if res:
                print(f"  {lid} -> {fname[:30]}: {res[0]} min ({res[1]} m)", flush=True)
            else:
                print(f"  {lid} -> {fname[:30]}: no route from Google either", flush=True)

    # Write back to the CSV
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
    print(f"Wrote back {n} rows (mode=walk_google) -> {CSV_PATH.name}", flush=True)


if __name__ == "__main__":
    main()
