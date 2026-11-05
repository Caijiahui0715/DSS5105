"""Human-ranking Google Form, version 7 (Chinese).

Decisions (2026-11-05):
- the same 15 cases as V6 (DSS5105 Human Listing Ranking V6);
- A01, A08, A09, B01 and G04 take their candidates from human_ranking/key.csv
  (sampled from the gold answer). In V6 each of them had a candidate that is
  delisted (A08, A09, B01, G04) or over budget at the latest rent (A01);
- the other 10 keep V6's candidates: the agent's top 3 from
  source/agent_profile20_20261105T032944Z.jsonl, the last turn of each case;
- every value comes from the frozen snapshot; every faculty is NUS Business School;
- each candidate shows the fields of the frontend's listing details, plus food
  places within 1 km and the commute to NUS Business School;
- one ranking grid per case (one candidate per rank), plus "cannot judge".

Output (evaluation/human_ranking/form_v7/):
    images/<case>.png      one comparison table per case, uploaded to Google Drive
    images/<case>.html     the same table, for checking
    build_form.gs          Google Apps Script that builds the form from those images
    key.csv                hidden key: listing IDs, candidate source, agent rank, gold rank
    cases.json             what the script puts in the form, for checking

Run from the repository root:
    .venv/Scripts/python.exe evaluation/form_v7.py
"""

from __future__ import annotations

import csv
import html
import json
import numbers
import random
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from gold import load  # noqa: E402

OUT = HERE / "human_ranking" / "form_v7"
IMAGES = OUT / "images"
GOLD = HERE / "gold" / "gold_answers.json"
CASES = HERE / "cases" / "cases.json"
KEY = HERE / "human_ranking" / "key.csv"
AGENT_RUN = HERE / "source" / "agent_profile20_20261105T032944Z.jsonl"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

FORM_CASES = ["A01", "A02", "A04", "A05", "A08", "A09", "B01", "B02", "B03", "B06",
              "G01", "G02", "G03", "G04", "G05"]
FROM_GOLD = {"A01", "A08", "A09", "B01", "G04"}
FACULTY = "NUS Business School"
WIDTH = 1240

QUERY_ZH = {
    "A01": ["我要找 D05 区的普通房，月租不超过 1,200 新元。在所有符合条件的房间里，租金便宜的排前面。"],
    "A02": ["我是女学生，想找一间有家具的房间，月租最多 1,400 新元。能做饭和有空调都是必须的。"],
    "A04": ["我想整租一套 condo 或私人公寓，月租最多 6,000 新元，至少 2 个浴室。先按到学院的通勤时间从短到长排，再按租金从低到高排。"],
    "A05": ["给我看有家具、有空调的主人房，月租不超过 1,800 新元。"],
    "A08": ["我要整租一套至少 80 平方米的房子，月租上限 7,000 新元。先按面积从大到小排，再按到地铁站步行从近到远排，最后按租金从低到高排。"],
    "A09": ["帮我找一间月租最多 1,500 新元的房间，1 公里内至少有 30 家餐饮，离最近的运营中地铁站步行不超过 1,000 米。优先餐饮选择多的，其次到地铁站步行近的。"],
    "B01": ["我要一间月租最多 1,300 新元的房间，必须明确允许正常做饭，包括煎炒。"],
    "B02": ["帮我找一间月租最多 1,500 新元的房间，但房东不能和我住在同一套房子里。"],
    "B03": ["我要一间有空调的房间，月租不高于 1,500 新元。"],
    "B06": ["我是女性租客，找一间月租不超过 1,400 新元的房间。把明确接受女性的房源，和没写性别要求的房源分开列出来。"],
    "G01": ["我的预算是每月 1,500 新元，想找一间靠近 NUS 的房间。",
            "我可以把预算提高到 1,800 新元。其他要求都不变。"],
    "G02": ["帮我找一间月租低于 1,600 新元的房间。价格是我最看重的。",
            "现在通勤时间比价格更重要，但预算保持不变。"],
    "G03": ["我需要一间能做饭、有空调的房间。",
            "能不能做饭对我不重要了，但空调仍然必须有。"],
    "G04": ["我在找一套整租的 apartment，每月预算 3,000 新元。",
            "预算不变，但我也可以接受合租。"],
    "G05": ["我的预算是 1,800 新元，想住得离 NUS 比较近。",
            "其实我的预算应该是 1,500 新元，而且通勤最好不超过 30 分钟。"],
}

