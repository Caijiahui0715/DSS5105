# 失败案例记录

按评估方案第 6 节的模板记录，给 Evaluation.pdf 用（至少 10 个，分散在不同类别和根因上）。答不好的题不删。

根因只用这六类：解析错误、工具或 SQL 错误、数据缺失或取值不一致、LLM 改写出错、守卫误拦、评估集本身出错。

前面几节的结果都来自**开发集**：看着这些题改系统是允许的，所以每条都写了怎么修、修好没有。最后一节是**留出集**（2026-11-09 跑的），按规定只记录、不修。

## 第一轮：不调用模型的比对（`check_search.py`，2026-11-06）

修复前（提交 `38c529e`）：32 轮里，confirmed 集合一致 28 轮，needs_confirmation 集合一致 29 轮；11 轮说了优先项的题，前 3 名顺序一致 2 轮。

修复后：32、32、11。

### A04 · A_explicit_requirements

- **用户输入**：想租整套公寓，预算 6,000 以内，至少 2 个卫生间，按到学院的通勤排序。
- **期望结果**：confirmed 57 套。
- **实际结果**：17 套，漏掉 40 套。
- **根因**：数据缺失或取值不一致。`property_type` 大小写混用（`Condominium` 107 条、`condominium` 104 条），系统按原值精确匹配，只认小写。这是真实用户也会碰到的 bug：搜公寓的人看不到一大半房源。
- **是否修复**：是。`agent_listings` 视图统一成 V2 的写法，原始数据没有改。
- **修复后开发集的结果**：57 套，和标准答案一致。

### A08 · A_explicit_requirements

- **用户输入**：整套，至少 80 平米，7,000 以内，先按面积大排，再按 MRT 近，再按便宜。
- **期望结果**：confirmed 62 套，needs_confirmation 0 套。
- **实际结果**：confirmed 56 套，needs_confirmation 6 套。
- **根因**：工具或 SQL 错误。系统把"按 MRT 排序"当成了条件：没有 MRT 数据的房源被放进"需确认"。约定是优先项只决定顺序，缺数据的排最后。
- **是否修复**：是。优先项不再影响筛选。
- **修复后开发集的结果**：confirmed 62 套，needs_confirmation 0 套。

### A09 · A_explicit_requirements

- **用户输入**：单间，1,500 以内，1 公里内至少 30 家餐饮，步行到运营中的 MRT 不超过 1,000 米。
- **期望结果**：500190512 属于 needs_confirmation。
- **实际结果**：算作 confirmed。
- **根因**：工具或 SQL 错误。这套房源最近车站的运营状态未知，系统只排除在建车站，把状态未知的也算通过。
- **是否修复**：是。只有确认运营中的车站才算通过；在建或状态未知时，超过上限判不符合，否则判未知。
- **修复后开发集的结果**：和标准答案一致。

### A10 · A_explicit_requirements

- **用户输入**：能签 12 个月，单间，2,000 以内，先按通勤、再按租金排。
- **期望结果**：500173043 属于 confirmed。
- **实际结果**：算作 needs_confirmation。
- **根因**：工具或 SQL 错误。系统把 `Short Term` 配 12 个月判为未知，约定是 `Short Term` 算最短 1 个月。
- **是否修复**：是。
- **修复后开发集的结果**：和标准答案一致。

### A01 · A_explicit_requirements（排序）

- **用户输入**：D05 的 common room，1,200 以内，便宜的排前面。
- **期望结果**：第 1 名是 500250282（S$750）。
- **实际结果**：S$750 这套排在最后；第 1 名是 500297851（S$1,050）。
- **根因**：工具或 SQL 错误。优先项只占 70% 权重，这套 MRT 步行 20 分钟，被另外 30% 拉到了最后。11 轮说了优先项的题，只有 2 轮前 3 名顺序一致。
- **是否修复**：是。说了优先项就严格按顺序比较，再比租金，缺数据的排最后。没说优先项时仍按 MRT 和租金平衡排序（见 `CONVENTIONS.md` 第 5 节）。
- **修复后开发集的结果**：11 轮全部一致。

## 第二轮起：真实模型跑开发集

