"""Merge two raters' behaviour sheets, measure how far they agree, then report the final rates.

    .venv/Scripts/python.exe evaluation/merge_behaviour.py holdout
    .venv/Scripts/python.exe evaluation/merge_behaviour.py holdout --final

Each rater copies results/<label>_behaviour.csv to results/<label>_behaviour_<name>.csv and fills in
the decision and explanation scores (0 or 1). The first form checks both sheets, prints the share of
rows where the raters agree and Cohen's kappa for each score, lists the rows where they differ, and
writes results/<label>_behaviour_merged.csv with the agreed scores filled in and the others left
blank for the raters to settle. After that, --final reads the merged sheet and prints the rates.
See behaviour_scoring_guide.md.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
SCORES = ("decision_score", "explanation_score")
TARGET = 0.85
# Sheets made before the columns were renamed in English use these names; they are read the same way.
OLD_COLUMNS = {"题号": "case_id", "轮": "turn", "期望行为": "expected_behaviour", "用户说的": "user_message",
               "决策分": "decision_score", "解释分": "explanation_score", "打分人": "rater", "备注": "note",
               "最终决策分": "final_decision", "最终解释分": "final_explanation", "讨论结论": "resolution"}
OLD_PREFIXES = {"决策分_": "decision_", "解释分_": "explanation_", "备注_": "note_"}
# results/ also holds the team's final holdout scores under the same name pattern; they are not rater sheets.
NOT_RATER_SHEETS = {"merged", "final", "adjudication"}


def english(column: str | None) -> str:
    column = (column or "").strip()
    if column in OLD_COLUMNS:
        return OLD_COLUMNS[column]
    for old, new in OLD_PREFIXES.items():
        if column.startswith(old):
            return new + column.removeprefix(old)
    return column


def read(path: Path) -> list[dict]:
    # Excel on a Chinese Windows may save CSV in GBK.
    for encoding in ("utf-8-sig", "gbk"):
        try:
            with path.open(encoding=encoding, newline="") as file:
                return [{english(k): v for k, v in row.items()} for row in csv.DictReader(file)]
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"Cannot read {path}: save it as CSV (UTF-8)")


def score(value: str, where: str) -> int:
    text = (value or "").strip()
    if text not in ("0", "1"):
        raise SystemExit(f"{where}: score must be 0 or 1, found {text!r}")
    return int(text)


def kappa(a: list[int], b: list[int]) -> float | None:
    """Cohen's kappa for two raters on 0/1 scores; None when chance agreement is total."""
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    expected = sum((a.count(c) / n) * (b.count(c) / n) for c in (0, 1))
    return None if expected == 1 else (observed - expected) / (1 - expected)


