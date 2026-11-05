"""Replacement questions for the V6 Google Form (DSS5105 Human Listing Ranking V6).

V6 shows the agent's top 3 for each case. In A08, A09, B01 and G04 one of those
three has been delisted since the 11/02 freeze. This script rebuilds those four
questions from human_ranking/key.csv (candidates sampled from the gold answer,
all active), drawn as one comparison image per case in the V6 layout.

Output: evaluation/human_ranking/v6_replacement/
    <case>.png        comparison image to upload into the form
    <case>.html       the same page, for checking
    questions.md      what to type into the form
    key.csv           hidden key (listing IDs, gold rank); do not show reviewers

Run from the repository root:
    .venv/Scripts/python.exe evaluation/v6_replacement.py
"""

from __future__ import annotations

import csv
import html
import json
import numbers
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from gold import load, summary  # noqa: E402

OUT = HERE / "human_ranking" / "v6_replacement"
KEY = HERE / "human_ranking" / "key.csv"
GOLD = HERE / "gold" / "gold_answers.json"
CASES = HERE / "cases" / "cases.json"
REPLACE = ["A08", "A09", "B01", "G04"]
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
WIDTH = 1800

PRIORITY = {
    "price": "lower rent", "space": "larger area", "mrt": "shorter MRT walk",
    "food_places": "more food places within 1 km", "commute": "shorter commute to faculty",
}
WORDS = {
    "room": "Room", "entire_unit": "Entire unit", "common_room": "Common room", "master_room": "Master room",
    "shared_room": "Shared room", "room_unspecified": "Room (type not stated)", "studio": "Studio",
    "fully_furnished": "Fully furnished", "partially_furnished": "Partially furnished",
    "furnished_unspecified": "Furnished (level not stated)", "unfurnished": "Unfurnished",
    "light_cooking": "Light cooking allowed", "cooking_any_cooking": "Any cooking allowed",
    "cooking_not_allowed": "No cooking", "not_allowed": "No cooking", "cooking_prefer_not_to_say": "Not stated",
    "no_restriction": "No restriction", "female_only": "Female only", "male_only": "Male only",
    "no_pets": "No pets", "pets_allowed": "Pets allowed", "yes": "Yes", "no": "No",
    "operational": "Operational", "under_construction": "Under construction",
}


def word(v) -> str:
    if v is None or v == "unknown" or v == "":
        return "Unknown"
    if isinstance(v, numbers.Number) and not isinstance(v, bool):
        v = float(v)
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return WORDS.get(v, str(v).replace("_", " "))


def describe_profile(p: dict) -> str:
    out = []
    if "max_price_sgd" in p:
        out.append(f"Budget S${p['max_price_sgd']:,}")
    out.append({"room": "Room", "entire_unit": "Entire unit"}.get(p.get("rental_scope"), "Room or entire unit"))
    labels = {
        "min_area_sqm": "Min area {} sqm", "min_food_places": "At least {} food places within 1 km",
        "max_mrt_distance_m": "Operating MRT within {:.0f} m", "max_mrt_minutes": "Operating MRT within {} min walk",
        "min_bedrooms": "Min bedrooms {}", "min_bathrooms": "Min bathrooms {}",
    }
    for k, fmt in labels.items():
        if k in p:
            out.append(fmt.format(p[k]))
    if p.get("cooking_level") == "full":
        out.append("Full cooking (incl. frying) definitely allowed")
    elif p.get("cooking_required"):
        out.append("Cooking allowed")
    return " · ".join(out)


def describe_order(order: list[str]) -> str:
    parts = [PRIORITY[o] for o in order]
    return (parts[0][0].upper() + parts[0][1:] + " first" + "".join(f", then {x}" for x in parts[1:])) if parts else ""


ROWS = [
    ("Listing name", lambda s, r: s["title"]),
    ("Monthly rent (SGD)", lambda s, r: word(s["rent_sgd"])),
    ("Area (sqm)", lambda s, r: word(s["area_sqm"])),
    ("MRT walk (min)", lambda s, r: word(s["mrt_minutes"])),
    ("MRT distance (m)", lambda s, r: word(s["mrt_distance_m"])),
    ("MRT station", lambda s, r: (s["mrt_station"] or "Unknown") + (
        "" if s["mrt_operation_status"] == "operational" else f" ({word(s['mrt_operation_status'])})")),
    ("Address / area", lambda s, r: word(r["address"] if isinstance(r["address"], str) else None)),
    ("District", lambda s, r: word(s["district_code"])),
    ("Property type", lambda s, r: word(r["ptype"]).replace("hdb", "HDB").capitalize().replace("Hdb", "HDB")),
    ("Rental scope", lambda s, r: word(s["rental_scope"])),
    ("Room type", lambda s, r: word(s["room_type"]) if s["rental_scope"] == "room" else "Entire unit"),
    ("Bedrooms", lambda s, r: word(s["bedrooms"])),
    ("Bathrooms", lambda s, r: word(s["bathrooms"])),
    ("Private bathroom", lambda s, r: word(s["private_bathroom"])),
    ("Furnishing", lambda s, r: word(s["furnishing"])),
    ("Air conditioning", lambda s, r: word(s["air_conditioning"])),
    ("Cooking policy", lambda s, r: word(s["cooking_policy"])),
    ("Lease term", lambda s, r: word(s["lease_term"])),
    ("Landlord lives in", lambda s, r: word(s["landlord_lives_in"])),
    ("Gender restriction", lambda s, r: word(s["gender_restriction"])),
    ("Pets policy", lambda s, r: word(s["pets_policy"])),
    ("Food places within 1km", lambda s, r: word(s["food_places_1km"])),
]

