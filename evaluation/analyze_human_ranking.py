"""Build the final V6 human-ranking set (15 cases) and analyse it.

The V6 form had 15 cases. In A08, A09, B01 and G04 one candidate had been delisted
by the 11/02 freeze, so those four were asked again with candidates from the gold
answer. This script puts the 11 kept cases and the 4 replacements together as one
questionnaire, then analyses it.

Inputs (raw exports and keys, not changed):
    human_ranking/responses/v6_part1_responses.csv     V6 form, 15 cases (A08, A09, B01, G04 not used)
    human_ranking/responses/v6_part2_responses.csv     the 4 replacement cases
    human_ranking/图片/<case>.png                       V6 images
    human_ranking/v6_replacement/<case>.png, key.csv    replacement images and their key
    human_ranking/v6_key.csv                           V6 candidates: listing, agent rank, gold rank
    source/agent_profile20_20261105T032944Z.jsonl      agent run the V6 candidates came from
    human_ranking/v6_final/system_order.csv            the frozen system's order of the replacement
                                                       candidates (human_ranking_system_order.py)

Reference orders: for the 11 kept cases, the 11/05 agent's order (the candidates are its top 3);
for the 4 replacements, which the agent never ranked in full, the frozen system's order (no model).

Output: human_ranking/v6_final/
    images/<case>.png      the 15 images reviewers ranked
    responses.csv          one row per reviewer, 15 cases
    key.csv                one row per candidate: listing, source, agent rank, gold status and rank
    analysis.md            agreement between reviewers and with the gold and agent orders
    questionnaire.html     the full questionnaire with every answer
    DSS5105_V6_human_ranking.pdf   the same, as PDF (Chrome headless)

Run from the repository root:
    .venv/Scripts/python.exe evaluation/analyze_human_ranking.py
"""

from __future__ import annotations

import csv
import html
import json
import math
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
HR = HERE / "human_ranking"
RESP = HR / "responses"
OUT = HR / "v6_final"
CASES_FILE = HERE / "cases" / "cases.json"
SYSTEM_ORDER = OUT / "system_order.csv"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

import gold as gold_rules  # noqa: E402  (evaluation/gold.py, pandas only)

# Values a V6 image showed that differ from the frozen data. The 11/05 agent run used data from
# before the 11/02 recheck, where 500203570 was 1,050; the frozen data has 1,300. The
# questionnaire gold uses what reviewers and the agent saw, so all three are compared on the same
# facts. The system's own gold answers (gold_answers.json) still use the frozen data.
SHOWN_RENT = {"500203570": 1050}

ORDER = ["A01", "A02", "A04", "A05", "A08", "A09", "B01", "B02", "B03", "B06", "G01", "G02", "G03", "G04", "G05"]
REPLACED = {"A08", "A09", "B01", "G04"}
# The same reviewer typed a different code once; the timestamps and comments match.
ALIASES = {"1ljy": "ljy"}
PRIORITY = {"price": "租金低", "commute": "到学院通勤短", "mrt": "MRT 步行近", "space": "面积大",
            "food_places": "1 km 内餐饮多"}
CATEGORY = {"A": "A 明确条件", "B": "B 未知字段", "G": "G 多轮修改"}