# Frontend Chinese labels (app/content/labels.py VALUE_ZH), plus the values it has no label for.
VALUE_ZH = {
    "room": "合租单间", "entire_unit": "整租",
    "common_room": "普通房", "master_room": "主人房", "studio": "开间", "shared_room": "合住房间",
    "room_unspecified": "房间（未注明类型）",
    "condominium": "公寓（Condo）", "executive_condominium": "执行共管公寓", "apartment": "公寓",
    "walk_up_apartment": "无电梯公寓", "hdb_flat": "组屋（HDB）", "terraced_house": "排屋",
    "corner_terrace": "角落排屋", "semi_detached_house": "半独立式洋房", "detached_house": "独立式洋房",
    "bungalow_house": "独立洋房", "good_class_bungalow": "优质独立洋房", "cluster_house": "集群住宅",
    "conservation_house": "保留建筑住宅", "shophouse": "店屋",
    "fully_furnished": "全家具", "partially_furnished": "部分家具", "unfurnished": "无家具",
    "furnished_unspecified": "有家具（未注明程度）",
    "asking": "叫价", "negotiable": "可议价", "starting_from": "起价", "guide_price": "参考价",
    "allowed": "允许", "not_allowed": "不允许", "light_only": "仅限简单烹饪",
    "yes": "有", "no": "没有", "active": "有效", "inactive": "已失效",
    "floor_reported": "整套面积", "room_reported": "房间面积",
    # not in the frontend table
    "light_cooking": "仅限简单烹饪", "cooking_any_cooking": "可以正常做饭（含煎炒）",
    "cooking_not_allowed": "不允许做饭", "cooking_prefer_not_to_say": "未注明",
    "no_restriction": "不限性别", "female_only": "仅限女性", "male_only": "仅限男性",
    "any": "不限", "female": "女性", "male": "男性",
    "no_pets": "不允许宠物", "pets_allowed": "允许宠物",
    "operational": "运营中", "under_construction": "在建",
}
YES_NO = {"landlord_lives_in": {"yes": "同住", "no": "不同住"},
          "private_bathroom": {"yes": "有", "no": "没有"},
          "air_conditioning": {"yes": "有", "no": "没有"}}
LEASE_ZH = {"1 year": "至少 1 年", "2 years": "至少 2 年", "Flexible": "灵活", "Short Term": "短租"}
ORDER_ZH = {"price": "租金低", "space": "面积大", "mrt": "到地铁站步行近",
            "food_places": "1 公里内餐饮多", "commute": "到商学院通勤短"}
PTYPE_ZH = {"condominium": "公寓（Condo）", "executive_condominium": "执行共管公寓",
            "apartment": "公寓", "walk_up_apartment": "无电梯公寓"}
NOT_STATED = "未注明"


def clean(v):
    if v is None:
        return None
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, str) and v.strip() in ("", "unknown", "Prefer not to say"):
        return None
    return v


def num(v, unit=""):
    v = clean(v)
    if v is None:
        return NOT_STATED
    if isinstance(v, numbers.Number) or re.fullmatch(r"-?\d+(\.\d+)?", str(v)):
        s = f"{float(v):,.2f}".rstrip("0").rstrip(".")
        return s + unit
    return str(v)


def code(v, table=VALUE_ZH):
    v = clean(v)
    if v is None:
        return NOT_STATED
    key = re.sub(r"[\s-]+", "_", str(v).strip().lower())
    return table.get(key, VALUE_ZH.get(key, str(v)))


