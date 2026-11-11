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
    review = [f"# {label}", "", *(f"版本：{json.dumps(version, ensure_ascii=False)}" for version in versions), ""]
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
            review += [f"## {row['id']} 第 {row['turn']} 轮：出错", "", row["error"], ""]
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
                notes.append(f"解析不一致：标准 {json.dumps({field: profile[field] for field in wrong}, ensure_ascii=False)}，系统 {json.dumps(wrong, ensure_ascii=False)}；多出 {json.dumps(extra, ensure_ascii=False)}")
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
                    notes.append(f"说错了总数：回复说 {stated} 套，标准答案 {len(confirmed)} 套")
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
                        notes.append(f"未知的房源说成了符合：{item['listing_id']}")
                else:
                    stat["shown_fail"] += 1
                    notes.append(f"展示了不符合条件的房源：{item['listing_id']}")
            if confirmed:
                stat["answerable"] += 1
                if not [item for item in shown if item["status"] == "match"]:
                    stat["missed"] += 1
                    notes.append(f"标准答案有 {len(confirmed)} 套符合，系统没有展示符合的房源")
            # The order counts only when the user stated priorities (CONVENTIONS.md section 5).
            if profile.get("ranking_priority") and confirmed:
                stat["ordered"] += 1
                system = [item["listing_id"] for item in shown if item["status"] == "match"]
                expected = answer["confirmed_ids_ranked"][:len(system)]
                stat["order_right"] += bool(system) and system == expected
                if system != expected:
                    notes.append(f"顺序不一致：系统 {system}，标准 {expected}")
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
                        notes.append(f"改成通勤优先后，前几套的平均通勤从 {tops[case_key]:.1f} 变成 {average:.1f} 分钟")
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
            notes.append("查不到来源的数字（要人工看）：" + "、".join(f"{kind} {value:g}" if isinstance(value, float) else f"{kind} {value}" for kind, value in untraced))
        # Metric 8.
        stat["seconds"] += row.get("seconds", 0)
        stat["tool_calls"] += len(row["tools"])
        stat["tool_errors"] += row["tool_errors"]
        stat["guard"] += len(row["guard"])
        if row["guard"]:
            notes.append("守卫：" + "；".join(row["guard"]))
        mentioned = LISTING_ID.findall(" ".join(conversation[case_key]) + row["reply"])
        about = dict.fromkeys([*(item["listing_id"] for item in row["shown"]), *mentioned])
        facts = [listing_facts(listing_id, listings, commutes, faculty) for listing_id in about if listing_id in listings]
        review += [
            f"## {row['id']} 第 {row['turn']} 轮 · 第 {row['run']} 遍 · 期望 {case['expected_behavior']}",
            "",
            *([f"**前面说过**：{case['preconditions']['prior_turns']}", ""] if case["preconditions"].get("prior_turns") else []),
            f"**用户**：{row['user']}",
            "",
            *([f"**应该怎么做**：{gold[row['id']]['gold_answer']}"] if isinstance(gold[row["id"]].get("gold_answer"), str) else []),
            "",
            f"**工具**：{row['tools']}；**展示**：{[item['listing_id'] + ('' if item['status'] == 'match' else '?') for item in row['shown']]}",
            "",
            f"**must**：{gold[row['id']].get('must')}  ",
            f"**must_not**：{gold[row['id']].get('must_not')}",
            "",
            *[f"- ⚠ {note}" for note in notes],
            "",
            *(["**数据里的事实**（冻结数据，租金取最新值）：", *[f"- {fact}" for fact in facts], ""] if facts else []),
            "```text",
            row["reply"],
            "```",
            "",
        ]

    total = defaultdict(float)
    for stat in stats.values():
        for key, value in stat.items():
            total[key] += value
    return {"rows": rows, "meta": meta, "versions": versions, "stats": stats, "total": total, "review": review}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    label = sys.argv[1]
    result = compute(label)
    rows, meta, versions, stats, total, review = (result[k] for k in ("rows", "meta", "versions", "stats", "total", "review"))
    print(f"{label}  commit {meta.get('commit')}  model {meta.get('model')}  split {meta.get('split')}  turns {int(total['turns'])}")
    if len(code := {(version.get("commit"), version.get("uncommitted_py_sha256")) for version in versions}) > 1:
        print(f"注意：这些结果来自 {len(code)} 个代码版本，不能当最终结果")
    print()
    head = f"{'类':<4}{'轮':>4}{'解析字段':>9}{'解析整轮':>9}{'展示符合':>9}{'违规':>7}{'漏报':>7}{'未知标注':>9}{'顺序':>8}{'查不到':>9}{'守卫':>5}{'秒/轮':>7}"
    print(head)

    def line(name, stat):
        def share(top, bottom):
            return f"{stat[top] / stat[bottom]:.0%}" if stat[bottom] else "-"

        def pair(top, bottom):
            return f"{int(stat[top])}/{int(stat[bottom])}" if stat[bottom] else "-"

        answered = stat["turns"] - stat["errors"]
        return (f"{name:<4}{int(stat['turns']):>4}{share('parse_right', 'parse_fields'):>9}{pair('parse_turns_right', 'parse_turns'):>9}"
                f"{share('shown_pass', 'shown'):>9}{share('shown_fail', 'shown'):>7}{pair('missed', 'answerable'):>7}{share('unknown_labelled', 'shown_unknown'):>9}"
                f"{pair('order_right', 'ordered'):>8}{pair('untraced', 'claims'):>9}{int(stat['guard']):>5}{(stat['seconds'] / answered if answered else 0):>7.1f}")

    for name in sorted(stats):
        print(line(name, stats[name]))
    print(line("全部", total))
    print(f"\n出错 {int(total['errors'])} 轮；工具调用 {int(total['tool_calls'])} 次，参数出错 {int(total['tool_errors'])} 次；守卫拦截 {int(total['guard'])} 次")
    print(f"适应性（改成通勤优先后平均通勤不变长）：{int(total['adapted_right'])}/{int(total['adapted'])}")
    print(f"回复里说的符合总数，说错的：{int(total['totals_wrong'])}/{int(total['totals'])}")
    print("目标：违规率 0%，编造率低于 2%，未知标注率不低于 90%，行为正确率不低于 85%（行为要人工打分）")
    print("注意：'查不到'只是待人工核对的候选，不等于编造。")
    if len(runs := {row["run"] for row in rows}) > 1:
        outcomes = defaultdict(set)
        for row in rows:
            if row["turn"] and "error" not in row:
                outcomes[row["id"], row["turn"]].add(json.dumps([row["preferences"], [item["listing_id"] for item in row["shown"]]], sort_keys=True))
        differ = sorted(key for key, seen in outcomes.items() if len(seen) > 1)
        print(f"\n跑了 {len(runs)} 遍，上面是合计。结果不一致的轮（理解的条件或展示的房源不同）：{len(differ)}/{len(outcomes)}")
        if differ:
            print("  " + "、".join(f"{case_id} 第 {turn} 轮" for case_id, turn in differ))
    output = RESULTS / f"{label}_review.md"
    output.write_text("\n".join(review), encoding="utf-8")
    print(f"\n逐轮记录：{output}")
    # People fill this in, so it is never written over. The plan scores one run of each system.
    sheet = RESULTS / f"{label}_behaviour.csv"
    if sheet.exists():
        print(f"打分表已经有了，没有覆盖：{sheet}")
    else:
        first_run = min(row["run"] for row in rows)
        with open(sheet, "w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["题号", "轮", "期望行为", "用户说的", "决策分", "解释分", "打分人", "备注"])
            for row in rows:
                if row["turn"] and row["run"] == first_run:
                    writer.writerow([row["id"], row["turn"], cases[row["id"]]["expected_behavior"], row["user"], "", "", "", row.get("error", "")])
        print(f"行为打分表（第 {first_run} 遍，每轮一行）：{sheet}")


def listing_facts(listing_id: str, listings: dict, commutes: dict, faculty: str | None) -> str:
    """What the data says about a listing, to hold a reply's reasons against."""
    listing = listings[listing_id]
    parts = [
        f"S${listing['rent_monthly_sgd_now'] or listing['rent_monthly_sgd']}（{listing['rent_price_type']}）",
        listing["room_type"] or listing["rental_scope"],
        listing["property_type"],
        f"{listing['area_sqm'] or '?'} sqm",
        f"{listing['mrt_station'] or '?'} 步行 {listing['mrt_minutes_reported'] or '?'} 分钟、{listing['mrt_distance_m'] or '?'} 米",
    ]
    if (listing_id, faculty) in commutes:
        parts.append(f"到 {faculty} {commutes[listing_id, faculty]:g} 分钟")
    for name, column in (("家具", "furnishing"), ("做饭", "cooking_policy"), ("空调", "air_conditioning"), ("性别", "gender_restriction"), ("房东同住", "landlord_lives_in"), ("宠物", "pets_policy")):
        parts.append(f"{name} {listing[column] or '未知'}")
    return f"{listing_id}：" + "；".join(str(part) for part in parts)


def system_top(shown: list[dict]) -> list[str]:
    return [item["listing_id"] for item in shown if item["status"] == "match"]


if __name__ == "__main__":
    main()
