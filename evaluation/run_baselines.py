"""Run baselines B1-B3 on the evaluation cases and save every turn in run_eval.py's format, so
score.py scores them the same way as the agent.

    .venv/Scripts/python.exe evaluation/run_baselines.py b1 b1-dev
    .venv/Scripts/python.exe evaluation/run_baselines.py b2 b2-dev
    .venv/Scripts/python.exe evaluation/run_baselines.py b3 b3-dev            # real model, costs money
    .venv/Scripts/python.exe evaluation/run_baselines.py b3 b3-holdout --holdout

B1 and B2 (baselines.py) need no model and no database. B3 gives the model the frozen listing data
as a table in its instructions and no tools, and keeps the conversation across turns. B4, the fixed
workflow, needs the system's database and runs from run_eval.py --system workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import baselines  # noqa: E402

RESULTS = HERE / "results"
SYSTEMS = {"b1": "B1_platform_filter", "b2": "B2_weighted_score", "b3": "B3_llm_no_tools"}

B3_INSTRUCTIONS = """You are a rental assistant for NUS students looking for a place to rent in Singapore.
You have no tools. Everything you know about listings is the table below (frozen listing data, last
refreshed on 2 November 2026); do not use outside knowledge about listings, and do not invent values.
You cannot contact landlords, book viewings, pay, sign or negotiate.

{faculty_line}

When the user asks for places to rent, recommend up to 3 listings from the table that meet every
requirement they stated, best first, ordered by what they said matters most (by rent when they did not
say). If the table does not state a field the user requires, you may still list the listing but mark it
as needs_confirmation and say what is unknown. If nothing meets the requirements, say so and suggest
the smallest single change that would find a listing. If the request is too vague to search, ask a
short question first. Answer other questions only from the table, and say when it does not have the
answer.

Answer with JSON only, in this shape:
{{"reply": "<your reply to the user>", "listings": [{{"listing_id": "<id>", "status": "match" or "needs_confirmation"}}]}}
"listings" holds the listings your reply recommends, in order; leave it empty when you recommend none.