# What stands out in each case, written after reading the answers, images and key.
NOTES = {
    "A01": "按图上的月租算：B、C 都是 Fragrance Court、1,050，租金相同算并列；A 是 1,200。标准答案 B=C > A。"
           "5 人都把 B 或 C 排第一、A 排最后；agent 的 B > C > A 也和标准答案一致（标准答案里 B、C 并列，0.82 已经是能达到的最高值）。"
           "lys、wxy 留言 B 的卫生间比 C 多，这是租金相同时用来区分的理由。",
    "A02": "评审之间分歧大（W 低）。用户没说怎么排，标准答案默认按租金。多数人第一名选了 C，备注提到 C 家具齐全、离地铁近。",
    "A04": "用户要求先按通勤、再按租金。评审之间一致性高，5 人都把 C 排第一（wxy 是 A、C 并列第一），和 agent、标准答案相同。",
    "A05": "用户没说怎么排。评审之间分歧较大，第一名和标准答案相同的只有 2 人。",
    "A08": "替换题，用户要求先按面积、再 MRT、再租金。5 人都把面积最大的 A 排第一。"
           "分歧在 B（Icon）：面积最小，但离 MRT 只要 4 分钟、周边餐饮最多。Jason、ljy 把它放到第 2，说明他们把 MRT 看得比用户说的面积优先更重。"
           "现在的系统给这 5 个候选的名次和标准答案完全一样（第 1、2、3、57、59 名）。",
    "A09": "替换题，用户要求先按餐饮数、再 MRT。一致性最低的一题：lys、wxy 和标准答案完全一致，ljy 只调换了前两名；"
           "Jason 把餐饮最少的 C（750）排第 2，看起来主要按租金排；zfy 把餐饮最多的 D 排最后，和标准答案接近相反（zfy 的 A08 和标准答案完全一致，原因不确定，可以问本人）。"
           "现在的系统给这 5 个候选的名次和标准答案完全一样。",
    "B01": "替换题。只有 3 个候选，最便宜的 A 离 MRT 也只要 4 分钟，几乎不用取舍，5 人都和标准答案完全一致，现在的系统也一样。",
    "B02": "用户没说怎么排，标准答案默认按租金：A、B 都是 1,050（并列），C 是 1,100。评审之间比较一致（W 0.76），5 人都把 C 排最后，和标准答案一致；"
           "agent 却把 C 排第一（τ −0.82）。留言提到 C 租金最贵、A 卫生间多。",
    "B03": "用户没说怎么排。评审第一名多数选 A，agent 和标准答案的第一名都是 C。",
    "B06": "用户没说怎么排。wxy 给了并列名次。评审和标准答案的一致性是负的。",
    "G01": "第 2 轮用户说 near NUS，按约定应以通勤为排序重点；但图上'排序重点'写的是'综合适合程度'（agent 当时没识别出通勤优先，这个问题后来修好了）。"
           "agent 的顺序和标准答案完全相反（τ = −1.00），评审更接近标准答案。",
    "G02": "第 2 轮用户改成通勤优先。A 到学院 20 分钟最短；B、C 都是 22 分钟、1,050（并列）。标准答案 A > B=C。"
           "agent 把 A 排最后（τ −0.82），说明当时没有按通勤排。评审之间几乎没有共识（W 0.04），3 人把 A 排第一。",
    "G03": "用户没说怎么排。评审之间一致性低。",
    "G04": "替换题。用户没说怎么排，图上的'租金低优先'是标准答案的默认规则。E、A 租金都是 750，算并列。"
           "lys 把最便宜的 D 排第 4，备注写着 D 是合住、A 和 B 离 MRT 远、C 没厕所；zfy 把最贵的 C 排第一。说明'租金低优先'不是大家都认同的默认。"
           "现在的系统在用户没说排序时同时看 MRT 和租金，排成 E > D > C > B > A：把 MRT 最近的 E 排第一，把离 MRT 20 分钟的 A 排最后，"
           "和 lys 的考虑接近。按约定，用户没说排序时不检查顺序，所以这里和标准答案不同不算错。",
    "G05": "第 1 轮说想离 NUS 近（按约定以通勤为排序重点），第 2 轮预算降到 1,500、通勤不超过 30 分钟。"
           "B 到学院 20 分钟最短；A、C 都是 22 分钟、1,050（并列）。标准答案 B > A=C，agent 的 B > A > C 和它一致。"
           "评审之间几乎没有共识（W 0.07），3 人把 B 排第一；lys 把 A、C 并列第一、B 排最后。",
}


# ---------- reading and merging

def read(path: Path):
    """{reviewer: {case: {label: rank or None}}}, {reviewer: {case: comment}}, {reviewer: timestamp}."""
    rows = list(csv.reader(path.open(encoding="utf-8-sig")))
    head, body = rows[0], rows[1:]
    ranks, notes, when = defaultdict(dict), defaultdict(dict), {}
    for r in body:
        who = ALIASES.get(r[1].strip(), r[1].strip())
        when[who] = r[0]
        for col, val in zip(head[2:], r[2:]):
            m = re.match(r"(\w\d\d) \| (?:候选|Candidate) ([A-E]) ", col)
            if m:
                case, lab = m.groups()
                ranks[who].setdefault(case, {})[lab] = int(val) if val.strip().isdigit() else None
            elif val.strip():
                notes[who][col.split(" |")[0]] = val.strip()
    return ranks, notes, when


def merge():
    r1, n1, t1 = read(RESP / "v6_part1_responses.csv")
    r2, n2, t2 = read(RESP / "v6_part2_responses.csv")
    assert set(r1) == set(r2), (sorted(r1), sorted(r2))
    ranks, notes = {}, {}
    for who in sorted(r1):
        ranks[who] = {c: (r2 if c in REPLACED else r1)[who][c] for c in ORDER}
        notes[who] = {c: (n2 if c in REPLACED else n1)[who].get(c, "") for c in ORDER}
    return ranks, notes, t1, t2


_DATA = None


