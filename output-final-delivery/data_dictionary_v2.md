# rental_data_v2.csv 数据字典

**版本**: v2.3 · **更新**: 2026-09-18 · **行数**: 519 条有效在租房源 · **字段数**: 50
**配套文件**: `removed_listings.csv`（74 条已下架房源，字段结构相同）

---

## 1. 数据集概览

| 项目 | 说明 |
|---|---|
| 数据对象 | PropertyGuru 新加坡站挂牌租房房源（Bukit Timah / Clementi / West Coast 等 D05 及周边区域为主，少量外区） |
| 采集时间线 | v1 搜索页采集 2026-09-09 → 详情页补齐 2026-09-17 → 失效/异常清洗 2026-09-17~18 |
| 反爬与获取方式 | Playwright 有头浏览器 + Cloudflare 会话复用；数据载体为页面内嵌 `__NEXT_DATA__` JSON |
| 坐标系 | WGS84 经纬度 |
| 清洗记录 | 74 条下架（removed）、6 条单间面积异常剔除、1 条无法定位剔除（git 历史可追溯） |

**处理流水**: 600（v1）→ 剔除 74 下架 → 526 active → 剔除 6 条面积异常 → 剔除 1 条 Paradise Island（无法定位）→ **519**

---

## 2. 字段字典

### 2.1 标识与价格

| # | 字段 | 类型 | 来源 | 说明 | 覆盖 | 典型值 / 范围 |
|---|---|---|---|---|---|---|
| 1 | `listing_id` | string | PG | 房源唯一 ID（主键） | 100% | — |
| 2 | `title` | string | PG | 挂牌标题（多为项目名/地址） | 100% | — |
| 3 | `listing_url` | string | PG | 房源链接，可用于回访核验 | 100% | — |
| 4 | `rent_monthly_sgd` | float | v1 | 月租（S$，9-9 采集时点） | 100% | 中位 4300，[580, 80000] |
| 5 | `rent_price_type` | string | v1 | 价格性质：`asking` 要价 / `negotiable` 可议 / `starting_from` 起价 / `guide_price` 指导价 | 100% | asking 68% |
| 31 | `rent_monthly_sgd_now` | float | PG 9-17 | 现挂牌价；与 #4 差值可分析降价行为 | 99% | 中位 4400 |

### 2.2 户型与面积

| # | 字段 | 类型 | 来源 | 说明 | 覆盖 | 取值 |
|---|---|---|---|---|---|---|
| 6 | `rental_scope` | string | PG 详情页 | 租赁方式：`room` 单间 / `entire_unit` 整租。中介自行申报字段 | 99% | entire_unit 348, room 169 |
| 7 | `room_type` | string | PG 详情页 | 房型：`common_room` / `master_room` / `studio` / `shared_room` / `room_unspecified`。整租房源不适用（unknown） | 34% | common 121 |
| 8 | `property_type` | string | PG | 物业类型：condominium / hdb_flat / apartment / terraced_house / detached_house 等 | 100% | condo 273, HDB 100 |
| 9 | `bedrooms` | int | PG | 卧室数；0=studio；单间出租不适用（空） | 68% | 中位 3 |
| 10 | `bathrooms` | int | PG | 卫浴数 | 92% | 中位 2 |
| 11 | `area_sqm` | float | PG | 面积（㎡）。口径由 #12 区分。极值（>2000㎡）为豪华有地住宅，属实 | 99% | 中位 68 |
| 12 | `area_scope` | string | PG | 面积口径：`floor_reported` 整套面积 / `room_reported` 单间面积 | 99% | floor 350, room 168 |

> ⚠️ 单间分析建议：`rental_scope=='room'` 的行面积中位仅 11㎡，与整套不可比；按平米算租金时用 `area_scope` 分组。

### 2.3 位置与交通

