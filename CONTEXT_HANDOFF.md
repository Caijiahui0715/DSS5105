# Singapore Rental Agent — 对话交接（2026-09-16，9/17 更新）

## 交接目的与当前任务

用户希望结束过长的旧对话，在一个新的、精简上下文的对话中继续项目。9/16 的开发已经完成并提交；9/17 只做了讨论（链接检查 403、数据字段缺失、Firecrawl），同时数据 v2 已放进 output-final-delivery/，最新状态见文末“2026-09-17”一节。没有未完成的实现任务。新对话先接收交接、核对工作目录和 Git 状态，简短确认后等待用户的下一项指令；不要自行继续开发、提交、推送、切换分支或安装依赖。

## 项目与工作目录

- 项目：DSS5105，新加坡租房推荐 Agent。
- 原始目录：C:\Users\23305\Desktop\nus\DSS5105\group project\DSS5105
- 当前分支：Agent-system（以 git branch --show-current 再核对）。
- 9/16 的改动已提交到 Agent-system（af999613）；main 上 9/17 有一个本地数据提交 2aa8eb2e（见文末）。修改前先看 git status，保留已有工作区修改。不要把远程分支或 main 的工作树当作最新代码。
- 9/16 交接前修改过的文件（已随 af999613 提交）：demo.py、graph.py、mock_db.py、models.py、parser.py、response.py、tests/test_graph.py、tests/test_parser.py、tests/test_tools.py、tools.py。
- output-final-delivery/ 是未跟踪的本地目录，包含最终数据；不要删除、覆盖或自动加入 Git。9/17 起还包含 rental_data_v2.csv 和 removed_listings.csv，代码仍读取 rental_data_v1.json。
- 用户不要跟踪 CSV/PDF/XLSX。不要转移、打印或提交 .env、API key、OneMap token、账号凭据；历史中出现的密钥也不要复述。
- Python：原目录 .venv\Scripts\python.exe。测试使用标准库 unittest，环境没有 pytest；不需要安装 pytest。

## 用户明确的设计决定

1. 编码使用 ponytail：复用现有代码、标准库优先、最小可工作的改动；用户不希望层层 if 和过度抽象。执行编码任务时先读取可用 ponytail/SKILL.md。
2. （2026-09-16 用户改为）采用“外层 agent、内层确定性工具”：agent.py 为默认入口，由模型选择工具；graph.py 受控工作流保留为评估对照（demo.py --workflow）。事实、排序、URL 校验和状态更新仍由代码决定。
3. URL 三状态保留 active / inactive / unknown。网络失败不能被当作房源下架。
4. 不允许按 URL 状态重新排序：不能 active 优先、unknown 作为不足时才补充。两者严格保持原推荐排序。
5. 无法核实的事实要如实说，不编造、不承诺联系房东、确认未来可租、保留房源或预约看房。
6. 有至少一个条件先搜索，再逐步引导补充偏好；不逐项强制确认预算、房型。
7. 预算未说明币种（包括泛称“元”）默认为 SGD；明确其他币种才转换。裸 $ / ¥ 视为歧义，不擅自猜币种。
8. 用户中文输入回复中文，英文输入回复英文；短回复结合上一轮语言。
9. SQLite 最终落库由队友负责；目前先用最终 JSON 建内存 SQLite，后续再接队友的数据源。
10. same_address_different_ids 不再判断/提醒，默认不同 listing_id 为不同房源；tenant_count_reported 是允许入住的最大人数。忽略 tenant_count_scope_unconfirmed。大面积不提醒，小于 80 sqft 的异常面积提醒核实。

## 当前文件职责与架构

