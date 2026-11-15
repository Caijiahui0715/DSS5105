"""Score a run_eval.py result against the gold answers and the frozen data.

    .venv/Scripts/python.exe evaluation/score.py dev1

Prints the automatic metrics by category and writes results/<label>_review.md, which lists each turn
for reading, with the numbers that could not be traced to the data, and results/<label>_behaviour.csv,
the sheet for scoring behaviour, unless it is already there. Behaviour (metric 5) and ranking
quality (metric 7) are scored by people. This script uses only the result, the gold answers, gold.py
and the data files: it imports nothing from the system, so it cannot share the system's mistakes.
"""

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evaluation"))

import gold as gold_rules

RESULTS = ROOT / "evaluation" / "results"
# The behaviour sheet that people fill in; merge_behaviour.py reads the same columns.
SHEET_COLUMNS = ["case_id", "turn", "expected_behaviour", "user_message", "decision_score", "explanation_score", "rater", "note"]
ROOM_TYPES = {"common_room", "master_room", "shared_room", "room_unspecified"}

MONEY = re.compile(r"(?:S\$|SGD\s*|\$)\s*(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s*(万)?\s*(?:新元|新币|新加坡元|元)|(\d[\d,]*(?:\.\d+)?)\s*(?:SGD|dollars?)\b", re.IGNORECASE)
MINUTES = re.compile(r"(\d+(?:\.\d+)?)\s*(?:分钟|mins?\b|minutes?\b|-minute\b)", re.IGNORECASE)
COUNTS = re.compile(r"(?<![\d,.])(\d+)\s*(?:套|listings?\b|matches\b|homes?\b|rooms?\b|units?\b|results?\b|strict\b|whole\b)", re.IGNORECASE)
LISTING_ID = re.compile(r"(?<!\d)\d{8,9}(?!\d)")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# A total the reply states: "57 strict matches", "**4** strict room matches", "1 confirmed match".
STATED_TOTAL = re.compile(r"(\d[\d,]*)\*{0,2}\s+(?:strict|confirmed)(?:\s+[\w-]+)?\s+match", re.IGNORECASE)
# Fields that are saved but do not filter listings.
NOT_FILTERS = {"ranking_priority", "room_type_flexible", "move_in_flexible", "occupant_count", "faculty"}


def number(text) -> float | None:
    try:
        return float(str(text).replace(",", ""))
    except ValueError:
        return None


def priorities(values) -> list[str]:
    """Rent is the last comparison anyway, so a final "price" says nothing; 吃饭方便 means food places."""
    names = ["food_places" if name == "amenities" else name for name in (values or [])]
    return names[:-1] if names[-1:] == ["price"] else names


def same_value(field: str, gold, system, parsed: dict) -> bool:
    if field == "ranking_priority":
        return priorities(gold) == priorities(system)
    if field == "rental_scope":
        return str(system or "").casefold() == gold or (gold == "room" and parsed.get("room_type") in ROOM_TYPES)
    if field == "cooking_required":
        return bool(system) or parsed.get("cooking_level") in ("light", "full")
    if field == "furnished_required":
        return bool(system) or bool(parsed.get("furnishing_types"))
    # The system states full furnishing as the accepted levels, not as a level of its own.
    if field == "furnishing_level" and gold == "full":
        return list(parsed.get("furnishing_types") or []) == ["fully_furnished"]
    if field == "room_type":
        return str(gold).casefold() == str(system).strip().casefold().replace(" ", "_")
    if isinstance(gold, list):
        return sorted(map(str, gold)) == sorted(map(str, system or []))
    if isinstance(gold, (int, float)) and isinstance(system, (int, float)):
        return abs(gold - system) < 1e-6
    return str(gold).strip().casefold() == str(system).strip().casefold()


def recount(frame, commutes: dict, profile: dict, faculty: str | None) -> set[float]:
    """Counts and cheapest values the tools report, worked out here by the gold rules: what dropping
    each condition gives, the smallest limit with a match, and the confirmed listings by rental type."""
    statuses = gold_rules.evaluate(frame, profile, faculty, commutes)
    rows = frame.set_index("listing_id")
    found = set()
    for field in statuses[next(iter(statuses))]:
        without = [listing_id for listing_id, status in statuses.items() if gold_rules.overall({key: value for key, value in status.items() if key != field}) == gold_rules.PASS]
        found.add(float(len(without)))
        if field in gold_rules.RELAX_VALUE:
            values = []
            for listing_id in without:
                row = rows.loc[listing_id].copy()
                row["listing_id"] = listing_id
                if (value := gold_rules.RELAX_VALUE[field](row, faculty, commutes)) is not None:
                    values.append(float(value))
            found |= set(values)
    confirmed = [listing_id for listing_id, status in statuses.items() if gold_rules.overall(status) == gold_rules.PASS]
    for scope in ("room", "entire_unit"):
        kind = [listing_id for listing_id in confirmed if rows.loc[listing_id, "rental_scope"] == scope]
        found.add(float(len(kind)))
        if kind:
            found.add(float(rows.loc[kind, "rent"].min()))
    return found


