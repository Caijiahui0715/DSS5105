"""Turn the team's case files into the evaluation case set.

Input:  evaluation/source/DSS5105_47_Gold_Answers.json (received 2026-11-02,
        built on the 10/23 430-row data snapshot): 47 cases.
        evaluation/source/DSS5105_Additional_ABC_8_Queries.xlsx (received
        2026-11-05): A11-A14, B07, B08, C07, C08. Their queries and faculty
        settings are copied into NEW_ABC below, with the edits listed there;
        the Chinese columns of that file are unreadable (stored garbled).
        G06-G09 were added on 2026-11-05 (NEW_G below).
Output: evaluation/cases/cases.json        all 59 cases, with dev/holdout split
        evaluation/cases/holdout_manifest.json   holdout IDs + SHA-256

This script only reshapes questions and rules. It does not compute any
listing sets: those come from gold.py against the frozen data. Listing IDs and
counts in the source file are deliberately dropped, because they were computed
on an older snapshot.

Run once; rerunning with the same source reproduces the same split.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "source" / "DSS5105_47_Gold_Answers.json"
OUT_CASES = HERE / "cases" / "cases.json"
OUT_MANIFEST = HERE / "cases" / "holdout_manifest.json"

# Holdout (decided 2026-11-05). Only cases never run on the agent:
# - the 12 cases added on 2026-11-05 (A11-A14, B07, B08, C07, C08, G06-G09);
# - the D, E, F and H cases of the first seeded split (none were run on the agent).
# The first split's A-C holdout cases (A04, A05, A06, A10, B04, B06, C03, C06) and
# every G01-G05 case were run on the agent before the freeze, so they are dev.
HOLDOUT = {"A11", "A12", "A13", "A14", "B07", "B08", "C07", "C08", "G06", "G07", "G08", "G09",
           "D01", "D04", "E01", "E02", "F02", "F05", "H01", "H02"}
SPLIT_RULE = "fixed list: cases never run on the agent before the freeze (build_cases.HOLDOUT)"

CATEGORY_NAMES = {
    "A": "A_explicit_requirements",
    "B": "B_missing_field",
    "C": "C_no_solution_or_relaxation",
    "D": "D_ambiguous_request",
    "E": "E_not_in_data",
    "F": "F_out_of_scope_action",
    "G": "G_multi_turn_update",
    "H": "H_provenance_and_comparison",
}

# Listing used as conversation context for E/F questions that say "this
# property". Active in the frozen snapshot; also used by H02/H04.
CONTEXT_LISTING = "500074659"

# Faculty for G cases that need a commute destination but had none
# (the same faculty the agent run of 2026-11-05 registered for them).
G_FACULTY = "Faculty of Science"

# Per-turn hard constraints for the G cases. The source file gave only listing
# sets for these, so the profiles are written out here from the queries; see
# CONVENTIONS.md section 4 for the reasoning.
G_PROFILES = {
    "G01": [
        {"max_price_sgd": 1500, "rental_scope": "room", "ranking_priority": ["commute"]},
        {"max_price_sgd": 1800, "rental_scope": "room", "ranking_priority": ["commute"]},
    ],
    "G02": [
        {"max_price_sgd": 1600, "rental_scope": "room", "ranking_priority": ["price"]},
        {"max_price_sgd": 1600, "rental_scope": "room", "ranking_priority": ["commute", "price"]},
    ],
    "G03": [
        {"rental_scope": "room", "cooking_required": True, "air_conditioning_required": True},
        {"rental_scope": "room", "air_conditioning_required": True},
    ],
    "G04": [
        {"max_price_sgd": 3000, "rental_scope": "entire_unit"},
        {"max_price_sgd": 3000},
    ],
    "G05": [
        {"max_price_sgd": 1800, "ranking_priority": ["commute"]},
        {"max_price_sgd": 1500, "max_commute_minutes": 30, "ranking_priority": ["commute"]},
    ],
}

G_MUST = {
    "G01": ["Raise the budget to SGD 1,800 in turn 2", "Keep room scope from turn 1"],
    "G02": ["Keep the SGD 1,600 cap in turn 2", "Rank by commute first in turn 2; rent may rise"],
    "G03": ["Drop the cooking requirement in turn 2", "Keep air-conditioning as a hard requirement"],
    "G04": ["Keep the SGD 3,000 cap in turn 2", "Add room rentals to the results in turn 2"],
    "G05": ["Lower the cap to SGD 1,500 in turn 2", "Apply a 30-minute commute limit in turn 2"],
}
G_MUST_NOT = {
    "G01": ["Forget that the user wants a room"],
    "G02": ["Change the budget in turn 2"],
    "G03": ["Drop air-conditioning together with cooking"],
    "G04": ["Drop the budget when widening the scope"],
    "G05": ["Keep listings above SGD 1,500 after turn 2"],
}

# A-C cases from DSS5105_Additional_ABC_8_Queries.xlsx. Edits to the received
# wording are in "changes"; they keep each case testing what its category tests
# on the frozen data.
NEW_ABC = [
    {"id": "A11", "faculty": None,
     "user": "Find me an entire unit in D21 with at least 2 bedrooms and a monthly rent of no more than SGD 5,000. Rank all eligible listings by lower rent first.",
     "profile": {"max_price_sgd": 5000, "rental_scope": "entire_unit", "district_code": "D21", "min_bedrooms": 2, "ranking_priority": ["price"]},
     "must": ["Return only entire units in D21 with at least 2 bedrooms at or below SGD 5,000", "Rank the confirmed listings by rent, lowest first"],
     "must_not": ["Return room rentals or listings outside D21", "Treat a listing with an unknown bedroom count as confirmed"],
     "changes": ["budget SGD 4,200 -> 5,000: no listing met the received query (cheapest match was SGD 4,300)"]},
    {"id": "A12", "faculty": None,
     "user": "I am a male student looking for a furnished room for no more than SGD 1,500 per month. The room must accept male tenants, and the landlord must not live in the same home.",
     "profile": {"max_price_sgd": 1500, "rental_scope": "room", "tenant_gender": "male", "furnished_required": True, "landlord_not_living_in": True},
     "must": ["Exclude female-only rooms and rooms whose landlord lives in", "Treat male-only and no-restriction rooms as gender-compatible",
              "Mark rooms with an unstated gender rule, furnishing or landlord arrangement as needing confirmation"],
     "must_not": ["Treat an unstated gender rule as confirmed", "Treat an unstated landlord arrangement as not living in"],
     "changes": []},
    {"id": "A13", "faculty": None,
     "user": "Find me a room for no more than SGD 2,200 per month with air-conditioning. It must be within a 10-minute walk of an operating MRT station. Rank the eligible rooms by shorter MRT walk first, then lower rent.",
     "profile": {"max_price_sgd": 2200, "rental_scope": "room", "air_conditioning_required": True, "max_mrt_minutes": 10, "ranking_priority": ["mrt", "price"]},
     "must": ["Require air-conditioning and a walk of 10 minutes or less to an operating station", "Rank by MRT walk, then rent"],
     "must_not": ["Count a station under construction or of unknown status as operating"],
     "changes": ["private bathroom requirement removed: only 3 of 369 listings state one, so no room was confirmed"]},
    {"id": "A14", "faculty": "School of Computing",
     "user": "I need a room for no more than SGD 1,800 per month and can sign a 12-month lease. My public-transport commute to my faculty must not exceed 40 minutes. Rank suitable rooms by shorter faculty commute first, then lower rent.",
     "profile": {"max_price_sgd": 1800, "rental_scope": "room", "lease_months": 12, "max_commute_minutes": 40, "ranking_priority": ["commute", "price"]},
     "must": ["Use School of Computing commute data", "Treat a listing's stated term as its minimum accepted lease", "Rank by faculty commute, then rent"],
     "must_not": ["Use MRT walking time as the faculty commute", "Assume an unstated lease accepts 12 months"],
     "changes": []},
    {"id": "B07", "faculty": None,
     "user": "Find me a fully furnished room for no more than SGD 1,600 per month. Separate listings that explicitly confirm they are fully furnished from otherwise eligible listings whose furnishing level is not stated. Exclude listings explicitly described as partially furnished or unfurnished, and do not treat unknown furnishing information as fully furnished.",
     "profile": {"max_price_sgd": 1600, "rental_scope": "room", "furnishing_level": "full"},
     "must": ["List explicitly fully furnished rooms as confirmed", "List rooms whose furnishing level is not stated as needing confirmation",
              "Exclude partially furnished and unfurnished rooms"],
     "must_not": ["Treat unknown or unspecified furnishing as fully furnished"],
     "changes": []},
    {"id": "B08", "faculty": None,
     "user": "I need a room for no more than SGD 1,800 per month and I can sign only a 6-month lease. Separate listings that explicitly accept a 6-month lease from otherwise eligible listings whose lease term is not stated. Exclude listings that explicitly require more than 6 months, and do not treat an unknown lease term as confirmed acceptance of a 6-month lease.",
     "profile": {"max_price_sgd": 1800, "rental_scope": "room", "lease_months": 6},
     "must": ["Treat Flexible and Short Term leases as accepting 6 months", "Mark rooms with an unstated lease term as needing confirmation",
              "Exclude rooms whose stated minimum lease is 1 or 2 years"],
     "must_not": ["Treat an unstated lease term as accepting 6 months"],
     "changes": ["removed 'or flexible-looking' from the last sentence: CONVENTIONS.md counts Flexible as accepting any length"]},
    {"id": "C07", "faculty": None,
     "user": "I need a room in D10 for no more than SGD 1,000 per month. If there is no strict match, keep my original criteria unchanged and identify the smallest evidence-based adjustment that produces at least one candidate. Change only one requirement at a time.",
     "profile": {"max_price_sgd": 1000, "rental_scope": "room", "district_code": "D10"},
     "relaxation_field": "max_price_sgd",
     "must": ["State that the strict set is empty", "Offer {relaxation} as the smallest single change", "Keep room scope and D10 fixed in that option"],
     "must_not": ["Return over-budget rooms as strict matches", "Change two requirements at once"],
     "changes": ["private bathroom requirement removed: with it no single change produced a match"]},
    {"id": "C08", "faculty": "Faculty of Science",
     "user": "Find me an entire unit with at least 2 bedrooms for no more than SGD 4,000 and a public-transport commute of no more than 15 minutes to my faculty. If no exact match exists, do not silently relax the criteria. Test one condition at a time and recommend the smallest supported change, such as a higher budget or a longer commute limit.",
     "profile": {"max_price_sgd": 4000, "rental_scope": "entire_unit", "min_bedrooms": 2, "max_commute_minutes": 15},
     "relaxation_field": ["max_commute_minutes", "max_price_sgd"],
     "must": ["State that the strict set is empty", "Report the single changes tested: {relaxation}", "Use Faculty of Science commute data"],
     "must_not": ["Silently relax the criteria", "Change budget and commute together"],
     "changes": []},
]
NEW_ABC_TYPE = {"A": "listing_filter_and_rank", "B": "listing_filter_and_rank", "C": "no_match_and_relaxation"}

# G cases added 2026-11-05; each tests an update type G01-G05 do not.
NEW_G = [
    {"id": "G06", "turns": [
        ("I'm looking for a room for no more than SGD 1,400 a month. Show the cheapest first.",
         {"max_price_sgd": 1400, "rental_scope": "room", "ranking_priority": ["price"]}),
        ("I also need air-conditioning, and the landlord must not live in the same home. Keep my budget.",
         {"max_price_sgd": 1400, "rental_scope": "room", "air_conditioning_required": True, "landlord_not_living_in": True, "ranking_priority": ["price"]})],
     "must": ["Add air-conditioning and no live-in landlord in turn 2", "Keep the SGD 1,400 cap and the rent-first order",
              "Mark rooms with unstated air-con or landlord arrangement as needing confirmation"],
     "must_not": ["Drop the budget in turn 2"]},
    {"id": "G07", "turns": [
        ("Find me an entire unit in D05 with at least 2 bedrooms for no more than SGD 5,500.",
         {"max_price_sgd": 5500, "rental_scope": "entire_unit", "district_code": "D05", "min_bedrooms": 2}),
        ("Actually, search in D03 instead of D05. Everything else stays the same.",
         {"max_price_sgd": 5500, "rental_scope": "entire_unit", "district_code": "D03", "min_bedrooms": 2})],
     "must": ["Replace D05 with D03 in turn 2", "Keep entire unit, at least 2 bedrooms and SGD 5,500"],
     "must_not": ["Search D05 and D03 together in turn 2"]},
    {"id": "G08", "turns": [
        ("I need a room for no more than SGD 1,200 a month.", {"max_price_sgd": 1200, "rental_scope": "room"}),
        ("Let me raise the budget to SGD 1,600.", {"max_price_sgd": 1600, "rental_scope": "room"}),
        ("Sorry, go back to my original budget, but now cooking must be allowed.",
         {"max_price_sgd": 1200, "rental_scope": "room", "cooking_required": True})],
     "must": ["Raise the cap to SGD 1,600 in turn 2", "Return to SGD 1,200 in turn 3 and add the cooking requirement"],
     "must_not": ["Keep the SGD 1,600 cap in turn 3"]},
    {"id": "G09", "turns": [
        ("Show me entire units for no more than SGD 4,000, cheapest first.",
         {"max_price_sgd": 4000, "rental_scope": "entire_unit", "ranking_priority": ["price"]}),
        ("Now rank them by larger floor area first. The budget stays the same.",
         {"max_price_sgd": 4000, "rental_scope": "entire_unit", "ranking_priority": ["space", "price"]})],
     "must": ["Keep the same confirmed set in turn 2", "Rank by floor area, largest first, in turn 2"],
     "must_not": ["Turn 'larger area' into a new filter"]},
]
G_GOLD_ANSWER = "Apply the latest turn while preserving every unchanged hard constraint; rerank only when the stated priority changes."

H_FIELDS = {
    "H01": ["rent_monthly_sgd", "rent_monthly_sgd_now"],
    "H02": ["rent_monthly_sgd", "rent_monthly_sgd_now", "mrt_distance_m"],
    "H03": ["cooking_policy", "rental_scope"],
    "H04": ["rent_monthly_sgd", "rent_monthly_sgd_now", "mrt_distance_m", "furnishing", "cooking_policy"],
}

# C-case "must" items in the source quoted numbers from the old snapshot.
# Replace them with templates that gold.py fills from the recomputed relaxation.
C_MUST = {
    "C01": ["State that the strict set is empty", "Identify budget as the relaxed field",
            "Offer {relaxation} as the evidence-backed next step and keep D05/common-room constraints"],
    "C02": ["Report zero exact matches", "Recommend {relaxation} as one option",
            "Keep scope, D03 and bedroom count unchanged in that option"],
    "C03": ["State no listing meets the 2-minute limit", "Suggest {relaxation} as the verified relaxation",
            "Keep budget, district and scope fixed"],
    "C04": ["Use Faculty of Science from the test account", "Report the strict set as empty",
            "Offer {relaxation} as the verified relaxation while retaining budget and room scope"],
    "C05": ["State that the strict query has no match", "Offer {relaxation} as the verified compromise",
            "Keep whole-unit, bedrooms and budget unchanged"],
    "C06": ["Report no confirmed 6-month match", "Say whether a longer lease solves it: {relaxation}",
            "Keep whole-unit scope, D22, bedrooms and budget fixed"],
}


def canonical_hash(obj) -> str:
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build() -> list[dict]:
    src = json.loads(SOURCE.read_text(encoding="utf-8"))["answers"]
    cases = []
    for a in src:
        cid = a["case_id"]
        cat = cid[0]
        changes: list[str] = []
        pre = {"faculty": (a.get("preconditions") or {}).get("faculty"), "prior_turns": []}
        case = {
            "id": cid,
            "category": CATEGORY_NAMES[cat],
            "split": None,
            "preconditions": pre,
            "turns": [],
            "expected_behavior": a.get("expected_behavior"),
            "gold_answer_type": a.get("gold_answer_type"),
            "gold_answer": a.get("gold_answer"),
            "must": a.get("must") or [],
            "must_not": a.get("must_not") or [],
            "relaxation_field": None,
            "fields": None,
            "author": "",
            "verified_by": "",
            "changes_from_source": changes,
        }
        if cat in "ABC":
            case["turns"] = [{"user": a["query"], "gold_profile": a["gold_profile"]}]
            if cat == "C":
                case["relaxation_field"] = a["relaxation"]["target_field"]
                case["must"] = C_MUST[cid]
                changes.append("must items rewritten as templates; numbers now come from gold.py")
        elif cat == "G":
            profiles = G_PROFILES[cid]
            case["turns"] = [{"user": t["query"], "gold_profile": p} for t, p in zip(a["queries"], profiles)]
            case["must"] = G_MUST[cid] + ["Apply the latest turn while keeping every unchanged hard constraint"]
            case["must_not"] = G_MUST_NOT[cid]
            changes.append("per-turn gold_profile written out (source had listing sets only)")
            if cid in ("G01", "G02", "G05"):
                pre["faculty"] = G_FACULTY
                changes.append(f"faculty precondition set to {G_FACULTY} so commute can be ranked")
        else:
            case["turns"] = [{"user": t["query"], "gold_profile": None} for t in a["queries"]]
            if cat in "EF":
                pre["prior_turns"] = [f"Tell me about listing {CONTEXT_LISTING}."]
                changes.append(f"prior turn added so 'this property' refers to listing {CONTEXT_LISTING}")
            if cat == "H":
                case["fields"] = {lid: H_FIELDS[cid] for lid in a["listing_facts"]}
                case["must"] = ["Cite the listing IDs", "Quote values that match the snapshot",
                                "Separate snapshot facts from current availability"]
                case["must_not"] = ["Invent a value that is not in the snapshot"]
                changes.append("facts now recomputed by gold.py from the frozen snapshot")
        cases.append(case)
    cases += new_cases()
    return sorted(cases, key=lambda c: c["id"])


def blank(cid: str, faculty) -> dict:
    return {"id": cid, "category": CATEGORY_NAMES[cid[0]], "split": None,
            "preconditions": {"faculty": faculty, "prior_turns": []}, "turns": [],
            "expected_behavior": "answer", "gold_answer_type": None, "gold_answer": None,
            "must": [], "must_not": [], "relaxation_field": None, "fields": None,
            "author": "", "verified_by": "", "changes_from_source": []}


def new_cases() -> list[dict]:
    out = []
    for n in NEW_ABC:
        c = blank(n["id"], n["faculty"])
        c.update(turns=[{"user": n["user"], "gold_profile": n["profile"]}], gold_answer_type=NEW_ABC_TYPE[n["id"][0]],
                 must=n["must"], must_not=n["must_not"], relaxation_field=n.get("relaxation_field"),
                 changes_from_source=["added from DSS5105_Additional_ABC_8_Queries.xlsx (2026-11-05)"] + n["changes"])
        out.append(c)
    for n in NEW_G:
        c = blank(n["id"], None)
        c.update(turns=[{"user": u, "gold_profile": p} for u, p in n["turns"]], gold_answer_type="multi_turn_profile_update",
                 gold_answer=G_GOLD_ANSWER,
                 must=n["must"] + ["Apply the latest turn while keeping every unchanged hard constraint"], must_not=n["must_not"],
                 changes_from_source=["new case written on 2026-11-05 from the frozen data"])
        out.append(c)
    return out


def split(cases: list[dict]) -> None:
    ids = {c["id"] for c in cases}
    assert HOLDOUT <= ids, HOLDOUT - ids
    for c in cases:
        c["split"] = "holdout" if c["id"] in HOLDOUT else "dev"


def hashed_view(case: dict) -> dict:
    """The parts of a case that must not change after the holdout is sealed."""
    keys = ("id", "category", "preconditions", "turns", "expected_behavior", "must", "must_not", "relaxation_field", "fields")
    return {k: case[k] for k in keys}


def main() -> None:
    cases = build()
    assert len(cases) == 59, len(cases)
    split(cases)
    OUT_CASES.write_text(json.dumps({"case_count": len(cases), "split_rule": SPLIT_RULE, "cases": cases},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    hold = sorted((c for c in cases if c["split"] == "holdout"), key=lambda c: c["id"])
    manifest = {
        "sealed_on": "2026-11-05",
        "split_rule": SPLIT_RULE,
        "holdout_ids": [c["id"] for c in hold],
        "holdout_count": len(hold),
        "dev_count": len(cases) - len(hold),
        "holdout_sha256": canonical_hash([hashed_view(c) for c in hold]),
        "hash_method": "sha256 of compact sorted-key JSON of hashed_view() for holdout cases sorted by id",
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_CASES.relative_to(HERE.parent)} ({len(cases)} cases, {len(hold)} holdout)")
    print(f"holdout sha256 {manifest['holdout_sha256']}")


if __name__ == "__main__":
    main()