| # | 字段 | 类型 | 来源 | 说明 | 覆盖 | 取值 |
|---|---|---|---|---|---|---|
| 13 | `district_code` | string | PG | URA 规划区（D05=Clementi/West Coast 等） | 100% | D05 最多(101) |
| 14 | `address` | string | v1 | 地址文本（门牌+街道，区域），约 18% 无门牌号 | 100% | — |
| 34 | `postcode` | string | PG 详情页 | 6 位邮编（精确到楼栋）。注意：个别中介填占位值 | 100% | — |
| 35 | `street_name` | string | PG 详情页 | 标准化路名 | 94% | — |
| 36 | `latitude` | float | 见 #48 | 纬度 | **100%** | [1.240, 1.454] |
| 37 | `longitude` | float | 见 #48 | 经度 | **100%** | [103.693, 103.969] |
| 48 | `coord_source` | string | 处理生成 | 坐标来源：`onemap_postcode`（496，OneMap 官方地理编码，门牌级）/ `pg_poi_inferred`（21，由周边设施步行距离反推，误差约 165m）/ `onemap_street_geocode`（2，路名级） | 100% | — |
| 49 | `coord_error_m` | float | 处理生成 | 坐标不确定度（米）。inferred≈165；street≈500；postcode 级不标注 | 4% | — |
| 15 | `mrt_station` | string | PG POI | 最近地铁站（含站编号，如 CR17 Clementi MRT） | 86% | — |
| 16 | `mrt_distance_m` | int | PG POI | 最近 MRT 步行距离（米，路网测算） | 86% | 中位 620 |
| 17 | `mrt_minutes_reported` | int | PG POI | 最近 MRT 步行时间（分钟） | 86% | 中位 7 |
| 18 | `mrt_operation_status` | string | 处理生成 | `operational` 运营中 / `under_construction` 在建（站名含 U/C） | 84% | operational 423 |

### 2.4 出租条件（PG 详情页 unitDetails，缺失=页面未提供）

| # | 字段 | 类型 | 说明 | 覆盖 | 取值 |
|---|---|---|---|---|---|
| 21 | `tenant_count_reported` | int | 最多租客数（单间场景） | 27% | 中位 1 |
| 22 | `tenant_gender_label` | string | 中介标注的租客性别：female / male / any | 27% | any 102 |
| 23 | `gender_restriction` | string | 规范化性别限制：`no_restriction` / `female_only` / `male_only`。**分组分析用此列** | 27% | no_restriction 101 |
| 24 | `gender_preference` | string | 性别偏好（页面不提供，仅 1 条有值，**建议忽略此列**） | 0% | — |
| 25 | `cooking_policy` | string | 炊事政策：`light_cooking` 可轻炊 / `cooking_any_cooking` 不限 / `cooking_not_allowed`+`not_allowed` 禁止 / `cooking_prefer_not_to_say`。仅单间场景有值 | 18% | light 72 |
| 26 | `furnishing` | string | 装修：`fully_furnished` / `partially_furnished` / `unfurnished` / `furnished_unspecified` | 99% | full 258, partial 219 |
| 27 | `landlord_lives_in` | string | 房东是否住内：yes / no（源自 ownerStays） | 22% | no 71 |
| 28 | `private_bathroom` | string | 独立卫浴：仅页面明确提供才填（yes） | 1% | yes 5 |
| 29 | `air_conditioning` | string | 空调：yes / no（仅结构化字段明确提供才填） | 40% | yes 208 |
| 30 | `pets_policy` | string | 宠物：`no_pets` / `pets_allowed`+`allowed`（仅明确提供才填） | 19% | no_pets 99 |

> 空值与 `unknown` 语义一致：**页面未提供即保留 unknown/空，不做推断**。

### 2.5 周边设施特征 A：OneMap 官方主题图层（1km 直线内数量，快照 2026-09-18）

| # | 字段 | 设施 | 数据机构 | POI 库存 | 覆盖 | 中位 |
|---|---|---|---|---|---|---|
| 38 | `poi_hawker_1km` | 小贩中心 | NEA | 129 | 95% | 1 |
| 39 | `poi_library_1km` | 图书馆 | NLB | 28 | 95% | 0 |
| 40 | `poi_sport_1km` | 体育设施 | SportSG | 45 | 95% | 0 |
| 41 | `poi_healthcare_1km` | 医院+注册药店 | MOH / HSA | 31+249 | 95% | 2 |
| 42 | `poi_community_1km` | 民众俱乐部 | PA | 125 | 95% | 1 |