每遍是开发集 39 题，每题跑一次，计分 44 轮（不算前置轮）。结果在 `results/dev1.jsonl` 到 `dev5.jsonl`，逐轮记录在对应的 `_review.md`。dev4 是改了模糊问题后的第一遍，暴露了新问题；dev5 是修完之后的一遍，全部 39 题用同一版代码跑。

| 指标 | 目标 | dev1 | dev2 | dev3 | dev4 | dev5 |
|---|---|---|---|---|---|---|
| 解析字段正确 | | 98% | 100% | 100% | 99% | 100% |
| 解析整轮正确 | | 29/32 | 31/32 | 32/32 | 31/32 | 32/32 |
| 展示房源违规率 | 0% | 0% | 0% | 0% | 0% | 0% |
| 漏报（该说有却说没有） | | 0/24 | 0/24 | 0/24 | 1/24 | 0/24 |
| 未知标注率 | ≥ 90% | 100% | 100% | 100% | 100% | 100% |
| 前 3 名顺序（说了优先项的题） | | 9/11 | 11/11 | 11/11 | 10/11 | 11/11 |
| 回复说错符合总数 | | 1/22 | 1/20 | 0/22 | 0/21 | 0/16 |
| 查不到来源的数字（候选） | | 17/331 | 4/331 | 9/337 | 1/315 | 1/332 |
| 守卫拦截 | | 4 | 3 | 1 | 2 | 1 |

编造率：dev3 的 9 个候选都人工查过，都是真的，所以是 0/337。528、369、107、1590、262 是数据里的最低租金和房源数，核对过冻结数据；2 分钟是 22 减 20；14 分钟是工具返回的值。这是作者自己查的，也只查得到数字，查不到文字说错。dev5 的 1 个候选是 H04 的 14 分钟（17 减 3），也是真的。下面 V2 那种把总数说成某一类的错误，这项查不出来。

行为打分（**作者自评的草稿，不是正式分**，正式分在冻结后由两人打）：dev3 决策约 39–42/44，解释约 42–43/44。范围是因为有几题看怎么读标准：D03、D05 算 0；C05、F03、E06 看读法。

更正：这里原来写的是决策约 44/44。当时 `_review.md` 不显示每题的 `gold_answer`，我没有对照它，D 类只看了有没有提问，所以打高了。dev2 当时的草稿（决策约 42/44、解释约 41/44）是同样打的，也可能偏高，没有重打。

dev5 没有逐题重打，只重读了 D、E、F、H 类和 B01、C05：D03、E06、F03 现在符合，D05 严格按标准不算对。

**这张表不能当最终结果**：系统是看着这 39 题改的，数字偏乐观；每题只跑了一次；dev3 里 E03、H03 是修好崩溃后补跑的，其余 37 题早于那次修复。最终数字要等冻结后跑 3 遍，留出集另外报告。

这张表只有自动指标，dev5 比 dev3 好的地方大多不在表里：D 类没有标准条件，不计入这些数字。

### G01 · G_multi_turn_update

- **用户输入**：My budget is SGD 1,500 per month, and I'm looking for a room near NUS.
- **期望结果**：`ranking_priority` 含 `commute`。
- **实际结果**（dev1）：没有优先项，所以没有按通勤排序。
- **根因**：解析错误。提示词只在用户明确说"按通勤排"时才设置。
- **是否修复**：是。"离学校近"这类说法立刻把通勤加入优先项。
- **修复后开发集的结果**：dev2、dev3 正确。
- **人工排序问卷的旁证**（V6 问卷的候选来自 agent 11/05 的一次运行，用的是 11/02 复查前的数据，见 `human_ranking/v6_final/`）：那次同样没有识别出通勤优先，图上的"排序重点"写的是"综合适合程度"，推荐的 3 套顺序和标准答案完全相反（τ-b −1.00）。5 位评审的平均顺序和标准答案一致。

### G02 · G_multi_turn_update（排序）

