# 评估集（59 题）

这一版标准答案是在 2026-11-02 冻结的最终数据（369 条）上重新算的。收到的原始文件在 `source/`，原样保留，不再修改。

## 目录

| 路径 | 内容 |
|---|---|
| `CONVENTIONS.md` | 评估约定：每个字段怎么判 pass / unknown / fail，题意怎么理解，怎么排序、怎么放宽。2026-11-05 已确认 |
| `cases/cases.json` | 59 道题：题目、每轮的 `gold_profile`、前置条件、`expected_behavior`、`must` / `must_not`、dev / holdout 划分 |
| `cases/holdout_manifest.json` | 留出集 20 题的编号和 SHA-256 |
| `gold/gold_answers.json` | 标准答案：每轮的 confirmed（已排序）、needs_confirmation（附未知字段）、排除原因计数、前 3 名、C 类放宽结果、H 类事实 |
| `gold/drift_vs_source.md` | 新旧标准答案逐题对比 |
| `human_ranking/v6_final/` | **人工排序问卷的最终版（15 题）**：V6 的 11 题，加上替换后的 A08、A09、B01、G04。`DSS5105_V6_human_ranking.pdf` 是完整问卷（每题的图、5 位评审的名次和留言、和标准答案及 agent 的对照）；还有合并后的 `responses.csv`、`key.csv`、`analysis.md` 和 `images/`。由 `analyze_human_ranking.py` 生成。这里的标准答案按图上显示的数值算（500203570 月租 1,050，冻结数据是 1,300），排序依据完全相同的候选算并列；`gold_answers.json` 不受影响。11 道原题对照 agent 11/05 的顺序；4 道替换题的候选 agent 没有完整排过，对照的是现在冻结的系统给这些候选的排序（`system_order.csv`，由 `human_ranking_system_order.py` 不经过模型算出，要先于 `analyze_human_ranking.py` 运行） |
| `human_ranking/responses/` | 两份 Google 表单导出的原始回答（V6 原题、4 道替换题），不修改 |
| `human_ranking/图片/`、`v6_key.csv` | V6 原题的对比图，以及从图上读出的候选房源和 agent 名次 |
| `human_ranking/form.csv` | 按冻结数据重做的 17 题排序表，没有整份发给评审；替换题的候选取自这里 |
| `human_ranking/key.csv` | 上一行排序表的答案表：房源 ID、抽样来源、标准答案名次。**不要给评审看** |
| `human_ranking/v6_replacement/` | V6 问卷 A08、A09、B01、G04 的替换题：对比图、表单设置（`questions.md`）、答案表（`key.csv`，不要给评审看）。由 `v6_replacement.py` 生成 |
| `human_ranking/form_v7/` | 中文版 Google 表单（V7）：15 张对比图、建表单的 Apps Script（`build_form.gs`）、答案表（`key.csv`，不要给评审看）。由 `form_v7.py` 生成，用法见该目录的 `README.md`。**暂停中：现有图片按"全部商学院"画的，已过时，恢复后要按各题学院重新生成** |
| `build_cases.py` | 原始文件 → `cases.json`，同时划分留出集 |
| `gold.py` | 冻结数据 + 通勤缓存 → 标准答案。只用 pandas，不 import 系统代码 |
| `human_ranking.py` | 标准答案 → 人工排序表 |
| `source/` | 收到的原始文件：47 题、新增 A–C 8 题（xlsx）、人工排序原表、11/05 agent 运行记录 |
| `check_search.py` | 不调用模型：把开发集每轮的 `gold_profile` 直接交给系统的搜索和排序，和标准答案比较。不花钱，改完搜索或排序就能复测 |
| `run_eval.py` | 用真实模型跑系统（B5 agent），每轮存一行到 `results/<标签>.jsonl`，开头记下代码版本、模型和数据的哈希。要花钱。默认只跑开发集，加 `--holdout` 才跑留出集 |
| `score.py` | 从 `results/<标签>.jsonl` 算指标，并写出逐轮的 `_review.md` 给人看。只用标准答案和冻结数据，不 import 系统代码。行为分不在里面，要人工打 |
| `failure_log.md` | 失败案例记录，按评估方案第 6 节的模板写，给 Evaluation.pdf 用。前面是开发集（写了怎么修），最后一节是留出集（只记录，不修） |
| `ranking_summary.md` | 排序评估总结：自动的顺序检查（开发集、留出集）、人工排序问卷（指标 7），以及各种排序不一致怎么归类 |
| `boundary/` | 边界测试：无关问题、租房常识、法律和准证、注入、拒绝过头。不属于这 59 题，也不动 `cases.json`；只用开发集的题，不碰留出集。见该目录的 `README.md` |

## 怎么运行

在仓库根目录：

```bash
.venv/Scripts/python.exe evaluation/build_cases.py
```

```bash
.venv/Scripts/python.exe evaluation/gold.py
```

```bash
.venv/Scripts/python.exe evaluation/human_ranking.py
```

`build_cases.py` 只在改题目时需要重跑；改 `CONVENTIONS.md` 之后重跑后两个。三个脚本的输出都是确定的，重跑结果不变（`gold_answers.json` 里的生成时间除外）。

## 和收到的版本相比改了什么