def merge(label: str, directory: Path, force: bool) -> None:
    sheets = sorted(p for p in directory.glob(f"{label}_behaviour_*.csv")
                    if p.stem.removeprefix(f"{label}_behaviour_") not in NOT_RATER_SHEETS)
    if len(sheets) != 2:
        raise SystemExit(f"Need exactly two rater sheets named {label}_behaviour_<name>.csv in {directory}, found {[p.name for p in sheets]}")
    names = [p.stem.removeprefix(f"{label}_behaviour_") for p in sheets]
    a_rows, b_rows = (read(p) for p in sheets)
    keys = [(r["case_id"], r["turn"]) for r in a_rows]
    if keys != [(r["case_id"], r["turn"]) for r in b_rows]:
        raise SystemExit("The two sheets do not list the same rows in the same order")
    a = {s: [score(r[s], f"{sheets[0].name} {r['case_id']} turn {r['turn']} {s}") for r in a_rows] for s in SCORES}
    b = {s: [score(r[s], f"{sheets[1].name} {r['case_id']} turn {r['turn']} {s}") for r in b_rows] for s in SCORES}

    print(f"{label}: {len(keys)} turns, raters {names[0]} and {names[1]}\n")
    for s in SCORES:
        same = sum(x == y for x, y in zip(a[s], b[s]))
        k = kappa(a[s], b[s])
        print(f"{s}: agree {same}/{len(keys)} ({same / len(keys):.0%}), Cohen's κ = {'– (both gave almost only one score)' if k is None else f'{k:.2f}'}")
    print("\nRows where the raters differ:")
    differ = 0
    for i, (case, turn) in enumerate(keys):
        diff = [s for s in SCORES if a[s][i] != b[s][i]]
        if diff:
            differ += 1
            parts = "; ".join(f"{s} {names[0]} {a[s][i]} / {names[1]} {b[s][i]}" for s in diff)
            notes = " | ".join(n for n in (a_rows[i].get("note", "").strip(), b_rows[i].get("note", "").strip()) if n)
            print(f"  {case} turn {turn}: {parts}" + (f" (notes: {notes})" if notes else ""))
    if not differ:
        print("  none")

    output = directory / f"{label}_behaviour_merged.csv"
    if output.exists() and not force:
        print(f"\n{output.name} already exists and was not overwritten (it may hold the scores agreed after discussion). Add --force to rebuild it.")
        return
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["case_id", "turn", "expected_behaviour", f"decision_{names[0]}", f"decision_{names[1]}", f"explanation_{names[0]}",
                         f"explanation_{names[1]}", "final_decision", "final_explanation", f"note_{names[0]}", f"note_{names[1]}", "resolution"])
        for i, row in enumerate(a_rows):
            final = [a[s][i] if a[s][i] == b[s][i] else "" for s in SCORES]
            writer.writerow([row["case_id"], row["turn"], row["expected_behaviour"], a["decision_score"][i], b["decision_score"][i],
                             a["explanation_score"][i], b["explanation_score"][i], *final, row.get("note", ""), b_rows[i].get("note", ""), ""])
    print(f"\nWrote {output.name}: agreed rows have their final scores; {differ} rows are blank. Fill them in after discussion, then run --final.")


def final(label: str, directory: Path) -> None:
    path = directory / f"{label}_behaviour_merged.csv"
    if not path.exists():
        raise SystemExit(f"{path.name} not found: run without --final first")
    rows = read(path)
    blank = [f"{r['case_id']} turn {r['turn']}" for r in rows if not (r["final_decision"].strip() and r["final_explanation"].strip())]
    if blank:
        raise SystemExit("These rows have no final score yet: " + ", ".join(blank))
    groups = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        d, e = score(r["final_decision"], r["case_id"]), score(r["final_explanation"], r["case_id"])
        for key in (r["expected_behaviour"], "all"):
            g = groups[key]
            g[0] += 1
            g[1] += d
            g[2] += e
            g[3] += d and e
    print(f"{label} final behaviour scores (target ≥ {TARGET:.0%})\n")
    print(f"{'Expected':<14}{'Turns':>6}{'Decision':>12}{'Explanation':>12}{'Both':>12}")
    for key in sorted(groups, key=lambda k: (k == "all", k)):
        n, d, e, both = groups[key]
        print(f"{key:<14}{n:>6}{f'{d}/{n} {d / n:.0%}':>12}{f'{e}/{n} {e / n:.0%}':>12}{f'{both}/{n} {both / n:.0%}':>12}")
    n, d, e, both = groups["all"]
    for name, value in (("Decision", d / n), ("Explanation", e / n)):
        print(f"\n{name} {value:.0%}: target {'met' if value >= TARGET else 'not met'}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("label", help="for example holdout, b3-holdout, b4-holdout")
    parser.add_argument("--final", action="store_true", help="report the final rates from the merged sheet")
    parser.add_argument("--force", action="store_true", help="rewrite the merged sheet even if it exists")
    parser.add_argument("--dir", type=Path, default=RESULTS, help=argparse.SUPPRESS)
    args = parser.parse_args()
    final(args.label, args.dir) if args.final else merge(args.label, args.dir, args.force)


if __name__ == "__main__":
    main()