### 2.6 周边设施特征 B：PropertyGuru What's nearby（步行路网距离，快照 2026-09-17）

| # | 字段 | 说明 | 覆盖 | 中位 |
|---|---|---|---|---|
| 43 | `pg_school_count` | PG 列出的周边学校数（含私立/国际学校） | 97% | 20 |
| 44 | `pg_school_nearest_walk_m` | 最近学校步行距离（米） | 97% | 600 |
| 45 | `pg_school_nearest_walk_min` | 最近学校步行时间（分钟，≈80m/min 口径） | 97% | 7 |
| 46 | `pg_mrt_count` | PG 列出的周边 MRT 站数 | 85% | 2 |
| 47 | `pg_mrt_nearest_walk_m` | 最近 MRT 步行距离（米） | 85% | 600 |

### 2.7 周边设施特征 C：OpenStreetMap（1km 直线内数量，快照 2026-09-18，ODbL）

| # | 字段 | 说明 | POI 库存 | 覆盖 | 范围 |
|---|---|---|---|---|---|
| 50 | `poi_fnb_1km` | 1km 内餐饮点（restaurant/cafe/fast_food/food_court/pub/bar 等） | 10,724（全岛） | 100% | 中位 64，[3, 1395] |

### 2.8 时间与管理字段

| # | 字段 | 类型 | 说明 |
|---|---|---|---|
| 19 | `listed_date` | date | 挂牌日期（PG lastPosted） |
| 20 | `collected_at` | datetime | v1 采集时间（2026-09-09） |
| 32 | `scrape_status` | string | 本文件全部为 `active`（下架房源见 removed_listings.csv） |
| 33 | `enriched_at` | datetime | 预留字段，当前为空（补齐批次日期见 git 提交历史：2026-09-17） |

---

## 3. 数据质量与使用注意事项

1. **unknown / 空值**：一律表示"页面未提供"，未做任何推断填充。缺失集中在中介条件类字段（单间场景才有：tenant/gender/cooking），以及 PG 站点本身不含的类别（gender_preference、private_bathroom 基本不可用）。
2. **rental_scope 为申报值**：由中介勾选，已人工核验修正 5 条（git `7754c79`）；1km 内小面积的 entire_unit 多为 co-living 微型 studio（Coliwoo、lyf 等），非错误。
3. **面积异常已清洗**：6 条单间面积 <2㎡ 或 >40㎡（整套面积误填）的房源已剔除（git `6fb3a8e`）。
4. **坐标精度分三档**：严格距离计算建议仅用 `coord_source=='onemap_postcode'`（496 条）；`pg_poi_inferred` 的 21 条建议加 ±200m 不确定度（方法：周边设施三角定位，485 条盲测中位误差 165m）。
5. **两套 POI 特征口径不同**：`poi_*`（OneMap/OSM）为直线 1km 计数；`pg_*` 为 PG 步行路网距离（更真实但仅学校/MRT 两类）。合并综合分时注意归一化。
6. **价格双时点**：`rent_monthly_sgd`（9-9）与 `rent_monthly_sgd_now`（9-17）差值可做"一周降价幅度"；removed 房源的租金是"下架前要价"，勿与在租混合同一回归。
7. **外部数据引用**：OneMap（SLA 官方开放数据）；OpenStreetMap 按 ODbL 许可使用，公开发布需署名；PropertyGuru 数据仅用于学术分析。

## 4. 复现脚本索引（propertyguru_data/）

| 脚本 | 作用 |
|---|---|
| `scrape_propertyguru.py` | 列表页→详情页抓取（Playwright） |
| `enrich_listings.py` | v1→v2 字段补齐主流程（含 Cloudflare 会话） |
| `enrich_geo.py` | 邮编/路名 + OneMap 地理编码 |
| `enrich_poi.py` | OneMap 主题图层 1km 计数 |
| `enrich_nearby.py` | PG What's nearby 解析 + 坐标重试 |
| `infer_location.py` | POI 三角定位反推坐标（含精度校准） |
| `raw_pg/*.json` | 每条房源的原始结构化数据（可离线重算） |
| `poi_themes/*.json` | OneMap 主题图层与 OSM F&B 快照 |