1. **数据换成冻结版。** 原文件用的是 10/23 的 430 条数据，其中 50 套房源 11/02 前已下架。重算后几乎每题的套数都变了（见 `gold/drift_vs_source.md`），有两题结论变了：
   - **A07**（D22、3 卧以上、整租、4,500 以内）：唯一匹配 500299663 已下架，现在 0 套。
   - **C06**（同样条件加 6 个月租期）：原结论"签 12 个月就能解决"不成立了。现在的标准答案是"只改租期解决不了"。
2. **A–C 和 D–H 统一用一套规则。** 原来 G03 第 1 轮"能做饭 + 有空调"判 0 套符合，和 A02 的口径矛盾。现在统一按 `CONVENTIONS.md`，G03 第 1 轮是 33 套。
3. **G 类补写了每一轮的 `gold_profile`。** 原文件只有房源集合，没有写明条件。G01、G02、G05 补了学院（Faculty of Science）。
4. **E、F 类加了前置轮**，让"this property"指向 500074659。
5. **C 类 `must` 里的数字改成从标准答案自动填入**，数据再变也不会过时。
6. **H 类事实改为从冻结数据读取。** 注意 H02、H04：按最近一次记录的租金，两套都是 900，打平；按原始挂牌价，是 1000 和 900。
7. **新增 12 题**（2026-11-05）：A11–A14、B07、B08、C07、C08 来自 `source/DSS5105_Additional_ABC_8_Queries.xlsx`（该文件的中文列已损坏，只用了英文题目和学院设定）；G06–G09 是根据冻结数据新写的。为了让题目在冻结数据上测得到本类要测的东西，改了 4 处原文，记在每题的 `changes_from_source` 里：
   - A11 预算 4,200 → 5,000（原题没有任何符合的房源，最便宜的是 4,300）；
   - A13、C07 去掉"独立卫浴"（369 套里只有 3 套写明有独立卫浴）；
   - B08 删去"flexible-looking"半句（按约定 Flexible 算可以签任意租期）。
8. **留出集改为固定名单**（2026-11-05）：只放从没在 agent 上跑过的题，共 20 题：新增的 12 题，加上 D01、D04、E01、E02、F02、F05、H01、H02。原留出集里跑过 agent 的 A04、A05、A06、A10、B04、B06、C03、C06，以及 11/05 全部跑过的 G01–G05，都移到开发集。G01–G05 只有开发集结果。
9. **人工排序表重做**，见下一节。

## 人工排序表

17 题，共 81 个候选，全部来自冻结数据。和原表相比：

- 题目按什么排，就显示什么字段（学院通勤时间、1 km 内餐饮数量、MRT 站是否运营），并写明按哪个学院算通勤。
- G 类同时显示两轮对话。
- 去掉 B04（0 套符合，排序没有意义），以及 C03、C04（没有严格匹配的房源）。
- 不把几乎一样的房源放在同一题里（同名、同价、同面积、同房型）。
- 符合的房源不到 5 套时（A01、A05 各 4 套，B01 3 套），候选就少于 5 个，不拿不符合的凑数。

`key.csv` 里有一列"Order fully set by user"。值为 yes 的题，用户已经说清楚怎么排（例如"便宜优先"），人工排序基本只是在核对规则，分析时建议和其他题分开报告。

## 还需要小组处理的事

1. ~~确认 `CONVENTIONS.md` 里的待定条目~~：2026-11-05 已确认。下一步把 `cases/holdout_manifest.json` 里的 `holdout_sha256` 发到组群，作为封存记录。之后题目或 G 类条件一改，hash 就会变。
2. **A07 怎么处理**：留作"条件太严、结果为空"的题（改到 C 类，或保留在 A 类并在报告中说明），还是换一道题。
3. ~~留出集里有题已经用 agent 跑过~~：2026-11-05 已重分，见上面第 8 条。**留出集的 20 题在 11/9 冻结系统之前不要在 agent 上跑**，包括 xlsx 里"Run Instructions"说要复制进 agent 的那 8 题。
4. **人工核验 20%**：另一位组员在 Excel 里手动筛几题，和 `gold_answers.json` 对照，并填 `cases.json` 里的 `verified_by`。我已经用另外写的 pandas 筛选核对了 A01、A03、A08、B01、B03、G03、G05 第 2 轮，结果完全一致，但这不能代替组员核验。
5. **填 `author`**：写明每题是谁出的。
6. **留出集只跑一次**：11/9 冻结系统后运行 `evaluation/run_eval.py holdout --holdout --runs 3`，开发集也用同一版代码跑 3 遍（`run_eval.py final --runs 3`）。`run_eval.py` 只支持 B5 agent，基线 B1–B3 还没有。
7. **行为分**：冻结后两人各自复制一份 `results/<标签>_behaviour.csv`，对照 `_review.md` 打决策分和解释分（各 0 或 1），规则见评估方案的指标 5。打完再看 `failure_log.md` 里作者的草稿分，它不是正式分。
8. **重新生成 PDF**：`CONVENTIONS.md` 2026-11-06 改过（第 5 节和更改记录），`CONVENTIONS.pdf`、`CONVENTIONS_confirmed.pdf` 还是旧的。
