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
SCORES = ("决策分", "解释分")
TARGET = 0.85


def read(path: Path) -> list[dict]:
    # Excel on a Chinese Windows may save CSV in GBK.
    for encoding in ("utf-8-sig", "gbk"):
        try:
            with path.open(encoding=encoding, newline="") as file:
                return list(csv.DictReader(file))
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
    sheets = sorted(p for p in directory.glob(f"{label}_behaviour_*.csv") if not p.stem.endswith("_merged"))
    if len(sheets) != 2:
        raise SystemExit(f"Need exactly two rater sheets named {label}_behaviour_<name>.csv in {directory}, found {[p.name for p in sheets]}")
    names = [p.stem.removeprefix(f"{label}_behaviour_") for p in sheets]
    a_rows, b_rows = (read(p) for p in sheets)
    keys = [(r["题号"], r["轮"]) for r in a_rows]
    if keys != [(r["题号"], r["轮"]) for r in b_rows]:
        raise SystemExit("The two sheets do not list the same rows in the same order")
    a = {s: [score(r[s], f"{sheets[0].name} {r['题号']} 第 {r['轮']} 轮 {s}") for r in a_rows] for s in SCORES}
    b = {s: [score(r[s], f"{sheets[1].name} {r['题号']} 第 {r['轮']} 轮 {s}") for r in b_rows] for s in SCORES}

    print(f"{label}：{len(keys)} 轮，评分人 {names[0]}、{names[1]}\n")
    for s in SCORES:
        same = sum(x == y for x, y in zip(a[s], b[s]))
        k = kappa(a[s], b[s])
        print(f"{s}：一致 {same}/{len(keys)}（{same / len(keys):.0%}），Cohen's κ = {'–（两人都几乎全给同一个分）' if k is None else f'{k:.2f}'}")
    print("\n两人不一致的行：")
    differ = 0
    for i, (case, turn) in enumerate(keys):
        diff = [s for s in SCORES if a[s][i] != b[s][i]]
        if diff:
            differ += 1
            parts = "；".join(f"{s} {names[0]} {a[s][i]} / {names[1]} {b[s][i]}" for s in diff)
            notes = " | ".join(n for n in (a_rows[i].get("备注", "").strip(), b_rows[i].get("备注", "").strip()) if n)
            print(f"  {case} 第 {turn} 轮：{parts}" + (f"（备注：{notes}）" if notes else ""))
    if not differ:
        print("  无")

    output = directory / f"{label}_behaviour_merged.csv"
    if output.exists() and not force:
        print(f"\n{output.name} 已经存在，没有覆盖（里面可能有讨论后的最终分）。要重新生成，加 --force。")
        return
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["题号", "轮", "期望行为", f"决策分_{names[0]}", f"决策分_{names[1]}", f"解释分_{names[0]}", f"解释分_{names[1]}",
                         "最终决策分", "最终解释分", f"备注_{names[0]}", f"备注_{names[1]}", "讨论结论"])
        for i, row in enumerate(a_rows):
            final = [a[s][i] if a[s][i] == b[s][i] else "" for s in SCORES]
            writer.writerow([row["题号"], row["轮"], row["期望行为"], a["决策分"][i], b["决策分"][i], a["解释分"][i], b["解释分"][i],
                             *final, row.get("备注", ""), b_rows[i].get("备注", ""), ""])
    print(f"\n已生成 {output.name}：一致的行已填最终分，{differ} 行留空，讨论后填上，再运行 --final。")


def final(label: str, directory: Path) -> None:
    path = directory / f"{label}_behaviour_merged.csv"
    if not path.exists():
        raise SystemExit(f"{path.name} not found: run without --final first")
    rows = read(path)
    blank = [f"{r['题号']} 第 {r['轮']} 轮" for r in rows if not (r["最终决策分"].strip() and r["最终解释分"].strip())]
    if blank:
        raise SystemExit("还有行没有最终分：" + "、".join(blank))
    groups = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        d, e = score(r["最终决策分"], r["题号"]), score(r["最终解释分"], r["题号"])
        for key in (r["期望行为"], "全部"):
            g = groups[key]
            g[0] += 1
            g[1] += d
            g[2] += e
            g[3] += d and e
    print(f"{label} 最终行为分（目标 ≥ {TARGET:.0%}）\n")
    print(f"{'期望行为':<14}{'轮':>4}{'决策分':>10}{'解释分':>10}{'两项都对':>10}")
    for key in sorted(groups, key=lambda k: (k == "全部", k)):
        n, d, e, both = groups[key]
        print(f"{key:<14}{n:>4}{f'{d}/{n} {d / n:.0%}':>12}{f'{e}/{n} {e / n:.0%}':>12}{f'{both}/{n} {both / n:.0%}':>12}")
    n, d, e, both = groups["全部"]
    for name, value in (("决策分", d / n), ("解释分", e / n)):
        print(f"\n{name} {value:.0%}：{'达到' if value >= TARGET else '没有达到'}目标")


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