def shown_gold(case: dict):
    """For the case's last turn, by gold.py on the frozen data with the values the V6 images showed
    (SHOWN_RENT): the confirmed listings ranked, the listings needing confirmation, and a function
    giving each listing's ranking key (equal keys are tied; gold.py only breaks them by listing ID)."""
    global _DATA
    if _DATA is None:
        df, commute = gold_rules.load()
        for listing, rent in SHOWN_RENT.items():
            df.loc[df["listing_id"] == listing, "rent"] = float(rent)
        _DATA = df, commute
    df, commute = _DATA
    profile, faculty = case["turns"][-1]["gold_profile"], case["preconditions"].get("faculty")
    answer = gold_rules.gold_for_turn(df, commute, profile, faculty)
    df_idx = df.set_index("listing_id")
    key = lambda lid: gold_rules.rank_key(lid, df_idx, profile.get("ranking_priority"), faculty, commute)  # noqa: E731
    return answer["confirmed_ids_ranked"], [x["listing_id"] for x in answer["needs_confirmation"]], key


def read_key(cases: dict):
    """{case: [{label, listing, source, agent, status, gold, gold_key}]} for the 15 cases."""
    names = {"gold_top3": "标准答案前 3 名", "random_confirmed": "标准答案中随机抽取", "cheapest_remaining": "其余符合房源中最便宜的"}
    rows = [(r["Case ID"], r["Label"], r["Listing ID"], "agent 前 3 名（11/05 运行）", int(r["Agent rank"]))
            for r in csv.DictReader((HR / "v6_key.csv").open(encoding="utf-8-sig")) if r["Case ID"] not in REPLACED]
    replaced = list(csv.DictReader((HR / "v6_replacement" / "key.csv").open(encoding="utf-8-sig")))
    rows += [(r["Case ID"], r["Label"], r["Listing ID"], names[r["Sampling source"]], None) for r in replaced]
    # Where the frozen system ranks each replacement candidate (human_ranking_system_order.py).
    system = {(r["Case ID"], r["Label"]): (int(r["System rank among confirmed"]), int(r["System confirmed total"]))
              for r in csv.DictReader(SYSTEM_ORDER.open(encoding="utf-8-sig")) if r["System rank among confirmed"]}
    out = defaultdict(list)
    for case_id, label, lid, source, agent in rows:
        confirmed, unknown, key = shown_gold(cases[case_id])
        status = "confirmed" if lid in confirmed else "needs_confirmation" if lid in unknown else "excluded"
        out[case_id].append({"label": label, "listing": lid, "source": source, "agent": agent, "status": status,
                             "gold": confirmed.index(lid) + 1 if lid in confirmed else None,
                             "gold_total": len(confirmed),
                             "gold_key": key(lid) if lid in confirmed else None,
                             "system": system.get((case_id, label))})
    # The replacement key was written from the same gold answer; check it still agrees.
    for r in replaced:
        mine = next(k for k in out[r["Case ID"]] if k["label"] == r["Label"])
        assert mine["gold"] == int(r["Gold rank among confirmed"]), (r["Case ID"], r["Label"])
    return {c: sorted(out[c], key=lambda x: x["label"]) for c in ORDER}


# ---------- statistics

def avg_ranks(order: dict[str, int | None]) -> dict[str, float]:
    """A reviewer's places (ties allowed) as average ranks 1..n."""
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
    return w, chi2_sf(m * (n - 1) * w, n - 1)


def chi2_sf(x: float, df: int) -> float:
    """Upper tail of chi-square for even df (closed form); 3 or 5 candidates give df 2 or 4."""
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
            da, db = a[labels[i]] - a[labels[j]], b[labels[i]] - b[labels[j]]
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


def fmt_order(r: dict[str, float]) -> str:
    groups = defaultdict(list)
    for k, v in r.items():
        groups[v].append(k)
    return " > ".join("=".join(sorted(groups[v])) for v in sorted(groups))


def case_stats(case: str, ranks: dict, key: list[dict]) -> dict:
    labels = [c["label"] for c in key]
    per = {who: avg_ranks(ranks[who][case]) for who in ranks}
    w, p = kendall_w(list(per.values()), labels)
    mean = {l: sum(r[l] for r in per.values()) / len(per) for l in labels}
    confirmed = sorted((c for c in key if c["status"] == "confirmed"), key=lambda c: c["gold"])
    # Candidates with equal ranking keys share a place: only the listing ID would separate them.
    places = sorted({c["gold_key"] for c in confirmed})
    gold = avg_ranks({c["label"]: places.index(c["gold_key"]) for c in confirmed})
    gold_order = [c["label"] for c in confirmed]
    # The reference order: the 11/05 agent's for the kept cases, the frozen system's for the replacements.
    kind = "agent" if any(c["agent"] for c in key) else "system" if any(c["system"] for c in key) else None
    place = (lambda c: c["agent"]) if kind == "agent" else (lambda c: c["system"] and c["system"][0])
    agent_order = [c["label"] for c in sorted((c for c in key if place(c)), key=place)] if kind else []
    agent = {l: i + 1 for i, l in enumerate(agent_order)}

    def against(ref):
        """Each reviewer's tau-b with `ref`, and how many put one of ref's first (or tied first) on top."""
        if not ref:
            return None
        rows = {who: tau_b({k: v for k, v in r.items() if k in ref}, ref) for who, r in per.items()}
        best = {k for k, v in ref.items() if v == min(ref.values())}
        firsts = 0
        for r in per.values():
            mine = {k: v for k, v in r.items() if k in ref}
            firsts += bool(best & {k for k, v in mine.items() if v == min(mine.values())})
        return {"taus": rows, "mean": sum(rows.values()) / len(rows), "first": firsts}

    return {
        "labels": labels, "per": per, "w": w, "p": p, "mean": mean,
        "consensus": sorted(labels, key=lambda l: mean[l]),
        "firsts": {l: sum(min(r.values()) == r[l] for r in per.values()) for l in labels},
        "gold_order": gold_order, "gold_text": fmt_order(gold), "agent_order": agent_order, "kind": kind,
        "ref_name": {"agent": "agent", "system": "系统"}.get(kind, ""),
        "ref_text": (" > ".join(agent_order) + ("（系统）" if kind == "system" else "")) if kind else "–",
        "vs_gold": against(gold), "vs_agent": against(agent),
        "agent_vs_gold": tau_b({l: v for l, v in agent.items() if l in gold}, gold) if agent else None,
    }


