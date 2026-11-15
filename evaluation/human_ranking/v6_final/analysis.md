# V6 human-ranking questionnaire: results (15 cases)

5 reviewers: Jason, ljy, lys, wxy, zfy. Reviewer code aliases: 1ljy → ljy.
A08, A09, B01 and G04 use replacement candidates (the original candidates included listings that were taken down). The agent never ranked all of these candidates, so the reference order for these 4 cases is how the frozen system ranks them (without the model; see `human_ranking_system_order.py`), marked "(system)" in the table. The reference order for the other 11 cases is the order the agent recommended in its 11/05 run.

## Results by case

| Case | Ranking stated | Candidates | W | p | Reviewers' mean order | Gold order | Reviewers vs gold τ-b | Same first as gold | Agent / system order | Reviewers vs agent/system τ-b | Agent/system vs gold τ-b |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A01 | yes | 3 | 0.76 | 0.022 | B > C > A | B=C > A | 0.82 | 5/5 | B > C > A | 0.73 | 0.82 |
| A02 | no | 3 | 0.12 | 0.549 | C > A > B | B > C > A | 0.07 | 2/5 | B > C > A | 0.07 | 1.00 |
| A04 | yes | 3 | 0.71 | 0.029 | C > B > A | C > B > A | 0.80 | 5/5 | C > B > A | 0.80 | 1.00 |
| A05 | no | 3 | 0.28 | 0.247 | C > A > B | A > C > B | 0.33 | 2/5 | C > A > B | 0.47 | 0.33 |
| A08 | yes | 5 | 0.73 | 0.006 | A > D > E > B > C | A > D > E > B > C | 0.72 | 5/5 | A > D > E > B > C (system) | 0.72 | 1.00 |
| A09 | yes | 5 | 0.30 | 0.193 | A > D > B > C > E | D > A > B > E > C | 0.48 | 2/5 | D > A > B > E > C (system) | 0.48 | 1.00 |
| B01 | no | 3 | 1.00 | 0.007 | A > B > C | A > B > C | 1.00 | 5/5 | A > B > C (system) | 1.00 | 1.00 |
| B02 | no | 3 | 0.76 | 0.022 | B > A > C | A=B > C | 0.82 | 5/5 | C > A > B | -0.73 | -0.82 |
| B03 | no | 3 | 0.28 | 0.247 | A > C > B | C > A > B | 0.07 | 1/5 | C > A > B | 0.07 | 1.00 |
| B06 | no | 3 | 0.14 | 0.504 | C > A > B | B > A > C | -0.30 | 1/5 | C > B > A | 0.13 | -0.33 |
| G01 | yes | 3 | 0.16 | 0.449 | A > C > B | A > C > B | 0.33 | 3/5 | B > C > A | -0.33 | -1.00 |
| G02 | yes | 3 | 0.04 | 0.819 | A > C > B | A > B=C | 0.16 | 3/5 | C > B > A | -0.07 | -0.82 |
| G03 | no | 3 | 0.16 | 0.449 | A > C > B | C > A > B | 0.20 | 1/5 | C > A > B | 0.20 | 1.00 |
| G04 | no | 5 | 0.39 | 0.098 | D > E > A > B > C | D > A=E > B > C | 0.57 | 3/5 | E > D > C > B > A (system) | 0.20 | 0.11 |
| G05 | yes | 3 | 0.07 | 0.692 | B > C > A | B > A=C | 0.13 | 3/5 | B > A > C | -0.03 | 0.82 |

## By whether the user stated a ranking (means)

| Group | Cases | W | Reviewers vs gold | Reviewers vs agent (11 original cases only) | Agent vs gold (11 original cases only) |
|---|---|---|---|---|---|
| User stated a ranking | A01, A04, A08, A09, G01, G02, G05 | 0.40 | 0.49 | 0.22 | 0.16 |
| User stated no ranking | A02, A05, B01, B02, B03, B06, G03, G04 | 0.39 | 0.34 | 0.03 | 0.36 |

## Each reviewer's agreement with the gold answer (τ-b)

| Reviewer | A01 | A02 | A04 | A05 | A08 | A09 | B01 | B02 | B03 | B06 | G01 | G02 | G03 | G04 | G05 | Mean |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Jason | 0.82 | 0.33 | 1.00 | 0.33 | 0.40 | 0.20 | 1.00 | 0.82 | 0.33 | 1.00 | 1.00 | 0.82 | -0.33 | 0.74 | -0.82 | 0.51 |
| ljy | 0.82 | -0.33 | 1.00 | -1.00 | 0.20 | 0.80 | 1.00 | 0.82 | -0.33 | -0.33 | 0.33 | 0.82 | -0.33 | 0.95 | 0.82 | 0.35 |
| lys | 0.82 | -0.33 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.82 | 0.33 | -1.00 | 0.33 | 0.82 | 0.33 | 0.11 | -1.00 | 0.41 |
| wxy | 0.82 | -0.33 | 0.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.82 | -1.00 | -0.82 | 1.00 | -0.82 | 0.33 | 0.95 | 0.82 | 0.38 |
| zfy | 0.82 | 1.00 | 1.00 | 0.33 | 1.00 | -0.60 | 1.00 | 0.82 | 1.00 | -0.33 | -1.00 | -0.82 | 1.00 | 0.11 | 0.82 | 0.41 |

## Data checks

- lys G05: tied A=C > B
- wxy A04: tied A=C > B
- wxy B06: tied A=C > B

## Reviewers' comments

Quoted as the reviewers wrote them (mostly in Chinese).

- A01 lys: 租金优势/地铁距离优势/b的bathroom数量多于c/bc的房屋信息比较明晰
- A01 wxy: B比C多一个bath
- A02 ljy: C家具齐全、比A月租更少；B是hdb且与房东同住
- A02 lys: c家具齐全有价格优势距地铁近不与房东同住/a符合全部条件价格比c贵/b只有部分家具
- A02 wxy: B便宜但只有部分家具
- A04 lys: c学院通勤时间最短/b和a相比有价格优势
- A05 ljy: B允许做饭，是apartment；A不让做饭
- A05 lys: a的限制较多，但价格优势明显
- A08 lys: 优先级：面积/MRT/租金
- A09 lys: 优先级：餐饮/MRT
- B01 lys: B比A贵面积还小/C离地铁远
- B02 ljy: A卫生间更多；C租金最贵
- B02 lys: ab有价格优势，a空调信息未知
- B02 zfy: 价格，卫生间数量
- B03 ljy: 虽然AC和房东同住，A家具齐全；B是condo
- B03 lys: 信息比较全，价格优势，家具齐全。但这种有性别限制的不知道该怎么排序推荐
- B06 ljy: B是shophouse，room要share;A家具齐全
- B06 lys: 面积和住宅类型和家具有优势/
- G01 ljy: C面积大、家具全；B通勤时间最长
- G01 lys: 通勤时间短，据地铁站近
- G02 ljy: C卫生间更多
- G02 lys: 最在意通勤时间
- G03 ljy: A是hdb但家具全性价比高；B是condo且通勤时间短;C通勤时间长时hdb
- G03 lys: 价格和面积通勤距离的性价比
- G03 wxy: 性别会作为打分依据吗
- G04 lys: E没什么大缺陷/ab离MRT太远/D是shared/c没厕所
- G05 ljy: B通勤时间最短；但是有一个问题，空调虽然标了未知但不一定代表没有吧？
- G05 lys: ac各种信息都差不多所以并列，价格距地铁距离优于b
- G05 wxy: C有空调