- models.py：Pydantic SearchPreferences、ParsedTurn；Listing / RankingResult 等使用 dict；本轮增加 ListingCheckSummary 和 ListingValidationResult TypedDict。
- parser.py：model.with_structured_output(ParsedTurn)，从用户消息和会话状态识别一个业务意图、提取并合并完整偏好、解析房源序号/ID、币种、让步编号等。
- graph.py：LangGraph 节点、条件路由、共享 AgentState。明确的查看清单、比较、指定 ID 详情等有规则快捷路由，其余使用模型理解。
- tools.py：参数化 SQL 搜索、读取结构化房源限制、价格/MRT 排序、URL 健康检查与缓存、让步搜索、OneMap 数据补充。
- mock_db.py：create_database() 从 output-final-delivery/rental_data_v1.json 加载 600 条最终 V1 房源，创建内存 SQLite；create_mock_database() 将 12 条旧合成 fixture 适配为同一 V1 schema，并预置模拟 URL 健康状态。
- response.py：基于工具结果生成中英文事实草稿、房源详情、比较、让步建议/预览和 URL 不确定性说明。
- demo.py：ChatOpenAI + MemorySaver，--chat 多轮模式；默认运行 agent.py，--workflow 运行 graph.py，--trace 打印工具调用；使用 config.env() 加载环境变量/.env。MemorySaver 和 SQLite 都在内存中，关闭进程会丢失状态。
- agent.py：tool-calling 循环（begin_turn → agent ⇄ tools → finalize）。6 个工具包装现有函数；同一条消息里的多个工具按顺序执行；保存条件需 user_quote 引用用户本轮原话；finalize 检查房源编号/金额/分钟数/套数是否出自工具输出，不通过则回退模板草稿。
- decision.py：条件三态（pass / fail / unknown）、needs-confirmation 分组、逐个放开条件的诊断（decision_context）、排序溯源（读取 source_evidence_v1.json）。

普通搜索主链：
START → language → interpret → normalize_budget → prepare_search → search
→ 有 SQL 候选：restrictions → rank → validate_listing_status
  → 有可展示结果：respond
  → 无可展示结果：relaxation → respond
→ 无 SQL 候选：relaxation → respond
→ generate_response → END

其他意图：shortlist_listing、remove_shortlisted_listing、show_shortlist、compare_shortlist、show_listing_details、show_results、accept_relaxation、reject_relaxation、reject_results、unknown。

graph.py 对照流程中，模型主要用于需求理解和事实草稿自然语言改写，搜索、评分、URL 校验和状态更新由代码决定。agent.py 中由模型选择工具，但工具本身和状态写入仍是确定性代码。收藏、移除收藏、查看清单及部分排除回复直接返回事实草稿，避免模型改错结果。

## State 与多轮语义

AgentState 保存 preferences、listings、ranked_listings、restrictions、relaxations、shown_listing_ids、shortlisted_listing_ids、excluded_listing_ids、回复语言、币种换算、事实草稿/最终回复等。本轮增加 listing_check_summary。

- shown_listing_ids 保存上次实际展示的顺序，序号引用据此解析。
- 只有一套展示房源，“这套”自动解析；多套时不猜。
- 候选清单只用 shortlisted_listing_ids 查询，不拿当前搜索结果替代。
- 搜索排除列表是 excluded_listing_ids + shortlisted_listing_ids，已经收藏的房源不重复当成新推荐。
- 查看清单不覆盖原搜索 ranked_listings，但更新实际展示 ID 供指代使用。
- 新搜索清空旧搜索结果、旧让步与校验摘要，保留长期会话偏好、候选/排除 ID。

## 最终数据与评分

V1 listings 表 30 个字段，包括 listing_id、listing_url、rent_monthly_sgd、rental_scope、room_type、bedrooms、bathrooms、area_sqm、district_code、address、MRT 字段、tenant_count_reported、cooking_policy、性别/房东同住等结构化策略。listing_metadata、district_lookup 与 agent_listings view 补充可用性和 review_flags；listing_health 保存在线校验，listing_route_enrichment 独立保存 OneMap 结果。已移除不可靠的 verified_only 偏好。

