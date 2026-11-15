"""Put the baselines (B1-B4) and the agent (B5) side by side, from the same automatic metrics as score.py.

    .venv/Scripts/python.exe evaluation/compare_systems.py

Reads results/<label>.jsonl for each system and split below (a missing file is skipped) and writes
results/baseline_comparison.md. Only search turns with a gold condition set count (categories A, B,
C and G); D, E, F and H are about behaviour, which people score.

Two checks are added here on top of score.py, both read from the reply text and so approximate
(compare_systems.py --detail prints every case for checking by hand):
  - B: when the gold answer has listings that need confirmation, does the system show at least one
    marked as such, or say how many there are (the gold count, next to a word such as "confirm")?
  - C: does the reply give the smallest single change in the gold answer (its value), or, where the
    gold answer says that field alone cannot help, say so?
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import score  # noqa: E402

SYSTEMS = [
    ("B1", "Portal-style filters + rent order (given the gold conditions)", "b1"),
    ("B2", "Weighted score (given the gold conditions)", "b2"),
    ("B3", "LLM without tools", "b3"),
    ("B4", "Fixed workflow (graph.py)", "b4"),
    ("B5", "Agent (frozen)", None),
]
LABELS = {"dev": {"b1": "b1-dev", "b2": "b2-dev", "b3": "b3-dev", "b4": "b4-dev", None: "dev5"},
          "holdout": {"b1": "b1-holdout", "b2": "b2-holdout", "b3": "b3-holdout", "b4": "b4-holdout", None: "holdout"}}
# B1 and B2 are handed the gold conditions; B3 gives no structured conditions to check.
NO_PARSE = {"B1": "given gold conditions", "B2": "given gold conditions", "B3": "no conditions output"}
GOLD = {a["case_id"]: a for a in json.loads((HERE / "gold" / "gold_answers.json").read_text(encoding="utf-8"))["answers"]}

UNKNOWN_WORDS = re.compile(r"confirm|not stated|unstated|unknown|not specified|does not state|doesn't state|需确认|需要确认|未写明|没写|未注明|不明|未知", re.I)
# "Changing this field alone does not help": a sentence naming the field and saying no.
FIELD_WORDS = {"max_price_sgd": r"budget|price|rent|预算|租金", "lease_months": r"lease|租期",
               "max_commute_minutes": r"commute|通勤", "max_mrt_minutes": r"MRT|walk|步行", "district_code": r"district|区"}
NEGATIVE = re.compile(r"\balone\b|no match|no listing|\bnot\b|n't|\bnone\b|nothing|无法|不能|没有|解决不了|不会", re.I)


def says_cannot(reply: str, field: str) -> bool:
    words = re.compile(FIELD_WORDS.get(field, re.escape(field)), re.I)
    return any(words.search(part) and NEGATIVE.search(part) for part in re.split(r"[.\n;。；!?！？]", reply))


def numbers(text: str) -> set[float]:
    return {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def lists_unknowns(row: dict, turn: dict) -> bool:
    if any(item["status"] == "needs_confirmation" for item in row["shown"]):
        return True
    count = float(len(turn["needs_confirmation"]))
    return count in numbers(row["reply"]) and bool(UNKNOWN_WORDS.search(row["reply"]))


def right_relaxation(row: dict, turn: dict) -> bool:
    items = turn["relaxation"] if isinstance(turn["relaxation"], list) else [turn["relaxation"]]
    said = numbers(row["reply"])
    for item in items:
        value = item.get("minimum_relaxed_value")
        if value is None:
            if not says_cannot(row["reply"], item["target_field"]):
                return False
        elif float(value) not in said:
            return False
    return True


def extra_checks(rows: list[dict]) -> dict:
    """B: unknowns listed or counted; C: the smallest change named. Each as [passed, turns, failed cases]."""
    out = {"B": [0, 0, []], "C": [0, 0, []]}
    for row in rows:
        if not row["turn"] or "error" in row or row["category"][0] not in out:
            continue
        turn = GOLD[row["id"]]["turns"][row["turn"] - 1]
        kind = row["category"][0]
        if kind == "B" and turn.get("needs_confirmation"):
            ok = lists_unknowns(row, turn)
        elif kind == "C" and turn.get("relaxation"):
            ok = right_relaxation(row, turn)
        else:
            continue
        out[kind][0] += ok
        out[kind][1] += 1
        if not ok:
            out[kind][2].append(f"{row['id']}#{row['run']}")
    return out


def rate(top: float, bottom: float, percent: bool = True) -> str:
    if not bottom:
        return "–"
    return f"{top / bottom:.0%}" if percent else f"{int(top)}/{int(bottom)}"


def row(code: str, name: str, label: str) -> tuple[str, dict] | None:
    if not (score.RESULTS / f"{label}.jsonl").exists():
        return None
    result = score.compute(label)
    t, rows = result["total"], result["rows"]
    runs = len({r["run"] for r in rows})
    shown = t["shown"]
    wrong_unknown = t["shown_unknown"] - t["unknown_labelled"]
    right = t["shown_pass"] + t["unknown_labelled"]
    answered = t["turns"] - t["errors"]
    parse = NO_PARSE.get(code) or rate(t["parse_turns_right"], t["parse_turns"], False)
    extra = extra_checks(rows)
    line = (f"| {code} {name} | {runs} | {rate(right, shown)} | {rate(t['shown_fail'], shown)} | {rate(wrong_unknown, shown)} | "
            f"{rate(t['missed'], t['answerable'], False)} | {rate(t['order_right'], t['ordered'], False)} | "
            f"{rate(*extra['B'][:2], False)} | {rate(*extra['C'][:2], False)} | "
            f"{rate(t['adapted_right'], t['adapted'], False)} | {rate(t['totals_wrong'], t['totals'], False)} | "
            f"{rate(t['untraced'], t['claims'], False)} | {parse} | {t['seconds'] / answered if answered else 0:.1f} |")
    return line, extra


HEAD = ("| System | Runs | Display correct | Hard violations | Unknown as confirmed | Missed | Stated-priority order | B: lists pending | C: minimum relaxation | "
        "After commute first | Wrong total | Untraced numbers | Conditions parsed (whole turn) | Seconds/turn |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")

NOTES = """Metrics (only turns of categories A, B, C and G that have gold conditions):

