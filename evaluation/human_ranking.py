"""Build the human-ranking form from the recomputed gold.

Output: evaluation/human_ranking/form.csv  what reviewers see (import into Google Form)
        evaluation/human_ranking/key.csv   hidden: listing IDs, sampling source, gold rank

Fixes relative to source/Google_Form_Human_Ranking_20.csv:
- candidates come from the frozen snapshot only (no delisted listings);
- the fields a query ranks on are always shown (faculty commute, food places,
  MRT status), plus the faculty used for commute;
- G cases show both turns, so "keep my other requirements" has context;
- cases with fewer than 3 confirmed matches (B04) and the relaxation cases
  (C03, C04, which have no strict matches) are left out;
- near-duplicate listings (same title, rent, area and room type) are not shown together;
- cases with fewer than 5 confirmed matches get fewer candidates instead of
  being padded with non-matches.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLD = HERE / "gold" / "gold_answers.json"
CASES = HERE / "cases" / "cases.json"
OUT_FORM = HERE / "human_ranking" / "form.csv"
OUT_KEY = HERE / "human_ranking" / "key.csv"

CANDIDATES = [
    "A01", "A02", "A04", "A05", "A06", "A08", "A09", "A10",
    "B01", "B02", "B03", "B06",
    "G01", "G02", "G03", "G04", "G05",
]
MIN_CANDIDATES = 3
MAX_CANDIDATES = 5

FRIENDLY = {
    "light_cooking": "light cooking only", "cooking_any_cooking": "any cooking", "cooking_not_allowed": "no cooking",
    "not_allowed": "no cooking", "cooking_prefer_not_to_say": "not stated", "unknown": "not stated",
    "fully_furnished": "fully furnished", "partially_furnished": "partially furnished",
    "furnished_unspecified": "furnished (level not stated)", "unfurnished": "unfurnished",
    "no_restriction": "any gender", "female_only": "female only", "male_only": "male only",
    "no_pets": "no pets", "pets_allowed": "pets allowed",
    "common_room": "common room", "master_room": "master room", "room_unspecified": "room (type not stated)",
    "shared_room": "shared room", "entire_unit": "entire unit", "room": "room",
    "yes": "yes", "no": "no",
}


def f(v):
    if v is None:
        return "not stated"
    return FRIENDLY.get(v, str(v).replace("_", " "))


def describe(c: dict, profile: dict, faculty: str | None) -> str:
    parts = [f"SGD {c['rent_sgd']:,.0f}/month", c["district_code"] or "district not stated"]
    kind = f(c["rental_scope"])
    if c["rental_scope"] == "room":
        kind = f(c["room_type"]) if c["room_type"] not in (None, "unknown") else "room (type not stated)"
    parts.append(f"{kind}, {c['property_type'] or 'property type not stated'}")
    if c["rental_scope"] == "entire_unit":
        parts.append(f"{c['bedrooms']:.0f} bedrooms" if c["bedrooms"] is not None else "bedrooms not stated")
        parts.append(f"{c['bathrooms']:.0f} bathrooms" if c["bathrooms"] is not None else "bathrooms not stated")
    parts.append(f"{c['area_sqm']:.0f} sqm" if c["area_sqm"] is not None else "area not stated")
    if c["mrt_minutes"] is not None:
        mrt = f"{c['mrt_minutes']:.0f} min walk to {c['mrt_station'] or 'MRT'}"
        if c["mrt_operation_status"] != "operational":
            mrt += f" ({f(c['mrt_operation_status'])} station)"
        parts.append(mrt)
    else:
        parts.append("MRT walk not stated")
    if faculty:
        m = c["faculty_commute_minutes"]
        parts.append(f"{m:.0f} min commute to {faculty}" if m is not None else f"commute to {faculty} not available")
    prio = profile.get("ranking_priority") or []
    if "food_places" in prio or "min_food_places" in profile:
        parts.append(f"{c['food_places_1km']:.0f} food places within 1 km")
    if c["rental_scope"] == "room":
        parts += [f"cooking: {f(c['cooking_policy'])}", f"landlord lives in: {f(c['landlord_lives_in'])}",
                  f"tenant gender: {f(c['gender_restriction'])}"]
    parts += [f"furnishing: {f(c['furnishing'])}", f"air-con: {f(c['air_conditioning'])}",
              f"lease: {c['lease_term'] or 'not stated'}"]
    return "; ".join(parts)


def dup_key(c):
    return (c["title"], c["rent_sgd"], c["area_sqm"], c["room_type"])


def pick(case_id: str, ranked: list[str], summaries: dict[str, dict]) -> list[tuple[str, str, int]]:
    """Top 3 by gold rank, the cheapest remaining, one seeded random; skip near-duplicates."""
    rng = random.Random(f"DSS5105-human-{case_id}-2026-11-05")
    gold_rank = {lid: i + 1 for i, lid in enumerate(ranked)}
    chosen: list[tuple[str, str]] = []
    seen = set()

    def add(lid, source):
        k = dup_key(summaries[lid])
        if lid in [x for x, _ in chosen] or k in seen:
            return False
        chosen.append((lid, source)); seen.add(k)
        return True

    for lid in ranked:
        if len([s for _, s in chosen if s == "gold_top3"]) >= 3:
            break
        add(lid, "gold_top3")
    rest = [lid for lid in ranked if lid not in [x for x, _ in chosen]]
    for lid in sorted(rest, key=lambda x: (summaries[x]["rent_sgd"], x)):
        if add(lid, "cheapest_remaining"):
            break
    rest = [lid for lid in rest if lid not in [x for x, _ in chosen]]
    rng.shuffle(rest)
    for lid in rest:
        if len(chosen) >= MAX_CANDIDATES:
            break
        add(lid, "random_confirmed")
    rng.shuffle(chosen)
    return [(lid, src, gold_rank[lid]) for lid, src in chosen]


def main():
    gold = {a["case_id"]: a for a in json.loads(GOLD.read_text(encoding="utf-8"))["answers"]}
    cases = {c["id"]: c for c in json.loads(CASES.read_text(encoding="utf-8"))["cases"]}
    # Same loader and summary as gold.py, so the form shows exactly the gold values.
    from gold import load, summary
    df, commute = load()
    idx = df.set_index("listing_id")
    form_rows, key_rows, skipped = [], [], []
    for cid in CANDIDATES:
        g, case = gold[cid], cases[cid]
        turn = g["turns"][-1]
        faculty = case["preconditions"].get("faculty")
        ranked = turn["confirmed_ids_ranked"]
        if len(ranked) < MIN_CANDIDATES:
            skipped.append((cid, len(ranked)))
            continue
        summaries = {lid: summary(lid, idx, faculty, commute) for lid in ranked}
        picks = pick(cid, ranked, summaries)
        if len(case["turns"]) > 1:
            query = " | ".join(f"Turn {i}: {t['user']}" for i, t in enumerate(case["turns"], 1))
        else:
            query = case["turns"][0]["user"]
        if faculty:
            query += f"  [The user studies at: {faculty}]"
        labels = "ABCDE"
        row = {"Case ID": cid, "Query": query, "Number of candidates": len(picks)}
        for i in range(MAX_CANDIDATES):
            row[f"Candidate {labels[i]}"] = ""
        for i, (lid, src, rank) in enumerate(picks):
            row[f"Candidate {labels[i]}"] = f"{labels[i]}. {summaries[lid]['title']} - " + describe(summaries[lid], turn["gold_profile"], faculty)
            key_rows.append({"Case ID": cid, "Label": labels[i], "Listing ID": lid, "Sampling source": src,
                             "Gold rank among confirmed": rank, "Confirmed total": len(ranked),
                             "Order fully set by user": "yes" if turn["gold_profile"].get("ranking_priority") else "no"})
        row["Rank scale"] = "|".join(str(n) for n in range(1, len(picks) + 1)) + " (1 = best)"
        form_rows.append(row)
    OUT_FORM.parent.mkdir(exist_ok=True)
    with OUT_FORM.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(form_rows[0].keys()))
        w.writeheader(); w.writerows(form_rows)
    with OUT_KEY.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(key_rows[0].keys()))
        w.writeheader(); w.writerows(key_rows)
    print(f"wrote {len(form_rows)} cases to {OUT_FORM.name}, key to {OUT_KEY.name}")
    for cid, n in skipped:
        print(f"skipped {cid}: only {n} confirmed matches")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(HERE))
    main()