def traceable_numbers(row: dict, turn: dict | None, listings: dict, commutes: dict, faculty: str | None, conversation: list[str]) -> set[float]:
    """What the data, the gold answer and the user's own words support for this reply."""
    allowed = {value for text in conversation for value in map(number, NUMBER.findall(text)) if value is not None}
    named = set(LISTING_ID.findall(row["reply"])) | {item["listing_id"] for item in row.get("shown", [])} | set(row.get("comparison_ids") or [])
    named |= set(LISTING_ID.findall(" ".join(conversation)))
    rents = set()
    for listing_id in named & listings.keys():
        data = listings[listing_id]
        for field in ("rent_monthly_sgd", "rent_monthly_sgd_now", "mrt_minutes_reported", "mrt_distance_m", "pg_mrt_nearest_walk_min"):
            if (value := number(data.get(field, ""))) is not None:
                allowed.add(value)
                allowed.add(round(value))
        for field in ("rent_monthly_sgd_now", "rent_monthly_sgd"):
            if (value := number(data.get(field, ""))) is not None:
                rents.add(value)
                break
        if faculty and (listing_id, faculty) in commutes:
            allowed.add(round(commutes[listing_id, faculty]))
            allowed.add(commutes[listing_id, faculty])
    if turn:
        allowed |= {float(value) for value in turn["counts"].values()}
        allowed.add(float(sum(turn["counts"].values())))
        relaxation = turn.get("relaxation") or {}
        for item in relaxation if isinstance(relaxation, list) else [relaxation]:
            allowed |= {float(step[key]) for step in item.get("ladder", []) for key in ("value", "confirmed_total")}
            if item.get("minimum_relaxed_value") is not None:
                allowed.add(float(item["minimum_relaxed_value"]))
    # Differences between rents, and from a budget the user gave: the system's tools state these.
    budget = (row.get("preferences") or {}).get("max_price_sgd")
    anchors = rents | ({float(budget)} if budget else set())
    allowed |= {abs(a - b) for a in anchors for b in anchors}
    # Each person's share, which the tools work out from the number of people.
    if people := (row.get("preferences") or {}).get("occupant_count"):
        allowed |= {rent / people for rent in rents} | {round(rent / people) for rent in rents}
    allowed |= {float(len(row.get("shown", [])))}
    return allowed


def claims(reply: str) -> list[tuple[str, float | str]]:
    found = []
    for first, second, wan, third in MONEY.findall(reply):
        value = number(first or second or third)
        if value is not None:
            found.append(("money", value * (10_000 if wan else 1)))
    found += [("minutes", float(value)) for value in MINUTES.findall(reply)]
    found += [("count", float(value)) for value in COUNTS.findall(reply)]
    found += [("id", value) for value in LISTING_ID.findall(reply)]
    return found