def profile_zh(p: dict) -> str:
    out = []
    if "max_price_sgd" in p:
        out.append(f"月租 ≤ {p['max_price_sgd']:,} 新元")
    out.append({"room": "合租单间", "entire_unit": "整租"}.get(p.get("rental_scope"), "合租或整租都可以"))
    if "room_type" in p:
        out.append(f"房型：{VALUE_ZH[p['room_type']]}")
    if "district_code" in p:
        out.append(f"区：{p['district_code']}")
    if "property_types" in p:
        out.append("物业类型：" + " / ".join(PTYPE_ZH.get(x, x) for x in p["property_types"]))
    if p.get("tenant_gender") == "female":
        out.append("租客是女性")
    if p.get("furnished_required"):
        out.append("要有家具")
    if p.get("cooking_level") == "full":
        out.append("必须能正常做饭（含煎炒）")
    elif p.get("cooking_required"):
        out.append("要能做饭")
    if p.get("air_conditioning_required"):
        out.append("要有空调")
    if p.get("landlord_not_living_in"):
        out.append("房东不同住")
    for k, fmt in [("min_bedrooms", "卧室 ≥ {}"), ("min_bathrooms", "浴室 ≥ {}"), ("min_area_sqm", "面积 ≥ {} 平方米"),
                   ("min_food_places", "1 公里内餐饮 ≥ {} 家"), ("max_mrt_distance_m", "到运营中地铁站 ≤ {:,} 米"),
                   ("max_mrt_minutes", "到运营中地铁站步行 ≤ {} 分钟"),
                   ("max_commute_minutes", "到商学院通勤 ≤ {} 分钟")]:
        if k in p:
            out.append(fmt.format(int(p[k]) if float(p[k]).is_integer() else p[k]))
    return " · ".join(out)


def order_zh(order: list[str]) -> str:
    return " → ".join(ORDER_ZH[o] for o in order) + "（按顺序比较，前一项相同才看下一项）"


def rows(r, commute):
    """(label, value) for one listing, in the order of the frontend's listing details."""
    rent_now, rent_orig = clean(r["rent_monthly_sgd_now"]), clean(r["rent_monthly_sgd"])
    minutes = commute.get((r.name, FACULTY))
    return [
        ("房源名称", str(r["title"])),
        ("最新记录的月租（新元）", num(rent_now if rent_now is not None else rent_orig)),
        ("原广告月租（新元）", num(rent_orig)),
        ("报价类型", code(r["rent_price_type"])),
        ("到 NUS 商学院通勤（分钟）", num(minutes) if minutes is not None else NOT_STATED),
        ("租住方式", code(r["rental_scope"])),
        ("房产类型", code(r["ptype"])),
        ("房间类型", code(r["room_type"]) if r["rental_scope"] == "room" else "整套"),
        ("卧室", num(r["bedrooms"])),
        ("浴室", num(r["bathrooms"])),
        ("面积（平方米）", num(r["area_sqm"])),
        ("面积口径", code(r["area_scope"])),
        ("区", code(r["district_code"])),
        ("地址", code(r["address"])),
        ("广告标注的地铁站", code(r["mrt_station"])),
        ("到地铁站距离（米）", num(r["mrt_distance_m"])),
        ("广告标注的步行分钟", num(r["mrt_minutes_reported"])),
        ("地铁站运营状态", code(r["mrt_operation_status"])),
        ("1 公里内餐饮数", num(r["poi_fnb_1km"])),
        ("家具", code(r["furnishing"])),
        ("独立卫浴", code(r["private_bathroom"], YES_NO["private_bathroom"])),
        ("做饭", code(r["cooking_policy"])),
        ("空调", code(r["air_conditioning"], YES_NO["air_conditioning"])),
        ("房东同住", code(r["landlord_lives_in"], YES_NO["landlord_lives_in"])),
        ("宠物政策", code(r["pets_policy"])),
        ("广告标注的租客数", num(r["tenant_count_reported"])),
        ("平台性别标签", code(r["tenant_gender_label"])),
        ("明确的性别限制", code(r["gender_restriction"])),
        ("性别偏好", code(r["gender_preference"])),
        ("租期", LEASE_ZH.get(clean(r["lease_term"]) or "", NOT_STATED)),
        ("快照状态", code(r["scrape_status"])),
        ("最近检查", code(r["enriched_at"])),
        ("房源 ID", str(r.name)),
    ]


