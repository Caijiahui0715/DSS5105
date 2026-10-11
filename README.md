# DSS5105 — Singapore Rental Decision Agent

## 第一次启动（给组员）

照着下面做一遍，就能在自己电脑上跑起来。命令都在仓库根目录的 PowerShell 里执行；用 macOS 的话，把 `.\.venv\Scripts\python.exe` 换成 `.venv/bin/python`，`Copy-Item` 换成 `cp`，路径里的 `\` 换成 `/`。每个设置项的说明、怎么用和常见问题见 [使用说明.md](使用说明.md)。

1. **装工具**（每台电脑一次）
   - [Git](https://git-scm.com/downloads)。
   - [uv](https://docs.astral.sh/uv/getting-started/installation/)：`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`，装完重开终端。项目用的 Python 3.12 由 uv 自动下载，不用另外装。
   - [PostgreSQL](https://www.postgresql.org/download/windows/)：用安装程序装，端口用默认的 5432，记住安装时给 `postgres` 用户设的密码；最后的 Stack Builder 可以跳过。装好后它是 Windows 服务，开机自动运行。
2. **拿代码和数据**
   ```powershell
   git clone <仓库地址>
   cd DSS5105
   ```
   再向组里要 `output-final-delivery` 整个文件夹（最终数据，不在 Git 里），放进仓库根目录。导入数据库用其中的 `rental_data_v1.json`、`rental_data_v2.csv` 和 `removed_listings.csv`，房源详情里的原文依据来自 `source_evidence_v1.json`。
3. **装依赖**
   ```powershell
   uv sync                    # 后端，装到 .venv
   uv sync --project app      # 前端，装到 app/.venv
   ```
4. **填 `.env`**
   ```powershell
   Copy-Item .env.example .env
   Copy-Item app\.env.example app\.env
   ```
   根目录的 `.env` 至少填这几行（每行一个 `KEY=value`，注释不要写在值后面）：
   ```
   OPENAI_API_KEY=你的 key
   OPENAI_MODEL=支持 tool calling 的模型名
   DB_HOST=localhost
   DB_PORT=5432
   DB_NAME=dss5105
   DB_USER=postgres
   DB_PASSWORD=装 PostgreSQL 时设的密码
   ```
   `DB_NAME` 随便取，下一步会自动建这个库。`app/.env` 不用改。两个 `.env` 都不提交到 Git，key 也不要贴进群聊。
5. **准备数据库**
   ```powershell
   .\.venv\Scripts\python.exe .\setup_database.py
   ```
   它会建库、建表，导入房源和通勤时间，最后打印“完成：N 套可用房源……”。可以重复运行。
6. **启动**：开两个终端，先启动后端，再启动前端。
   ```powershell
   .\.venv\Scripts\python.exe .\server.py                     # 终端 1：后端
   uv run --project app streamlit run app/streamlit_app.py    # 终端 2：前端
   ```
   浏览器打开 http://localhost:8501，注册一个账号（用户名 3–20 个字母、数字或下划线，密码至少 8 位），选好学院就可以开始聊天。账号存在你自己的数据库里，组员之间不通用。

**以后再用**：PostgreSQL 开机就在运行，只需要第 6 步。拉了新代码后先运行 `uv sync` 和 `uv sync --project app`；组里发了新版本的数据，就换掉 `output-final-delivery`，再运行一次 `setup_database.py`。改了 `.env` 要重启对应的程序。

**以前跑过旧版本的组员**：后端现在只用 PostgreSQL。在 `.env` 里删掉 `AGENT_DB`，补上 `DB_*`，再运行一次 `setup_database.py`。旧的 `sessions.sqlite` 不再使用，账号要重新注册（演示账号也一样，`app/.env` 不用改），确认不需要后可以删除。

启动失败时先看终端里的提示：后端会写明要检查什么，常见情况见 [使用说明.md](使用说明.md) 的“常见问题”。

## 常用命令

```powershell
.\.venv\Scripts\python.exe .\setup_database.py          # 首次（或数据换版本后）：建库、建表、导入房源和通勤，可以重复运行
.\.venv\Scripts\python.exe .\server.py                  # 多用户网页版：浏览器打开 http://127.0.0.1:8000
.\.venv\Scripts\python.exe .\server.py --lan            # 同一 Wi-Fi 的同学也能打开（见下方“多用户网页版”）
.\.venv\Scripts\python.exe .\demo.py --chat             # 命令行开发工具（默认 Agent）；接着用户 demo 最近的对话
.\.venv\Scripts\python.exe .\demo.py --chat --user=alice        # 接着 alice 最近的对话，关掉程序、隔天再开都在
.\.venv\Scripts\python.exe .\demo.py --chat --user=alice --new  # alice 开始一段新对话
.\.venv\Scripts\python.exe .\demo.py --chat --trace     # 同时打印每轮的工具调用（失败时带原因）、货币换算、链接检查结果和被拦的回复
.\.venv\Scripts\python.exe .\demo.py --chat --workflow  # 原固定 LangGraph workflow，作对照
.\.venv\Scripts\python.exe .\build_commutes.py          # 用 OneMap 算每套房源到各学院的通勤时间（约一小时，可中断续跑）
.\.venv\Scripts\python.exe .\build_commutes.py --import # 把 commute_faculty.csv 写入数据库（--export 反过来）
.\.venv\Scripts\python.exe .\show_route.py 24611200 牙医学院  # 打印 OneMap 的具体路线，核对看起来不对的通勤时间
.\.venv\Scripts\python.exe -m unittest discover -s tests   # 需要 PostgreSQL，用 <DB_NAME>_test，见“数据和存储位置”
```

房源、账号、对话和用户同意后的长期档案都在项目的 PostgreSQL 里，见下方“数据和存储位置”。

命令行 `demo.py` 是本机开发工具，不需要密码：`--user=NAME` 和网页版用的是同一套用户名（不区分大小写），所以在网页上注册的 alice 和 `--user=alice` 看到的是同样的对话和长期档案。只在自己电脑上用它。

## 多用户网页版

`server.py` 是一个本地 FastAPI 服务，同时提供接口和单页网页 `static/index.html`，几个人可以同时用。

- 账号：开放注册，用户名 3–20 个字母、数字或下划线（不区分大小写），密码至少 8 位；密码只存加盐的 scrypt 哈希。连续输错 5 次密码锁定 1 分钟。登录后服务端发一个令牌放在 HttpOnly cookie 里（7 天有效，数据库只存它的 SHA-256），退出登录即作废。
- 对话：每个用户可以有多段对话，按最近活动排序，默认打开最近一段；标题是第一条消息的前 20 个字。新对话不带入旧对话内容，跨对话只靠上面的长期档案（同意后才保存）。每段对话的状态用 LangGraph checkpointer 按 thread 保存，`threads` 表记录它属于谁；访问别人的对话一律返回“找不到这段对话”。
- 处理中：回复仍在整轮结束、通过事实核对后一次性显示。等待时显示“思考中……”，下面一行小字是当前步骤（正在搜索房源、正在检查房源链接（第 2 套）等），通过 Server-Sent Events 推送，不显示工具参数或模型推理。同一段对话里上一条还没处理完时，新消息排队。关掉页面不会中断正在处理的一轮，刷新后能看到结果。
- 查看处理过程：每条回复下面可以展开，按顺序列出这一轮调用了哪些工具、链接检查、汇率换算、被拦下重写等；这些步骤和回复一起保存，刷新或隔天回来也能看。
- 我的学院：注册时可以选（也可以暂不选择），之后在左侧栏“我的学院”里随时修改。通勤时间都按这个学院计算，所有对话通用，改了以后从下一条消息起生效。对话里也能改：还没设置时 agent 会先问你在哪个学院，你的回答就会保存；已经设置、你又说了另一个学院时，agent 先确认“要把你的学院改成 X 吗？之后所有对话都会按 X 计算通勤时间”，你同意后才改，回复开头固定显示改动。只是问“如果我在法学院呢”这类假设，只查不改。
- 删除：可以删除单段对话；“删除我的所有数据”删除这个用户的全部对话、长期档案和学院设置，账号保留，并让所有设备退出登录。对话里说“忘掉我的信息”只删除长期档案，学院设置不变。
- `--lan`：监听 0.0.0.0 并打印本机局域网地址（Windows 第一次运行会弹出防火墙提示，需要允许专用网络）。这是明文 HTTP，密码和对话在局域网里不加密，只在信任的网络里用；默认只监听 127.0.0.1。

## 数据和存储位置

- 全部在项目的 PostgreSQL：连接设置是 `.env` 里的 `DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER`、`DB_PASSWORD`，和数据管道共用；可选 `DB_CONNECT_TIMEOUT`，默认 10 秒。
  - `public` schema：房源（`listings`、`listing_enrichment`、`listing_metadata`、`district_lookup`）和通勤（`listing_commutes`、`nus_destinations`），只由数据管道写（`src/dss5105/data`、`build_commutes.py`）。
  - `agent` schema：只由服务器写。账号、令牌、对话列表、长期档案、学院设置、LangGraph 的 checkpoint 表，链接检查结果 `listing_health`（重启后 24 小时内继续复用），以及 `agent_listings` 视图。
  - `agent_listings` 视图（`group_db.py`）：每次搜索都读它。它只取 `scrape_status = 'active'` 的房源，在数据库里算好排序用的值（周边餐饮和各类设施的名次、面积百分位、到每个学院更快的那种通勤方式），把 V2 的标签换成搜索用的 V1 写法，并连上区名、可用性、review flags 和链接检查结果。服务器每次启动时重建这个视图；数据管道更新数据后，下一次查询就能看到，不用重启。
  - 第一次准备（或数据换版本后）：运行 `setup_database.py`。它依次建库（服务器上还没有时）、补跑 `src/dss5105/database/` 里还没跑过的建表脚本、运行 `load_data.py`（V1）和 `sync_v2.py`（V2）、把 `commute_faculty.csv` 写入数据库，最后建好 `agent_listings` 并打印可用房源数。可以重复运行，`agent` 里的账号和对话不受影响。它只新增或更新文件里的房源：新版 V2 文件里没有、`removed_listings.csv` 也没写的旧房源仍是 active，脚本会提示有几套。需要 `output-final-delivery/` 里的数据文件（组里共享，不在 Git 里）。学院以 `faculties.py` 为准，不要再用 `seed_nus_destinations.py` 覆盖。
  - 连不上：启动时直接退出，并说明要检查什么（服务是否在运行、连接设置，或者先运行 `setup_database.py`）。运行中断开时，这一轮回复“数据库暂时连不上，请稍后再试。”，下一条消息自动重新连接。
  - 重新导入房源数据时只清理 `public` 里的表，不要删除整个数据库，否则所有账号和对话都会丢失。
- 测试：用同一台服务器上的 `<DB_NAME>_test`，第一次运行时自动创建（账号需要建库权限，没有的话先在 pgAdmin 里手动建）。每组数据放在自己的 schema 里：`mock` 是 `tests/fixtures` 里 12 套虚构房源，每个测试前重建；`real` 是 `output-final-delivery` 的数据，每次运行用 `load_data.py` 和 `sync_v2.py` 导入一次；`storage` 放账号和对话，每个测试前清空。连不上 PostgreSQL 时，需要数据库的测试会跳过并写明原因，其余照常运行。

## 架构

- `agent.py`：外层 agent。模型读取对话、会话状态和工具结果，自己决定调用哪些工具、调用几次；每轮最多 5 轮工具调用。
- 工具都是确定性代码：`search_listings`、`explore_budgets`、`get_listing_details`、`explain_listing`、`compare_listings`、`shortlist`、`exclude_listings`、`estimate_costs`（有账号时还有 `user_memory`、`faculty`）。
- `costs.py`：租房费用的计算（总租金、印花税、押金、签约时预付、中介费），规则写在文件开头，`estimate_costs` 用它。
- `decision.py`：条件三态判断（符合 / 不符合 / 数据未注明）、逐个放开条件的诊断、排序溯源。严格匹配结果与 `tools.search_listings` 完全一致。
- `graph.py`：原固定 workflow，保留作评估 baseline。
- `tools.py`、`response.py`：检索与 URL 校验、事实模板，两套流程共用。`mock_db.py`：测试用的数据库（见“数据和存储位置”）。
- `sessions.py`：`agent` schema 里的对话表和 LangGraph 的 PostgresSaver（和房源共用一个连接池），用 checkpointer 把每轮的完整状态（条件、候选、排除、对话消息、每条回复的处理过程）按对话保存，`threads` 表记录每段对话属于哪个用户；Agent 与 workflow 的对话分开存。
- `accounts.py`：注册、密码校验、登录锁定和令牌，只用标准库。
- `group_db.py`：项目 PostgreSQL 的连接池、`agent_listings` 视图和启动检查；`open_database()` 连上数据库并建好视图，网页版、命令行和通勤脚本都用它。
- `setup_database.py`：一键准备数据库（见“数据和存储位置”）。
- `src/dss5105/`：pizza 的数据层，`database/` 是建表和迁移，`data/` 是 V1 导入、V2 同步和学院表脚本。推荐逻辑统一用 agent 的，原来的 `api/`、`backend/`、`commute/`、`decision/` 已不再使用（计划移进 `archive/`）。
- `faculties.py`：NUS 各学院的地址、坐标和数据库里的学院代码（`code`），供地点条件按学院名定位，也是通勤时间的目的地。
- `build_commutes.py`：用 OneMap 离线计算每套房源到每个学院的公共交通时间（1.5 公里内再比较步行），写入 `commute_faculty.csv`。数据库是源头：先把 `listing_commutes` 导出成 CSV，补算缺的，结束（包括中途出错）时写回数据库。CSV 在 Git 里，新的数据库用 `setup_database.py` 导入它就有通勤时间，不需要 OneMap。`--import` / `--export` 单独做写入或导出，例如跑完 `fix_transit_google.py` 后用 `--import`。
- `show_route.py`：打印某套房到某个学院的 OneMap 路线（每段的方式、起止和分钟数），用来核对可疑的通勤时间。
- `server.py`、`static/index.html`：多用户网页版的接口和页面（页面留作开发测试，正式前端是 Streamlit，见“给前端的接口”）。
- `profiles.py`：长期记住用户（只在 Agent 中，workflow baseline 不变）。档案存在同一个存储的 `user_profiles` 表，只保存经过 `user_quote` 检查而保存的条件（附每个字段对应的用户原话和日期）、按原说法记录的预算（金额、币种、覆盖月数）、候选和排除，不保存对话内容，也不让模型自由写入记忆。
  - 征得同意：第一次保存条件时固定问一次“要我记住这些条件吗”；用户同意（工具 `user_memory`，`action=allow`）后才写入，拒绝则不保存。之后每轮有变化时自动更新档案。
  - 沿用：同一用户开新对话（网页上的“新建对话”或命令行 `--new`）时，回复开头固定列出上次记住的条件和候选（已下架的标出来），但不自动套用；用户说“沿用”时 `action=restore` 恢复条件、候选和排除，非新币或按年的预算按当天汇率重新换算（换算失败则沿用上次的月租上限并说明）。只显示、未沿用时档案保持不变；用户在新对话里直接保存新条件，档案就换成这段对话的内容。
  - 查看与删除：“你记得我什么”是 `action=show`；“忘掉我的信息”是 `action=forget`，删除档案并不再保存（当前这段对话的记录仍保留，开新对话后不会带入）。
- 继续之前的对话时，Agent 每轮先移除候选清单里已不在当前数据中的房源并固定提示；隔天回来时清掉旧的让步建议和上次搜索统计（它们基于旧数据和旧的链接检查），入住日期已过去时提醒用户更新。

## Streamlit 前端（`app/`）

正式前端是 `app/` 里的 Streamlit 应用（Fangyue 做的页面），它是单独的 uv 项目，和后端各用各的环境，开两个终端运行：

```powershell
.\.venv\Scripts\python.exe .\server.py                                   # 终端 1：后端，http://127.0.0.1:8000
uv run --project app streamlit run app/streamlit_app.py                  # 终端 2：前端，http://localhost:8501
uv run --project app pytest app/tests                                    # 前端测试（离线演示模式，不需要后端）
```

账号、房源、推荐、通勤、对话和收藏都来自后端：聊天走真正的 agent，前端不再自己打分，也不用演示通勤。前端的设置写在 `app/.env`（不提交）：`BACKEND_URL`（默认 `http://127.0.0.1:8000`）；`DEMO_USERNAME` / `DEMO_PASSWORD` 填一个先在网页上注册好的演示账号（例如 `demo_user`）后，登录页才显示“Continue with demo account”，大家共用这个账号的对话；`AGENT_MODE=mock` 时改为不连后端的离线演示（静态文件和脚本化的演示 agent）。界面语言默认英文，登录页和对话栏可切换中文。agent 按消息本身的语言回复（中文消息回中文），只有消息看不出语言时（只发了数字、区号或 yes）才用界面语言。“记住我”把登录令牌存在浏览器 cookie 里 7 天（这个 cookie 页面脚本读得到，和网页版的 HttpOnly cookie 不同），退出登录时删除 cookie 并作废令牌。