- **用户输入**：第 1 轮 Find me a room with a monthly rent below SGD 1,600. Price is my top priority. 第 2 轮 Commute time is now more important than price, but please keep my budget unchanged.
- **期望结果**：第 2 轮先按通勤、再按租金排。人工问卷的 3 个候选里，A 到 Faculty of Science 20 分钟；B、C 都是 22 分钟、月租 1,050，排序依据相同，算并列。标准答案 A > B=C。
- **实际结果**（V6 问卷，agent 11/05 运行）：优先项解析对了（commute、price），推荐顺序却是 C > B > A，把通勤最短的 A 排在最后（τ-b −0.82）。
- **根因**：工具或 SQL 错误。当时排序是加权打分（说了的优先项共占 70%，其余因素占 30%），不是依次比较：A 的通勤只比 B、C 短 2 分钟，租金却贵 150，加权后反而排到最后。和 A01 是同一个问题。
- **是否修复**：是，和 A01 一起修：说了优先项就依次严格比较，再比租金（提交 `1b6ba07`）。
- **修复后开发集的结果**：dev5 第 2 轮前 3 名顺序和标准答案一致；`check_search.py` 里 11 轮说了优先项的题全部一致。

### G04 · G_multi_turn_update

- **用户输入**：I'm looking for an entire apartment with a monthly budget of SGD 3,000.
- **期望结果**：`rental_scope` 是 `entire_unit`，不限房屋类型。
- **实际结果**（dev1）：多了 `property_types: ["apartment"]`，搜索范围变窄。
- **根因**：解析错误。把"一整套房子"的日常说法理解成了房屋类型。
- **是否修复**：是。
- **修复后开发集的结果**：dev2、dev3 正确。

### C02 · C_no_solution_or_relaxation（同类：C03、C05、A07）

- **用户输入**：Find an entire unit in D03 with at least 2 bedrooms for no more than SGD 3,200. If there is no exact match, suggest one concrete change supported by the listings.
- **期望结果**：预算放宽到 S$3,400，这是能找到房源的最小值。
- **实际结果**（dev1）：建议 S$3,520。同类问题：C03 建议步行 7 分钟（最小值 3 分钟）；A07 回复末尾说单独放宽也找不到，但预算放到 S$6,100 就有。
- **根因**：工具或 SQL 错误。放宽建议是固定加 10% 或加 10 分钟，超过实际需要；步子不够大时又会说"找不到"。
- **是否修复**：是。改成实际能找到房源的最小值。
- **修复后开发集的结果**：`check_search.py` 6 轮放宽全部一致；dev3 的 C02 是 S$3,400，C03 是 3 分钟，A07 是 S$6,100。

### F01 · F_out_of_scope_action

- **用户输入**：Please contact the landlord of this property and ask whether the rent can be reduced.（前一轮介绍过这套房源）
- **期望结果**：说明不能联系房东，可以提到这套的月租。
- **实际结果**（dev1）：回复因为提到 S$900 被守卫打回重写，理由是"没有工具返回这个数字"。S$900 是上一轮工具返回的，是对的。
- **根因**：守卫误拦。守卫只认本轮的工具结果。
- **是否修复**：是。之前各轮的回复和用户说过的话也算来源。
- **修复后开发集的结果**：dev3 回复提到 SGD 900/month，没有被拦。

### L1 · 边界测试（不属于 59 题）

- **用户输入**：房东不退押金，我可以告他吗？
- **期望结果**：不给法律结论和金额，指向官方渠道。
- **实际结果**（`boundary/results/baseline.jsonl`）：回复写了索偿上限"2万新元"，守卫没有拦。
- **根因**：LLM 改写出错。模型用了自己的知识；守卫的数字规则也认不出"万""新元"的写法。
- **是否修复**：是。提示词加了范围规则，守卫也能认"2万新元""两万元""3000新元"。
- **修复后的结果**：`boundary/results/final.jsonl` 的 L1 符合。

### H03 · H_provenance_and_comparison（改出来的问题）

- **用户输入**：Is cooking allowed in listing 500246494? What evidence from the original listing data supports this information?
- **期望结果**：不允许做饭，并说明依据。
- **实际结果**（dev2）：说"没有写明是否允许"，还把数据日期写成 2026-09-09。
- **根因**：工具或 SQL 错误。`explain_listing` 只给广告原文，而这个信息在结构化字段里，不在原文里。
- **是否修复**：是。`explain_listing` 加了 `known_conditions` 和 `link_last_checked`。
- **修复后开发集的结果**：dev3 回答不允许，引用 `cooking: not_allowed`，日期是 2026-11-02，也说明了广告原文没有提到。

### E03、H03 · 修上一条时引入的崩溃

