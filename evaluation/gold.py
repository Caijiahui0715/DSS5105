"""Compute gold answers for the evaluation cases from the frozen snapshot.

Independent of the system on purpose: this file reads the CSV snapshot and the
commute cache with pandas and implements the rules in CONVENTIONS.md from
scratch. It must never import tools.py, decision.py, parser.py or agent.py,
otherwise a bug in the system would be copied into the answer key.

Inputs:  evaluation/cases/cases.json
         output-final-delivery/rental_data_v2.csv   (frozen 2026-11-02, 369 rows)
         commute_faculty.csv                        (OneMap commute cache)
Output:  evaluation/gold/gold_answers.json
         evaluation/gold/drift_vs_source.md         (what changed vs the received file)
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CASES = HERE / "cases" / "cases.json"
LISTINGS = ROOT / "output-final-delivery" / "rental_data_v2.csv"
COMMUTE = ROOT / "commute_faculty.csv"
SOURCE = HERE / "source" / "DSS5105_47_Gold_Answers.json"
OUT = HERE / "gold" / "gold_answers.json"
OUT_DRIFT = HERE / "gold" / "drift_vs_source.md"

PASS, UNKNOWN, FAIL = "pass", "unknown", "fail"
TOP_K = 3

COOK_ANY = {"light_cooking", "cooking_any_cooking", "allowed", "light_only"}
COOK_FULL = {"cooking_any_cooking", "allowed"}
COOK_NO = {"cooking_not_allowed", "not_allowed"}
FURNISHED = {"fully_furnished", "partially_furnished", "furnished_unspecified"}
LEASE_MONTHS = {"1 year": 12, "2 years": 24, "Short Term": 1, "Flexible": 0}


# --------------------------------------------------------------------------- data

def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):
        v = v.item()
    return v


def norm_type(v) -> str:
    return str(v or "").strip().lower().replace("-", "_").replace(" ", "_")


def load() -> tuple[pd.DataFrame, dict[tuple[str, str], float]]:
    df = pd.read_csv(LISTINGS, dtype={"listing_id": str})
    df["listing_id"] = df["listing_id"].str.replace(r"\.0$", "", regex=True)
    df["rent"] = df["rent_monthly_sgd_now"].fillna(df["rent_monthly_sgd"])
    df["ptype"] = df["property_type"].map(norm_type)
    c = pd.read_csv(COMMUTE, dtype={"listing_id": str}, encoding="utf-8-sig")
    commute = {(r.listing_id, r.faculty): float(r.minutes) for r in c.itertuples()}
    return df, commute


# --------------------------------------------------------------------------- rules

def mrt_rule(row, limit, col):
    """Walk to the nearest *operating* MRT must be <= limit.

    The data gives the nearest station of any status. If that station is
    operating, the value decides. If it is not (under construction / unknown)
    the nearest operating one is at least as far, so a value already above the
    limit is a fail and anything else is unknown.
    """
    v = clean(row[col])
    status = clean(row["mrt_operation_status"])
    if v is None:
        return UNKNOWN
    if v > limit:
        return FAIL
    return PASS if status == "operational" else UNKNOWN


def check(row, key, want, faculty, commute):
    """Return pass / unknown / fail for one hard constraint, or None if the key is not a filter."""
    scope = row["rental_scope"]
    if key == "max_price_sgd":
        v = clean(row["rent"])
        return UNKNOWN if v is None else (PASS if v <= want else FAIL)
    if key == "rental_scope":
        return PASS if scope == want else FAIL
    if key == "room_type":
        rt = row["room_type"]
        if scope != "room":
            return FAIL
        if rt == want:
            return PASS
        return UNKNOWN if rt in ("room_unspecified", "unknown") else FAIL
    if key == "district_code":
        return PASS if row["district_code"] == want else FAIL
    if key == "tenant_gender":
        g = row["gender_restriction"]
        own, other = (("female_only", "male_only") if want == "female" else ("male_only", "female_only"))
        if g in (own, "no_restriction"):
            return PASS
        return FAIL if g == other else UNKNOWN
    if key == "furnished_required":
        f = row["furnishing"]
        if f in FURNISHED:
            return PASS
        return FAIL if f == "unfurnished" else UNKNOWN
    if key == "furnishing_level":  # "fully furnished"; only "full" is used
        f = row["furnishing"]
        if f == "fully_furnished":
            return PASS
        return FAIL if f in ("partially_furnished", "unfurnished") else UNKNOWN
    if key in ("cooking_required", "cooking_level"):
        c = row["cooking_policy"]
        ok = COOK_FULL if (key == "cooking_level" and want == "full") else COOK_ANY
        if c in ok:
            return PASS
        if c in COOK_NO or c == "light_cooking":  # light_cooking only reaches here for "full"
            return FAIL
        return UNKNOWN
    if key == "air_conditioning_required":
        a = row["air_conditioning"]
        return PASS if a == "yes" else (FAIL if a == "no" else UNKNOWN)
    if key in ("min_bedrooms", "min_bathrooms"):
        v = clean(row["bedrooms" if key == "min_bedrooms" else "bathrooms"])
        return UNKNOWN if v is None else (PASS if v >= want else FAIL)
    if key == "max_mrt_minutes":
        return mrt_rule(row, want, "mrt_minutes_reported")
    if key == "max_mrt_distance_m":
        return mrt_rule(row, want, "mrt_distance_m")
    if key == "max_commute_minutes":
        v = commute.get((row["listing_id"], faculty)) if faculty else None
        return UNKNOWN if v is None else (PASS if v <= want else FAIL)
    if key == "property_types":
        return PASS if row["ptype"] in want else FAIL
    if key == "min_area_sqm":
        v = clean(row["area_sqm"])
        return UNKNOWN if v is None else (PASS if v >= want else FAIL)
    if key == "min_food_places":
        v = clean(row["poi_fnb_1km"])
        return UNKNOWN if v is None else (PASS if v >= want else FAIL)
    if key == "lease_months":
        term = clean(row["lease_term"])
        if term not in LEASE_MONTHS:
            return UNKNOWN
        return PASS if LEASE_MONTHS[term] <= want else FAIL
    if key == "landlord_not_living_in":
        v = row["landlord_lives_in"]
        return PASS if v == "no" else (FAIL if v == "yes" else UNKNOWN)
    if key == "pets_allowed_required":
        v = row["pets_policy"]
        return PASS if v == "pets_allowed" else (FAIL if v == "no_pets" else UNKNOWN)
    if key == "private_bathroom_required":
        v = row["private_bathroom"]
        return PASS if v == "yes" else (FAIL if v == "no" else UNKNOWN)
    return None  # ranking_priority, occupant_count: not filters (CONVENTIONS.md 3)


NOT_FILTERS = {"ranking_priority", "occupant_count"}


def evaluate(df, profile, faculty, commute):
    """Per-listing status for every hard constraint."""
    keys = [k for k in profile if k not in NOT_FILTERS]
    out = {}
    for row in df.to_dict("records"):
        out[row["listing_id"]] = {k: check(row, k, profile[k], faculty, commute) for k in keys}
    return out


def overall(statuses: dict[str, str]) -> str:
    vals = statuses.values()
    if FAIL in vals:
        return FAIL
    return UNKNOWN if UNKNOWN in vals else PASS


# --------------------------------------------------------------------------- ranking

def rank(ids, df_idx, priority, faculty, commute):
    """Strict lexicographic order on the stated priorities; missing values last; then rent, then id."""
    def value(lid, p):
        r = df_idx.loc[lid]
        if p == "price":
            v = clean(r["rent"])
        elif p == "commute":
            v = commute.get((lid, faculty)) if faculty else None
        elif p == "mrt":
            v = clean(r["mrt_minutes_reported"])
        elif p == "space":
            v = clean(r["area_sqm"]); v = None if v is None else -v
        elif p == "food_places":
            v = clean(r["poi_fnb_1km"]); v = None if v is None else -v
        else:
            raise ValueError(p)
        return (1, 0) if v is None else (0, v)

    order = list(priority or ["price"])
    if "price" not in order:
        order.append("price")
    return sorted(ids, key=lambda lid: tuple(value(lid, p) for p in order) + (lid,))


def summary(lid, df_idx, faculty, commute):
    r = df_idx.loc[lid]
    return {
        "listing_id": lid,
        "title": clean(r["title"]),
        "rent_sgd": clean(r["rent"]),
        "rent_monthly_sgd": clean(r["rent_monthly_sgd"]),
        "district_code": clean(r["district_code"]),
        "rental_scope": clean(r["rental_scope"]),
        "room_type": clean(r["room_type"]),
        "property_type": clean(r["property_type"]),
        "bedrooms": clean(r["bedrooms"]),
        "bathrooms": clean(r["bathrooms"]),
        "area_sqm": clean(r["area_sqm"]),
        "mrt_station": clean(r["mrt_station"]),
        "mrt_minutes": clean(r["mrt_minutes_reported"]),
        "mrt_distance_m": clean(r["mrt_distance_m"]),
        "mrt_operation_status": clean(r["mrt_operation_status"]),
        "food_places_1km": clean(r["poi_fnb_1km"]),
        "faculty_commute_minutes": commute.get((lid, faculty)) if faculty else None,
        "coord_source": clean(r["coord_source"]),
        "lease_term": clean(r["lease_term"]),
        "furnishing": clean(r["furnishing"]),
        "air_conditioning": clean(r["air_conditioning"]),
        "cooking_policy": clean(r["cooking_policy"]),
        "landlord_lives_in": clean(r["landlord_lives_in"]),
        "gender_restriction": clean(r["gender_restriction"]),
        "private_bathroom": clean(r["private_bathroom"]),
        "pets_policy": clean(r["pets_policy"]),
        "listing_url": clean(r["listing_url"]),
    }


# --------------------------------------------------------------------------- relaxation

RELAX_VALUE = {
    "max_price_sgd": lambda r, f, c: clean(r["rent"]),
    "max_mrt_minutes": lambda r, f, c: clean(r["mrt_minutes_reported"]),
    "max_mrt_distance_m": lambda r, f, c: clean(r["mrt_distance_m"]),
    "max_commute_minutes": lambda r, f, c: c.get((r["listing_id"], f)),
    "lease_months": lambda r, f, c: LEASE_MONTHS.get(clean(r["lease_term"])),
}
RELAX_LABEL = {
    "max_price_sgd": lambda v: f"a budget of SGD {v:,.0f}",
    "max_mrt_minutes": lambda v: f"a {v:.0f}-minute MRT walk",
    "max_mrt_distance_m": lambda v: f"a {v:,.0f} m MRT walk",
    "max_commute_minutes": lambda v: f"a {v:.0f}-minute commute limit",
    "lease_months": lambda v: f"a {v:.0f}-month lease",
}


def relaxation(df, statuses, profile, field, faculty, commute):
    """Smallest single change to `field` that yields at least one confirmed match.

    Only listings that pass every *other* constraint count. For the MRT fields
    the nearest station must also be operating, otherwise the relaxed value
    still would not be confirmed.
    """
    df_idx = df.set_index("listing_id")
    rows = []
    for lid, st in statuses.items():
        others = {k: v for k, v in st.items() if k != field}
        if overall(others) != PASS or st.get(field) != FAIL:
            continue
        r = df_idx.loc[lid].copy(); r["listing_id"] = lid
        if field in ("max_mrt_minutes", "max_mrt_distance_m") and r["mrt_operation_status"] != "operational":
            continue
        v = RELAX_VALUE[field](r, faculty, commute)
        if v is not None:
            rows.append((v, lid))
    result = {"target_field": field, "original_value": profile[field]}
    if not rows:
        alternatives = []
        for other in statuses[next(iter(statuses))]:
            if other == field:
                continue
            n = sum(1 for st in statuses.values() if overall({k: v for k, v in st.items() if k != other}) == PASS)
            if n:
                alternatives.append({"drop_field": other, "confirmed_if_dropped": n})
        result.update(single_field_relaxation_available=False, minimum_relaxed_value=None,
                      newly_confirmed_ids=[], label=f"no; changing {field} alone does not produce a confirmed match",
                      other_single_field_drops=alternatives)
        return result
    rows.sort()
    distinct = sorted({v for v, _ in rows})
    best = distinct[0]
    ladder = [{"value": v, "confirmed_total": sum(1 for x, _ in rows if x <= v)} for v in distinct[:4]]
    result.update(single_field_relaxation_available=True, minimum_relaxed_value=best,
                  newly_confirmed_ids=[lid for v, lid in rows if v == best],
                  ladder=ladder, label=RELAX_LABEL[field](best))
    return result


# --------------------------------------------------------------------------- per case

def gold_for_turn(df, commute, profile, faculty, relax_field=None):
    df_idx = df.set_index("listing_id")
    statuses = evaluate(df, profile, faculty, commute)
    confirmed = [lid for lid, st in statuses.items() if overall(st) == PASS]
    unknown = [lid for lid, st in statuses.items() if overall(st) == UNKNOWN]
    excluded = [lid for lid, st in statuses.items() if overall(st) == FAIL]
    priority = profile.get("ranking_priority")
    confirmed = rank(confirmed, df_idx, priority, faculty, commute)
    unknown = rank(unknown, df_idx, priority, faculty, commute)
    fail_counts: dict[str, int] = {}
    for st in statuses.values():
        for k, v in st.items():
            if v == FAIL:
                fail_counts[k] = fail_counts.get(k, 0) + 1
    out = {
        "gold_profile": profile,
        "ranking_order": list(priority or ["price"]) + ([] if "price" in (priority or ["price"]) else ["price"]),
        "counts": {"confirmed": len(confirmed), "needs_confirmation": len(unknown), "excluded": len(excluded)},
        "confirmed_ids_ranked": confirmed,
        "needs_confirmation": [
            {"listing_id": lid, "unknown_fields": [k for k, v in statuses[lid].items() if v == UNKNOWN]} for lid in unknown
        ],
        "excluded_failure_counts": dict(sorted(fail_counts.items())),
        "top_3": [summary(lid, df_idx, faculty, commute) for lid in confirmed[:TOP_K]],
    }
    if isinstance(relax_field, list):  # several fields, each tested on its own (C08)
        out["relaxation"] = [relaxation(df, statuses, profile, f, faculty, commute) for f in relax_field]
    elif relax_field:
        out["relaxation"] = relaxation(df, statuses, profile, relax_field, faculty, commute)
    return out


def h_facts(df, fields_by_listing):
    df_idx = df.set_index("listing_id")
    facts = {}
    for lid, fields in fields_by_listing.items():
        if lid not in df_idx.index:
            facts[lid] = {"present_in_snapshot": False}
            continue
        r = df_idx.loc[lid]
        facts[lid] = {"present_in_snapshot": True, "title": clean(r["title"]),
                      **{f: clean(r[f]) for f in fields}}
    return facts


def h_comparison(facts):
    ids = [k for k, v in facts.items() if v.get("present_in_snapshot")]
    if len(ids) != 2:
        return None
    a, b = ids
    out = {}
    ra = facts[a].get("rent_monthly_sgd_now") or facts[a].get("rent_monthly_sgd")
    rb = facts[b].get("rent_monthly_sgd_now") or facts[b].get("rent_monthly_sgd")
    if ra is not None and rb is not None:
        out["cheaper"] = a if ra < rb else b if rb < ra else "tie"
    da, db = facts[a].get("mrt_distance_m"), facts[b].get("mrt_distance_m")
    if da is not None and db is not None:
        out["closer_to_mrt"] = a if da < db else b if db < da else "tie"
    return out


def render_must(items, relax):
    if isinstance(relax, list):
        label = "; ".join(r["label"] for r in relax)
    else:
        label = relax["label"] if relax else ""
    return [m.replace("{relaxation}", label) for m in items]


def build():
    df, commute = load()
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    answers = []
    for case in cases:
        faculty = case["preconditions"].get("faculty")
        item = {"case_id": case["id"], "category": case["category"], "split": case["split"],
                "expected_behavior": case["expected_behavior"], "gold_answer_type": case["gold_answer_type"]}
        if case["turns"][0]["gold_profile"] is not None:
            turns = []
            for i, t in enumerate(case["turns"], 1):
                g = gold_for_turn(df, commute, t["gold_profile"], faculty, case.get("relaxation_field"))
                turns.append({"turn": i, "user": t["user"], **g})
            item["turns"] = turns
            relax = turns[-1].get("relaxation")
            item["must"] = render_must(case["must"], relax)
        else:
            item["turns"] = [{"turn": i, "user": t["user"]} for i, t in enumerate(case["turns"], 1)]
            item["must"] = case["must"]
            item["gold_answer"] = case.get("gold_answer")
            if case.get("fields"):
                facts = h_facts(df, case["fields"])
                item["listing_facts"] = facts
                item["comparison"] = h_comparison(facts)
        item["must_not"] = case["must_not"]
        answers.append(item)
    meta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "evaluation/gold.py",
        "git_head": git_head(),
        "listings_file": str(LISTINGS.relative_to(ROOT)).replace("\\", "/"),
        "listings_rows": len(df),
        "listings_sha256": file_sha256(LISTINGS),
        "commute_file": str(COMMUTE.relative_to(ROOT)).replace("\\", "/"),
        "commute_sha256": file_sha256(COMMUTE),
        "cases_sha256": file_sha256(CASES),
        "conventions": "evaluation/CONVENTIONS.md",
        "top_k": TOP_K,
    }
    return {"metadata": meta, "answers": answers}, df


# --------------------------------------------------------------------------- drift report

def drift_report(gold, df) -> str:
    src = {a["case_id"]: a for a in json.loads(SOURCE.read_text(encoding="utf-8"))["answers"]}
    active = set(df["listing_id"])
    lines = ["# Gold drift vs the received file", "",
             "Received file: `source/DSS5105_47_Gold_Answers.json` (430-row snapshot of 10/23).",
             f"New gold: `gold/gold_answers.json` ({len(df)}-row frozen snapshot of 11/02).", "",
             "| Case | Turn | Confirmed old → new | Needs confirmation old → new | Old IDs now delisted | Top-3 changed | Note |",
             "|---|---|---|---|---|---|---|"]
    for g in gold["answers"]:
        s = src.get(g["case_id"])
        if s is None:  # added after the received file (A11-A14, B07, B08, C07, C08, G06-G09)
            continue
        if "counts" in s:
            old_turns = [{"c": s["counts"]["confirmed"], "u": s["counts"]["needs_confirmation"],
                          "ids": s["confirmed_ids"] + s["needs_confirmation_ids"],
                          "top": [x["listing_id"] for x in s.get("top_3", [])], "relax": s.get("relaxation")}]
        elif "turns_gold" in s:
            old_turns = [{"c": t["confirmed_count"], "u": t["needs_confirmation_count"],
                          "ids": t["confirmed_ids"] + t["needs_confirmation_ids"],
                          "top": [x["listing_id"] for x in t["gold_ranked_top_5"][:3]], "relax": None} for t in s["turns_gold"]]
        else:
            continue
        for i, (o, n) in enumerate(zip(old_turns, g["turns"]), 1):
            gone = sum(1 for x in o["ids"] if x not in active)
            new_top = [x["listing_id"] for x in n["top_3"]]
            note = ""
            if o["relax"] and n.get("relaxation"):
                ov, nv = o["relax"].get("minimum_relaxed_value"), n["relaxation"].get("minimum_relaxed_value")
                if ov != nv:
                    note = f"relaxation {ov} → {nv}"
            lines.append(f"| {g['case_id']} | {i} | {o['c']} → {n['counts']['confirmed']} | {o['u']} → {n['counts']['needs_confirmation']} "
                         f"| {gone} | {'yes' if o['top'] != new_top else 'no'} | {note} |")
    return "\n".join(lines) + "\n"


def main():
    gold, df = build()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_DRIFT.write_text(drift_report(gold, df), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} and {OUT_DRIFT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
