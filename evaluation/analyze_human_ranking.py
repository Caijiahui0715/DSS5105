"""Analyse the human-ranking responses of the V6 form (Part 1) and its Part 2.

Inputs:  evaluation/human_ranking/responses/v6_part1_responses.csv   (V6, Chinese, 15 cases x 3 candidates)
         evaluation/human_ranking/responses/v6_part2_responses.csv   (A08, A09, B01, G04 rebuilt from the gold answer)
         evaluation/human_ranking/v6_replacement/key.csv              (gold order of the Part 2 candidates)
         evaluation/human_ranking/v6_key.csv                          (V6 Part 1: listing per label, agent rank,
                                                                       gold rank; read off the V6 images)
Output:  evaluation/human_ranking/responses/analysis.md

Part 1's A08, A09, B01 and G04 are superseded by Part 2 (their V6 candidates
included a delisted listing) and are left out.

Agreement between reviewers: Kendall's W with tie correction, per case.
Agreement with the gold order (Part 2 only, where the key is known): Kendall's
tau-b per reviewer, the share of reviewers whose first choice is the gold first
choice, and the mean reviewer ranking compared with the gold order.

Run from the repository root:
    .venv/Scripts/python.exe evaluation/analyze_human_ranking.py
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESP = HERE / "human_ranking" / "responses"
PART1 = RESP / "v6_part1_responses.csv"
PART2 = RESP / "v6_part2_responses.csv"
KEY2 = HERE / "human_ranking" / "v6_replacement" / "key.csv"
KEY1 = HERE / "human_ranking" / "v6_key.csv"
OUT = RESP / "analysis.md"
CASES = HERE / "cases" / "cases.json"

SUPERSEDED = {"A08", "A09", "B01", "G04"}
# Reviewer codes typed differently in the two parts; the timestamps and comments show the same person.
ALIASES = {"1ljy": "ljy"}


def read(path: Path, part: str):
    """{reviewer: {case: {label: rank or None}}} and {reviewer: {case: comment}}."""
    rows = list(csv.reader(path.open(encoding="utf-8-sig")))
    head, body = rows[0], rows[1:]
    ranks, notes = defaultdict(dict), defaultdict(dict)
    for r in body:
        who = r[1].strip()
        who = ALIASES.get(who, who)
        for col, val in zip(head[2:], r[2:]):
            m = re.match(r"(\w\d\d) \| (?:候选|Candidate) ([A-E]) ", col)
            if m:
                case, lab = m.groups()
                ranks[who].setdefault(case, {})[lab] = int(val) if val.strip().isdigit() else None
            elif val.strip():
                notes[who][col.split(" |")[0]] = val.strip()
    return ranks, notes


def avg_ranks(order: dict[str, int | None]) -> dict[str, float]:
    """Turn a reviewer's stated places (ties allowed) into average ranks 1..n."""
    items = sorted((v, k) for k, v in order.items() if v is not None)
    out, i = {}, 0
    while i < len(items):
        j = i
        while j < len(items) and items[j][0] == items[i][0]:
            j += 1
        for _, k in items[i:j]:
            out[k] = (i + 1 + j) / 2
        i = j
    return out


def kendall_w(rankings: list[dict[str, float]], labels: list[str]) -> tuple[float, float]:
    """Kendall's W with tie correction, and its chi-square p-value (df = n - 1)."""
    m, n = len(rankings), len(labels)
    sums = [sum(r[l] for r in rankings) for l in labels]
    mean = sum(sums) / n
    s = sum((x - mean) ** 2 for x in sums)
    ties = 0.0
    for r in rankings:
        counts = defaultdict(int)
        for v in r.values():
            counts[v] += 1
        ties += sum(t ** 3 - t for t in counts.values())
    w = 12 * s / (m ** 2 * (n ** 3 - n) - m * ties)
    chi2 = m * (n - 1) * w
    return w, chi2_sf(chi2, n - 1)