- 硬筛选：预算、地区、房型、MRT 上限、做饭（允许或 light_only）、卧室/入住人数等。
- 入住日期目前无法用最终快照准确验证，只保留用户需求并明确不确定，不声称未来仍可租。
- 排序是成本比例，rank_value 越小越靠前。price = rent / budget；MRT = minutes / MRT reference。
- 两项可计算时 balanced 为 50/50；显式 price 或 MRT 优先为 70/30；只有一个可计算项则 100%。
- “离 MRT 近一点”没有分钟硬上限时，用 10 分钟作为软评分参考，不加 10 分钟 SQL 硬过滤。
- 已计算的 OneMap 步行值优先于广告分钟数。OneMap refresh_mrt_walk_data() 存在，但当前搜索 Graph 不会自动现场调用它。
- 默认让步只单项调整：预算向上取整增加约 10%、MRT 上限增加 5 分钟；不自动放宽做饭/房型等，也不自动修改用户条件。

## 本次最新完成：URL 校验后的推荐与让步闭环

1. check_listing_url() 判断 HTTP 和最终重定向 URL 的房源 ID：
   - 成功且同一 ID：active。
   - 404/410，或跳转到其他 ID/其他页面：inactive。
   - 其他 HTTP 错误、超时、网络错误、无法确认 ID 等：unknown。
2. listing_health 保存 status、checked_at、final_url、http_status、error_reason，缓存 24 小时。agent_listings 暴露 live_error_reason。
3. error_reason 包括 http_403/http_429 等、network_error、timeout、checker_error、listing_id_not_found、重定向原因。响应说明实际检查失败类型，并声明 unknown 不表示房源下架。
4. validate_ranked_listings() API 已改变：不再只返回列表，而是：
   {"ranked_listings": [...], "summary": {...}}
   summary 字段：database_match_count、checked_count、active_count、unknown_count、inactive_count、unchecked_count。
5. 普通搜索、让步分析及让步预览默认最多扫描 30 个候选，按原排名逐个检查，找到 3 个 active/unknown 可展示结果即停止。丢弃 inactive 后继续补位，包括扫描原前 10 名以后的候选。不按健康状态重排。
6. graph 在 URL 校验后增加条件分支：结果空时进入 relaxation。
7. analyze_relaxations() 也使用同一个 checker/缓存/扫描规则；match_count 是本次校验后可展示数（最多 3），不是未经校验的 SQL 总数。每项建议附带 check_summary；没有可展示结果的建议不输出。
8. 响应区分 SQL 匹配、已检查（含缓存）、active/unknown/inactive、尚未检查数量，不把可展示 3 套说成数据库全部只有 3 套。active URL 也不等于已确认仍可租。
9. preview_relaxation 再走相同校验规则，更新建议数量与 check_summary；数量变化明确提示“本次检查结果已更新”。预览始终不修改原 preferences，只有用户接受后才正式更新。
10. 查看候选/比较/详情检查用户明确指定的集合，不受搜索展示 3 套的截断影响。

已知边界：检查到 30 上限后还可能有未检查候选，因此没有结果只表示本次范围内没有可展示结果；代码仍可提供可选让步，但不证明原条件下完全没有房源。URL 检查是顺序执行、每请求默认 6 秒超时，没有并行/重试/全局时间预算。反爬 403/429 未被“解决”，而是如实记录 unknown。模型改写有提示与部分保护，不是全面事实一致性校验。

## 验证与如何继续

最新验证：
- .\.venv\Scripts\python.exe -m unittest discover -s tests
- 61 个测试全部通过。
- git diff --check 通过。
- 使用最终 600 条 JSON、模拟模型和 HTTP 403 做两轮离线测试：“预算1100能做饭” → 1210 让步 → 预览 500213223。
- 建议 match_count 与预览展示数同为 1；原预算仍为 1100；预览明确 HTTP 403 / unknown。
- 上述测试没有调用真实 GPT、OneMap 或 PropertyGuru API，不要声称通过真实在线端到端测试。
- 手动真实模型测试：原目录 .\.venv\Scripts\python.exe .\demo.py --chat；需要已有 .env 配置 OPENAI_API_KEY / OPENAI_MODEL，不打印内容。

## 2026-09-16 后续：Agent 化