## 给前端的接口

除聊天页面用的接口外，供 Streamlit 前端从它自己的服务器调用（对话状态都在服务端，前端只传对话 ID 和用户说的话；`app/adapters/backend_client.py` 是前端这边的调用，`tests/test_frontend_client.py` 检查两边一致）：

- 不用登录：`GET /api/faculties` 返回各学院的 `name`、`zh`、`campus`、`code`、`latitude`、`longitude`（注册表单和地图用）；`GET /api/options` 返回有房源的区 `{"code", "name"}` 和物业类型，供注册和个人资料表单选择。
- 登录：`POST /api/token`（`{"username", "password"}`）返回 `{"token", "token_type": "bearer", "username", "faculty"}`，之后每个请求带 `Authorization: Bearer <token>`；注册仍用 `POST /api/register`（可带 `faculty`），`POST /api/logout` 作废令牌，`PUT /api/me/faculty` 改学院。网页用的 cookie 登录不变。下面的接口都要登录。
- 房源：`GET /api/listings?limit=50&offset=0`（`limit` 最多 200）返回 `{"total", "listings"}`，字段和 agent 排序用的一样（含 `commutes` 各学院通勤、`live_status` 链接检查结果、`lease_term` 广告写的租期；`rent_monthly_sgd` 是重新检查过的月租，原广告月租在 `rent_monthly_sgd_card`）；`GET /api/listings/{id}` 返回 `{"listing", "source_evidence"}`，后者是房源页的完整记录（图片、原文、字段依据），没有记录时为 `null`，找不到房源返回 404。
- 对话：`POST /api/conversations` 新建，`POST /api/conversations/{id}/messages`（`{"message", "language"}`，`language` 是界面语言 `zh` / `en`，只在消息本身看不出语言时使用，例如只发了 `1000`；其他时候回复跟随消息的语言）用 Server-Sent Events 返回 `progress`（`{"zh", "en"}` 两种文字）和最后的 `reply`。`reply` 里有 `text`、`steps`、保存的条件 `preferences`、对话的收藏 `shortlist`，以及 `recommendations`：这一轮搜索展示的房源，`{"preview", "listings": [...]}`，每套带 `status`（`match` 完全符合 / `needs_confirmation` 需确认，后者有 `unknown_conditions` 和按回复语言写好的 `unknown_condition_labels`）、`position`、月租、MRT、到“我的学院”的 `commute_minutes_to_faculty` 和 `commute_mode`、`lease_term`、`link_status` / `link_note` 等；这一轮没有搜索时为 `null`，前端保留上一次的列表。`preview` 为 true 表示只是假设，条件没有保存。
- 重新打开对话：`GET /api/conversations` 列出对话，`GET /api/conversations/{id}/messages` 是消息和每条回复的处理过程，`GET /api/conversations/{id}` 返回 `{"id", "preferences", "recommendations", "shortlist"}`（`recommendations` 是最近一次搜索展示的房源，格式同上）。
- 收藏：就是 agent 的候选清单，每段对话各有一份，agent 在对话里也看得到。`POST /api/conversations/{id}/shortlist`（`{"listing_id"}`）加入，`DELETE /api/conversations/{id}/shortlist/{listing_id}` 移除，都返回 `{"shortlist"}`；规则和对话里的 shortlist 工具相同，用户同意记住时也写进长期档案。

