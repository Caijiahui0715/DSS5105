"""The system's search and ranking against the gold answers on the dev set; no model, no cost.

    .venv/Scripts/python.exe evaluation/check_search.py

Each turn's gold_profile goes straight to the system, so a difference is in search or ranking rather
than in understanding the user. The order counts only when the user stated priorities (CONVENTIONS.md
section 5). Holdout cases are never run.
"""

import json
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from decision import search_with_unknowns
from mock_db import create_database
from models import SearchPreferences
from tools import analyze_relaxations, rank_listings


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    data = json.loads((ROOT / "evaluation" / "cases" / "cases.json").read_text(encoding="utf-8"))
    cases = data["cases"] if "cases" in data else list(data.values())
    answers = json.loads((ROOT / "evaluation" / "gold" / "gold_answers.json").read_text(encoding="utf-8"))["answers"]
    gold = {answer["case_id"]: answer for answer in answers}
    turns = confirmed_same = pending_same = ordered = order_same = relaxed = relaxed_same = 0
    with closing(create_database()) as connection:
        for case in cases:
            if case["split"] != "dev":
                continue
            for answer in gold[case["id"]]["turns"]:
                profile = answer.get("gold_profile")
                if not profile:
                    continue
                turns += 1
                usable = {key: value for key, value in profile.items() if key in SearchPreferences.model_fields}
                preferences = SearchPreferences.model_validate({**usable, "faculty": case["preconditions"].get("faculty")})
                strict, pending = search_with_unknowns(connection, preferences)
                ranked = [item["listing"]["listing_id"] for item in rank_listings(strict, preferences)]
                top = [item["listing_id"] for item in answer["top_3"]]
                problems = []
                if set(ranked) == set(answer["confirmed_ids_ranked"]):
                    confirmed_same += 1
                else:
                    problems.append(
                        f"confirmed system {len(ranked)}, gold {len(answer['confirmed_ids_ranked'])}: "
                        f"extra {sorted(set(ranked) - set(answer['confirmed_ids_ranked']))[:3]}, "
                        f"missing {sorted(set(answer['confirmed_ids_ranked']) - set(ranked))[:3]}"
                    )
                if {listing["listing_id"] for listing in pending} == {item["listing_id"] for item in answer["needs_confirmation"]}:
                    pending_same += 1
                else:
                    problems.append(f"needs confirmation system {len(pending)}, gold {len(answer['needs_confirmation'])}")
                if profile.get("ranking_priority"):
                    ordered += 1
                    if ranked[:3] == top:
                        order_same += 1
                    else:
                        problems.append(f"order {profile['ranking_priority']}: system {ranked[:3]}, gold {top}")
                # The smallest change to the field the case names (CONVENTIONS.md section 6).
                if answer.get("relaxation"):
                    relaxed += 1
                    suggestions = {item["field"]: item for item in analyze_relaxations(connection, preferences)}
                    expected = answer["relaxation"]
                    suggestion = suggestions.get(expected["target_field"])
                    same = suggestion["suggested"] == expected["minimum_relaxed_value"] if suggestion else expected["minimum_relaxed_value"] is None
                    relaxed_same += same
                    if not same:
                        problems.append(f"relaxation of {expected['target_field']}: system {suggestion and suggestion['suggested']}, gold {expected['minimum_relaxed_value']}")
                if problems:
                    print(case["id"], f"turn {answer['turn']}:", "; ".join(problems))
    print(f"\n{turns} turns: confirmed sets same {confirmed_same}, needs-confirmation sets same {pending_same}")
    print(f"{ordered} with stated priorities: top 3 in the same order {order_same}")
    print(f"{relaxed} with a relaxation: same smallest change {relaxed_same}")


if __name__ == "__main__":
    main()