- 新增 agent.py、decision.py、tests/test_agent.py、tests/test_decision.py；修改 demo.py、response.py（render_response 增加 start 参数和“需确认”行，新增 needs-confirmation / decision-context / 排序溯源 / 条件变更渲染）、README.md。之后为 rental_scope 和 property_types 小改了 models.py、tools.py、graph.py、parser.py。
- 真实运行发现 gpt-5.6-luna 在 /v1/chat/completions 不支持 function tools + reasoning（400）。demo.py 已让 agent 使用 Responses API（use_responses_api=True，--workflow 仍走 chat completions）；agent.py 用 AIMessage.text 读取 Responses 内容块。
- 真实对话测试后的修复：
  - 模型第一次搜索用了 preview=true，导致预算和做饭条件没保存。现在没有已保存条件时 preview 无效，第一次搜索一定保存。
  - agent 原先没有 workflow 的固定让步步骤。现在已保存搜索没有可展示严格匹配时，调用 analyze_relaxations()（预算约 +10%、MRT +5 分钟、URL 校验），以固定文字附在回复末尾；建议存入 state.relaxations 并出现在下一轮状态快照的 pending_relaxations。
  - 模型把“整租”映射成 room_type=studio。SearchPreferences 新增 rental_scope（entire_unit / room），tools.search_listings 增加 rental_scope 过滤，graph._has_search_criteria 与 parser 提示同步支持；decision.py 中 rental_scope 未知列为需确认，studio 与 room 房源、common/master 等房型与 entire_unit 房源互斥。
  - 需确认房源按未注明条件数量从少到多排序，同组内保持原排名。
- 第二次真实对话后的改动（用户确认方案并要求加物业类型）：
  - SearchPreferences 新增 property_types（PropertyType 字面量元组，空列表视为不限）；tools.search_listings 增加 property_type IN 过滤；graph._has_search_criteria、parser 与 agent 提示同步。“公寓”= condominium / executive_condominium / apartment / walk_up_apartment，“组屋”= hdb_flat，“有地住宅”= 各类 house。
  - 新工具 explore_budgets：decision.budget_ladder + default_budget_levels（约 1.15x / 1.5x / 2.3x 向上取整到百位，再加“不限预算”）；只查数据库、不检查链接、不保存，返回每档完全匹配 / 需确认数量、步行 10 分钟内到 MRT 数、明确整租数与最低月租，以及 strict_matches_grow_with_budget。
  - 每次保存的搜索把完全匹配数、需确认数、decision_context 存入 state.last_search，快照中为 last_saved_search。
  - 提示词：用户愿意加预算 / 让步 / 问更好选择但没给数字时，不追问、不保存，先 explore_budgets 或预览，说明瓶颈，再问一个问题。
  - finalize：回复不通过检查时删除该回复、以 SystemMessage 反馈原因并重试一次（trace 记录）；仍失败才退回草稿；没有草稿时显示当前保存条件与上次展示房源。
- 链接检查说明（用户发现 agent 只说“实时可租状态未知”，看不出链接检查结果）：
  - agent 的搜索 / 详情 / 比较 / 查看候选清单一直会调用 validate_ranked_listings；explore_budgets 不检查链接。问题在于模型只拿到 live_status 代码值，没被要求逐套说明。
  - _facts 增加 link_note（response._link_status_text 的同款句子）和 availability_note；提示词要求逐套说明链接结果，并与可租状态分开。
  - 模型回复被采用时，本轮展示过且状态为 unknown 的房源由 finalize 以“链接检查：”固定文字附在末尾；退回模板草稿时不重复（草稿的数据提示已含原因）。
  - trace 条目带标签：[tool] 工具调用、[links] 每套链接状态与原因（含跳过的 inactive 数）、[guard] 回复被拦与重试；demo.py --trace 原样打印。
- 验证：unittest discover 共 93 个测试通过（原 61 个 + 新增 32 个），其中 1 个用 httpx.MockTransport 模拟 Responses API 往返；尚未用真实 GPT 完整跑通 agent，需用 demo.py --chat --trace 手动检查。

