# DSS5105 — Singapore Rental Decision Agent

## 运行

```powershell
.\.venv\Scripts\python.exe .\demo.py --chat             # Agent（默认）
.\.venv\Scripts\python.exe .\demo.py --chat --trace     # 同时打印每轮的工具调用、链接检查结果和被拦的回复
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
- 保存条件变更时，工具参数必须引用用户本轮原话（`user_quote`）；`preview=true` 只看不改。条件变更、收藏和排除以固定文字显示给用户。
- 数据未注明不再等同于不符合：其他条件都符合、只是部分要求未注明的房源单独列为“需确认”，并说明是哪个条件卡住了结果。
- 已保存的搜索没有严格匹配时，按原 workflow 的单项放宽规则（预算约 +10%、MRT +5 分钟，结果经过链接检查）在回复末尾固定附上让步建议。
- 整租 / 合租使用 `rental_scope`（entire_unit / room）。数据只根据明确的 “Whole Unit” 文字或房间标签判断，未注明的房源列为“需确认”，不当作整租。
- 物业类型使用 `property_types`：“公寓”对应 condominium、executive_condominium、apartment、walk_up_apartment，“组屋”对应 hdb_flat。保存时会显示实际使用的类型，说得不对可以直接纠正。
- 用户愿意加预算或问“有没有更好的”却没给数字时，agent 调用 `explore_budgets` 比较几个价位（只查数据库、不检查链接、不保存条件），说明预算是不是瓶颈，再问用户选哪个方向。
- 回复没通过检查时，会把原因反馈给模型重试一次；仍不通过才退回模板，没有模板时显示当前保存的条件和展示过的房源。`--trace` 会显示被拦原因。
- 链接检查沿用 workflow 规则：搜索、详情、比较、查看候选清单时，对要展示的房源检查原网址（active / inactive / unknown，不改变排序，inactive 排除，原因写入 `listing_health.error_reason`）；`explore_budgets` 只统计数据库，不检查链接。模型拿到每套房源的 `link_note`（与 workflow 相同的说明句）和 `availability_note`，要求分开说明；链接无法确认的房源由系统在回复末尾固定列出原因。
