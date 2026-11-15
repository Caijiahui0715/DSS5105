"""Build the final V6 human-ranking set (15 cases) and analyse it.

The V6 form had 15 cases. In A08, A09, B01 and G04 one candidate had been delisted
by the 11/02 freeze, so those four were asked again with candidates from the gold
answer. This script puts the 11 kept cases and the 4 replacements together as one
questionnaire, then analyses it.

Inputs (raw exports and keys, not changed):
    human_ranking/responses/v6_part1_responses.csv     V6 form, 15 cases (A08, A09, B01, G04 not used)
    human_ranking/responses/v6_part2_responses.csv     the 4 replacement cases
    human_ranking/v6_images/<case>.png                   V6 images
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
PRIORITY = {"price": "lower rent", "commute": "shorter commute to the faculty", "mrt": "shorter MRT walk", "space": "larger area",
            "food_places": "more food places within 1 km"}
CATEGORY = {"A": "A explicit requirements", "B": "B unknown fields", "G": "G multi-turn update"}

# What stands out in each case, written after reading the answers, images and key.
NOTES = {
    "A01": "By the rents in the image: B and C are both Fragrance Court at 1,050, a tie on rent; A is 1,200. Gold answer B=C > A. "
           "All 5 reviewers put B or C first and A last; the agent's B > C > A also agrees with the gold answer (with B and C tied in the gold answer, 0.82 is the highest possible). "
           "lys and wxy commented that B has more bathrooms than C, their reason for separating two listings at the same rent.",
    "A02": "Reviewers disagree a lot (low W). The user did not say how to rank, so the gold answer ranks by rent by default. Most reviewers put C first, noting that C is fully furnished and close to the MRT.",
    "A04": "The user asked for commute first, then rent. Reviewers agree strongly: all 5 put C first (wxy put A and C joint first), as do the agent and the gold answer.",
    "A05": "The user did not say how to rank. Reviewers disagree fairly widely; only 2 put the gold answer's first choice first.",
    "A08": "Replacement case; the user asked for area first, then MRT, then rent. All 5 reviewers put A, the largest, first. "
           "They differ on B (Icon): the smallest, but only 4 minutes from the MRT and with the most food places nearby. Jason and ljy put it second, weighting the MRT above the user's stated area priority. "
           "The frozen system ranks these 5 candidates exactly as the gold answer does (1st, 2nd, 3rd, 57th and 59th).",
    "A09": "Replacement case; the user asked for food places first, then MRT. The case with the least agreement: lys and wxy match the gold answer exactly, and ljy only swapped the top two; "
           "Jason put C, with the fewest food places (750), second, apparently ranking mainly by rent; zfy put D, with the most food places, last, nearly the reverse of the gold answer (zfy's A08 matches the gold answer exactly; the reason is unclear and could be asked). "
           "The frozen system ranks these 5 candidates exactly as the gold answer does.",
    "B01": "Replacement case. Only 3 candidates, and the cheapest, A, is also just 4 minutes from the MRT, so there is hardly a trade-off: all 5 reviewers match the gold answer exactly, and so does the frozen system.",
    "B02": "The user did not say how to rank, so the gold answer ranks by rent: A and B are both 1,050 (tied), C is 1,100. Reviewers agree fairly well (W 0.76), and all 5 put C last, as the gold answer does; "
           "the agent put C first (τ −0.82). Comments mention that C has the highest rent and A more bathrooms.",
    "B03": "The user did not say how to rank. Most reviewers put A first; the agent and the gold answer both put C first.",
    "B06": "The user did not say how to rank. wxy gave tied ranks. Reviewers' agreement with the gold answer is negative.",
    "G01": "In turn 2 the user says near NUS, so by the conventions commute is the ranking focus; but the image's 'ranking focus' says 'overall suitability' (the agent then missed the commute priority; this was fixed later). "
           "The agent's order is the exact reverse of the gold answer (τ = −1.00); the reviewers are closer to the gold answer.",
    "G02": "In turn 2 the user switches to commute first. A has the shortest commute to the faculty, 20 minutes; B and C are both 22 minutes and 1,050 (tied). Gold answer A > B=C. "
           "The agent put A last (τ −0.82), so it did not rank by commute at the time. Reviewers have almost no consensus (W 0.04); 3 put A first.",
    "G03": "The user did not say how to rank. Reviewers agree little.",
    "G04": "Replacement case. The user did not say how to rank; the image's 'lower rent first' is the gold answer's default rule. E and A are both 750, a tie. "
           "lys put D, the cheapest, 4th, noting that D is shared, A and B are far from the MRT, and C has no toilet; zfy put C, the most expensive, first. So 'lower rent first' is not a default everyone accepts. "
           "With no stated ranking, the frozen system weighs MRT and rent together and ranks E > D > C > B > A: E, nearest the MRT, first and A, 20 minutes from the MRT, last, "
           "close to lys's reasoning. By the conventions the order is not checked when the user states no ranking, so differing from the gold answer here is not an error.",
    "G05": "Turn 1 asks to be near NUS (by the conventions, commute is the ranking focus); turn 2 lowers the budget to 1,500 with a commute of at most 30 minutes. "
           "B has the shortest commute to the faculty, 20 minutes; A and C are both 22 minutes and 1,050 (tied). Gold answer B > A=C; the agent's B > A > C agrees with it. "
           "Reviewers have almost no consensus (W 0.07); 3 put B first, and lys put A and C joint first and B last.",
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
    names = {"gold_top3": "gold top 3", "random_confirmed": "random from the gold answer", "cheapest_remaining": "cheapest of the other matches"}
    rows = [(r["Case ID"], r["Label"], r["Listing ID"], "agent top 3 (11/05 run)", int(r["Agent rank"]))
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
        "ref_name": {"agent": "agent", "system": "system"}.get(kind, ""),
        "ref_text": (" > ".join(agent_order) + (" (system)" if kind == "system" else "")) if kind else "–",
        "vs_gold": against(gold), "vs_agent": against(agent),
        "agent_vs_gold": tau_b({l: v for l, v in agent.items() if l in gold}, gold) if agent else None,
    }


# ---------- outputs

def write_csvs(ranks, notes, t1, t2, keys):
    head = ["Reviewer", "V6 form submitted", "Replacement form submitted"]
    for c in ORDER:
        head += [f"{c} | Candidate {c_['label']} rank" for c_ in keys[c]] + [f"{c} | Ranking rationale (optional)"]
    with (OUT / "responses.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        for who in sorted(ranks):
            row = [who, t1[who], t2[who]]
            for c in ORDER:
                row += [ranks[who][c][k["label"]] if ranks[who][c][k["label"]] is not None else "Cannot judge" for k in keys[c]]
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
        return "not stated (the gold answer defaults to lower rent)"
    return " → ".join([PRIORITY[p] for p in prio] + ([] if "price" in prio else ["lower rent"]))


def f2(x):
    return "–" if x is None else f"{x:.2f}"


def write_analysis(stats, cases, ranks, notes, keys):
    L = ["# V6 human-ranking questionnaire: results (15 cases)", "",
         f"{len(ranks)} reviewers: {', '.join(sorted(ranks))}. Reviewer code aliases: {', '.join(f'{k} → {v}' for k, v in ALIASES.items())}.",
         "A08, A09, B01 and G04 use replacement candidates (the original candidates included listings that were taken down). The agent never ranked all of these candidates, "
         "so the reference order for these 4 cases is how the frozen system ranks them (without the model; see `human_ranking_system_order.py`), marked \"(system)\" in the table. "
         "The reference order for the other 11 cases is the order the agent recommended in its 11/05 run.", "",
         "## Results by case", "",
         "| Case | Ranking stated | Candidates | W | p | Reviewers' mean order | Gold order | Reviewers vs gold τ-b | Same first as gold | Agent / system order | Reviewers vs agent/system τ-b | Agent/system vs gold τ-b |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in ORDER:
        s, (_, _, stated) = stats[c], describe(cases[c])
        vg, va = s["vs_gold"], s["vs_agent"]
        L.append(f"| {c} | {'yes' if stated else 'no'} | {len(s['labels'])} | {s['w']:.2f} | {s['p']:.3f} | {' > '.join(s['consensus'])} | "
                 f"{s['gold_text']} | {f2(vg['mean'])} | {vg['first']}/{len(ranks)} | "
                 f"{s['ref_text']} | {f2(va and va['mean'])} | {f2(s['agent_vs_gold'])} |")
    L += ["", "## By whether the user stated a ranking (means)", "",
          "| Group | Cases | W | Reviewers vs gold | Reviewers vs agent (11 original cases only) | Agent vs gold (11 original cases only) |", "|---|---|---|---|---|---|"]
    for name, flag in (("User stated a ranking", True), ("User stated no ranking", False)):
        cs = [c for c in ORDER if describe(cases[c])[2] == flag]
        ag = [c for c in cs if stats[c]["kind"] == "agent"]
        mean = lambda xs: sum(xs) / len(xs) if xs else float("nan")
        L.append(f"| {name} | {', '.join(cs)} | {mean([stats[c]['w'] for c in cs]):.2f} | {mean([stats[c]['vs_gold']['mean'] for c in cs]):.2f} | "
                 f"{mean([stats[c]['vs_agent']['mean'] for c in ag]):.2f} | {mean([stats[c]['agent_vs_gold'] for c in ag]):.2f} |")
    L += ["", "## Each reviewer's agreement with the gold answer (τ-b)", "",
          "| Reviewer | " + " | ".join(ORDER) + " | Mean |", "|---|" + "---|" * (len(ORDER) + 1)]
    for who in sorted(ranks):
        vals = [stats[c]["vs_gold"]["taus"][who] for c in ORDER]
        L.append(f"| {who} | " + " | ".join(f"{v:.2f}" for v in vals) + f" | {sum(vals) / len(vals):.2f} |")
    L += ["", "## Data checks", ""]
    issues = [f"- {who} {c}: tied {fmt_order(avg_ranks(ranks[who][c]))}" for who in sorted(ranks) for c in ORDER
              if len(set(v for v in ranks[who][c].values() if v is not None)) < len(ranks[who][c])]
    L += issues or ["- none"]
    L += ["", "## Reviewers' comments", "", "Quoted as the reviewers wrote them (mostly in Chinese).", ""]
    L += [f"- {c} {who}: {notes[who][c]}" for c in ORDER for who in sorted(ranks) if notes[who][c]]
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
    H = [f"<!doctype html><html><head><meta charset='utf-8'><title>DSS5105 human-ranking questionnaire V6</title><style>{CSS}</style></head><body>"]

    # cover and overview
    H.append("<div class='page'><h1>DSS5105 human listing-ranking questionnaire V6 (full version)</h1>")
    H.append(f"<p>15 cases · {len(reviewers)} reviewers ({', '.join(reviewers)}) · filled in from {dates[0]} to {dates[-1]}</p>")
    H.append("<h3>How the questionnaire was run</h3><ul>"
             "<li>Each case shows the user's rental request and a comparison image of 3 to 5 candidate listings. Reviewers only rank them; they do not judge whether a listing meets the conditions. Ranks may be tied, and \"Cannot judge\" is allowed.</li>"
             "<li>In <b>11 cases</b> the candidates are the top 3 the agent recommended in its 11/05 run.</li>"
             "<li><b>A08, A09, B01 and G04</b> each had one original candidate taken down before the data froze on 11/02, so they were replaced with 3 to 5 candidates drawn from the gold answer, and the same 5 reviewers ranked them again (marked \"replacement\" below). "
             "The agent shows only its top 3 and never ranked all of these candidates, so for these 4 cases the frozen system ranked them once (without the model) as the reference order.</li>"
             "<li>All 15 cases are from the dev set; the holdout had no human ranking.</li></ul>")
    H.append("<h3>How to read it</h3><ul>"
             "<li><b>W</b> (Kendall's W): whether the reviewers ranked alike, from 0 to 1, where 1 means identical.</li>"
             "<li><b>τ-b</b>: whether two orders agree, from −1 to 1, where 1 means identical and −1 completely reversed. The tables give the mean over the 5 reviewers.</li>"
             "<li><b>Gold order</b> follows <code>CONVENTIONS.md</code> section 5: with stated priorities, compare them in turn, then rent; otherwise by rent. Only confirmed candidates are compared. "
             "Candidates equal on every ranking value are tied, shown as \"=\".</li>"
             "<li><b>Values are those in the images</b>: listing 500203570's rent is taken as the 1,050 shown in the image (the frozen data, after a later recheck, has 1,300), so the reviewers, the agent and the gold answer use the same figures. "
             "This affects A01, B02, G02 and G05. The gold answers used for the system evaluation (<code>gold_answers.json</code>) are unchanged and still use the frozen data.</li>"
             "<li><b>Agent / system order</b>: for the 11 original cases, the order the agent recommended in its 11/05 run (old data, before the ranking fix); "
             "for the 4 replacement cases, the frozen system's order of the candidates, marked \"(system)\".</li></ul>")

    def mean(xs):
        return sum(xs) / len(xs) if xs else float("nan")
    groups = {flag: [c for c in ORDER if describe(cases[c])[2] == flag] for flag in (True, False)}
    H.append("<h3>By whether the user stated a ranking (means)</h3><table><tr><th>Group</th><th>Cases</th><th class='num'>W</th>"
             "<th class='num'>Reviewers vs gold</th><th class='num'>Reviewers vs agent</th><th class='num'>Agent vs gold</th></tr>")
    for flag, name in ((True, "User stated a ranking"), (False, "User stated no ranking")):
        cs = groups[flag]
        ag = [c for c in cs if stats[c]["kind"] == "agent"]
        H.append(f"<tr><td>{name}</td><td>{', '.join(cs)}</td><td class='num'>{mean([stats[c]['w'] for c in cs]):.2f}</td>"
                 f"<td class='num'>{mean([stats[c]['vs_gold']['mean'] for c in cs]):.2f}</td>"
                 f"<td class='num'>{mean([stats[c]['vs_agent']['mean'] for c in ag]):.2f}</td>"
                 f"<td class='num'>{mean([stats[c]['agent_vs_gold'] for c in ag]):.2f}</td></tr>")
    H.append("</table><p class='muted'>\"Reviewers vs agent\" and \"Agent vs gold\" cover only the 11 original cases (the 11/05 agent). The 4 replacement cases are compared with the frozen system and listed on the next page.</p></div>")

    H.append("<div class='page'><h2>Results by case</h2><table class='tight'><tr><th>Case</th><th>Ranking stated</th><th class='num'>Candidates</th><th class='num'>W</th>"
             "<th>Reviewers' mean order</th><th>Gold order</th><th class='num'>Reviewers vs gold</th><th class='num'>Same first as gold</th>"
             "<th>Agent / system order</th><th class='num'>Reviewers vs agent/system</th><th class='num'>Agent/system vs gold</th></tr>")
    for c in ORDER:
        s, (_, _, stated) = stats[c], describe(cases[c])
        va = s["vs_agent"]
        new = " <span class='tag new'>replacement</span>" if c in REPLACED else ""
        H.append(f"<tr><td><b>{c}</b>{new}</td>"
                 f"<td>{'yes' if stated else 'no'}</td><td class='num'>{len(s['labels'])}</td><td class='num'>{s['w']:.2f}</td>"
                 f"<td>{' > '.join(s['consensus'])}</td><td>{s['gold_text']}</td><td class='num'>{f2(s['vs_gold']['mean'])}</td>"
                 f"<td class='num'>{s['vs_gold']['first']}/{len(reviewers)}</td><td>{s['ref_text']}</td>"
                 f"<td class='num'>{f2(va and va['mean'])}</td><td class='num'>{f2(s['agent_vs_gold'])}</td></tr>")
    H.append("</table><p class='muted'>\"=\" means tied: these candidates have exactly the same ranking values (rent, commute and so on). "
             "\"(system)\" is the frozen system's order of the replacement candidates; the others are the agent's order from 11/05.</p>")
    H.append("<h3>Each reviewer's agreement with the gold answer (τ-b)</h3><table class='tight'><tr><th>Reviewer</th>"
             + "".join(f"<th class='num'>{c}</th>" for c in ORDER) + "<th class='num'>Mean</th></tr>")
    for who in reviewers:
        vals = [stats[c]["vs_gold"]["taus"][who] for c in ORDER]
        H.append(f"<tr><td>{esc(who)}</td>" + "".join(f"<td class='num'>{v:.2f}</td>" for v in vals) + f"<td class='num'><b>{mean(vals):.2f}</b></td></tr>")
    H.append("</table></div>")

    H.append(f"<div class='page'><h2>Main findings</h2>{FINDINGS}</div>")

    # one case = image page + result page
    for i, c in enumerate(ORDER, 1):
        case, s, key = cases[c], stats[c], keys[c]
        turns, faculty, stated = describe(case)
        tag = "replacement · candidates from the gold answer" if c in REPLACED else "candidates from the agent's top 3 (11/05 run)"
        req = "".join(f"<div><b>{'Turn ' + str(j) if len(turns) > 1 else 'User'}: </b>{esc(t)}</div>" for j, t in enumerate(turns, 1))
        H.append(f"<div class='page'><div class='bar'>Case {i} · {c} · {CATEGORY[c[0]]}<span>{tag}</span></div>"
                 f"<div class='req'>{req}<div><b>Faculty: </b>{esc(faculty or 'not set')}　<b>Ranking: </b>{esc(priority_text(case))}</div></div>"
                 f"<img class='shot' src='images/{c}.png'></div>")

        H.append(f"<div class='page'><div class='bar'>Case {i} · {c} · results<span>W = {s['w']:.2f} (p = {s['p']:.3f})</span></div>")
        H.append("<div class='cols'><div><h3>Reviewers' ranks</h3><table><tr><th>Reviewer</th>"
                 + "".join(f"<th class='num'>{l}</th>" for l in s["labels"])
                 + "<th>Order</th><th class='num'>vs gold</th>" + (f"<th class='num'>vs {s['ref_name']}</th>" if s["vs_agent"] else "") + "</tr>")
        for who in reviewers:
            raw = ranks[who][c]
            H.append(f"<tr><td>{esc(who)}</td>" + "".join(f"<td class='num'>{raw[l] if raw[l] is not None else '?'}</td>" for l in s["labels"])
                     + f"<td>{fmt_order(s['per'][who])}</td><td class='num'>{s['vs_gold']['taus'][who]:.2f}</td>"
                     + (f"<td class='num'>{s['vs_agent']['taus'][who]:.2f}</td>" if s["vs_agent"] else "") + "</tr>")
        H.append("<tr class='ref'><td>Mean rank</td>" + "".join(f"<td class='num'>{s['mean'][l]:.1f}</td>" for l in s["labels"])
                 + f"<td>{' > '.join(s['consensus'])}</td><td class='num'>{s['vs_gold']['mean']:.2f}</td>"
                 + (f"<td class='num'>{s['vs_agent']['mean']:.2f}</td>" if s["vs_agent"] else "") + "</tr></table>")

        system = s["kind"] == "system"
        H.append("<h3>Candidates and reference order</h3><table><tr><th>Candidate</th><th>Listing ID</th><th>Source</th>"
                 + ("<th class='num'>System rank</th>" if system else "<th class='num'>Agent rank</th>")
                 + "<th>Matches?</th><th class='num'>Gold rank</th><th class='num'>Reviewers ranking it first (ties count)</th></tr>")
        for k in key:
            status = {"confirmed": "match", "excluded": "no match"}.get(k["status"], k["status"])
            ref = f"{k['system'][0]}/{k['system'][1]}" if system and k["system"] else (k["agent"] or "–")
            gold_rank = f"{k['gold']}/{k['gold_total']}" if k["gold"] else "–"
            H.append(f"<tr><td>{k['label']}</td><td>{k['listing']}</td><td>{esc(k['source'])}</td><td class='num'>{ref}</td>"
                     f"<td>{status}</td><td class='num'>{gold_rank}</td><td class='num'>{s['firsts'][k['label']]}</td></tr>")
        H.append("</table><p class='muted'>The gold rank is the rank among all matching listings (for example 57/62); where the ranking values are identical, listings are ordered by ID, but count as tied in comparisons. "
                 + ("The system rank is the frozen system's rank among all matching listings (without the model)." if system else "The agent rank is the order of the agent's 11/05 recommendation.") + "</p>")
        H.append(f"<p><b>Gold order</b>: {s['gold_text']}　·　same first as gold: {s['vs_gold']['first']}/{len(reviewers)}</p>")
        if s["vs_agent"]:
            label = "System order (the frozen system, without the model)" if system else "Agent order (11/05 run)"
            H.append(f"<p><b>{label}</b>: {' > '.join(s['agent_order'])}　·　vs gold τ-b = {s['agent_vs_gold']:.2f}</p>")
        H.append("</div><div>")
        H.append(f"<h3>Notes</h3><div class='note'>{esc(NOTES[c])}</div>")
        said = [(who, notes[who][c]) for who in reviewers if notes[who][c]]
        H.append("<h3>Reviewers' comments (as written)</h3>" + ("<ul>" + "".join(f"<li><b>{esc(w)}</b>: {esc(t)}</li>" for w, t in said) + "</ul>" if said else "<p class='muted'>none</p>"))
        H.append("</div></div></div>")
    H.append("</body></html>")
    return "".join(H)


FINDINGS = """
<h3>Conclusions</h3><ol>
<li><b>Where the user stated a ranking, reviewers are closer to the gold answer.</b> The mean τ-b is 0.49, against 0.34 where no ranking was stated. In A01, A04 and A08, single-turn cases with explicit requirements, all 5 reviewers' first choice is the gold answer's first. In B01 and B02 the user stated no ranking, but the trade-off is simple, and all 5 first choices also match the gold answer.</li>
<li><b>When the user does not say how to rank, "lower rent first" is not a consensus default.</b> Reviewers weigh furnishing, flatmates, MRT, bathrooms and whether the landlord lives in (see each case's comments). Cases with no stated ranking have no single right order, so it is reasonable for the automatic scoring to check only cases with a stated ranking. Agreement between reviewers (W) is similar in both groups, around 0.4.</li>
<li><b>In multi-turn cases, even with commute stated as the priority, reviewers have almost no consensus.</b> W for G01, G02 and G05 is only 0.04 to 0.16, and in each 3/5 reviewers put the gold answer's first choice first. G01's image gives the ranking focus as "overall suitability", so reviewers may not have known to rank by commute.</li>
<li><b>Reviewers differ when the stated priority clashes with intuition.</b> In A08 the listing near the MRT, and in A09 the cheap listing, were moved up by some reviewers, even though the user stated other priorities.</li>
<li><b>The agent's order comes from the 11/05 run, before the ranking was fixed.</b> In G01 the agent's order is the exact reverse of the gold answer, and in G02 the agent put A, the shortest commute, last (the user asked to rank by commute, and the agent did not). After the 11/06 change to compare stated priorities strictly one after another, the top 3 of every case with a stated ranking match the gold answer in dev5 and on the holdout. So "reviewers vs agent" here reflects the system before the fix.</li>
<li><b>The frozen system agrees with the gold answer.</b> The agent never ranked all the replacement candidates, so the frozen system ranked them once (without the model): in A08, A09 and B01 every candidate's rank equals the gold answer, including listings ranked 57th and 59th. In G04 the user stated no ranking; the system weighs MRT and rent together and differs from the rent-only gold answer, which by the conventions is not an error.</li>
</ol>
<h3>Limitations</h3><ul>
<li>Only 5 reviewers, all team members; 3 to 5 candidates per case; dev set only.</li>
<li>The images of the 11 original cases were drawn from the data the agent used at the time. Only listing 500203570's rent differs from the frozen data: the image shows 1,050, from before the 11/02 recheck, and the frozen data has 1,300 after it. The questionnaire's gold answer uses the 1,050 in the image; at 1,300 it would be over budget in A01, and the orders in B02, G02 and G05 would also differ.</li>
<li>Candidates with exactly the same ranking values are tied (the two Fragrance Court listings in A01, B02, G02 and G05; A and E in G04). The gold answer separates them only by listing ID, which means nothing to a person.</li>
<li>The images of the 4 replacement cases are in English and the rest in Chinese, as the reviewers saw them.</li>
</ul>
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "images").mkdir(exist_ok=True)
    for c in ORDER:
        src = HR / ("v6_replacement" if c in REPLACED else "v6_images") / f"{c}.png"
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