def compute(label: str) -> dict:
    """Every automatic metric of one result file, by category; compare_systems.py reads this too."""
    rows = [json.loads(line) for line in (RESULTS / f"{label}.jsonl").read_text(encoding="utf-8").splitlines()]
    meta = rows[0].get("meta", {})
    versions = [row["meta"] for row in rows if "meta" in row]
    # A case run again replaces its earlier rows. Prior turns share turn 0, so the message tells them apart.
    rows = list({(row["id"], row["run"], row["turn"], row["user"]): row for row in rows if "meta" not in row}.values())
    data = json.loads((ROOT / "evaluation" / "cases" / "cases.json").read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in (data["cases"] if "cases" in data else data.values())}
    gold = {item["case_id"]: item for item in json.loads((ROOT / "evaluation" / "gold" / "gold_answers.json").read_text(encoding="utf-8"))["answers"]}
    with open(ROOT / "output-final-delivery" / "rental_data_v2.csv", encoding="utf-8-sig", newline="") as file:
        listings = {row["listing_id"]: row for row in csv.DictReader(file)}
    frame, commutes = gold_rules.load()

    stats = defaultdict(lambda: defaultdict(float))
    review = [f"# {label}", "", *(f"Version: {json.dumps(version, ensure_ascii=False)}" for version in versions), ""]
    conversation = defaultdict(list)
    tops = {}
    for row in rows:
        case_key = (row["id"], row["run"])
        conversation[case_key].append(row["user"])
        if row["turn"] == 0:
            continue
        case, category = cases[row["id"]], row["category"][0]
        stat = stats[category]
        stat["turns"] += 1
        if "error" in row:
            stat["errors"] += 1
            review += [f"## {row['id']} turn {row['turn']}: error", "", row["error"], ""]
            continue
        answer = gold[row["id"]]["turns"][row["turn"] - 1] if gold[row["id"]]["turns"] else None
        profile = answer.get("gold_profile") if answer else None
        faculty = case["preconditions"].get("faculty")
        notes = []
        # Metric 1: parsing.
        parsed = row["preferences"]
        if profile:
            wrong = {field: parsed.get(field) for field, value in profile.items() if not same_value(field, value, parsed.get(field), parsed)}
            # Either field states the same requirement.
            implied = {"cooking_level", "cooking_required"} if profile.get("cooking_required") or profile.get("cooking_level") else set()
            implied |= {"furnishing_types", "furnished_required"} if profile.get("furnished_required") or profile.get("furnishing_level") else set()
            extra = {field: value for field, value in parsed.items() if field not in profile and field not in NOT_FILTERS and field not in implied}
            stat["parse_fields"] += len(profile)
            stat["parse_right"] += len(profile) - len(wrong)
            stat["parse_turns"] += 1
            stat["parse_turns_right"] += not wrong and not extra
            if wrong or extra:
                notes.append(f"Parsing differs: gold {json.dumps({field: profile[field] for field in wrong}, ensure_ascii=False)}, system {json.dumps(wrong, ensure_ascii=False)}; extra {json.dumps(extra, ensure_ascii=False)}")
        # Metrics 2 and 3: what was shown.
        # A preview shows what relaxed conditions would find, so it is not held to the original ones.
        if answer and "confirmed_ids_ranked" in answer and profile and not row.get("preview"):
            confirmed = set(answer["confirmed_ids_ranked"])
            unknown = {item["listing_id"] for item in answer["needs_confirmation"]}
            shown = row["shown"]
            for stated in STATED_TOTAL.findall(row["reply"]):
                stat["totals"] += 1
                if number(stated) != len(confirmed):
                    stat["totals_wrong"] += 1
                    notes.append(f"Wrong total: the reply says {stated}, the gold answer has {len(confirmed)}")
            for item in shown:
                stat["shown"] += 1
                if item["listing_id"] in confirmed:
                    stat["shown_pass"] += 1
                    stat["confirmed_labelled_confirm"] += item["status"] != "match"
                elif item["listing_id"] in unknown:
                    stat["shown_unknown"] += 1
                    if item["status"] == "needs_confirmation":
                        stat["unknown_labelled"] += 1
                    else:
                        notes.append(f"Listing with unknown fields presented as a match: {item['listing_id']}")
                else:
                    stat["shown_fail"] += 1
                    notes.append(f"Listing that fails a condition was shown: {item['listing_id']}")
            if confirmed:
                stat["answerable"] += 1
                if not [item for item in shown if item["status"] == "match"]:
                    stat["missed"] += 1
                    notes.append(f"The gold answer has {len(confirmed)} matches; the system showed none as a match")
            # The order counts only when the user stated priorities (CONVENTIONS.md section 5).
            if profile.get("ranking_priority") and confirmed:
                stat["ordered"] += 1
                system = [item["listing_id"] for item in shown if item["status"] == "match"]
                expected = answer["confirmed_ids_ranked"][:len(system)]
                stat["order_right"] += bool(system) and system == expected
                if system != expected:
                    notes.append(f"Order differs: system {system}, gold {expected}")
            # Metric 6: a change to commute first must not lengthen the commute.
            if faculty and system_top(shown):
                minutes = [commutes[item, faculty] for item in system_top(shown) if (item, faculty) in commutes]
                average = sum(minutes) / len(minutes) if minutes else None
                earlier = gold[row["id"]]["turns"][row["turn"] - 2].get("gold_profile", {}) if row["turn"] > 1 else {}
                changed = (profile.get("ranking_priority") or [None])[0] == "commute" and (earlier.get("ranking_priority") or [None])[0] != "commute"
                if changed and tops.get(case_key) is not None and average is not None:
                    stat["adapted"] += 1
                    if average <= tops[case_key] + 1e-9:
                        stat["adapted_right"] += 1
                    else:
                        notes.append(f"After switching to commute first, the average commute of the top listings went from {tops[case_key]:.1f} to {average:.1f} minutes")
                tops[case_key] = average
        # Metric 4: figures that cannot be traced. Cost estimates are worked out by a tool, so they are read by hand.
        allowed = traceable_numbers(row, answer if answer and "counts" in answer else None, listings, commutes, faculty, conversation[case_key])
        if profile:
            allowed |= recount(frame, commutes, profile, faculty)
        found = claims(row["reply"])
        untraced = []
        for kind, value in found:
            if kind == "id":
                if value not in listings:
                    untraced.append(("id", value))
            elif "estimate_costs" not in row["tools"] and value not in allowed and round(value) not in allowed:
                untraced.append((kind, value))
        stat["claims"] += len(found)
        stat["untraced"] += len(untraced)
        if untraced:
            notes.append("Numbers with no traceable source (check by hand): " + ", ".join(f"{kind} {value:g}" if isinstance(value, float) else f"{kind} {value}" for kind, value in untraced))
        # Metric 8.
        stat["seconds"] += row.get("seconds", 0)
        stat["tool_calls"] += len(row["tools"])
        stat["tool_errors"] += row["tool_errors"]
        stat["guard"] += len(row["guard"])
        if row["guard"]:
            notes.append("Guard: " + "; ".join(row["guard"]))
        mentioned = LISTING_ID.findall(" ".join(conversation[case_key]) + row["reply"])
        about = dict.fromkeys([*(item["listing_id"] for item in row["shown"]), *mentioned])
        facts = [listing_facts(listing_id, listings, commutes, faculty) for listing_id in about if listing_id in listings]
        review += [
            f"## {row['id']} turn {row['turn']} · run {row['run']} · expected {case['expected_behavior']}",
            "",
            *([f"**Said earlier**: {case['preconditions']['prior_turns']}", ""] if case["preconditions"].get("prior_turns") else []),
            f"**User**: {row['user']}",
            "",
            *([f"**What should happen**: {gold[row['id']]['gold_answer']}"] if isinstance(gold[row["id"]].get("gold_answer"), str) else []),
            "",
            f"**Tools**: {row['tools']}; **Shown**: {[item['listing_id'] + ('' if item['status'] == 'match' else '?') for item in row['shown']]}",
            "",
            f"**must**: {gold[row['id']].get('must')}  ",
            f"**must_not**: {gold[row['id']].get('must_not')}",
            "",
            *[f"- ⚠ {note}" for note in notes],
            "",
            *(["**Facts in the data** (frozen data, latest rent):", *[f"- {fact}" for fact in facts], ""] if facts else []),
            "```text",
            row["reply"],
            "```",
            "",
        ]

    total = defaultdict(float)
    for stat in stats.values():
        for key, value in stat.items():
            total[key] += value
    return {"rows": rows, "meta": meta, "versions": versions, "stats": stats, "total": total, "review": review, "cases": cases}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    label = sys.argv[1]
    result = compute(label)
    rows, meta, versions, stats, total, review, cases = (result[k] for k in ("rows", "meta", "versions", "stats", "total", "review", "cases"))
    print(f"{label}  commit {meta.get('commit')}  model {meta.get('model')}  split {meta.get('split')}  turns {int(total['turns'])}")
    if len(code := {(version.get("commit"), version.get("uncommitted_py_sha256")) for version in versions}) > 1:
        print(f"Note: these results come from {len(code)} code versions and cannot count as final results")
    print()
    head = (f"{'Cat':<4}{'Turns':>6}{'Fields':>8}{'Parsed':>8}{'Matched':>9}{'Violate':>9}{'Missed':>8}{'UnkLbl':>8}"
            f"{'Order':>8}{'Untraced':>10}{'Guard':>6}{'Sec':>6}")
    print(head)

    def line(name, stat):
        def share(top, bottom):
            return f"{stat[top] / stat[bottom]:.0%}" if stat[bottom] else "-"

        def pair(top, bottom):
            return f"{int(stat[top])}/{int(stat[bottom])}" if stat[bottom] else "-"

        answered = stat["turns"] - stat["errors"]
        return (f"{name:<4}{int(stat['turns']):>6}{share('parse_right', 'parse_fields'):>8}{pair('parse_turns_right', 'parse_turns'):>8}"
                f"{share('shown_pass', 'shown'):>9}{share('shown_fail', 'shown'):>9}{pair('missed', 'answerable'):>8}{share('unknown_labelled', 'shown_unknown'):>8}"
                f"{pair('order_right', 'ordered'):>8}{pair('untraced', 'claims'):>10}{int(stat['guard']):>6}{(stat['seconds'] / answered if answered else 0):>6.1f}")

    for name in sorted(stats):
        print(line(name, stats[name]))
    print(line("All", total))
    print("\nFields: share of gold fields parsed right. Parsed: turns parsed fully right. Matched: shown listings that are confirmed. "
          "Violate: shown listings that fail a condition. Missed: answerable turns with no match shown. UnkLbl: shown listings with "
          "unknown fields marked as needing confirmation. Order: turns with stated priorities in the gold order. Untraced: numbers "
          "with no traceable source. Sec: seconds per turn.")
    print(f"\nErrors {int(total['errors'])} turns; tool calls {int(total['tool_calls'])}, with argument errors {int(total['tool_errors'])}; guard interventions {int(total['guard'])}")
    print(f"Adaptation (the average commute does not grow after switching to commute first): {int(total['adapted_right'])}/{int(total['adapted'])}")
    print(f"Totals of matches stated in replies that were wrong: {int(total['totals_wrong'])}/{int(total['totals'])}")
    print("Targets: violation rate 0%, fabrication rate under 2%, unknown-labelling rate at least 90%, behaviour correctness at least 85% (behaviour is scored by people)")
    print("Note: 'Untraced' numbers are candidates to check by hand, not proven fabrications.")
    if len(runs := {row["run"] for row in rows}) > 1:
        outcomes = defaultdict(set)
        for row in rows:
            if row["turn"] and "error" not in row:
                outcomes[row["id"], row["turn"]].add(json.dumps([row["preferences"], [item["listing_id"] for item in row["shown"]]], sort_keys=True))
        differ = sorted(key for key, seen in outcomes.items() if len(seen) > 1)
        print(f"\n{len(runs)} runs; the figures above are their total. Turns whose outcome differed between runs (conditions understood or listings shown): {len(differ)}/{len(outcomes)}")
        if differ:
            print("  " + ", ".join(f"{case_id} turn {turn}" for case_id, turn in differ))
    output = RESULTS / f"{label}_review.md"
    output.write_text("\n".join(review), encoding="utf-8")
    print(f"\nTurn-by-turn record: {output}")
    # People fill this in, so it is never written over. The plan scores one run of each system.
    sheet = RESULTS / f"{label}_behaviour.csv"
    if sheet.exists():
        print(f"Behaviour sheet already exists, not overwritten: {sheet}")
    else:
        first_run = min(row["run"] for row in rows)
        with open(sheet, "w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(SHEET_COLUMNS)
            for row in rows:
                if row["turn"] and row["run"] == first_run:
                    writer.writerow([row["id"], row["turn"], cases[row["id"]]["expected_behavior"], row["user"], "", "", "", row.get("error", "")])
        print(f"Behaviour sheet (run {first_run}, one row per turn): {sheet}")


def listing_facts(listing_id: str, listings: dict, commutes: dict, faculty: str | None) -> str:
    """What the data says about a listing, to hold a reply's reasons against."""
    listing = listings[listing_id]
    parts = [
        f"S${listing['rent_monthly_sgd_now'] or listing['rent_monthly_sgd']} ({listing['rent_price_type']})",
        listing["room_type"] or listing["rental_scope"],
        listing["property_type"],
        f"{listing['area_sqm'] or '?'} sqm",
        f"{listing['mrt_station'] or '?'}, {listing['mrt_minutes_reported'] or '?'} min walk, {listing['mrt_distance_m'] or '?'} m",
    ]
    if (listing_id, faculty) in commutes:
        parts.append(f"{commutes[listing_id, faculty]:g} min to {faculty}")
    for name, column in (("furnishing", "furnishing"), ("cooking", "cooking_policy"), ("air-con", "air_conditioning"), ("gender", "gender_restriction"), ("landlord lives in", "landlord_lives_in"), ("pets", "pets_policy")):
        parts.append(f"{name} {listing[column] or 'unknown'}")
    return f"{listing_id}: " + "; ".join(str(part) for part in parts)


def system_top(shown: list[dict]) -> list[str]:
    return [item["listing_id"] for item in shown if item["status"] == "match"]


if __name__ == "__main__":
    main()