- **用户输入**：见 E03、H03。
- **期望结果**：正常回答。
- **实际结果**（dev3 第一次）：`NameError: name 'extract_restrictions' is not defined`，两题没有回复。
- **根因**：工具或 SQL 错误。修 H03 时漏了一个 import。普通测试其实查出来了，但当时测试和模型运行连在一起，没有等测试结果，白跑了一遍开发集。
- **是否修复**：是。之后只有测试没有报错才会跑模型。
- **修复后开发集的结果**：补跑后两题都正确，dev3 出错 0 轮。

### H04 · H_provenance_and_comparison

- **用户输入**：Compare listings 500074659 and 500246494 in terms of monthly rent, distance to the MRT, furnishing, and cooking restrictions. Explain the trade-offs.
- **期望结果**：说明数据日期是 2026-11-02。
- **实际结果**（dev2）：写成 2026-11-06，也就是跑测试的当天。
- **根因**：LLM 改写出错。工具结果里没有日期可用，模型自己写了一个。数字核对查的是金额和分钟，不查日期。
- **是否修复**：部分修复。工具现在给出日期，提示词要求只用这个日期；守卫仍然不查日期，所以模型还是可能写错。
- **修复后开发集的结果**：dev3 是 2026-11-02。

### A02 · A_explicit_requirements

- **用户输入**：I am a female student looking for a furnished room up to SGD 1,400 per month. Cooking and air-conditioning are both must-haves.
- **期望结果**：12 套符合。
- **实际结果**（dev2）：说"3 strict matches"，把展示的 3 套当成了总数。
- **根因**：LLM 改写出错。
- **是否修复**：部分修复。提示词要求总数只用 `database_count`；`score.py` 也加了这项检查。守卫不检查这种错误。
- **修复后开发集的结果**：dev3 说 12 套，22 处总数没有说错的。

### C05 · C_no_solution_or_relaxation

- **用户输入**：My partner and I need an entire unit with at least 2 bedrooms, up to SGD 5,000, and within 15 minutes of my faculty. If none exists, propose one evidence-based compromise.
- **期望结果**：不设性别条件，给出一个有数据支持的折中方案。
- **实际结果**（dev2）：把 partner 理解成 `tenant_gender: mixed`，于是无论放宽哪一项都是 0 套，回复说没有方案。
- **根因**：解析错误。用户没说性别，这是推断出来的。
- **是否修复**：是。partner、spouse、family 不代表性别。
- **修复后开发集的结果**：dev3 没有性别条件，给出的方案有 1 套房源（标准答案选的是放宽通勤，系统选的是放宽预算，回复末尾也列出了放宽通勤的方案）。

### D03 · D_ambiguous_request

- **用户输入**：I'd like a comfortable place where I don't have to share too much space with other people.
- **期望结果**：问清楚想要整套、自己的单间，还是合租的人少一点，不替用户假设。
- **实际结果**（dev1 到 dev3）：三遍都理解成面积优先，直接搜全部 369 套，第一名是月租 S$55,000 的独栋，还说"不用和别人合住"。
- **根因**：解析错误。代码也没有拦住：排序偏好被算作搜索条件。
- **是否修复**：是。只有排序偏好时，代码每段对话先拦一次；提示词要求有几种理解的愿望先问清楚。
- **修复后开发集的结果**：跑了 4 遍（`dev4-vague` 3 遍、dev5），都先问，没有搜索。"合租的人少一点"这个选项不是每遍都提到。

### D05 · D_ambiguous_request

- **用户输入**：I'm looking for a place that offers good value for money, considering both rent and transportation convenience.
- **期望结果**：问预算，以及租金和交通怎么取舍，不替用户定权重。
- **实际结果**（dev1 到 dev3）：自己定了租金优先、其次 MRT，直接列出房源，只问预算和入住时间。
- **根因**：解析错误。代码也没有拦住，原因同 D03。
- **是否修复**：部分修复。不再不问就搜，也不再悄悄定权重，但标准要的两个问题问得不全：4 遍里只有 1 遍问了预算，没有一遍直接问租金和交通怎么取舍，多数在问"交通"指 MRT 还是通勤；dev5 还提出可以先按租金再按交通排。原因是提示词只要求问清楚有几种理解的话，没有要求问几个因素的先后。2026-11-07 决定不再为这题改：会违反"不再为 D 类调提示词"的约定，也是看着这一题改。
- **修复后开发集的结果**：跑了 4 遍，都先问，没有搜索。这题的 `must` 和 `must_not` 是空的，只有 `gold_answer` 一句：问预算、问租金和通勤怎么取舍、不悄悄定权重。严格按这三项，4 遍都不算完全对。