Listing table (CSV; "unknown" means the data does not state it):
{table}"""

COLUMNS = [
    ("listing_id", "listing_id"), ("title", "title"), ("rental_scope", "rental_scope"), ("room_type", "room_type"),
    ("property_type", "property_type"), ("district_code", "district"), ("rent", "rent_sgd_latest"),
    ("rent_monthly_sgd", "rent_sgd_advertised"), ("rent_price_type", "rent_price_type"), ("area_sqm", "area_sqm"),
    ("area_scope", "area_scope"), ("bedrooms", "bedrooms"), ("bathrooms", "bathrooms"),
    ("private_bathroom", "private_bathroom"), ("furnishing", "furnishing"), ("air_conditioning", "air_conditioning"),
    ("cooking_policy", "cooking_policy"), ("gender_restriction", "gender_restriction"),
    ("landlord_lives_in", "landlord_lives_in"), ("lease_term", "lease_term"), ("pets_policy", "pets_policy"),
    ("mrt_station", "nearest_mrt"), ("mrt_operation_status", "mrt_status"), ("mrt_minutes_reported", "mrt_walk_min"),
    ("mrt_distance_m", "mrt_walk_m"), ("poi_fnb_1km", "food_places_1km"),
]


def cell(value) -> str:
    text = baselines.gold_rules.clean(value)
    if text is None or text == "":
        return "unknown"
    if isinstance(text, float):
        text = int(text) if text.is_integer() else round(text, 2)
    text = str(text)
    return f'"{text}"' if "," in text or '"' in text else text


def table(faculty: str | None) -> str:
    df, commute, _ = baselines.data()
    head = [name for _, name in COLUMNS] + (["commute_min_to_your_faculty"] if faculty else [])
    lines = [",".join(head)]
    for row in df.sort_values("listing_id").to_dict("records"):
        values = [cell(row[col]) for col, _ in COLUMNS]
        if faculty:
            minutes = commute.get((row["listing_id"], faculty))
            values.append("unknown" if minutes is None or minutes != minutes else str(round(minutes)))
        lines.append(",".join(values))
    return "\n".join(lines)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def header(system: str, split: str, model: str | None) -> dict:
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True).stdout.decode().strip()
    files = [HERE / "baselines.py", Path(__file__)]
    return {"meta": {
        "system": SYSTEMS[system], "split": split, "commit": commit,
        "baseline_code_sha256": hashlib.sha256(b"".join(f.read_bytes() for f in files)).hexdigest(),
        "model": model,
        "listings_sha256": sha256(ROOT / "output-final-delivery" / "rental_data_v2.csv"),
        "commute_sha256": sha256(ROOT / "commute_faculty.csv"),
        "cases_sha256": sha256(HERE / "cases" / "cases.json"),
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }}


def parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("system", choices=sorted(SYSTEMS))
    parser.add_argument("label")
    parser.add_argument("--only", default="")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--holdout", action="store_true")
    args = parser.parse_args()
    split = "holdout" if args.holdout else "dev"
    cases = [c for c in json.loads((HERE / "cases" / "cases.json").read_text(encoding="utf-8"))["cases"] if c["split"] == split]
    if args.only:
        cases = [c for c in cases if c["id"] in args.only.split(",")]

    client = model = None
    if args.system == "b3":
        from openai import OpenAI
        from config import env
        model = env("OPENAI_MODEL")
        client = OpenAI(api_key=env("OPENAI_API_KEY"))

    output = RESULTS / f"{args.label}.jsonl"
    if output.exists():
        raise SystemExit(f"{output} exists; use a new label")
    RESULTS.mkdir(exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        file.write(json.dumps(header(args.system, split, model), ensure_ascii=False) + "\n")
        for run in range(1, args.runs + 1):
            for number, case in enumerate(cases, 1):
                faculty = case["preconditions"].get("faculty")
                instructions = None
                if args.system == "b3":
                    line = (f"The user's NUS faculty is {faculty}; commute_min_to_your_faculty is the public-transport time to it (leaving 08:30 on a weekday)."
                            if faculty else "The user has not told you their NUS faculty, so there are no commute times.")
                    instructions = B3_INSTRUCTIONS.format(faculty_line=line, table=table(faculty))
                history = []
                prior = case["preconditions"].get("prior_turns", [])
                turns = [(m, None, True) for m in prior] + [(t["user"], t.get("gold_profile"), False) for t in case["turns"]]
                turn_number = 0
                for index, (message, profile, is_prior) in enumerate(turns):
                    turn_number += not is_prior
                    row = {"id": case["id"], "category": case["category"], "run": run, "turn": 0 if is_prior else turn_number,
                           "last_turn": index == len(turns) - 1, "user": message}
                    started = time.perf_counter()
                    try:
                        if args.system in ("b1", "b2"):
                            shown = getattr(baselines, args.system)(profile, faculty) if profile else []
                            used = profile and ({k: v for k, v in profile.items() if k in baselines.PLATFORM_FILTERS | {"ranking_priority"}}
                                                if args.system == "b1" else profile)
                            row.update({"reply": baselines.reply(args.system, profile, shown), "preferences": used or {},
                                        "shown": [{"listing_id": lid, "status": "match"} for lid in shown]})
                        else:
                            history.append({"role": "user", "content": message})
                            response = client.responses.create(model=model, instructions=instructions, input=history)
                            text = response.output_text
                            history.append({"role": "assistant", "content": text})
                            try:
                                answer = parse_json(text)
                                reply_text = str(answer.get("reply", ""))
                                shown = [{"listing_id": str(item.get("listing_id")),
                                          "status": "needs_confirmation" if item.get("status") == "needs_confirmation" else "match"}
                                         for item in answer.get("listings") or [] if isinstance(item, dict)]
                            except (ValueError, AttributeError):
                                reply_text, shown = text, []
                            usage = getattr(response, "usage", None)
                            row.update({"reply": reply_text, "preferences": {}, "shown": shown,
                                        "tokens": {"input": getattr(usage, "input_tokens", None), "output": getattr(usage, "output_tokens", None)}})
                        row.update({"preview": None, "comparison_ids": None, "tools": [], "tool_errors": 0, "guard": [], "trace": []})
                    except Exception as error:  # noqa: BLE001
                        row["error"] = f"{type(error).__name__}: {error}"[:500]
                    row["seconds"] = round(time.perf_counter() - started, 1)
                    file.write(json.dumps(row, ensure_ascii=False) + "\n")
                    file.flush()
                    print(f"[{number}/{len(cases)}] {case['id']} turn {row['turn']} {row.get('error') or [s['listing_id'] for s in row['shown']]} {row['seconds']}s", flush=True)
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