9/16 的开发任务已完成。下一步等待用户选择，不擅自实施 evaluation 或提交推送。后续可讨论持久化会话、队友 SQLite 接入、更多最终字段偏好和真实模型评估，但这些都还没有获得新的实施指令。

## 2026-09-17：Git 现状、讨论结论与待定事项

### Git 与工作区（9/17 19:00 通过 .git 日志和索引核对，本会话没有 shell，未运行 git 命令）

- Agent 化改动已提交到 Agent-system：af999613 "feat: add tool-calling rental decision agent and checked recommendations"（9/16 22:22）。工作区的 agent.py（820 行，含 link_note、explore_budgets、property_types）、tests/test_agent.py（23 个测试）、tests/test_decision.py（9 个）就是这个提交的版本；全部测试共 93 个。
- 9/17 14:43–14:46：切到 main → `git pull --ff-only origin main` → 在 main 本地提交 2aa8eb2e "data: add rental_data_v2 (fields enriched, active-only) and removed listings" → 切回 Agent-system。这个提交是否已推送、包含哪些文件没有核对，可用 `git show --stat 2aa8eb2e` 查看。
- Agent-system 上未跟踪：CONTEXT_HANDOFF.md、output-final-delivery/（现在多了 rental_data_v2.csv、removed_listings.csv）、Claude outputs/（9/16 设备断线时留下的旧补丁备份，已过时）。
- 新窗口先运行 `git status` 和 `git log --oneline -3` 再核对一次。

### 链接检查几乎全是 403（只讨论，未实施）

- 原因：600 个网址都来自 PropertyGuru，网站拦截程序请求（反爬），403 与房源是否下架无关。结果几乎全是 unknown，inactive 排除基本不会触发，检查还拖慢回复。
- 助手立场：不协助绕过反爬（伪装浏览器、代理、Firecrawl 隐匿模式都不做）。用户希望做"实时监控"，保证演示时能打开链接；已说明 403 只挡程序，用户在浏览器里点开一般正常，演示的真实风险是房源已经下架。
- 已提出、等用户选择的方案：
  1. 同一次运行连续遇到 403 就停止请求；状态仍是 unknown，原因记为"网站拒绝自动检查"，回复只说明一次。三状态、不改排序的规则不变。
  2. 在线检查做成开关，演示和评估默认关闭，改为说明"数据采集于某日，现在是否仍在出租无法确认"，评估结果也可复现。
  3. 演示前人工核验：导出演示对话会展示的房源 → 前一天在浏览器逐个点开标记 → 程序启动时把核验表写入 listing_health（已下架的排除，有效的显示"链接已于某日人工核验"）。
  4. 前端卡片显示快照信息兜底，链接在新标签页打开，不用 iframe；演示前一周请数据组刷新数据。
  5. 真正的实时监控需要平台授权或官方接口，可写进 Strategic Recommendations。
- 新情况：数据 v2 已剔除 74 条下架房源，接入后方案 3 只需在演示当天复核。

### 数据 v2（已放进 output-final-delivery/，代码尚未接入）

- 代码现状：mock_db.create_database() 仍读取 rental_data_v1.json（600 条、30 字段，全部来自 PropertyGuru 搜索结果卡片，没有详情页）。
- v2：rental_data_v2.csv 526 条、33 字段，scrape_status 全是 active；removed_listings.csv 74 条，状态 removed。两者合起来正好是 v1 的 600 条，没有重叠。新增列 rent_monthly_sgd_now（45 条与原月租不同）、scrape_status、enriched_at（全空）。
- 同一批 526 条的字段覆盖率（v1 → v2）：
  - 大幅补齐：出租方式 34% → 99.6%（整租 352、房间 172、未知 2）；面积 68% → 99.8%；家具 5% → 99%；空调 0.8% → 40%；性别限制 0.6% → 28%；房东同住 1.3% → 23%；宠物 0.4% → 20%；做饭 0.4% → 19%。
  - 基本没变：房型 35%、卧室数 67%、MRT 分钟数 86%、可住人数 26% → 28%、独立卫浴 1%。