CSS = """
* { box-sizing: border-box; margin: 0; }
body { width: %dpx; font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
       background: #fff; color: #1f2a37; font-size: 22px; line-height: 1.35; }
.bar { background: #172b45; color: #fff; font-size: 30px; padding: 16px 24px; }
.meta { padding: 14px 24px 6px; }
.meta div { display: flex; padding: 4px 0; }
.meta b { width: 130px; flex: none; font-weight: 400; color: #4b5563; }
table { width: calc(100%% - 24px); margin: 10px 12px 14px; border-collapse: collapse; table-layout: fixed; }
th { background: #dfe7f1; text-align: left; font-weight: 700; padding: 9px 10px; }
td { padding: 7px 10px; vertical-align: top; word-break: break-word; }
tr:nth-child(even) td { background: #f3f6fa; }
td:first-child { color: #4b6584; }
col.attr { width: 230px; }
tr.key td { font-weight: 700; }
.note { padding: 0 24px 16px; font-size: 18px; color: #6b7280; }
""" % WIDTH
KEY_ROWS = {"房源名称", "最新记录的月租（新元）", "到 NUS 商学院通勤（分钟）"}


def page(cid, gold_case, labelled, idx, commute) -> str:
    first, last = gold_case["turns"][0], gold_case["turns"][-1]
    meta = [("最初条件", profile_zh(first["gold_profile"])), ("当前条件", profile_zh(last["gold_profile"])),
            ("排序要求", order_zh(last["ranking_order"]))]
    if len(gold_case["turns"]) == 1:
        meta = [("用户条件", profile_zh(last["gold_profile"])), meta[2]]
    cols = [(lab, rows(idx.loc[lid], commute)) for lab, lid in labelled]
    h = [f'<div class="bar">{cid}　候选房源对比</div><div class="meta">']
    h += [f"<div><b>{k}</b><span>{html.escape(v)}</span></div>" for k, v in meta]
    h.append('</div><table><colgroup><col class="attr">' + "<col>" * len(cols) + "</colgroup>")
    h.append("<tr><th>字段</th>" + "".join(f"<th>候选 {lab}</th>" for lab, _ in cols) + "</tr>")
    for i, (name, _) in enumerate(cols[0][1]):
        cls = ' class="key"' if name in KEY_ROWS else ""
        h.append(f"<tr{cls}><td>{name}</td>" + "".join(f"<td>{html.escape(c[i][1])}</td>" for _, c in cols) + "</tr>")
    h.append("</table><div class=\"note\">通勤：公共交通，工作日 08:30 出发，到 NUS 商学院（OneMap 缓存）。"
             "“未注明”表示数据里没有写。数据快照：2026-11-02。</div>")
    return f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>{CSS}</style></head><body>{"".join(h)}</body></html>'


def screenshot(html_path: Path, png_path: Path):
    """Two headless passes: measure the page height, then capture exactly that."""
    probe = html_path.with_suffix(".probe.html")
    probe.write_text(html_path.read_text(encoding="utf-8").replace(
        "</body>", "<script>document.title='H'+document.documentElement.scrollHeight</script></body>"), encoding="utf-8")
    dom = subprocess.run([CHROME, "--headless=new", "--disable-gpu", f"--window-size={WIDTH},800", "--dump-dom",
                          probe.as_uri()], check=True, capture_output=True, text=True, encoding="utf-8").stdout
    probe.unlink()
    height = int(re.search(r"<title>H(\d+)</title>", dom).group(1))
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={WIDTH},{height}",
                    f"--screenshot={png_path}", html_path.as_uri()], check=True, capture_output=True)
    return height


def agent_top3() -> dict[str, tuple[int, list[str]]]:
    last = {}
    for line in AGENT_RUN.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["case_id"] not in last or r["turn"] >= last[r["case_id"]][0]:
                last[r["case_id"]] = (r["turn"], r["listing_ids"])
    return last