def chi2_sf(x: float, df: int) -> float:
    """Upper tail of chi-square for even df (closed form); n = 3 or 5 gives df 2 or 4."""
    assert df % 2 == 0
    term, total = 1.0, 1.0
    for k in range(1, df // 2):
        term *= (x / 2) / k
        total += term
    return math.exp(-x / 2) * total


def tau_b(a: dict[str, float], b: dict[str, float]) -> float:
    labels = sorted(set(a) & set(b))
    conc = disc = ta = tb = 0
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            da = a[labels[i]] - a[labels[j]]
            db = b[labels[i]] - b[labels[j]]
            if da == 0 and db == 0:
                continue
            if da == 0:
                ta += 1
            elif db == 0:
                tb += 1
            elif da * db > 0:
                conc += 1
            else:
                disc += 1
    denom = math.sqrt((conc + disc + ta) * (conc + disc + tb))
    return (conc - disc) / denom if denom else float("nan")


def gold_orders() -> dict[str, list[str]]:
    rows = list(csv.DictReader(KEY2.open(encoding="utf-8-sig")))
    out = defaultdict(list)
    for r in sorted(rows, key=lambda r: (r["Case ID"], int(r["Gold rank among confirmed"]))):
        out[r["Case ID"]].append(r["Label"])
    return out


def part1_keys():
    """{case: (agent order, gold order over confirmed candidates, labels not confirmed)}."""
    rows = list(csv.DictReader(KEY1.open(encoding="utf-8-sig")))
    out = {}
    for case in sorted({r["Case ID"] for r in rows}):
        rs = [r for r in rows if r["Case ID"] == case]
        agent = [r["Label"] for r in sorted(rs, key=lambda r: int(r["Agent rank"]))]
        conf = [r for r in rs if r["Gold status"] == "confirmed"]
        gold = [r["Label"] for r in sorted(conf, key=lambda r: int(r["Gold rank among confirmed"]))]
        out[case] = (agent, gold, [f'{r["Label"]} ({r["Gold status"]})' for r in rs if r["Gold status"] != "confirmed"])
    return out


def compare(reviews: dict, case: str, order: list[str]):
    """Mean tau-b against `order` (restricted to its labels), per-reviewer taus, first-choice hits, consensus."""
    ref = {lab: i + 1 for i, lab in enumerate(order)}
    taus, hits, rankings = [], 0, []
    for who in sorted(reviews):
        r = avg_ranks({k: v for k, v in reviews[who][case].items() if k in ref})
        rankings.append(r)
        taus.append((who, tau_b(r, ref)))
        best = min(r.values())
        hits += r.get(order[0]) == best
    mean = {l: sum(r[l] for r in rankings) / len(rankings) for l in ref}
    return sum(t for _, t in taus) / len(taus), taus, hits, " > ".join(sorted(ref, key=lambda l: mean[l]))


def fmt_order(r: dict[str, float]) -> str:
    groups = defaultdict(list)
    for k, v in r.items():
        groups[v].append(k)
    return " > ".join("=".join(sorted(groups[v])) for v in sorted(groups))


def main():
    r1, n1 = read(PART1, "1")
    r2, n2 = read(PART2, "2")
    gold = gold_orders()
    lines = ["# 人工排序问卷结果分析", "",
             f"Part 1：{len(r1)} 位评审（{', '.join(sorted(r1))}）；Part 2：{len(r2)} 位评审（{', '.join(sorted(r2))}）。",
             f"评审编号别名：{', '.join(f'{k} → {v}' for k, v in ALIASES.items())}。",
             "Part 1 的 A08、A09、B01、G04 已被 Part 2 取代（V6 候选里有下架房源），不计入。", ""]

    # --- data quality
    lines += ["## 数据检查", ""]
    issues = []
    for part, rr in (("Part 1", r1), ("Part 2", r2)):
        for who, cases in sorted(rr.items()):
            for case, order in sorted(cases.items()):
                if part == "Part 1" and case in SUPERSEDED:
                    continue
                vals = [v for v in order.values() if v is not None]
                if len(vals) < len(order):
                    issues.append(f"{part} {who} {case}：有候选选了无法判断")
                if len(set(vals)) < len(vals):
                    issues.append(f"{part} {who} {case}：并列 {fmt_order(avg_ranks(order))}")
                if vals and max(vals) > len(order):
                    issues.append(f"{part} {who} {case}：名次超出候选数")
    lines += [f"- {x}" for x in issues] or ["- 无"]
    lines.append("")

    # --- agreement
    lines += ["## 评审之间的一致性（Kendall's W）", "",
              "W 在 0 到 1 之间，1 表示所有评审排得完全一样。p 值来自卡方近似，评审人数少，只作参考。", "",
              "| 部分 | 题目 | 候选数 | 评审数 | W | p | 平均名次顺序 |", "|---|---|---|---|---|---|---|"]
    w_rows = []
    for part, rr in (("Part 1", r1), ("Part 2", r2)):
        cases = sorted({c for v in rr.values() for c in v})
        for case in cases:
            if part == "Part 1" and case in SUPERSEDED:
                continue
            rankings = [avg_ranks(v[case]) for v in rr.values() if case in v]
            labels = sorted(rankings[0])
            rankings = [r for r in rankings if set(r) == set(labels)]
            w, p = kendall_w(rankings, labels)
            mean = {l: sum(r[l] for r in rankings) / len(rankings) for l in labels}
            order = " > ".join(f"{l}({mean[l]:.1f})" for l in sorted(labels, key=lambda l: mean[l]))
            w_rows.append((part, case, w))
            lines.append(f"| {part} | {case} | {len(labels)} | {len(rankings)} | {w:.2f} | {p:.3f} | {order} |")
    lines.append("")

    # --- gold comparison
    lines += ["## Part 2 和标准答案的对照", "",
              "标准答案顺序来自 `v6_replacement/key.csv`（按 CONVENTIONS.md 的排序规则）。τ-b 为 1 表示和标准答案完全一致，-1 表示完全相反。", "",
              "| 题目 | 标准答案 | 评审平均顺序 | 平均 τ-b | 各评审 τ-b | 第 1 名和标准答案相同 |", "|---|---|---|---|---|---|"]
    for case in sorted(gold):
        g = {lab: i + 1 for i, lab in enumerate(gold[case])}
        taus, hits, rankings = [], 0, []
        for who in sorted(r2):
            r = avg_ranks(r2[who][case])
            rankings.append(r)
            taus.append((who, tau_b(r, g)))
            hits += min(r, key=r.get) == gold[case][0]
        mean = {l: sum(r[l] for r in rankings) / len(rankings) for l in g}
        consensus = " > ".join(sorted(g, key=lambda l: mean[l]))
        lines.append(f"| {case} | {' > '.join(gold[case])} | {consensus} | {sum(t for _, t in taus) / len(taus):.2f} | "
                     + ", ".join(f"{w} {t:.2f}" for w, t in taus) + f" | {hits}/{len(taus)} |")
    lines.append("")

    # --- Part 1 against the agent and the gold order
    keys = part1_keys()
    cases = {c["id"]: c for c in json.loads(CASES.read_text(encoding="utf-8"))["cases"]}
    stated = {cid for cid in keys if cases[cid]["turns"][-1]["gold_profile"].get("ranking_priority")}
    summary = {True: [], False: []}
    lines += ["## Part 1 和 agent、标准答案的对照", "",
              "候选和 agent 名次见 `v6_key.csv`（从 V6 的图上读出房源 ID）。标准答案只比较在冻结数据里仍是 confirmed 的候选。",
              "注意：V6 的图是按 agent 运行时的数据画的，个别房源的租金和冻结数据不同（例如 500203570 图上 1,050，冻结数据 1,300）。", "",
              "| 题目 | 评审平均顺序 | agent 顺序 | 和 agent 的平均 τ-b | 第 1 名同 agent | 标准答案顺序 | 和标准答案的平均 τ-b | 第 1 名同标准答案 | agent 和标准答案的 τ-b | 备注 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for case, (agent, gold, dropped) in keys.items():
        ta, _, ha, cons = compare(r1, case, agent)
        tg, _, hg, _ = compare(r1, case, gold)
        ag = tau_b({l: i for i, l in enumerate(agent) if l in gold}, {l: i for i, l in enumerate(gold)})
        summary[case in stated].append((case, ta, tg, ag))
        lines.append(f"| {case} | {cons} | {' > '.join(agent)} | {ta:.2f} | {ha}/{len(r1)} | {' > '.join(gold)} | {tg:.2f} | {hg}/{len(r1)} | {ag:.2f} | "
                     + ("不是 confirmed：" + "、".join(dropped) if dropped else "") + " |")
    lines.append("")
    lines += ["### 按用户有没有给排序要求分组（平均 τ-b）", "",
              "| 分组 | 题目 | 评审 vs agent | 评审 vs 标准答案 | agent vs 标准答案 |", "|---|---|---|---|---|"]
    for flag, name in ((True, "用户给了排序要求"), (False, "用户没给排序要求（标准答案默认按租金）")):
        rows = summary[flag]
        mean = lambda i: sum(r[i] for r in rows) / len(rows)
        lines.append(f"| {name} | {'、'.join(r[0] for r in rows)} | {mean(1):.2f} | {mean(2):.2f} | {mean(3):.2f} |")
    lines.append("")

    # --- comments
    lines += ["## 评审留言", ""]
    for part, notes, rr in (("Part 1", n1, r1), ("Part 2", n2, r2)):
        for who in sorted(notes):
            for case, text in sorted(notes[who].items()):
                tag = "（已被 Part 2 取代）" if part == "Part 1" and case in SUPERSEDED else ""
                lines.append(f"- {part} {case} {who}{tag}：{text}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