- 接入前要处理：
  - 格式：v2 是 CSV，没有 listing_metadata / district_lookup；START_HERE_ZH.md、字段字典、source_evidence 都还是 v1 版本。
  - 取值和代码不一致：cooking_policy 出现 light_cooking（72）、cooking_any_cooking（13）、cooking_not_allowed（9）、cooking_prefer_not_to_say（3）。tools.search_listings 和 decision.condition_status 只认 allowed / light_only，照现在的代码 v2 里只有 1 条能匹配"要做饭"，light_cooking 等会被判成不符合。另外 pets_policy 有 no_pets / pets_allowed，gender_restriction 有 no_restriction，tenant_gender_label 有 any，area_scope 有 room_reported。先和数据组对齐取值，再在加载时做映射。
  - 出租方式的可信度：352 条整租里有 347 条在 v1 是 unknown，补值依据没有记录。抽查发现可疑：16 条"整租"面积小于 25 平方米（包括 Coliwoo、Lyf One-North 这类 coliving，以及标 4.09 平方米的 344 Clementi Avenue 5），3 条"整租"月租低于 S$1,800。数据字典原本规定不能把未知当整租，接入前要问清方法，必要时把补值单独成列。
  - 排序和筛选用 rent_monthly_sgd 还是 rent_monthly_sgd_now，需要决定。
- 之前针对 v1 提的补字段方案（规则推断出租方式、人工保存详情页再抽取、合成评估数据、生成看房问题清单、用 OneMap 补 MRT 和 NUS 通勤）：前两条大部分已被 v2 覆盖，后三条仍适用。用户当时没有选。

### Firecrawl（只讨论）

- 用户问过能否下载 Firecrawl skill，以及它的原理。已按源码解释：取网页（托管版用闭源的 Fire-engine Chrome，自部署用 Playwright，再退回普通请求）→ 清洗 → 转 Markdown → 大模型按 schema 抽取；遇到 401/403/429 默认升级为隐匿代理重试。
- 结论：不用它访问 PropertyGuru。用户账号和插件目录里没有 Firecrawl skill；Claude 连接器目录里的 Firecrawl 只有搜索类工具；它的 GitHub 仓库自带给编程 agent 用的 skill（如 firecrawl-build），需要 API key。它"先删无关区域、再转 Markdown、按 schema 抽取"的思路，可以借鉴到人工保存详情页的抽取脚本。

### 建议的下一步（9/16 给用户的排序，按现状更新）

1. 真实模型复测：`.\.venv\Scripts\python.exe .\demo.py --chat --trace`。重点看 explore_budgets 有没有调用、"公寓""整租"映射对不对、链接说明和可租状态是否分开、[guard] 重试是否频繁；出错的对话留作评估素材。
2. Sprint 1（10/16）冻结共享数据结构前告诉组员：SearchPreferences 新增 rental_scope、property_types，search_listings 增加了对应过滤。
3. 和数据组对齐 v2 的格式、取值和补值方法，再接入代码并更新测试。
4. 评估框架：30–50 条场景（直接需求、模糊需求、无解条件、数据里没有答案的问题，再加多轮），分调试集和留出集；同一批场景对比 5 个系统（平台式筛选加租金排序、只用加权打分、不带工具的 LLM、旧 workflow、新 agent）；自动指标用 condition_status 算满足条件比例、_reply_problems 算编造比例，再查越权承诺和改条件后结果是否跟着变；排序质量人工标注；保存 trace，挑至少 10 个失败案例。
5. 到 NUS 的通勤时间（OneMap 公共交通），先和负责外部 API 的组员分工。
6. 产品决定：整租是否默认可以做饭（v2 做饭覆盖 19%，需重新评估）、"公寓"包含哪些物业类型。
7. Sprint 2 前：会话持久化、接入队友的 SQLite、用 FastAPI 包给前端（入口 `graph.invoke({"message": ...})`）。

- 流程图（主循环、search_listings 流程、finalize 检查）：https://claude.ai/artifact/VWVKDMYgVWBLzAVuBVe5Yx

目前没有新的实施指令。新窗口核对状态后，等用户选择下一步。
