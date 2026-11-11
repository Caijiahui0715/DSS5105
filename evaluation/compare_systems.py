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
    ("B1", "平台式筛选 + 租金排序（条件由标准答案提供）", "b1"),
    ("B2", "加权打分（条件由标准答案提供）", "b2"),
    ("B3", "LLM，不给工具", "b3"),
    ("B4", "固定 workflow（graph.py）", "b4"),
    ("B5", "agent（冻结版）", None),
]
LABELS = {"dev": {"b1": "b1-dev", "b2": "b2-dev", "b3": "b3-dev", "b4": "b4-dev", None: "dev5"},
          "holdout": {"b1": "b1-holdout", "b2": "b2-holdout", "b3": "b3-holdout", "b4": "b4-holdout", None: "holdout"}}
# B1 and B2 are handed the gold conditions; B3 gives no structured conditions to check.
NO_PARSE = {"B1": "直接用标准条件", "B2": "直接用标准条件", "B3": "不输出条件"}
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


HEAD = ("| 系统 | 遍数 | 展示正确 | 违反硬条件 | 未知说成符合 | 漏报 | 说了排序的顺序 | B 类：列出需确认的 | C 类：最小放宽对 | "
        "改通勤优先后 | 总数说错 | 查不到出处的数字 | 理解条件（整轮） | 秒/轮 |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")

NOTES = """指标（只算 A、B、C、G 类有标准条件的轮）：

- **展示正确**：展示的房源里，确定符合且标为符合、或者缺数据且标为需确认的比例。
- **违反硬条件**：展示了明确不符合条件的房源。目标 0%。
- **未知说成符合**：数据没写明的条件，系统当成已满足。
- **漏报**：标准答案有符合的房源，系统一套也没展示。
- **说了排序的顺序**：用户说了优先项的轮，前几名顺序和标准答案一致的轮数。
- **B 类：列出需确认的**：标准答案里有"数据没写明、需要确认"的房源时，系统有没有把它们单独标出来，或者说出有多少套。只给确定符合的房源、对缺数据的只字不提，算没做到。
- **C 类：最小放宽对**：没有符合的房源时，回复里有没有给出标准答案的最小改动（例如预算放到 2,205、通勤放到 29 分钟）；标准答案说"只改这一项解决不了"的，回复要说明这一点。
- **改通勤优先后**：改成通勤优先后，前几名的平均通勤没有变长。
- **总数说错**：回复里说的"N 套符合"和标准答案不一致。
- **查不到出处的数字**：回复里的数字在数据和标准答案里找不到，是编造的候选，要人工核对。
- **理解条件**：系统理解出的条件和标准条件完全一致的轮数。

**B1、B2 的条件由标准答案直接提供**，等于替它们把"理解用户"和"记住多轮里改了什么"做对了；它们判断字段用的也是生成标准答案的同一套规则，所以"违反硬条件""展示正确"这几列对它们几乎必然好看。真正测它们的是"说了排序的顺序"和 B、C 两列。

B、C 两列是从回复文字里自动判断的，是近似值，逐题结果用 `compare_systems.py --detail` 查看。

D、E、F、H 类（追问、说不知道、拒绝、说出处）看行为，要人工打分，不在这张表里。B1、B2 只会按条件搜索，这几类都做不到。"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    detail = "--detail" in sys.argv
    out = ["# 基线对比", "", "由 `compare_systems.py` 生成。系统说明见 `baselines.py`，解读见 `baseline_report.md`。", ""]
    for split, title in (("holdout", "测试集（20 题）"), ("dev", "开发集（39 题）")):
        made = [(code, row(code, name, LABELS[split][key])) for code, name, key in SYSTEMS]
        made = [(code, m) for code, m in made if m]
        if not made:
            continue
        out += [f"## {title}", "", HEAD, *(m[0] for _, m in made), ""]
        if split == "dev":
            out += ["开发集上 B5 是看着这些题改出来的（dev5，冻结版代码），数字偏乐观；基线没有针对任何一题调过。", ""]
        if detail:
            for code, (_, extra) in made:
                print(f"{split} {code}: B 没做到 {extra['B'][2]}；C 没做到 {extra['C'][2]}")
    out += [NOTES, ""]
    text = "\n".join(out)
    (score.RESULTS / "baseline_comparison.md").write_text(text, encoding="utf-8")
    if not detail:
        print(text)


if __name__ == "__main__":
    main()
