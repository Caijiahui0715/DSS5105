# 评估约定（2026-11-05 确认）

`gold.py` 严格按本页计算标准答案。系统和评估脚本都按这一页执行，Evaluation.pdf 里原样写进去。改任何一条，都要重跑 `gold.py`，并在本页末尾记一笔。

草案中标为待定的 4 条（"below X"、入住人数、"near NUS"、"entire apartment"）已于 2026-11-05 确认，按下文执行。

## 1. 数据快照

- 房源：`output-final-delivery/rental_data_v2.csv`，2026-11-02 冻结的最终数据，369 条，全部 `scrape_status=active`。61 条已下架房源在 `removed_listings.csv` 里，**不参与评估**。系统推荐了下架房源，算作违规。
- 通勤：`commute_faculty.csv`，OneMap 公共交通缓存，369 条 × 16 个学院，出发时间工作日 08:30。评估时只读缓存，不在线调用 OneMap。
- 文件 hash 由 `gold.py` 写进 `gold/gold_answers.json` 的 metadata；系统跑分时也要记录同样的 hash。

## 2. 三分类

每套房源对每个硬条件的判定只有三种：

| 判定 | 含义 |
|---|---|
| pass | 数据明确满足 |
| unknown | 数据没写，或写了但无法判断 |
| fail | 数据明确不满足 |

整体判定：有一项 fail 就是 **excluded**；没有 fail、但有 unknown，就是 **needs_confirmation**；全部 pass 才是 **confirmed**。系统只能把 confirmed 当成"符合"展示；needs_confirmation 可以展示，但必须标"需确认"，并说出哪一项未知（`gold_answers.json` 里每套都有 `unknown_fields`）。

## 3. 各字段的判定规则

| 条件 | pass | unknown | fail |
|---|---|---|---|
| 预算 `max_price_sgd` | 租金 ≤ 上限 | 租金缺失 | 租金 > 上限 |
| 整租/合租 `rental_scope` | 一致 | — | 不一致 |
| 房型 `room_type` | 一致 | `room_unspecified`、`unknown` | 其他房型，或不是单间 |
| 区 `district_code` | 一致 | — | 不一致 |
| 性别 `tenant_gender=female` | `female_only`、`no_restriction` | `unknown` | `male_only` |
| 家具 `furnished_required` | 全家具、半家具、`furnished_unspecified` | `unknown` | `unfurnished` |
| 全家具 `furnishing_level=full`（B07） | `fully_furnished` | `furnished_unspecified`、`unknown` | 半家具、`unfurnished` |
| 能做饭 `cooking_required` | `light_cooking`、`cooking_any_cooking` | `unknown`、`cooking_prefer_not_to_say` | `cooking_not_allowed`、`not_allowed` |
| 能大火做饭 `cooking_level=full` | `cooking_any_cooking` | `unknown`、`cooking_prefer_not_to_say` | `light_cooking`、禁止做饭 |
| 空调 | `yes` | `unknown` | `no`（数据里没有） |
| 卧室、卫生间下限 | ≥ 下限 | 缺失 | < 下限 |
| MRT 步行（分钟或米） | 最近站在运营，且 ≤ 上限 | 最近站不在运营（在建或状态未知）且 ≤ 上限；或数值缺失 | 数值 > 上限 |
| 到学院通勤 | 缓存分钟数 ≤ 上限 | 缓存里没有 | > 上限 |
| 物业类型 | 归一化后在列表内 | — | 不在列表内 |
| 面积、餐饮数量下限 | ≥ 下限 | 缺失 | < 下限 |
| 能签 N 个月 `lease_months` | 房源最短租期 ≤ N（Flexible 算 0，Short Term 算 1，1 year 算 12，2 years 算 24） | 缺失、`Prefer not to say` | 最短租期 > N |
| 房东不同住 | `no` | `unknown` | `yes` |
| 可养宠物 | `pets_allowed` | `unknown` | `no_pets` |
| 独立卫浴 | `yes` | `unknown` | `no`（数据里没有） |

其他约定：

- **租金用哪一列**：用 `rent_monthly_sgd_now`（最近一次记录的挂牌价），缺失时才退回 `rent_monthly_sgd`。H01、H02 这类题两列都要答。
- **"below / under X"** 按 ≤ X 处理，和"no more than X"相同。- **MRT 在建站**：数据只给最近的车站，不管它是否运营。最近站在建时，最近的运营站只会更远：数值已经超过上限就判 fail，否则判 unknown。
- **入住人数 `occupant_count`** 不作为筛选条件，因为整租房源没有"最多可住几人"的字段。它只用来考系统的解析准确率（A06、A07 的 must_not 要求不能把 4 个人理解成 4 个卧室）。- **物业类型归一化**：转小写，空格和连字符换成下划线（`HDB Flat` → `hdb_flat`，`Condominium` → `condominium`）。
- **坐标推断的房源**：`coord_source=pg_poi_inferred` 的房源，通勤和 MRT 数值误差约 165 m，标准答案照常使用，但 `top_3` 里会带上 `coord_source`，失败分析时要考虑这一点。

## 4. 题意上的约定

- **"near NUS" / "close to NUS"**（G01、G05 第 1 轮）：没给数字，按软偏好处理，只用来排序（通勤优先），不作为筛选条件。- **学院**：按每题原设定（A03、A10、C04 是 Faculty of Science，A04、A06、C05 是 School of Computing）。G01、G02、G05 原题没有学院，按通勤排序需要目的地，设为 Faculty of Science（和 agent 运行时注册的一致）。写在题目的 `preconditions` 里。
- **"entire apartment"**（G04）：理解为整租，不限制物业类型。新加坡口语里 apartment 常泛指一套房子。- **G04 第 2 轮"也可以合租"**：去掉整租/合租限制，整租和单间都算。
- **G05**：两轮都没说整租还是合租，所以不限制。
- **E、F 类里的"this property"**：先发一句"Tell me about listing 500074659."作为前置轮，不计分；之后的提问都指这套房源。

## 5. 排序

- 按用户说的优先项做严格字典序；用户没说时按租金升序。租金如果不在用户的优先项里，就作为最后一级比较；再相同时按 listing_id 排。
- 映射：price → 租金升序；commute → 到所设学院的通勤升序；mrt → MRT 步行分钟升序；space → 面积降序；food_places → 1 km 内餐饮数降序。缺失值排最后。
- 只对 confirmed 排序。`top_3` 是标准答案的前 3 名。

## 6. 放宽（C 类）

只放宽题目指定的那一个字段（`relaxation_field`）。在"其他条件全部 pass、只有这一项 fail"的房源中，找能让至少一套变成 confirmed 的最小改动，写进 `relaxation.minimum_relaxed_value`；`ladder` 给出前几档放宽值和累计套数。放宽 MRT 条件时，最近站必须在运营。

`relaxation_field` 是列表时（C08），每个字段单独试一次，分别给出结果，不比较不同字段之间谁"更小"。

如果单改这一个字段不够（例如 C06），就写 `single_field_relaxation_available=false`，并列出单独去掉哪个其他条件能有结果（`other_single_field_drops`）。

## 7. 变更记录

| 日期 | 改了什么 | 谁确认 |
|---|---|---|
| 2026-11-05 | 初稿；改用 11/02 冻结数据重算全部标准答案 | — |
| 2026-11-05 | 4 条待定项按初稿确认，规则未改动 | Caijiahui0715 |
| 2026-11-05 | 新增 B07 用的"全家具"规则；C 类可以同时测试多个放宽字段（C08） | Caijiahui0715 |