def main():
    IMAGES.mkdir(parents=True, exist_ok=True)
    gold = {a["case_id"]: a for a in json.loads(GOLD.read_text(encoding="utf-8"))["answers"]}
    cases = {c["id"]: c for c in json.loads(CASES.read_text(encoding="utf-8"))["cases"]}
    sampled = {}
    for r in csv.DictReader(KEY.open(encoding="utf-8-sig")):
        sampled.setdefault(r["Case ID"], []).append(r)
    agent = agent_top3()
    df, commute = load()
    idx = df.set_index("listing_id")
    active = set(df["listing_id"])

    key_rows, form_cases, problems = [], [], []
    for cid in FORM_CASES:
        assert cases[cid]["preconditions"]["faculty"] == FACULTY, cid
        last = gold[cid]["turns"][-1]
        ranked = last["confirmed_ids_ranked"]
        unknown = {x["listing_id"] for x in last["needs_confirmation"]}
        if cid in FROM_GOLD:
            labelled = [(r["Label"], r["Listing ID"]) for r in sampled[cid]]
            source = {r["Listing ID"]: r["Sampling source"] for r in sampled[cid]}
            agent_rank = {}
        else:
            turn, ids = agent[cid]
            assert turn == len(gold[cid]["turns"]), cid
            agent_rank = {lid: i + 1 for i, lid in enumerate(ids)}
            order = list(ids)
            random.Random(f"DSS5105-form-v7-{cid}").shuffle(order)
            labelled = list(zip("ABCDE", order))
            source = {lid: "agent_top3" for lid in ids}
        for lab, lid in labelled:
            assert lid in active, (cid, lid)
            status = "confirmed" if lid in ranked else "needs_confirmation" if lid in unknown else "excluded"
            if status != "confirmed":
                problems.append(f"{cid} {lab} {lid}: {status}")
            key_rows.append({
                "Case ID": cid, "Label": lab, "Listing ID": lid,
                "Candidate source": "gold_sample" if cid in FROM_GOLD else "agent_top3",
                "Sampling source": source[lid], "Agent rank": agent_rank.get(lid, ""),
                "Gold status": status, "Gold rank among confirmed": ranked.index(lid) + 1 if lid in ranked else "",
                "Confirmed total": len(ranked),
                "Gold order of these candidates": "",
            })
        in_gold = sorted((ranked.index(l), lab) for lab, l in labelled if l in ranked)
        for row in key_rows[-len(labelled):]:
            row["Gold order of these candidates"] = " > ".join(lab for _, lab in in_gold)

        doc = page(cid, gold[cid], labelled, idx, commute)
        html_path = IMAGES / f"{cid}.html"
        html_path.write_text(doc, encoding="utf-8")
        screenshot(html_path, IMAGES / f"{cid}.png")

        turns_en = [t["user"] for t in cases[cid]["turns"]]
        if len(turns_en) == 1:
            query = f"{QUERY_ZH[cid][0]}\n\n英文原文：{turns_en[0]}"
        else:
            query = "\n".join(f"第 {i} 轮：{zh}" for i, zh in enumerate(QUERY_ZH[cid], 1)) + "\n\n英文原文：\n" + \
                    "\n".join(f"Turn {i}: {en}" for i, en in enumerate(turns_en, 1)) + \
                    "\n\n请按最后一轮之后的条件排序。"
        form_cases.append({"id": cid, "query": query, "image": f"{cid}.png", "labels": [lab for lab, _ in labelled]})

    with (OUT / "key.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(key_rows[0].keys()))
        w.writeheader()
        w.writerows(key_rows)
    (OUT / "cases.json").write_text(json.dumps(form_cases, ensure_ascii=False, indent=2), encoding="utf-8")
    template = (HERE / "form_v7_template.gs").read_text(encoding="utf-8")
    (OUT / "build_form.gs").write_text(
        template.replace("/*CASES*/[]", json.dumps(form_cases, ensure_ascii=False, indent=2)), encoding="utf-8")
    print(f"wrote {len(form_cases)} cases, {len(key_rows)} candidates to {OUT}")
    print("candidates that are not confirmed in the gold answer:", problems or "none")


if __name__ == "__main__":
    main()