- **Display correct**: share of shown listings that are confirmed and marked as matches, or have missing data and are marked as needing confirmation.
- **Hard violations**: listings shown that clearly fail a condition. Target 0%.
- **Unknown as confirmed**: a condition the data does not state, treated by the system as met.
- **Missed**: the gold answer has matching listings, but the system showed none.
- **Stated-priority order**: turns where the user stated priorities and the top listings are in the gold order.
- **B: lists pending**: when the gold answer has listings whose data does not state a condition, whether the system marks them separately or says how many there are. Showing only the confirmed listings and saying nothing about the missing data counts as not done.
- **C: minimum relaxation**: when nothing matches, whether the reply gives the gold answer's smallest change (for example budget up to 2,205, or commute up to 29 minutes); where the gold answer says changing that one condition alone cannot help, the reply has to say so.
- **After commute first**: after switching to commute first, the average commute of the top listings does not grow.
- **Wrong total**: the "N matches" stated in the reply differs from the gold answer.
- **Untraced numbers**: numbers in the reply that cannot be found in the data or the gold answer; candidates for fabrication, to be checked by hand.
- **Conditions parsed**: turns where the conditions the system understood are exactly the gold conditions.

**B1 and B2 are given the gold conditions directly**, which does "understanding the user" and "remembering what changed across turns" for them; they also judge fields with the same rules that generate the gold answer, so the "Hard violations" and "Display correct" columns are almost bound to look good for them. What really tests them is "Stated-priority order" and the B and C columns.

The B and C columns are judged automatically from the reply text and are approximate; `compare_systems.py --detail` shows the result for every case.

Categories D, E, F and H (asking first, saying the data does not know, declining, citing sources) are about behaviour, which people score; they are not in this table. B1 and B2 can only search by conditions and can do none of these."""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    detail = "--detail" in sys.argv
    out = ["# Baseline comparison", "", "Generated by `compare_systems.py`. The systems are described in `baselines.py`; the interpretation is in `baseline_report.md`.", ""]
    for split, title in (("holdout", "Holdout (20 cases)"), ("dev", "Dev set (39 cases)")):
        made = [(code, row(code, name, LABELS[split][key])) for code, name, key in SYSTEMS]
        made = [(code, m) for code, m in made if m]
        if not made:
            continue
        out += [f"## {title}", "", HEAD, *(m[0] for _, m in made), ""]
        if split == "dev":
            out += ["On the dev set, B5 was tuned on these very cases (dev5, the frozen code), so its figures are optimistic; the baselines were not tuned on any case.", ""]
        if detail:
            for code, (_, extra) in made:
                print(f"{split} {code}: B not done {extra['B'][2]}; C not done {extra['C'][2]}")
    out += [NOTES, ""]
    text = "\n".join(out)
    (score.RESULTS / "baseline_comparison.md").write_text(text, encoding="utf-8")
    if not detail:
        print(text)


if __name__ == "__main__":
    main()