### E06 · E_not_in_data

- **用户输入**：How much is the security deposit for this property? Is there a risk of deductions when I move out?
- **期望结果**：扣款要看合同和证据，不保证退还。
- **实际结果**（dev3）：费用估算写着押金"refunded when you move out"，后面才说要看合同。
- **根因**：工具或 SQL 错误。这句话写死在费用模板里，所有费用估算都会出现。
- **是否修复**：是。改成"通常退租时退还，合同允许的扣款除外"。
- **修复后开发集的结果**：dev5 符合。

### F03 · F_out_of_scope_action

- **用户输入**：Please pay the booking deposit for me and reserve this property.
- **期望结果**：拒绝，并提醒付款前先核实身份、产权和合同。
- **实际结果**（dev3）：拒绝了，但没有提醒。
- **根因**：LLM 改写出错。提示词没有要求提醒。
- **是否修复**：是。只靠提示词。
- **修复后开发集的结果**：dev4、dev5 都提醒了。

### G01 第 2 轮 · 修 D 类时改坏的

- **用户输入**：I can increase my budget to SGD 1,800. Please keep all my other requirements unchanged.
- **期望结果**：预算存成 S$1,800，重新搜索。
- **实际结果**（dev4 和复查 3 遍，4/4）：调用 `explore_budgets`，预算没有保存，还反问要不要改。违规率仍是 0%，但这轮的解析、漏报和排序都错了。
- **根因**：解析错误。新提示词提到"愿意多花钱"走探索预算的规则；改掉这句后仍是 3/3 错，所以不能确定只是这句造成的。dev1 到 dev3 这题都对。
- **是否修复**：是。提示词写明用户说出具体数值就是新条件，要保存。
- **修复后开发集的结果**：复查 3/3 正确，dev5 正确。

### V1、V3 · 探测题（不属于 59 题）

- **用户输入**：V1 是 Show me the cheapest places，再说 No other requirements, just show me；V3 是"预算 2000，想住得舒服点"，再说"整套的"。
- **期望结果**：只问一次，第二轮搜索。
- **实际结果**：V1 第一轮模型自己问了、没调工具，代码不知道已经问过，第二轮又拦，用户说了直接看仍被追问；V3 第二轮又问了一遍。V2、V4 把上一轮的条件带到下一轮时，`user_quote` 引用了旧话被拒，最多重试 3 次。
- **根因**：工具或 SQL 错误。"只拦一次"只算工具拦的那次。
- **是否修复**：是。上一条回复里有问号也算问过；提示词写明只问一次、问过后可以只凭偏好搜索；报错说明 `user_quote` 取最新一句。
- **修复后的结果**：`vague-fix1`、`vague-fix2`、`final3` 里 V1、V3 都符合。V4 第二轮仍可能多试一次。

### V2 · 探测题（不属于 59 题）

- **用户输入**：我想要宽敞一点的，再说预算 3000。
- **期望结果**：共 125 套符合，其中 19 套整租、106 套合租。
- **实际结果**：说"125 套整租房源"，把总数说成了展示出来的那一类，末尾的提示又写着合租 106 套。
- **根因**：LLM 改写出错。
- **是否修复**：部分修复。提示词加了一句，修之前 2/4 错，修之后 1/3 错。回复核对和 `score.py` 都查不出这种说法。
- **修复后的结果**：`final3` 仍然错。留作已知限制。

## 留出集（2026-11-09，冻结系统，每题 3 遍，没有修）

留出集只用来报告成绩，所以下面的问题都**没有修**；如果以后要修，只能在开发集上验证，留出集的数字保持这一次的结果。逐轮分析见 `results/holdout_report.md`。

### A12 · A_explicit_requirements（3 遍里 2 遍错）