# ---------- outputs

def write_csvs(ranks, notes, t1, t2, keys):
    head = ["评估者编号", "原题提交时间", "替换题提交时间"]
    for c in ORDER:
        head += [f"{c} | 候选 {c_['label']} 名次" for c_ in keys[c]] + [f"{c} | 排序依据（选填）"]
    with (OUT / "responses.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        for who in sorted(ranks):
            row = [who, t1[who], t2[who]]
            for c in ORDER:
                row += [ranks[who][c][k["label"]] if ranks[who][c][k["label"]] is not None else "无法判断" for k in keys[c]]
                row.append(notes[who][c])
            w.writerow(row)
    with (OUT / "key.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["Case ID", "Label", "Listing ID", "Candidate source", "Agent rank", "Gold status", "Gold rank among confirmed"])
        for c in ORDER:
            for k in keys[c]:
                w.writerow([c, k["label"], k["listing"], k["source"], k["agent"] or "", k["status"], k["gold"] or ""])


def describe(case: dict) -> tuple[list[str], str, bool]:
    """User turns, the faculty, and whether the user stated how to rank."""
    turns = [t["user"] for t in case["turns"]]
    prio = case["turns"][-1]["gold_profile"].get("ranking_priority") or []
    return turns, case["preconditions"].get("faculty") or "", bool(prio)


def priority_text(case: dict) -> str:
    prio = case["turns"][-1]["gold_profile"].get("ranking_priority") or []
    if not prio:
        return "用户没说（标准答案默认按租金低）"
    return " → ".join([PRIORITY[p] for p in prio] + ([] if "price" in prio else ["租金低"]))


def f2(x):
    return "–" if x is None else f"{x:.2f}"


def write_analysis(stats, cases, ranks, notes, keys):
    L = ["# V6 人工排序问卷结果（15 题）", "",
         f"评审 {len(ranks)} 人：{', '.join(sorted(ranks))}。评审编号别名：{', '.join(f'{k} → {v}' for k, v in ALIASES.items())}。",
         "A08、A09、B01、G04 用的是替换后的候选（原候选里有下架房源）。agent 没有对这些候选完整排过序，"
         "所以这 4 题的参考顺序是现在冻结的系统给这些候选的排序（不经过模型，见 `human_ranking_system_order.py`），表中标“（系统）”。"
         "其余 11 题的参考顺序是 agent 11/05 运行时推荐的顺序。", "",
         "## 每题结果", "",
         "| 题 | 用户说了排序 | 候选数 | W | p | 评审平均顺序 | 标准答案顺序 | 评审 vs 标准答案 τ-b | 第 1 名同标准答案 | agent / 系统顺序 | 评审 vs agent/系统 τ-b | agent/系统 vs 标准答案 τ-b |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in ORDER:
        s, (_, _, stated) = stats[c], describe(cases[c])
        vg, va = s["vs_gold"], s["vs_agent"]
        L.append(f"| {c} | {'是' if stated else '否'} | {len(s['labels'])} | {s['w']:.2f} | {s['p']:.3f} | {' > '.join(s['consensus'])} | "
                 f"{s['gold_text']} | {f2(vg['mean'])} | {vg['first']}/{len(ranks)} | "
                 f"{s['ref_text']} | {f2(va and va['mean'])} | {f2(s['agent_vs_gold'])} |")
    L += ["", "## 按用户有没有说排序分组（平均值）", "",
          "| 分组 | 题目 | W | 评审 vs 标准答案 | 评审 vs agent（只含 11 道原题） | agent vs 标准答案（只含 11 道原题） |", "|---|---|---|---|---|---|"]
    for name, flag in (("用户说了排序", True), ("用户没说排序", False)):
        cs = [c for c in ORDER if describe(cases[c])[2] == flag]
        ag = [c for c in cs if stats[c]["kind"] == "agent"]
        mean = lambda xs: sum(xs) / len(xs) if xs else float("nan")
        L.append(f"| {name} | {'、'.join(cs)} | {mean([stats[c]['w'] for c in cs]):.2f} | {mean([stats[c]['vs_gold']['mean'] for c in cs]):.2f} | "
                 f"{mean([stats[c]['vs_agent']['mean'] for c in ag]):.2f} | {mean([stats[c]['agent_vs_gold'] for c in ag]):.2f} |")
    L += ["", "## 每位评审和标准答案的一致性（τ-b）", "",
          "| 评审 | " + " | ".join(ORDER) + " | 平均 |", "|---|" + "---|" * (len(ORDER) + 1)]
    for who in sorted(ranks):
        vals = [stats[c]["vs_gold"]["taus"][who] for c in ORDER]
        L.append(f"| {who} | " + " | ".join(f"{v:.2f}" for v in vals) + f" | {sum(vals) / len(vals):.2f} |")
    L += ["", "## 数据检查", ""]
    issues = [f"- {who} {c}：并列 {fmt_order(avg_ranks(ranks[who][c]))}" for who in sorted(ranks) for c in ORDER
              if len(set(v for v in ranks[who][c].values() if v is not None)) < len(ranks[who][c])]
    L += issues or ["- 无"]
    L += ["", "## 评审留言", ""]
    L += [f"- {c} {who}：{notes[who][c]}" for c in ORDER for who in sorted(ranks) if notes[who][c]]
    (OUT / "analysis.md").write_text("\n".join(L) + "\n", encoding="utf-8")


CSS = """
@page { size: A4 landscape; margin: 9mm 11mm; }
* { box-sizing: border-box; }
body { font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif; color: #1f2a37; font-size: 10.5pt; margin: 0; }
h1 { font-size: 22pt; margin: 0 0 4mm; color: #172b45; }
h2 { font-size: 14pt; margin: 0 0 2.5mm; color: #172b45; }
h3 { font-size: 11.5pt; margin: 4mm 0 1.5mm; color: #172b45; }
p, li { line-height: 1.5; margin: 1mm 0; }
.page { page-break-after: always; }
.page:last-child { page-break-after: auto; }
.bar { background: #172b45; color: #fff; padding: 2.5mm 4mm; font-size: 13pt; margin-bottom: 2.5mm; display: flex; justify-content: space-between; }
.bar span { font-size: 10pt; opacity: .85; }
.req { font-size: 10pt; margin: 0 0 2mm; }
.req b { color: #36597f; font-weight: 600; }
.shot { display: block; margin: 0 auto; max-width: 100%; max-height: 158mm; border: 1px solid #d7dee8; }
table { border-collapse: collapse; width: 100%; font-size: 9.5pt; margin: 1mm 0 2mm; }
th { background: #dfe7f1; text-align: left; font-weight: 600; padding: 1.4mm 2mm; }
td { padding: 1.2mm 2mm; border-bottom: 1px solid #e5eaf1; vertical-align: top; }
tr.ref td { background: #f3f6fa; font-weight: 600; }
.num { text-align: center; }
.note { background: #fff8e6; border-left: 3px solid #e0a800; padding: 2mm 3mm; margin: 2mm 0; }
.muted { color: #5b6b7f; font-size: 9pt; }
.cols { display: flex; gap: 6mm; }
.cols > div { flex: 1; }
.tag { display: inline-block; padding: 0 2mm; border-radius: 2mm; font-size: 9pt; background: #e8eef6; color: #36597f; }
.tag.new { background: #fdeccc; color: #8a5a00; }
table.tight td, table.tight th { padding: 1mm 1.6mm; white-space: nowrap; }
"""


def esc(x) -> str:
    return html.escape(str(x))


def build_html(stats, cases, ranks, notes, keys, t1, t2) -> str:
    reviewers = sorted(ranks)
    dates = sorted({t.split(" ")[0] for t in list(t1.values()) + list(t2.values())})
    H = [f"<!doctype html><html><head><meta charset='utf-8'><title>DSS5105 人工排序问卷 V6</title><style>{CSS}</style></head><body>"]

    # cover and overview
    H.append("<div class='page'><h1>DSS5105 人工房源排序问卷 V6（完整版）</h1>")
    H.append(f"<p>15 道题 · 评审 {len(reviewers)} 人（{', '.join(reviewers)}）· 填写时间 {dates[0]} 至 {dates[-1]}</p>")
    H.append("<h3>问卷怎么做的</h3><ul>"
             "<li>每题给出用户的租房要求和 3 到 5 套候选房源的对比图，评审只排先后，不判断房源是否符合条件。名次可以并列，也可以选“无法判断”。</li>"
             "<li><b>11 道题</b>的候选是 agent 11/05 运行时推荐的前 3 名。</li>"
             "<li><b>A08、A09、B01、G04</b> 原来的候选里各有 1 套在 11/02 冻结数据前已下架，所以换成了从标准答案里抽取的 3 到 5 套候选，请同样 5 位评审重新排序（下文标为“替换题”）。"
             "agent 只会展示前 3 名，没有对这些候选完整排过序，所以这 4 题用现在冻结的系统给这些候选排一次（不经过模型），作为参考顺序。</li>"
             "<li>15 题都属于开发集，留出集没有做人工排序。</li></ul>")
    H.append("<h3>怎么读</h3><ul>"
             "<li><b>W</b>（Kendall's W）：评审之间排得是否一样，0 到 1，1 表示完全一样。</li>"
             "<li><b>τ-b</b>：两个顺序是否一致，−1 到 1，1 表示完全一致，−1 表示完全相反。表中是 5 位评审的平均。</li>"
             "<li><b>标准答案顺序</b>按 <code>CONVENTIONS.md</code> 第 5 节：用户说了优先项就依次比较，再比租金；没说就按租金。只比较确定符合的候选。"
             "所有排序依据都相同的候选算并列，用“=”表示。</li>"
             "<li><b>数值以图上为准</b>：500203570 的月租按图上的 1,050 算（冻结数据后来复查是 1,300），这样评审、agent 和标准答案用的是同一组数字。"
             "影响 A01、B02、G02、G05。系统评估用的标准答案（<code>gold_answers.json</code>）不变，仍按冻结数据。</li>"
             "<li><b>agent / 系统顺序</b>：11 道原题是 agent 11/05 运行时（旧数据、排序修复前）推荐的顺序；"
             "4 道替换题是现在冻结的系统对这些候选的排序，标“（系统）”。</li></ul>")

    def mean(xs):
        return sum(xs) / len(xs) if xs else float("nan")
    groups = {flag: [c for c in ORDER if describe(cases[c])[2] == flag] for flag in (True, False)}
    H.append("<h3>按用户有没有说排序分组（平均值）</h3><table><tr><th>分组</th><th>题目</th><th class='num'>W</th>"
             "<th class='num'>评审 vs 标准答案</th><th class='num'>评审 vs agent</th><th class='num'>agent vs 标准答案</th></tr>")
    for flag, name in ((True, "用户说了排序"), (False, "用户没说排序")):
        cs = groups[flag]
        ag = [c for c in cs if stats[c]["kind"] == "agent"]
        H.append(f"<tr><td>{name}</td><td>{'、'.join(cs)}</td><td class='num'>{mean([stats[c]['w'] for c in cs]):.2f}</td>"
                 f"<td class='num'>{mean([stats[c]['vs_gold']['mean'] for c in cs]):.2f}</td>"
                 f"<td class='num'>{mean([stats[c]['vs_agent']['mean'] for c in ag]):.2f}</td>"
                 f"<td class='num'>{mean([stats[c]['agent_vs_gold'] for c in ag]):.2f}</td></tr>")
    H.append("</table><p class='muted'>“评审 vs agent”“agent vs 标准答案”只算 11 道原题（11/05 的 agent）。4 道替换题对照的是现在的系统，单独列在下一页。</p></div>")

    H.append("<div class='page'><h2>每题结果</h2><table class='tight'><tr><th>题</th><th>用户说了排序</th><th class='num'>候选数</th><th class='num'>W</th>"
             "<th>评审平均顺序</th><th>标准答案顺序</th><th class='num'>评审 vs 标准答案</th><th class='num'>第 1 名同标准答案</th>"
             "<th>agent / 系统顺序</th><th class='num'>评审 vs agent/系统</th><th class='num'>agent/系统 vs 标准答案</th></tr>")
    for c in ORDER:
        s, (_, _, stated) = stats[c], describe(cases[c])
        va = s["vs_agent"]
        new = " <span class='tag new'>替换题</span>" if c in REPLACED else ""
        H.append(f"<tr><td><b>{c}</b>{new}</td>"
                 f"<td>{'是' if stated else '否'}</td><td class='num'>{len(s['labels'])}</td><td class='num'>{s['w']:.2f}</td>"
                 f"<td>{' > '.join(s['consensus'])}</td><td>{s['gold_text']}</td><td class='num'>{f2(s['vs_gold']['mean'])}</td>"
                 f"<td class='num'>{s['vs_gold']['first']}/{len(reviewers)}</td><td>{s['ref_text']}</td>"
                 f"<td class='num'>{f2(va and va['mean'])}</td><td class='num'>{f2(s['agent_vs_gold'])}</td></tr>")
    H.append("</table><p class='muted'>“=” 表示并列：这些候选的租金、通勤等排序依据完全相同。"
             "“（系统）”是现在冻结的系统对替换题候选的排序；其余是 agent 11/05 的顺序。</p>")
    H.append("<h3>每位评审和标准答案的一致性（τ-b）</h3><table class='tight'><tr><th>评审</th>"
             + "".join(f"<th class='num'>{c}</th>" for c in ORDER) + "<th class='num'>平均</th></tr>")
    for who in reviewers:
        vals = [stats[c]["vs_gold"]["taus"][who] for c in ORDER]
        H.append(f"<tr><td>{esc(who)}</td>" + "".join(f"<td class='num'>{v:.2f}</td>" for v in vals) + f"<td class='num'><b>{mean(vals):.2f}</b></td></tr>")
    H.append("</table></div>")

    H.append(f"<div class='page'><h2>主要发现</h2>{FINDINGS}</div>")

    # one case = image page + result page
    for i, c in enumerate(ORDER, 1):
        case, s, key = cases[c], stats[c], keys[c]
        turns, faculty, stated = describe(case)
        tag = "替换题 · 候选来自标准答案" if c in REPLACED else "候选来自 agent 11/05 运行的前 3 名"
        req = "".join(f"<div><b>{'第 ' + str(j) + ' 轮' if len(turns) > 1 else '用户'}：</b>{esc(t)}</div>" for j, t in enumerate(turns, 1))
        H.append(f"<div class='page'><div class='bar'>第 {i} 题 · {c} · {CATEGORY[c[0]]}<span>{tag}</span></div>"
                 f"<div class='req'>{req}<div><b>学院：</b>{esc(faculty or '未设定')}　<b>排序要求：</b>{esc(priority_text(case))}</div></div>"
                 f"<img class='shot' src='images/{c}.png'></div>")

        H.append(f"<div class='page'><div class='bar'>第 {i} 题 · {c} · 结果<span>W = {s['w']:.2f}（p = {s['p']:.3f}）</span></div>")
        H.append("<div class='cols'><div><h3>评审的名次</h3><table><tr><th>评审</th>"
                 + "".join(f"<th class='num'>{l}</th>" for l in s["labels"])
                 + "<th>顺序</th><th class='num'>vs 标准答案</th>" + (f"<th class='num'>vs {s['ref_name']}</th>" if s["vs_agent"] else "") + "</tr>")
        for who in reviewers:
            raw = ranks[who][c]
            H.append(f"<tr><td>{esc(who)}</td>" + "".join(f"<td class='num'>{raw[l] if raw[l] is not None else '?'}</td>" for l in s["labels"])
                     + f"<td>{fmt_order(s['per'][who])}</td><td class='num'>{s['vs_gold']['taus'][who]:.2f}</td>"
                     + (f"<td class='num'>{s['vs_agent']['taus'][who]:.2f}</td>" if s["vs_agent"] else "") + "</tr>")
        H.append("<tr class='ref'><td>平均名次</td>" + "".join(f"<td class='num'>{s['mean'][l]:.1f}</td>" for l in s["labels"])
                 + f"<td>{' > '.join(s['consensus'])}</td><td class='num'>{s['vs_gold']['mean']:.2f}</td>"
                 + (f"<td class='num'>{s['vs_agent']['mean']:.2f}</td>" if s["vs_agent"] else "") + "</tr></table>")

        system = s["kind"] == "system"
        H.append("<h3>候选和参考顺序</h3><table><tr><th>候选</th><th>房源 ID</th><th>来源</th>"
                 + ("<th class='num'>系统名次</th>" if system else "<th class='num'>agent 名次</th>")
                 + "<th>是否符合</th><th class='num'>标准答案名次</th><th class='num'>评审第 1 名票数（并列都算）</th></tr>")
        for k in key:
            status = {"confirmed": "符合", "excluded": "不符合"}.get(k["status"], k["status"])
            ref = f"{k['system'][0]}/{k['system'][1]}" if system and k["system"] else (k["agent"] or "–")
            gold_rank = f"{k['gold']}/{k['gold_total']}" if k["gold"] else "–"
            H.append(f"<tr><td>{k['label']}</td><td>{k['listing']}</td><td>{esc(k['source'])}</td><td class='num'>{ref}</td>"
                     f"<td>{status}</td><td class='num'>{gold_rank}</td><td class='num'>{s['firsts'][k['label']]}</td></tr>")
        H.append("</table><p class='muted'>标准答案名次是在全部符合房源中的名次（如 57/62）；排序依据完全相同时按房源 ID 排，比较时算并列。"
                 + ("系统名次是现在冻结的系统在全部符合房源中给出的名次（不经过模型）。" if system else "agent 名次是 agent 11/05 推荐时的先后。") + "</p>")
        H.append(f"<p><b>标准答案顺序</b>：{s['gold_text']}　·　第 1 名和标准答案相同：{s['vs_gold']['first']}/{len(reviewers)}</p>")
        if s["vs_agent"]:
            label = "系统顺序（现在冻结的系统，不经过模型）" if system else "agent 顺序（11/05 运行）"
            H.append(f"<p><b>{label}</b>：{' > '.join(s['agent_order'])}　·　vs 标准答案 τ-b = {s['agent_vs_gold']:.2f}</p>")
        H.append("</div><div>")
        H.append(f"<h3>要点</h3><div class='note'>{esc(NOTES[c])}</div>")
        said = [(who, notes[who][c]) for who in reviewers if notes[who][c]]
        H.append("<h3>评审留言</h3>" + ("<ul>" + "".join(f"<li><b>{esc(w)}</b>：{esc(t)}</li>" for w, t in said) + "</ul>" if said else "<p class='muted'>无</p>"))
        H.append("</div></div></div>")
    H.append("</body></html>")
    return "".join(H)


FINDINGS = """
<h3>结论</h3><ol>
<li><b>用户说了排序的题，评审更接近标准答案。</b>平均 τ-b 是 0.49，没说排序的题是 0.34。单轮、要求明确的 A01、A04、A08，5 人的第 1 名都和标准答案相同。B01、B02 用户没说排序，但取舍简单，5 人的第 1 名也都和标准答案相同。</li>
<li><b>用户没说怎么排时，“按租金低”这个默认不是共识。</b>评审会考虑家具、合住、MRT、卫浴、房东同住（见各题留言）。也就是说，没说排序的题本来就没有唯一正确的顺序，自动评分只检查说了排序的题是合理的。两组评审之间的一致性（W）差不多，都在 0.4 左右。</li>
<li><b>多轮修改题即使说了通勤优先，评审之间也几乎没有共识。</b>G01、G02、G05 的 W 只有 0.04 到 0.16，第 1 名和标准答案相同的都是 3/5。G01 的图上“排序重点”写的是“综合适合程度”，评审不一定知道要按通勤排。</li>
<li><b>优先项和直觉冲突时会有分歧。</b>A08 里离 MRT 近的、A09 里便宜的房源，被部分评审往前排，即使用户说了别的优先项。</li>
<li><b>agent 的顺序来自 11/05 的运行，那时还没修排序。</b>G01 里 agent 和标准答案完全相反，G02 里 agent 把通勤最短的 A 排在最后（用户要按通勤排，agent 没有做到）。11/06 改成按优先项依次严格比较后，开发集 dev5 和留出集里，说了排序的题前 3 名都和标准答案一致。所以这里的“评审 vs agent”反映的是修复前的系统。</li>
<li><b>现在冻结的系统和标准答案一致。</b>替换题的候选 agent 没有完整排过，所以用现在冻结的系统（不经过模型）给它们排了一次：A08、A09、B01 每个候选的名次都和标准答案相同，包括排在第 57、59 名的房源。G04 用户没说排序，系统同时看 MRT 和租金，和只看租金的标准答案不同，按约定不算错。</li>
</ol>
<h3>局限</h3><ul>
<li>评审只有 5 人，都是组员；每题 3 到 5 个候选；只覆盖开发集。</li>
<li>11 道原题的对比图是按 agent 运行时的数据画的。只有 500203570 的月租和冻结数据不同：图上是 11/02 复查前的 1,050，冻结数据是复查后的 1,300。问卷的标准答案按图上的 1,050 算；如果按 1,300 算，它在 A01 超出预算，B02、G02、G05 的顺序也会不同。</li>
<li>候选的排序依据完全相同时算并列（A01、B02、G02、G05 里两套 Fragrance Court；G04 的 A、E）。标准答案本身只按房源 ID 区分它们，这个区分对人没有意义。</li>
<li>4 道替换题的图是英文的，其余是中文的，评审看到的就是这样。</li>
</ul>
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "images").mkdir(exist_ok=True)
    for c in ORDER:
        src = HR / ("v6_replacement" if c in REPLACED else "图片") / f"{c}.png"
        shutil.copyfile(src, OUT / "images" / f"{c}.png")
    ranks, notes, t1, t2 = merge()
    cases = {c["id"]: c for c in json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]}
    keys = read_key(cases)
    stats = {c: case_stats(c, ranks, keys[c]) for c in ORDER}
    write_csvs(ranks, notes, t1, t2, keys)
    write_analysis(stats, cases, ranks, notes, keys)
    page = OUT / "questionnaire.html"
    page.write_text(build_html(stats, cases, ranks, notes, keys, t1, t2), encoding="utf-8")
    pdf, fresh = OUT / "DSS5105_V6_human_ranking.pdf", OUT / "_printing.pdf"
    fresh.unlink(missing_ok=True)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={fresh}", page.as_uri()], check=True, capture_output=True)
    # Chrome exits 0 even when it writes nothing; replacing fails loudly if the old PDF is open somewhere.
    if not fresh.exists() or fresh.stat().st_size == 0:
        raise SystemExit("Chrome did not write the PDF")
    fresh.replace(pdf)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
