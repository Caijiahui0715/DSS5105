# DSS5105 — Singapore Rental Decision Agent

## 运行

```powershell
.\.venv\Scripts\python.exe .\demo.py --chat             # Agent（默认）
.\.venv\Scripts\python.exe .\demo.py --chat --trace     # 同时打印每轮的工具调用（失败时带原因）、货币换算、链接检查结果和被拦的回复
.\.venv\Scripts\python.exe .\demo.py --chat --workflow  # 原固定 LangGraph workflow，作对照
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

需要 `.env` 中的 `OPENAI_API_KEY` 和 `OPENAI_MODEL`，模型需要支持 tool calling。

## 架构

- `agent.py`：外层 agent。模型读取对话、会话状态和工具结果，自己决定调用哪些工具、调用几次；每轮最多 5 轮工具调用。
- 工具都是确定性代码：`search_listings`、`explore_budgets`、`get_listing_details`、`explain_listing`、`compare_listings`、`shortlist`、`exclude_listings`。
- `decision.py`：条件三态判断（符合 / 不符合 / 数据未注明）、逐个放开条件的诊断、排序溯源。严格匹配结果与 `tools.search_listings` 完全一致。
- `graph.py`：原固定 workflow，保留作评估 baseline。
- `tools.py`、`response.py`、`mock_db.py`：检索与 URL 校验、事实模板、数据加载，两套流程共用。

## Agent 的边界

- 事实只来自工具结果或会话状态。回复里的房源编号、金额、分钟数、套数必须出现在本轮工具输出中，否则回退为模板草稿；提出联系房东、确认可租、预约看房等超出能力的动作也会回退。
- 保存条件变更时，工具参数必须引用用户本轮原话（`user_quote`）；`preview=true` 只看不改。`set` 里只放要改成新值的字段，空值和默认值会被忽略（模型有时会把所有字段都带上，否则会清掉已保存的条件）；要去掉某个已保存条件，用 `clear` 列出字段名。条件变更、收藏和排除以固定文字显示给用户。
- 数据未注明不再等同于不符合：其他条件都符合、只是部分要求未注明的房源单独列为“需确认”，并说明是哪个条件卡住了结果。
- 已保存的搜索没有严格匹配时，按原 workflow 的单项放宽规则（预算约 +10%、MRT +5 分钟，结果经过链接检查）在回复末尾固定附上让步建议。
- 整租 / 合租使用 `rental_scope`（entire_unit / room），取 v2 数据的出租方式；未注明的房源列为“需确认”，不当作整租。引导用户补充条件时先问整租还是合租，选了合租再问房型。用户没选、而完全符合的房源里两种都有时，回复末尾固定提示展示的是哪一种，以及另一种的套数和最低月租。
- 排序：MRT 步行距离始终参与（米数 ÷ 参考距离，参考距离 = 步行上限 × 85 米，没给上限时 850 米），有预算时再加月租 ÷ 预算；吃饭方便、到 NUS 通勤只在用户提出时参与。用户点名的偏好占 70%，其余平分；没点名时等权。没有 MRT 数据或最近的站尚未通车按参考距离计（比值 1）；但用户点名在意 MRT 时，这类房源列为“需确认”。并列时先比权重最高的一项，再比下一项，最后才比月租。
- 限制条件（符合 / 不符合 / 未注明三态，未注明一律列为“需确认”，整租也一样）：`tenant_gender`（用户自己说明的住户性别：female / male / mixed，对照数据的 gender_restriction）、`landlord_not_living_in`（不要房东同住）、`furnished_required`、`air_conditioning_required`。
- 到 NUS 的公共交通时间：`max_commute_minutes` 和排序偏好 `commute`。数据从可选文件 `output-final-delivery/commute_nus.csv`（列 listing_id、commute_nus_minutes）读取；文件不存在时所有房源的通勤时间都是未注明。测试用 fixture 里的模拟分钟数。
- 面积：明确的最低面积用 `min_area_sqm`（平方米；sqft × 0.09290304）筛选；“空间大一点 / 宽敞”用 `ranking_priority=space`，无需先给预算或整租方式。空间偏好占 70%，按同一出租方式和面积口径内的面积百分位排序，不把房间与整套平方米直接比较。整租使用 `floor_reported`，房间使用 `room_reported`；未注明、出租方式未知或房间只报整套面积的房源列为“需确认”。搜索结果和详情显示面积口径。
- 其余数据中的租房需求也已接入（缺失仍为“需确认”）：卫生间数 `min_bathrooms`、独立卫浴 `private_bathroom_required`、宠物 `pets_allowed_required`、报价性质 `rent_price_types`、项目/地址/街道/邮编 `title_keyword` / `address_keyword` / `street_name` / `postcode`、最近运营 MRT `mrt_station`、周边站数 `min_mrt_stations`、步行米数上限 `max_mrt_distance_m`、挂牌日期下限 `listed_after`、房东明确的性别偏好 `gender_preference`。
- 家具程度用 `furnishing_types`（全家具/部分家具/无家具/带家具但程度未注明），做饭强度用 `cooking_level`（light 接受轻炊或不限烹饪；full 仅接受不限烹饪；none 要求禁止做饭）。旧的 `furnished_required`、`cooking_required` 继续兼容；改成无家具/禁止做饭时需清掉冲突的旧条件，否则工具报错且不保存。
- 周边数量下限：`min_food_places`、`min_hawker_centres`、`min_libraries`、`min_sports_facilities`、`min_healthcare_places`、`min_community_centres`、`min_schools`。前六项是直线 1 公里内计数，学校和 MRT 使用 PropertyGuru 的周边统计；医疗计数混合医院和药店，不能据此承诺附近一定有医院。只想“多一些”时用排序偏好 `food_places` / `hawker` / `libraries` / `sports` / `healthcare` / `community` / `schools`，不凭空设置数量门槛。
- 最近学校步行上限使用 `max_school_walk_m` / `max_school_walk_minutes`；“学校近”用排序偏好 `school_distance`。这些指最近广告学校，不特指 NUS 或其他指定学校。`pg_mrt_nearest_walk_m` 作为 MRT 米数的后备来源，但仍排除未通车站；周边 MRT 总数不代表所有站均已运营。
- 地点范围使用 `nearby_location`（`query` 或用户提供的 `latitude` / `longitude`，以及明确的 `radius_m`）。地名用现有 OneMap 配置解析；多地点歧义或 API 失败时不保存位置条件，要求更明确地址/邮编/坐标。坐标距离为直线距离，使用房源的 `coord_error_m` 判断边界，误差跨过范围上限时列为“需确认”。位置和新增条件支持保存、清除和不改原条件的预览，Agent 与 workflow 共用规则。
- 物业类型使用 `property_types`：“公寓”对应 condominium、executive_condominium、apartment、walk_up_apartment，“组屋”对应 hdb_flat。保存时会显示实际使用的类型，说得不对可以直接纠正。
- 用户愿意加预算或问“有没有更好的”却没给数字时，agent 调用 `explore_budgets` 比较几个价位（只查数据库、不检查链接、不保存条件），说明预算是不是瓶颈，再问用户选哪个方向。
- 工具出错时，错误信息会写明哪里错了、下一步怎么做（例如换成 ISO 4217 币种代码再调用，或询问用户）；提示词要求模型能改正的先改正参数重试，再回答用户。币种别名 RMB 在换算前自动转成 CNY。
- 回复没通过检查时，会把原因反馈给模型重试一次；仍不通过才退回模板，没有模板时显示当前保存的条件和展示过的房源。`--trace` 会显示被拦原因。
- 链接检查沿用 workflow 规则：搜索、详情、比较、查看候选清单时，对要展示的房源检查原网址（active / inactive / unknown，不改变排序，inactive 排除，原因写入 `listing_health.error_reason`）；`explore_budgets` 只统计数据库，不检查链接。模型拿到每套房源的 `link_note`（与 workflow 相同的说明句）和 `availability_note`，要求分开说明；链接无法确认的房源由系统在回复末尾固定列出原因。
