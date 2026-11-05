#!/usr/bin/env python3
"""Build the unified 47-case Gold set and the 20-case human-ranking pack.

This script combines the independently generated A-C gold answers with the
team's D-H gold workbook.  It does not call the rental Agent.  The output is a
reproducible evaluation reference, plus a five-candidate pack for human ranking.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


ROOT = Path(__file__).resolve().parent
PROJECT = Path(r"E:\nus classes\dss5105\Capstone-project\Capstone Project")
AC_WORKBOOK = PROJECT / "A-C_22_queries_agent_answers_and_human11.xlsx"
DH_QUERY_WORKBOOK = PROJECT / "DEFGH_Queries_Updated.xlsx"
DH_GOLD_WORKBOOK = PROJECT / "DSS5105_DEFGH_Gold_Answers_Excel.xlsx"
LISTINGS_CSV = Path(r"E:\nus classes\dss5105\Capstone-project\Final_project\DSS5105\output-final-delivery\rental_data_v2.csv")
AC_GOLD_JSON = ROOT / "gold_answers.json"

OUT_JSON = ROOT / "DSS5105_47_Gold_Answers.json"
OUT_XLSX = ROOT / "DSS5105_47_Gold_Answers_and_Human20.xlsx"
OUT_FORM_CSV = ROOT / "Google_Form_Human_Ranking_20.csv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def norm_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def num(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def load_listings() -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    with LISTINGS_CSV.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_id = {norm_id(row["listing_id"]): row for row in rows}
    by_title: dict[str, list[str]] = defaultdict(list)
    for lid, row in by_id.items():
        by_title[row.get("title", "").strip().lower()].append(lid)
    return by_id, by_title


def read_ac_queries_and_answers() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
    query_rows = {}
    wb = load_workbook(AC_WORKBOOK, read_only=True, data_only=True)
    ws = wb["22 Queries and Answers"]
    headers = [str(v) for v in next(ws.iter_rows(values_only=True))]
    for values in ws.iter_rows(min_row=2, values_only=True):
        row = dict(zip(headers, values))
        query_rows[str(row["ID"])] = row
    gold = json.loads(AC_GOLD_JSON.read_text(encoding="utf-8-sig"))
    return {x["id"]: x for x in gold["answers"]}, query_rows


def read_dh_queries() -> dict[str, dict[str, Any]]:
    wb = load_workbook(DH_QUERY_WORKBOOK, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    headers = [str(x) for x in rows[0]]
    grouped: dict[str, dict[str, Any]] = {}
    for values in rows[1:]:
        row = dict(zip(headers, values))
        cid = str(row.get("Case ID") or "").strip()
        if not cid:
            continue
        item = grouped.setdefault(cid, {"id": cid, "category": cid[0], "turns": []})
        raw_turn = row.get("Turn")
        turn = int(raw_turn) if raw_turn not in (None, "") else len(item["turns"]) + 1
        if any(existing["turn"] == turn for existing in item["turns"]):
            turn = len(item["turns"]) + 1
        item["turns"].append({"turn": turn, "query": str(row.get("English Query") or "").strip()})
    for item in grouped.values():
        item["turns"].sort(key=lambda x: x["turn"])
    return grouped


def read_dh_gold() -> tuple[dict[str, dict[str, Any]], dict[tuple[str, int], dict[str, list[str]]], dict[str, list[dict[str, Any]]]]:
    wb = load_workbook(DH_GOLD_WORKBOOK, read_only=True, data_only=True)
    overview: dict[str, dict[str, Any]] = {}
    ws = wb["Gold Overview"]
    headers = [str(v) for v in next(ws.iter_rows(values_only=True))]
    for values in ws.iter_rows(min_row=2, values_only=True):
        row = dict(zip(headers, values))
        overview[str(row["Case ID"])] = row
    sets: dict[tuple[str, int], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    ws = wb["Listing ID Sets"]
    next(ws.iter_rows(values_only=True))
    for cid, turn, set_name, lid in ws.iter_rows(min_row=2, values_only=True):
        sets[(str(cid), int(turn))][str(set_name)].append(norm_id(lid))
    facts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ws = wb["H Listing Facts"]
    next(ws.iter_rows(values_only=True))
    for cid, lid, field, value, review in ws.iter_rows(min_row=2, values_only=True):
        facts[str(cid)].append({"listing_id": norm_id(lid), "field": str(field), "value": value, "evidence_review_required": bool(review)})
    return overview, sets, facts


CLARIFY = {
    "D01": "Ask for a maximum monthly budget and an acceptable commute/location boundary before recommending listings.",
    "D02": "Clarify what 'pleasant' and 'quiet' mean using observable criteria; state that the dataset has no reliable ambience or noise field.",
    "D03": "Clarify whether the user wants an entire unit, a private room, or simply fewer housemates; do not assume privacy.",
    "D04": "Ask for the commute destination and maximum acceptable travel time; do not invent a faculty or time limit.",
    "D05": "Ask for budget and how the user trades rent against commute; do not silently choose weights for 'value for money'.",
}

UNKNOWN = {
    "E01": "Say that landlord personality is not verified in the dataset. Do not claim a landlord is friendly; suggest a viewing/call and concrete questions.",
    "E02": "Say that sound insulation and night noise are not reliably recorded. Do not promise quietness; suggest viewing at relevant hours and checking construction/traffic.",
    "E03": "Say that pest history is not verified. Do not claim pest-free; suggest inspection and asking for recent pest-control records.",
    "E04": "Say that exact monthly utilities cannot be calculated from the available listing data. Distinguish advertised rent from utilities and ask for bills/inclusion terms.",
    "E05": "Say that landlord-entry behaviour is not verified. Do not predict conduct; advise checking the tenancy agreement, notice clause and speaking with current tenants.",
    "E06": "Explain that deposit deductions depend on the actual contract and evidence. Do not guarantee a refund; advise inventory photos, receipts and written clauses.",
}

DECLINE = {
    "F01": "State that the system cannot contact the landlord or negotiate. It may draft a message and list negotiation points, but must not claim contact occurred.",
    "F02": "State that the system cannot book a viewing. It may provide the listing link and a viewing-request template, but must not claim a booking.",
    "F03": "State that the system cannot transfer a deposit or reserve a unit. Warn against payment before identity, ownership and contract checks.",
    "F04": "State that the system cannot sign a tenancy agreement or accept terms. It may provide a checklist and flag clauses for review.",
    "F05": "Provide decision support and trade-offs, but leave the final decision and any external action to the user; do not claim to proceed.",
}


def compact_listing(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "listing_id": norm_id(row.get("listing_id")),
        "title": row.get("title"),
        "rent_sgd": num(row.get("rent_monthly_sgd_now")) or num(row.get("rent_monthly_sgd")),
        "district": row.get("district_code"),
        "scope": row.get("rental_scope"),
        "room_type": row.get("room_type"),
        "property_type": row.get("property_type"),
        "mrt_minutes": num(row.get("mrt_minutes_reported")),
        "mrt_distance_m": num(row.get("mrt_distance_m")),
        "bedrooms": num(row.get("bedrooms")),
        "bathrooms": num(row.get("bathrooms")),
        "area_sqm": num(row.get("area_sqm")),
        "gender_restriction": row.get("gender_restriction"),
        "cooking_policy": row.get("cooking_policy"),
        "furnishing": row.get("furnishing"),
        "landlord_lives_in": row.get("landlord_lives_in"),
        "private_bathroom": row.get("private_bathroom"),
        "air_conditioning": row.get("air_conditioning"),
        "pets_policy": row.get("pets_policy"),
        "lease_term": row.get("lease_term"),
        "listing_url": row.get("listing_url"),
    }


def rank_g(case_id: str, turn: int, ids: list[str], by_id: dict[str, dict[str, Any]]) -> list[str]:
    def key(lid: str):
        row = by_id.get(lid, {})
        rent = num(row.get("rent_monthly_sgd_now")) or num(row.get("rent_monthly_sgd")) or 10**9
        mrt = num(row.get("mrt_minutes_reported")) or 10**9
        if case_id == "G02" and turn == 2:
            return (mrt, rent, lid)
        return (rent, mrt, lid)
    return sorted([lid for lid in ids if lid in by_id], key=key)


def build_gold() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[tuple[str, int], dict[str, list[str]]], dict[str, dict[str, Any]]]:
    by_id, _ = load_listings()
    ac_gold, ac_rows = read_ac_queries_and_answers()
    dh_queries = read_dh_queries()
    overview, sets, facts = read_dh_gold()
    answers: list[dict[str, Any]] = []
    for cid in sorted(ac_gold):
        item = dict(ac_gold[cid])
        item["case_id"] = item.pop("id")
        item["turn_count"] = 1
        item["gold_answer_type"] = "listing_filter_and_rank" if cid[0] in "AB" else "no_match_and_relaxation"
        item["observed_agent_answer"] = ac_rows[cid].get("Agent answer summary")
        answers.append(item)
    for cid in sorted(dh_queries):
        q = dh_queries[cid]
        base: dict[str, Any] = {
            "case_id": cid,
            "category": cid[0],
            "turn_count": len(q["turns"]),
            "queries": q["turns"],
            "expected_behavior": overview[cid].get("Expected Behavior"),
        }
        if cid in CLARIFY:
            base.update(gold_answer_type="clarification", gold_answer=CLARIFY[cid], listing_sets=None)
        elif cid in UNKNOWN:
            base.update(gold_answer_type="missing_information", gold_answer=UNKNOWN[cid], listing_sets=None)
        elif cid in DECLINE:
            base.update(gold_answer_type="scope_boundary", gold_answer=DECLINE[cid], listing_sets=None)
        elif cid.startswith("G"):
            turns = []
            for turn in q["turns"]:
                t = turn["turn"]
                s = sets[(cid, t)]
                ranked = rank_g(cid, t, s.get("pass", []), by_id)
                turns.append({
                    "turn": t,
                    "query": turn["query"],
                    "confirmed_count": len(s.get("pass", [])),
                    "needs_confirmation_count": len(s.get("unknown", [])),
                    "excluded_count": len(s.get("fail", [])),
                    "confirmed_ids": s.get("pass", []),
                    "needs_confirmation_ids": s.get("unknown", []),
                    "gold_ranked_top_5": [compact_listing(by_id[x]) for x in ranked[:5]],
                })
            base.update(gold_answer_type="multi_turn_profile_update", gold_answer="Apply the latest turn while preserving every unchanged hard constraint; rerank only when the stated priority changes.", turns_gold=turns)
        else:
            grouped: dict[str, dict[str, Any]] = defaultdict(dict)
            for fact in facts[cid]:
                grouped[fact["listing_id"]][fact["field"]] = fact["value"]
            base.update(
                gold_answer_type="fixed_listing_fact_or_comparison",
                gold_answer="Answer only from the structured snapshot facts, cite the listing IDs and distinguish snapshot evidence from current availability.",
                listing_facts=grouped,
                evidence_review_required=True,
            )
        answers.append(base)
    assert len(answers) == 47, len(answers)
    return answers, ac_gold, sets, by_id


HUMAN20 = [
    "A01", "A02", "A04", "A05", "A06", "A08", "A09", "A10",
    "B01", "B02", "B03", "B04", "B06", "C03", "C04",
    "G01", "G02", "G03", "G04", "G05",
]

# C03 and C04 are deliberately evaluated as relaxation scenarios.  Their
# candidate sets include concrete listings exposed by the tested relaxations,
# so human reviewers can still rank 3-5 alternatives rather than rank an empty
# strict-result set.
C_RELAXATION_CANDIDATES = {
    "C03": ["25122875", "25024041", "23614828", "500299696", "24926395"],
    "C04": ["60151578", "500211006", "500203570", "500297851", "24689163"],
}


def human_candidates(case_id: str, ac_gold: dict[str, dict[str, Any]], sets: dict[tuple[str, int], dict[str, list[str]]], by_id: dict[str, dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    rng = random.Random(f"DSS5105-{case_id}-2026")
    if case_id.startswith(("A", "B")):
        item = ac_gold[case_id]
        pool = list(item.get("confirmed_ids", []))
        if not pool:
            pool = list(item.get("needs_confirmation_ids", []))
        ranked = [x["listing_id"] for x in item.get("top_3", []) if x.get("listing_id") in by_id]
        turn = 1
    elif case_id.startswith("C"):
        turn = 1
        pool = [x for x in C_RELAXATION_CANDIDATES[case_id] if x in by_id]
        ranked = pool[:3]
    else:
        turn = 2
        pool = list(sets[(case_id, turn)].get("pass", []))
        ranked = rank_g(case_id, turn, pool, by_id)[:3]
    # Composition: three criterion-ranked items, cheapest remaining baseline,
    # and one deterministic random strict match.  De-duplicate and refill.
    chosen: list[tuple[str, str]] = []
    for lid in ranked[:3]:
        if lid in by_id and lid not in [x[0] for x in chosen]:
            chosen.append((lid, "criterion_top3"))
    remaining = [x for x in pool if x in by_id and x not in [y[0] for y in chosen]]
    remaining.sort(key=lambda lid: (num(by_id[lid].get("rent_monthly_sgd_now")) or 10**9, lid))
    if remaining:
        chosen.append((remaining.pop(0), "rent_baseline"))
    if remaining:
        chosen.append((rng.choice(remaining), "random_strict_match"))
    for lid in remaining:
        if len(chosen) >= 5:
            break
        if lid not in [x[0] for x in chosen]:
            chosen.append((lid, "strict_match_refill"))
    candidates = []
    shuffled = chosen[:5]
    rng.shuffle(shuffled)
    for idx, (lid, source) in enumerate(shuffled):
        data = compact_listing(by_id[lid])
        data["label"] = chr(65 + idx)
        data["sampling_source"] = source
        candidates.append(data)
    return turn, candidates


def style(ws, widths: list[int]) -> None:
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width


def write_outputs() -> None:
    answers, ac_gold, sets, by_id = build_gold()
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_count": 47,
        "turn_count": sum(int(x["turn_count"]) for x in answers),
        "human_ranking_case_count": 20,
        "candidate_count_per_case": 5,
        "candidate_sampling": "criterion-ranked top 3 + cheapest remaining strict match + deterministic random remaining strict match; de-duplicated and shuffled",
        "sources": {
            "ac_gold": str(AC_GOLD_JSON),
            "ac_gold_sha256": sha256(AC_GOLD_JSON),
            "dh_queries": str(DH_QUERY_WORKBOOK),
            "dh_queries_sha256": sha256(DH_QUERY_WORKBOOK),
            "dh_gold": str(DH_GOLD_WORKBOOK),
            "dh_gold_sha256": sha256(DH_GOLD_WORKBOOK),
            "listings": str(LISTINGS_CSV),
            "listings_sha256": sha256(LISTINGS_CSV),
        },
        "limitations": [
            "D-H workbook labels its gold status exploratory/manual review; this combined file preserves that limitation.",
            "H source facts are snapshot facts and require original-evidence review.",
            "For G cases, criterion-ranked top 3 are gold-script ranks, not captured live Agent outputs.",
        ],
    }
    payload = {"metadata": metadata, "answers": answers}
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    answer_by_id = {x["case_id"]: x for x in answers}
    wb = Workbook()
    ws = wb.active
    ws.title = "47 Gold Overview"
    ws.append(["Case ID", "Category", "Turn count", "Gold answer type", "Query / turns", "Gold answer / rule", "Confirmed counts", "Needs-confirmation counts", "Evidence caveat"])
    for item in answers:
        if item["case_id"].startswith(("A", "B", "C")):
            query_text = item.get("query", "")
            rule = "; ".join(item.get("must", [])) or str(item.get("gold_spec", ""))
            counts = item.get("counts", {})
            confirmed = str(counts.get("confirmed", ""))
            unknown = str(counts.get("needs_confirmation", ""))
        elif item["case_id"].startswith("G"):
            query_text = "\n".join(f"Turn {x['turn']}: {x['query']}" for x in item["queries"])
            rule = item["gold_answer"]
            confirmed = ", ".join(str(x["confirmed_count"]) for x in item["turns_gold"])
            unknown = ", ".join(str(x["needs_confirmation_count"]) for x in item["turns_gold"])
        else:
            query_text = "\n".join(f"Turn {x['turn']}: {x['query']}" for x in item.get("queries", []))
            rule = item.get("gold_answer", "")
            confirmed = unknown = ""
        caveat = "Snapshot/original evidence review required" if item["case_id"].startswith("H") else ""
        ws.append([item["case_id"], item["category"], item["turn_count"], item["gold_answer_type"], query_text, rule, confirmed, unknown, caveat])
    style(ws, [10, 10, 12, 30, 75, 95, 20, 24, 38])

    human = wb.create_sheet("Human Ranking 20")
    human.append(["Case ID", "Turn", "Query", "Candidate", "Listing ID", "Title", "Rent SGD", "District", "Scope / room type", "MRT min", "Bedrooms", "Bathrooms", "Area sqm", "Sampling source (hide from reviewers)", "Listing URL"])
    form_rows = []
    for cid in HUMAN20:
        item = answer_by_id[cid]
        turn, candidates = human_candidates(cid, ac_gold, sets, by_id)
        if cid.startswith(("A", "B", "C")):
            query = item.get("query", "")
        else:
            query = next(x["query"] for x in item["queries"] if x["turn"] == turn)
        for c in candidates:
            human.append([cid, turn, query, c["label"], c["listing_id"], c["title"], c["rent_sgd"], c["district"], f"{c['scope']} / {c['room_type']}", c["mrt_minutes"], c["bedrooms"], c["bathrooms"], c["area_sqm"], c["sampling_source"], c["listing_url"]])
        option_texts = []
        for c in candidates:
            details = [f"SGD {c['rent_sgd']:.0f}" if c["rent_sgd"] is not None else "rent unknown"]
            if c["district"]:
                details.append(c["district"])
            if c["scope"] or c["room_type"]:
                details.append(" / ".join(str(x) for x in (c["scope"], c["room_type"]) if x))
            if c["property_type"]:
                details.append(str(c["property_type"]))
            if c["mrt_minutes"] is not None:
                details.append(f"{c['mrt_minutes']:.0f} min to MRT")
            if c["bedrooms"] is not None:
                details.append(f"{c['bedrooms']:.0f} bedrooms")
            if c["area_sqm"] is not None:
                details.append(f"{c['area_sqm']:.2f} sqm")
            for label, key in (
                ("furnishing", "furnishing"), ("air-con", "air_conditioning"),
                ("cooking", "cooking_policy"), ("landlord lives in", "landlord_lives_in"),
                ("gender", "gender_restriction"), ("private bathroom", "private_bathroom"),
                ("pets", "pets_policy"), ("lease", "lease_term"),
            ):
                value = c.get(key)
                if value is not None and str(value).strip() and str(value).strip().lower() != "nan":
                    details.append(f"{label}: {value}")
            option_texts.append(f"{c['label']}. {c['title']} ({c['listing_id']}) — " + "; ".join(details))
        form_rows.append({"case_id": cid, "turn": turn, "query": query, "candidates": option_texts})
    style(human, [10, 8, 72, 12, 16, 42, 14, 12, 24, 12, 12, 12, 12, 30, 55])

    instructions = wb.create_sheet("Human Form Instructions")
    instructions.append(["Item", "Instruction"])
    instructions.append(["Recommended number", "Use 5 candidates per query. This is enough to distinguish ranking quality without creating the fatigue of 8 candidates × 20 queries."])
    instructions.append(["Candidate mix", "Three criterion-ranked candidates, one rent-low baseline candidate, and one deterministic random strict match; de-duplicated and shuffled as A-E."])
    instructions.append(["Reviewer task", "For each query, rank A-E from 1 (best) to 5 (worst). Use each rank exactly once. Judge only from the stated query and displayed snapshot facts."])
    instructions.append(["Do not show", "Hide the Sampling source column from reviewers. It is retained only for auditability."])
    instructions.append(["Important limitation", "The four selected G cases use the Gold Script's criterion ranking as the top-3 component because no captured live Agent output was supplied in the teammate workbooks. Replace these with live Agent top 3 before the final system-vs-human comparison if available."])
    style(instructions, [28, 120])

    wb.save(OUT_XLSX)
    with OUT_FORM_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Case ID", "Turn", "Query", "Candidate A", "Candidate B", "Candidate C", "Candidate D", "Candidate E", "Form question type", "Rank columns"])
        for row in form_rows:
            writer.writerow([row["case_id"], row["turn"], row["query"], *row["candidates"], "Multiple-choice grid", "1 (best)|2|3|4|5 (worst)"])
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_XLSX}")
    print(f"Wrote {OUT_FORM_CSV}")


if __name__ == "__main__":
    write_outputs()
