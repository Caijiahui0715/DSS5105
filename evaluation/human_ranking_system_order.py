"""How the frozen system ranks the candidates of the four replacement questions; no model, no cost.

The replacement questions (A08, A09, B01, G04) use candidates picked from the gold answer, so the
agent never ranked all of them: it shows only its top 3. Like check_search.py, this gives each case's
gold_profile straight to the system's search and ranking, and reads off where each candidate lands
among the system's confirmed listings.

Output: human_ranking/v6_final/system_order.csv, read by analyze_human_ranking.py. Kept apart from
that script so the analysis itself imports no system code.

Run from the repository root (needs the test database, like check_search.py):
    .venv/Scripts/python.exe evaluation/human_ranking_system_order.py
"""

import csv
import json
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from decision import search_with_unknowns  # noqa: E402
from mock_db import create_database  # noqa: E402
from models import SearchPreferences  # noqa: E402
from tools import rank_listings  # noqa: E402

HR = ROOT / "evaluation" / "human_ranking"
OUT = HR / "v6_final" / "system_order.csv"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    cases = {c["id"]: c for c in json.loads((ROOT / "evaluation" / "cases" / "cases.json").read_text(encoding="utf-8"))["cases"]}
    key = list(csv.DictReader((HR / "v6_replacement" / "key.csv").open(encoding="utf-8-sig")))
    rows = []
    with closing(create_database()) as connection:
        for case_id in sorted({r["Case ID"] for r in key}):
            case = cases[case_id]
            profile = case["turns"][-1]["gold_profile"]
            usable = {k: v for k, v in profile.items() if k in SearchPreferences.model_fields}
            preferences = SearchPreferences.model_validate({**usable, "faculty": case["preconditions"].get("faculty")})
            strict, _ = search_with_unknowns(connection, preferences)
            ranked = [item["listing"]["listing_id"] for item in rank_listings(strict, preferences)]
            for r in (r for r in key if r["Case ID"] == case_id):
                position = ranked.index(r["Listing ID"]) + 1 if r["Listing ID"] in ranked else ""
                rows.append({"Case ID": case_id, "Label": r["Label"], "Listing ID": r["Listing ID"],
                             "System rank among confirmed": position, "System confirmed total": len(ranked),
                             "Gold rank among confirmed": r["Gold rank among confirmed"]})
                print(case_id, r["Label"], r["Listing ID"], "system", position, "of", len(ranked), "| gold", r["Gold rank among confirmed"])
    with OUT.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