## Agent 的边界

- 事实只来自工具结果或会话状态。回复里的房源编号、金额、分钟数、套数必须出现在本轮工具输出中，否则回退为模板草稿；提出联系房东、确认可租、预约看房等超出能力的动作也会回退。
- 保存条件变更时，工具参数必须引用用户本轮原话（`user_quote`）；`preview=true` 只看不改。`set` 里只放要改成新值的字段，空值和默认值会被忽略（模型有时会把所有字段都带上，否则会清掉已保存的条件）；要去掉某个已保存条件，用 `clear` 列出字段名。条件变更、收藏和排除以固定文字显示给用户。
- 数据未注明不再等同于不符合：其他条件都符合、只是部分要求未注明的房源单独列为“需确认”，并说明是哪个条件卡住了结果。
- 已保存的搜索没有严格匹配时，按原 workflow 的单项放宽规则（预算约 +10%、MRT +5 分钟，设了租期时再试签 1 年、2 年，结果经过链接检查）在回复末尾固定附上让步建议。
- 整租 / 合租使用 `rental_scope`（entire_unit / room），取 v2 数据的出租方式；未注明的房源列为“需确认”，不当作整租。引导用户补充条件时先问整租还是合租，选了合租再问房型。用户没选、而完全符合的房源里两种都有时，回复末尾固定提示展示的是哪一种，以及另一种的套数和最低月租。
- 排序：MRT 步行距离始终参与（米数 ÷ 参考距离，参考距离 = 步行上限 × 85 米，没给上限时 850 米），有预算时再加月租 ÷ 预算；吃饭方便、到 NUS 通勤只在用户提出时参与。`ranking_priority` 最多保存 3 个偏好，点名的几项平分 70%，其余因素平分 30%，但其余每项不超过任何一个点名项（例如点名 3 项、只剩 1 项时四项各 25%）；没点名时等权。多轮对话中用户说“还 / 也 / 另外”时追加偏好，说“算了 / 改成 / 只要”时替换；分不清时追加，并以固定文字显示变更，用户可以直接纠正。超过 3 个时先问用户哪三个最重要。点名的每一项都需要数据，缺任何一项的房源列为“需确认”。没有 MRT 数据或最近的站尚未通车按参考距离计（比值 1）；但用户点名在意 MRT 时，这类房源列为“需确认”。并列时先比权重最高的一项，再比下一项，最后才比月租。
- 限制条件（符合 / 不符合 / 未注明三态，未注明一律列为“需确认”，整租也一样）：`tenant_gender`（用户自己说明的住户性别：female / male / mixed，对照数据的 gender_restriction）、`landlord_not_living_in`（不要房东同住）、`furnished_required`、`air_conditioning_required`。
- 通勤时间：`max_commute_minutes` 和排序偏好 `commute` 指从房源到用户账号里“我的学院”的时间：公共交通按工作日早上 8:30 出发（OneMap 路线，含步行段）；学院在直线 1.5 公里以内时，再查 OneMap 步行路线，取更快的一种，回复里写“步行约 X 分钟”或“公共交通约 X 分钟（工作日 8:30 出发）”。数据来自数据库的 `listing_commutes`，由 `build_commutes.py` 生成，同时存成 `commute_faculty.csv`（列 listing_id、faculty、minutes、mode、departure；mode 是 transit、walk 或 transit_google（见下一条），minutes 为空表示没有可用路线）。这个文件在项目根目录，是唯一提交到 Git 的 CSV（`.gitignore` 忽略其他 CSV，用 `!commute_faculty.csv` 单独放行），组员拉取后运行 `build_commutes.py --import`（或 `setup_database.py`）写入自己的数据库即可，不需要 OneMap 账号。由一个人重跑脚本并提交，免得几个人各自重算、提交时冲突；房源数据换版本后要重跑，新房源才有通勤时间，没有通勤记录的房源显示为没有数据。重跑只补缺的部分：新房源、旧文件缺的步行检查、上次中断后没算的路线；OneMap 连续超时三次时脚本停下，已算好的都保存，再运行一次接着算，不会把超时记成“没有路线”。这套房没有通勤数据或用户没设学院时，通勤一律算“未注明”：设了通勤条件的房源列为“需确认”，没设学院时回复末尾固定提示去设置；用户问“去学校要多久”时，没有数据就明说，并给出到学院的直线距离和最近 MRT 步行时间作参考，不估算分钟。只支持数据里的房源，不算任意地址。测试用 fixture 里的模拟分钟数。脚本需要 `.env` 里的 `ONEMAP_EMAIL` / `ONEMAP_PASSWORD`。
- 2026-10-07 核对 OneMap 结果时发现：49 Normanton Park 的两套房（24611200、24666342）到 1.5–4.6 公里外的学院公共交通要 81–110 分钟，同距离的其他房源只要 25–37 分钟，所以这两套到 16 个学院的时间改用 Google Routes API 的公共交通路线（`fix_transit_google.py`，工作日 8:30 出发，mode 为 `transit_google`）。回复里同样写“公共交通约 X 分钟（工作日 8:30 出发）”，解释排名时数据来源写“Google 公共交通路线”。`build_commutes.py` 的 `UNRELIABLE_TRANSIT` 记下了这两套，重跑时不向 OneMap 查询，也不覆盖这些行；重算它们需要 `.env` 里的 `GOOGLE_MAPS_API_KEY`。圣淘沙湾的房源普遍比距离推算慢 45–50 分钟，其中两套没有公共交通路线，看起来是那里公共交通确实不便，暂时保留。
- 面积：明确的最低面积用 `min_area_sqm`（平方米；sqft × 0.09290304）筛选；“空间大一点 / 宽敞”在 `ranking_priority` 中加入 `space`，无需先给预算或整租方式。空间偏好按上面的规则分到权重，按同一出租方式和面积口径内的面积百分位排序，不把房间与整套平方米直接比较。整租使用 `floor_reported`，房间使用 `room_reported`；未注明、出租方式未知或房间只报整套面积的房源列为“需确认”。搜索结果和详情显示面积口径。
- 其余数据中的租房需求也已接入（缺失仍为“需确认”）：卫生间数 `min_bathrooms`、独立卫浴 `private_bathroom_required`、宠物 `pets_allowed_required`、报价性质 `rent_price_types`、项目/地址/街道/邮编 `title_keyword` / `address_keyword` / `street_name` / `postcode`、最近运营 MRT `mrt_station`、周边站数 `min_mrt_stations`、步行米数上限 `max_mrt_distance_m`、挂牌日期下限 `listed_after`、房东明确的性别偏好 `gender_preference`。
- 家具程度用 `furnishing_types`（全家具/部分家具/无家具/带家具但程度未注明），做饭强度用 `cooking_level`（light 接受轻炊或不限烹饪；full 仅接受不限烹饪；none 要求禁止做饭）。旧的 `furnished_required`、`cooking_required` 继续兼容；改成无家具/禁止做饭时需清掉冲突的旧条件，否则工具报错且不保存。
- 周边数量下限：`min_food_places`、`min_hawker_centres`、`min_libraries`、`min_sports_facilities`、`min_healthcare_places`、`min_community_centres`、`min_schools`。前六项是直线 1 公里内计数，学校和 MRT 使用 PropertyGuru 的周边统计；医疗计数混合医院和药店，不能据此承诺附近一定有医院。只想“多一些”时用排序偏好 `food_places` / `hawker` / `libraries` / `sports` / `healthcare` / `community` / `schools`，不凭空设置数量门槛。
- 最近学校步行上限使用 `max_school_walk_m` / `max_school_walk_minutes`；“学校近”用排序偏好 `school_distance`。这些指最近广告学校，不特指 NUS 或其他指定学校。`pg_mrt_nearest_walk_m` 作为 MRT 米数的后备来源，但仍排除未通车站；周边 MRT 总数不代表所有站均已运营。
- 地点范围使用 `nearby_location`（`query` 或用户提供的 `latitude` / `longitude`，以及明确的 `radius_m`）。地名用现有 OneMap 配置解析，NUS 学院除外（见下一条）；多地点歧义或 API 失败时不保存位置条件，要求更明确地址/邮编/坐标。坐标距离为直线距离，使用房源的 `coord_error_m` 判断边界，误差跨过范围上限时列为“需确认”。位置和新增条件支持保存、清除和不改原条件的预览，Agent 与 workflow 共用规则。
- NUS 学院地址：`faculties.py` 记录了 `facultyaddress.docx` 里的 16 个学院 / 学校（名称、代表建筑、地址、校区），坐标是 2026-10-06 按地址查到的 OneMap 结果（同一邮编有多栋楼时取文档写的那栋）。用户说学院的英文名、中文名或缩写（如 School of Computing、商学院、SoC）时直接用记录的坐标，不调用 OneMap，也不会因为同一邮编有多栋楼而被判为地点不唯一。离学院多远仍然需要用户给出范围。每个学院都是独立的通勤目的地，所以武吉知马的李光耀公共政策学院、欧南的 Duke-NUS 也有各自的通勤时间。改地址或加学院时编辑 `faculties.py`（坐标需要重新按 OneMap 查询），再重跑 `build_commutes.py`；改的是已有学院的地址时，先删掉 `commute_faculty.csv` 里这个学院的行，否则会被当成已算过而跳过。
- 租期：2026-10-09 的 V2 数据加了 `lease_term`（"1 year"、"2 years"、"Flexible"、"Short Term"、"Prefer not to say" 或空，约三分之一未注明），当作房东接受的最短租期。用户说“只租 6 个月 / 租一年 / 签两年”时保存为 `lease_months`（月数，和其他条件一样记下原话，同意记住时进长期档案），筛选规则：1 year 要求至少 12 个月、2 years 至少 24 个月，想租得更久也算符合；Flexible 都符合；Short Term 只对 12 个月以下算符合，12 个月以上列为“需确认”；未注明列为“需确认”。用户要的租期短于 6 个月时，回复开头固定提示法定最短租期（私人住宅 3 个月、HDB 组屋和组屋房间 6 个月，URA / HDB 规定）。每套房源的展示、详情和网页卡片都显示租期。
- 费用：`estimate_costs` 算一套或几套房源（最多 3 套，或候选清单）、用户给的月租（可换币种）或保存的预算的费用：整个租期总租金、印花税（租期 4 年以内为总租金 × 0.4%，向下取整、最少 S$1；平均年租 S$1,000 以下免征）、押金（每年租期 1 个月）、签约时预付（押金 + 第一个月租金 + 印花税 + 中介费）和不含押金的总花费，并说明定金签约后转为押金、不另外计入。租期依次用用户说的、房源要求的（比用户说的长时以房源为准并写明）、12 个月。中介费只在用户说用了中介时计算，默认每年租期半个月租金另加 9% GST（惯例，可协商）。明细以固定文字显示，第一行写明假设，最后一句请用户补充租期、押金或中介后重算；用户说的押金月数、是否用中介、中介费在这段对话里沿用，说的租期保存为搜索条件。规则来源见 `costs.py` 开头（2026-10-10 核对）。
- 物业类型使用 `property_types`：“公寓”对应 condominium、executive_condominium、apartment、walk_up_apartment，“组屋”对应 hdb_flat。保存时会显示实际使用的类型，说得不对可以直接纠正。
- 用户愿意加预算或问“有没有更好的”却没给数字时，agent 调用 `explore_budgets` 比较几个价位（只查数据库、不检查链接、不保存条件），说明预算是不是瓶颈，再问用户选哪个方向。
- 预算：保存的是每月租金上限。用户说一年 / 每年 / 整个租期的预算时，Agent 的 `budget.months`（workflow 为 `budget_months`）记为 12 或租期月数，先换算币种、再除以月数，新币的年预算也一样；回复开头的固定换算文字会写出计算过程。Agent 新保存的月租上限如果高于数据中 90% 房源的月租，会固定提醒用户确认是不是年预算或总预算。反过来，换算后的月租上限不到数据中最便宜房源月租的十分之一时（比如“一年30rmb”，多半少写了“万”“千”），这个预算不使用也不保存，回复开头固定提示并请用户给出正确金额，其他条件照常保存和搜索；只是略低一些的预算仍照常搜索，没有结果时给出放宽建议。
- 工具出错时，错误信息会写明哪里错了、下一步怎么做（例如换成 ISO 4217 币种代码再调用，或询问用户）；提示词要求模型能改正的先改正参数重试，再回答用户。币种别名 RMB 在换算前自动转成 CNY。
- 回复没通过检查时，会把原因反馈给模型重试一次；仍不通过才退回模板，没有模板时显示当前保存的条件和展示过的房源。`--trace` 会显示被拦原因。
- 链接检查沿用 workflow 规则：搜索、详情、比较、查看候选清单时，对要展示的房源检查原网址（active / inactive / unknown，不改变排序，inactive 排除，原因写入 `listing_health.error_reason`）；`explore_budgets` 只统计数据库，不检查链接。模型拿到每套房源的 `link_note`（与 workflow 相同的说明句）和 `availability_note`，要求分开说明；链接无法确认的房源由系统在回复末尾固定列出原因。