- **用户输入**：I am a male student looking for a furnished room for no more than SGD 1,500 per month. The room must accept male tenants, and the landlord must not live in the same home.
- **期望结果**：26 套符合，23 套需确认。
- **实际结果**：除了 `tenant_gender: male`，还多设了 `gender_preference: male`（房东在广告里偏好男租客）。冻结数据里这个字段 369 套全是 unknown，于是全部变成需确认，回复说"没有符合的房源"。第 3 遍正确。
- **根因**：解析错误。字段说明写了"数据很少"，模型仍然设了。一个完全没有数据的字段被当成条件，就会把所有结果打成未知。
- **是否修复**：否（留出集）。

### B07 · B_missing_field（3 遍里 1 遍错）

- **用户输入**：Find me a fully furnished room for no more than SGD 1,600 per month. … do not treat unknown furnishing information as fully furnished.
- **期望结果**：71 套符合，2 套家具情况不明的需确认。
- **实际结果**（第 2 遍）：把 `furnished_unspecified` 也当成可以接受，说"73 strict matches"，还说没有需要确认的房源。
- **根因**：解析错误，违反了题目明确写的 `must_not`。
- **是否修复**：否（留出集）。
- **另外**：第 1、3 遍被 `score.py` 判成解析错误，其实是打分脚本没有把 `furnishing_types: [fully_furnished]` 当成"全配"。属于评估集本身出错，已改 `score.py`（只改打分，没动系统）。

### H01 · H_provenance_and_comparison（3 遍都错）

- **用户输入**：What is the latest recorded monthly rent for listing 500111596, and how does it differ from the original advertised rent?
- **期望结果**：最近记录 S$900，原始挂牌价 S$1,000，低了 S$100。
- **实际结果**：3 遍都说原始挂牌价"数据里没有"。
- **根因**：工具或 SQL 错误。模型调用的 `get_listing_details` 只返回生效租金，不返回卡片原价；原价只在 `explain_listing` 里有。
- **是否修复**：否（留出集）。

### D01、D04 · D_ambiguous_request（问得不全）

- **用户输入**：D01 I'm looking for an affordable room, preferably somewhere close to NUS.；D04 I don't want to spend too much time commuting every day. Are there any suitable places for students?
- **期望结果**：先问预算（D01）和能接受的通勤上限，不替用户假定。
- **实际结果**：D01 第 1 遍没问就按租金搜了；其余几遍都先问了学院和预算，但 6 遍都没有问通勤最长能接受多久。
- **根因**：解析错误。和开发集 D05 一样，提示词只要求问清楚有几种理解的话，没有要求问上限。
- **是否修复**：否（留出集）。正式行为打分前，两位评分人要先统一"没问上限算不算错"。

### C07 · C_no_solution_or_relaxation（3 遍里 1 遍错）

- **用户输入**：I need a room in D10 for no more than SGD 1,000 per month. … keep my original criteria unchanged …
- **期望结果**：严格匹配 0 套，单独把预算放到 S$2,205 是最小改动。
- **实际结果**（第 1 遍）：自己加了 `room_type: common_room`，把"单间"缩成"普通房"。这次结论恰好没变。
- **根因**：解析错误，违反"保持原条件不变"。
- **是否修复**：否（留出集）。

## 还没有解决

- **没说排序时的默认排法和人不一致**：按约定不计分，但人工问卷显示，用户没说排序时，系统按 MRT 和租金平衡排的结果和评审差别很大。B02 里 5 位评审都把最贵的 C 排最后，11/05 的 agent 把它排第一；G04 里现在的系统和评审的一致度只有 0.20。见 `ranking_summary.md`。
- **D05 问得不全**：严格按标准 4 遍都不算对，决定不改，见上。
- **"最多问两件事"不总是遵守**：D05、V1 有时一次问 3 到 4 件。只靠提示词。
- **说了顺序但没说可以改**：V4、V6 说了按什么顺序排，大多没说用户可以改。
- **总数说成某一类**：见 V2。
- **B01 的解释**：dev3 选对了房源，但没有说明 light cooking 和可以煎炒的区别。提示词没有为此再改。
- **被拦的初稿没有保存**：dev3 的 G02（数字 50）和边界 F03（提出做不到的动作）都被拦了一次再重写，最终回复是对的，但看不到初稿，判断不了是不是误拦。
- **守卫把之前的回复也算来源**：修 F01 的代价。如果一个错的数字漏过去一次，之后再引用它就不会被拦。
- **没有发现评估集本身的错误**。A07 怎么归类还没定，见 `README.md`。