CSS = """
* { box-sizing: border-box; margin: 0; }
body { width: %dpx; font-family: "Source Sans Pro", "Segoe UI", Arial, sans-serif; background: #fff; color: #1f2a37; }
.bar { background: #172b45; color: #fff; font-size: 30px; padding: 18px 28px; letter-spacing: .5px; }
.meta { padding: 16px 28px 8px; font-size: 19px; }
.meta div { display: flex; padding: 3px 0; }
.meta b { width: 200px; font-weight: 400; color: #374151; flex: none; }
table { width: calc(100%% - 32px); margin: 10px 16px 18px; border-collapse: collapse; table-layout: fixed; font-size: 18px; }
th { background: #dfe7f1; text-align: left; font-weight: 400; font-size: 21px; padding: 9px 12px; }
td { padding: 7px 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
tr:nth-child(even) td { background: #f3f6fa; }
td:first-child { color: #4b6584; }
col.attr { width: 300px; }
tr.id td { color: #36597f; font-size: 17px; }
""" % WIDTH


def page(cid, case, gold_case, picks, idx, commute) -> str:
    first, last = gold_case["turns"][0], gold_case["turns"][-1]
    meta = [("Initial profile", describe_profile(first["gold_profile"])),
            ("Effective profile", describe_profile(last["gold_profile"])),
            ("Ranking priority", describe_order(last["ranking_order"]))]
    if len(gold_case["turns"]) > 1:
        meta.append(("Latest updates", "Turn 2: " + last["user"]))
    else:
        meta.append(("Latest updates", "Single-turn request; no updates"))
    sums = [(lab, summary(lid, idx, None, commute), idx.loc[lid]) for lab, lid in picks]
    h = [f'<div class="bar">{cid} &nbsp;|&nbsp; SIDE-BY-SIDE LISTING COMPARISON</div><div class="meta">']
    h += [f"<div><b>{html.escape(k)}</b><span>{html.escape(v)}</span></div>" for k, v in meta]
    h.append('</div><table><colgroup><col class="attr">' + "<col>" * len(sums) + "</colgroup>")
    h.append("<tr><th>Listing attribute</th>" + "".join(f"<th>Candidate {lab}</th>" for lab, _, _ in sums) + "</tr>")
    for name, fn in ROWS:
        h.append(f"<tr><td>{name}</td>" + "".join(f"<td>{html.escape(str(fn(s, r)))}</td>" for _, s, r in sums) + "</tr>")
    h.append('<tr class="id"><td></td>' + "".join(f"<td>ID {s['listing_id']}</td>" for _, s, _ in sums) + "</tr></table>")
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>{"".join(h)}</body></html>'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gold = {a["case_id"]: a for a in json.loads(GOLD.read_text(encoding="utf-8"))["answers"]}
    cases = {c["id"]: c for c in json.loads(CASES.read_text(encoding="utf-8"))["cases"]}
    key = [r for r in csv.DictReader(KEY.open(encoding="utf-8-sig")) if r["Case ID"] in REPLACE]
    df, commute = load()
    idx = df.set_index("listing_id")
    active = set(df["listing_id"])
    md = ["# V6 问卷替换题（A08、A09、B01、G04）", "",
          "这 4 题原来的候选里各有 1 套 11/02 前已下架的房源。下面的候选来自 `human_ranking/key.csv`，全部在冻结数据里。",
          "", "每题在表单里的设置和 V6 其他题一致：一段题目文字、一张对比图、每个候选一道单选题、一道选填说明。",
          "候选多于 3 个的题，名次选项要改成 1 到候选数，再加 \"Cannot judge\"。", ""]
    for cid in REPLACE:
        picks = [(r["Label"], r["Listing ID"]) for r in key if r["Case ID"] == cid]
        assert all(lid in active for _, lid in picks), cid
        doc = page(cid, cases[cid], gold[cid], picks, idx, commute)
        (OUT / f"{cid}.html").write_text(doc, encoding="utf-8")
        height = 300 + 37 * (len(ROWS) + 2)
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--window-size={WIDTH},{height}", f"--screenshot={OUT / (cid + '.png')}",
                        (OUT / f"{cid}.html").as_uri()], check=True, capture_output=True)
        n = len(picks)
        opts = ", ".join(str(i) for i in range(1, n + 1)) + ", Cannot judge"
        md += [f"## {cid}", "", f"- 题目文字：{gold[cid]['turns'][-1]['user']}",
               "- 题目说明：Candidates were preliminarily screened; rank only.",
               f"- 图片：`{cid}.png`",
               f"- 名次题：{n} 道（{', '.join(f'{cid} | Candidate {lab} rank' for lab, _ in picks)}），选项 {opts}",
               f"- 选填：{cid} | Ranking rationale / ties / missing information (optional)", ""]
    with (OUT / "key.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(key[0].keys()))
        w.writeheader()
        w.writerows(key)
    (OUT / "questions.md").write_text("\n".join(md), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
