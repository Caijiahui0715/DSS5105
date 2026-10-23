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

**以后再用**：PostgreSQL 开机就在运行，只需要第 6 步（启动时提示连不上 PostgreSQL，多半是服务停了，按 `使用说明.md` 常见问题里的“PostgreSQL 没在运行”处理）。拉了新代码后先运行 `uv sync` 和 `uv sync --project app`；组里发了新版本的数据，就换掉 `output-final-delivery`，再运行一次 `setup_database.py`。改了 `.env` 要重启对应的程序。

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
.\.venv\Scripts\python.exe .\check_onemap_rate.py     # 测 OneMap 每分钟能查几次路线，给出 ONEMAP_CALLS_PER_MINUTE 的建议值
.\.venv\Scripts\python.exe -m unittest discover -s tests   # 需要 PostgreSQL，用 <DB_NAME>_test，见“数据和存储位置”
```

房源、账号、对话、长期资料、收藏和排除都在项目的 PostgreSQL 里，见下方“数据和存储位置”。

命令行 `demo.py` 是本机开发工具，不需要密码：`--user=NAME` 和网页版用的是同一套用户名（不区分大小写），所以在网页上注册的 alice 和 `--user=alice` 看到的是同样的对话、长期资料和收藏。只在自己电脑上用它。

## 多用户网页版

`server.py` 是一个本地 FastAPI 服务，同时提供接口和单页网页 `static/index.html`，几个人可以同时用。

- 账号：开放注册，用户名 3–20 个字母、数字或下划线（不区分大小写），密码至少 8 位；密码只存加盐的 scrypt 哈希。连续输错 5 次密码锁定 1 分钟。登录后服务端发一个令牌放在 HttpOnly cookie 里（7 天有效，数据库只存它的 SHA-256），退出登录即作废。
- 对话：每个用户可以有多段对话，按最近活动排序，默认打开最近一段；标题是第一条消息的前 20 个字。新对话不带入旧对话的消息；长期记忆打开时，新对话从长期资料的条件开始（见“架构”里的 `profiles.py`）。收藏和排除属于账号，所有对话共用。每段对话的状态用 LangGraph checkpointer 按 thread 保存，`threads` 表记录它属于谁；访问别人的对话一律返回“找不到这段对话”。
- 处理中：回复仍在整轮结束、通过事实核对后一次性显示。等待时显示“思考中……”，下面一行小字是当前步骤（正在搜索房源、正在检查房源链接（第 2 套）等），通过 Server-Sent Events 推送，不显示工具参数或模型推理。同一段对话里上一条还没处理完时，新消息排队。关掉页面不会中断正在处理的一轮，刷新后能看到结果。
- 查看处理过程：每条回复下面可以展开，按顺序列出这一轮调用了哪些工具、链接检查、汇率换算、被拦下重写等；这些步骤和回复一起保存，刷新或隔天回来也能看。
- 我的学院：注册时可以选（也可以暂不选择），之后在左侧栏“我的学院”里随时修改。通勤时间都按这个学院计算，所有对话通用，改了以后从下一条消息起生效。对话里也能改：还没设置时 agent 会先问你在哪个学院，你的回答就会保存；已经设置、你又说了另一个学院时，agent 先确认“要把你的学院改成 X 吗？之后所有对话都会按 X 计算通勤时间”，你同意后才改，回复开头固定显示改动。只是问“如果我在法学院呢”这类假设，只查不改。
- 删除：可以删除单段对话（Streamlit 左侧对话栏里，当前打开的对话那一行的垃圾桶，确认后删除；回复生成期间不能删）；“删除我的全部数据”（个人资料页最下面，勾选确认后才能点）删除这个用户的全部对话、长期资料、收藏、排除和学院设置，账号保留，并让所有设备退出登录。“删除长期资料”（个人资料页，或对话里说“删除我的长期资料”）只删除保存的条件，长期记忆开关不变；对话里说“忘掉我的信息”删除条件并关闭长期记忆。这两种都不动收藏、排除和学院。
- `--lan`：监听 0.0.0.0 并打印本机局域网地址（Windows 第一次运行会弹出防火墙提示，需要允许专用网络）。这是明文 HTTP，密码和对话在局域网里不加密，只在信任的网络里用；默认只监听 127.0.0.1。

## 数据和存储位置

- 全部在项目的 PostgreSQL：连接设置是 `.env` 里的 `DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER`、`DB_PASSWORD`，和数据管道共用；可选 `DB_CONNECT_TIMEOUT`，默认 10 秒。
  - `public` schema：房源（`listings`、`listing_enrichment`、`listing_metadata`、`district_lookup`）和通勤（`listing_commutes`、`nus_destinations`），只由数据管道写（`src/dss5105/data`、`build_commutes.py`）。
  - `agent` schema：只由服务器写。账号、令牌、对话列表、长期资料、长期记忆和自动保存开关（`user_profiles`）、学院设置、账号的收藏和排除（`user_listings`）、一次性数据迁移的记录（`migrations`）、LangGraph 的 checkpoint 表，链接检查结果 `listing_health`（重启后 24 小时内继续复用），到用户说的地点的路线 `place_routes`（见“另一个通勤目的地”），以及 `agent_listings` 视图。
  - `agent_listings` 视图（`group_db.py`）：每次搜索都读它。它只取 `scrape_status = 'active'` 的房源，在数据库里算好排序用的值（周边餐饮和各类设施的名次、面积百分位、到每个学院更快的那种通勤方式、到用户说过的地点的路线），把 V2 的标签换成搜索用的 V1 写法，并连上区名、可用性、review flags 和链接检查结果。服务器每次启动时重建这个视图；数据管道更新数据后，下一次查询就能看到，不用重启。
  - 第一次准备（或数据换版本后）：运行 `setup_database.py`。它依次建库（服务器上还没有时）、补跑 `src/dss5105/database/` 里还没跑过的建表脚本、运行 `load_data.py`（V1）和 `sync_v2.py`（V2）、把 `commute_faculty.csv` 写入数据库，最后建好 `agent_listings` 并打印可用房源数。可以重复运行，`agent` 里的账号和对话不受影响。它只新增或更新文件里的房源：新版 V2 文件里没有、`removed_listings.csv` 也没写的旧房源仍是 active，脚本会提示有几套。需要 `output-final-delivery/` 里的数据文件（组里共享，不在 Git 里）。学院以 `faculties.py` 为准，不要再用 `seed_nus_destinations.py` 覆盖。
  - 连不上：启动时直接退出，并说明要检查什么（服务是否在运行、连接设置，或者先运行 `setup_database.py`）。运行中断开时，这一轮回复“数据库暂时连不上，请稍后再试。”，下一条消息自动重新连接。
  - 重新导入房源数据时只清理 `public` 里的表，不要删除整个数据库，否则所有账号和对话都会丢失。
- 测试：用同一台服务器上的 `<DB_NAME>_test`，第一次运行时自动创建（账号需要建库权限，没有的话先在 pgAdmin 里手动建）。每组数据放在自己的 schema 里：`mock` 是 `tests/fixtures` 里 12 套虚构房源，每个测试前重建；`real` 是 `output-final-delivery` 的数据，每次运行用 `load_data.py` 和 `sync_v2.py` 导入一次；`storage` 放账号和对话，每个测试前清空。连不上 PostgreSQL 时，需要数据库的测试会跳过并写明原因，其余照常运行。

## 架构

- `agent.py`：外层 agent。模型读取对话、会话状态和工具结果，自己决定调用哪些工具、调用几次；每轮最多 5 轮工具调用。
- 工具都是确定性代码：`search_listings`、`explore_budgets`、`get_listing_details`、`explain_listing`、`compare_listings`、`shortlist`、`exclude_listings`、`estimate_costs`（有账号时还有 `user_memory`、`faculty`）。
- 比较：`compare_listings` 一次比较两到三套（多了就请用户挑三套），按用户给的顺序生成对比表（月租及比最便宜的贵多少、到学院通勤、MRT、租住方式和房型、面积、卫浴、家具、租期、可入住、按当时条件是否符合、链接检查，中英文都有），和一句系统算出的关键差异；链接已失效或已不在数据中的房源不比较，由系统在回复开头写明，只剩一套时不比较。对比表随回复返回给页面，最近一次存在对话状态里（`last_comparison`）。模型只写差异、取舍和建议，不再逐套列数据。每个账号第一次比较时，系统在回复开头说明对比表在右侧“比较”栏（`user_profiles.compare_hint_shown`）。
- `costs.py`：租房费用的计算（总租金、印花税、押金、签约时预付、中介费），规则写在文件开头，`estimate_costs` 用它。
- `decision.py`：条件三态判断（符合 / 不符合 / 数据未注明）、逐个放开条件的诊断、排序溯源。严格匹配结果与 `tools.search_listings` 完全一致。
- `graph.py`：原固定 workflow，保留作评估 baseline。
- `tools.py`、`response.py`：检索与 URL 校验、事实模板，两套流程共用。`mock_db.py`：测试用的数据库（见“数据和存储位置”）。
- `sessions.py`：`agent` schema 里的对话表和 LangGraph 的 PostgresSaver（和房源共用一个连接池），用 checkpointer 把每轮的完整状态（条件和每个条件的原话、对话消息、每条回复的处理过程）按对话保存，`threads` 表记录每段对话属于哪个用户；Agent 与 workflow 的对话分开存。
- `accounts.py`：注册、密码校验、登录锁定和令牌，只用标准库。
- `group_db.py`：项目 PostgreSQL 的连接池、`agent_listings` 视图和启动检查；`open_database()` 连上数据库并建好视图，网页版、命令行和通勤脚本都用它。
- `setup_database.py`：一键准备数据库（见“数据和存储位置”）。
- `src/dss5105/`：pizza 的数据层，`database/` 是建表和迁移，`data/` 是 V1 导入、V2 同步和学院表脚本。推荐逻辑统一用 agent 的，原来的 `api/`、`backend/`、`commute/`、`decision/` 已不再使用（计划移进 `archive/`）。
- `faculties.py`：NUS 各学院的地址、坐标和数据库里的学院代码（`code`），供地点条件按学院名定位，也是通勤时间的目的地。
- `build_commutes.py`：用 OneMap 离线计算每套房源到每个学院的公共交通时间（1.5 公里内再比较步行），写入 `commute_faculty.csv`。数据库是源头：先把 `listing_commutes` 导出成 CSV，补算缺的，结束（包括中途出错）时写回数据库。CSV 在 Git 里，新的数据库用 `setup_database.py` 导入它就有通勤时间，不需要 OneMap。`--import` / `--export` 单独做写入或导出，例如跑完 `fix_transit_google.py` 后用 `--import`。
- `show_route.py`：打印某套房到某个学院的 OneMap 路线（每段的方式、起止和分钟数），用来核对可疑的通勤时间。
- `server.py`、`static/index.html`：多用户网页版的接口和页面（页面留作开发测试，正式前端是 Streamlit，见“给前端的接口”）。
- `profiles.py`：长期资料、长期记忆和自动保存两个开关、账号的收藏 / 排除（只在 Agent 中，workflow baseline 不变）。
  - 长期资料（`user_profiles.profile`）：用户选择保存的条件，每个条件附来源（对话里的原话和日期，或“个人资料页修改”和日期），预算按原说法记录（金额、币种、覆盖月数）。不保存对话内容，也不让模型自由写入。
  - 只在用户保存或选了自动保存时更新：在个人资料页改表单、首页“本次对话的条件”里点“存为长期资料”（先列出改动，确认后才保存）、在对话里说“存到我的资料”（工具 `user_memory`，`action=save`），或打开了自动保存（见下）。没有自动保存时，对话里改的条件只属于这段对话，回复开头写“已更新本次对话的条件：……”，首页条件面板上方会提示还有几项改动没存到长期资料；系统不会在对话里问要不要保存。
  - 只合并改过的字段：拿对话现在的条件和它开始时套用的长期资料（或上次保存后的值，存在状态的 `profile_base` 里）比，不一样的字段才写入，清掉的条件也算；这段时间里别的对话或个人资料页改过的其他字段保持不变。对话开始时没有套用长期资料的，对话里设过的条件都算。个人资料页的表单也只提交改过的字段。
  - 长期记忆开关（`user_profiles.consent`）：新用户是“未开启”，第一次保存时自动打开；个人资料页可以开关，对话里说“打开 / 关闭长期记忆”也行（`action=on` / `off`）。关闭是暂停：保存的条件还在、能看、能删，但新对话不套用、页面只读、也不能保存；关着时要保存，agent 先问“长期记忆已关闭，要打开并保存吗？”，同意后才打开并保存（`switch_on=true`）。
  - 自动保存开关（`user_profiles.auto_save`）：打开且长期记忆也开着时，对话里的条件一改（`search_listings` 不是预览时，或 `estimate_costs` 里说了新的租期）就马上合并进长期资料，规则和手动保存一样（只写改过的字段），回复写“已更新本次对话的条件，并自动存到长期资料：……”。新用户是“未选”；自动保存没开、长期记忆没关、也没点过提示条的 × 时，首页对话有了条件后，聊天输入框上方出现提示条“以后对话里改的条件，自动存到长期资料吗？［自动保存］ ×”：点“自动保存”就打开（长期记忆未开启时一起打开），并马上存这段对话到目前为止的改动，提示条换成一句怎么关闭的说明，点 × 才消失；点提示条的 × 以后不再出现（`user_profiles.offer_closed`）。也可以在个人资料页“长期记忆”下面开关（长期记忆关着时变灰），或在对话里说“打开 / 关闭自动保存”（`action=auto_on` / `auto_off`）。长期记忆关着时自动保存的设置保留但暂停，重新打开后继续；“忘掉我的信息”同时关闭自动保存；“删除我的全部数据”连同提示条的选择一起清掉。
  - 新对话：开关打开且有保存的条件时，`POST /api/conversations` 建对话时就套用这些条件（非新币或按年的预算按当天汇率重新换算，换算失败则用上次的月租上限并说明），并写入一条系统写的开场消息“已按你的长期资料设好条件：……”；前端在第一条消息发出前就显示这条消息和这些条件。对话里说“沿用 / 用我的长期资料”会重新套用（`action=restore`）；“我的长期资料是什么”是 `action=show`。
  - 收藏和排除（`user_listings`）：属于账号，所有对话共用，点一下就生效，不受长期记忆开关影响。一套房要么在收藏里、要么被排除，后做的操作为准。搜索结果不再推荐收藏和排除的房源；收藏里有完全符合这次条件的，回复末尾固定提一句“另外，你收藏的 … 也符合这次的全部条件”。个人资料页列出已排除的房源，可以恢复。以前存在每段对话和长期档案里的收藏、排除，服务器第一次启动时合并到账号里（先长期档案，再按对话最后活动时间从早到晚，同一套房以后面的为准），只合并一次。
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
- 房源：`GET /api/listings?limit=50&offset=0`（`limit` 最多 200）返回 `{"total", "listings"}`，字段和 agent 排序用的一样（含 `commutes` 各学院通勤、`live_status` 链接检查结果、`lease_term` 广告写的租期、`photos` 照片链接；`rent_monthly_sgd` 是重新检查过的月租，原广告月租在 `rent_monthly_sgd_card`）；`GET /api/listings/{id}` 返回 `{"listing", "source_evidence"}`，后者是房源页的完整记录（图片、原文、字段依据），没有记录时为 `null`，找不到房源返回 404。
- 对话：`POST /api/conversations` 新建（可带 `{"language": "zh" | "en"}`，是开场消息的语言；长期记忆打开时对话从长期资料的条件开始，见上），`POST /api/conversations/{id}/messages`（`{"message", "language"}`，`language` 是界面语言 `zh` / `en`，只在消息本身看不出语言时使用，例如只发了 `1000`；其他时候回复跟随消息的语言）用 Server-Sent Events 返回 `progress`（`{"zh", "en"}` 两种文字）和最后的 `reply`。`reply` 里有 `text`、`steps`、保存的条件 `preferences`、每个条件的来源 `sources`（`{"quote", "date"}`）、给页面列出条件用的 `items`（每个条件的 `field`，`label` 和 `value` 各有 `zh` / `en`，以及 `source`）、还没存到长期资料的改动 `profile_changes`（格式同下面的 `changes`）、账号的收藏 `shortlist`、这一轮的对比表 `comparison`（没有比较时为 `null`，格式见 `app/API_CONTRACT.md`），以及 `recommendations`：这一轮搜索展示的房源，`{"preview", "listings": [...]}`，每套带 `status`（`match` 完全符合 / `needs_confirmation` 需确认，后者有 `unknown_conditions` 和按回复语言写好的 `unknown_condition_labels`）、`position`、月租、MRT、到“我的学院”的 `commute_minutes_to_faculty` 和 `commute_mode`、`lease_term`、`link_status` / `link_note` 等；这一轮没有搜索时为 `null`，前端保留上一次的列表。`preview` 为 true 表示只是假设，条件没有保存。
- 重新打开对话：`GET /api/conversations` 列出对话，`GET /api/conversations/{id}/messages` 是消息和每条回复的处理过程，`GET /api/conversations/{id}` 返回 `{"id", "preferences", "sources", "items", "profile_changes", "recommendations", "comparison", "shortlist"}`（`recommendations` 是最近一次搜索展示的房源，`comparison` 是最近一次的对比表，格式同上）。
- 收藏和排除：就是 agent 的候选清单和排除名单，属于账号，所有对话共用，agent 也看得到。`GET /api/me/listings` 返回 `{"shortlist", "excluded"}`；`POST /api/me/shortlist`（`{"listing_id"}`）收藏（被排除的同时取消排除），`DELETE /api/me/shortlist/{listing_id}` 取消收藏，`DELETE /api/me/excluded/{listing_id}` 恢复被排除的房源，都返回同样的 `{"shortlist", "excluded"}`。
- 长期资料：`GET /api/me/profile` 返回 `{"memory", "auto_save", "auto_save_offer", "saved_on", "preferences", "sources", "budget", "items", "opening"}`：`memory` 是开关 `on` / `off` / `undecided`；`auto_save` 是自动保存开关（长期记忆关着时暂停）；`auto_save_offer` 表示首页要不要显示自动保存的提示条；`opening` 是新对话开场消息的 `{"zh", "en"}`，开关没打开或没有条件时为 `null`。`PUT /api/me/profile`（`{"changes": {条件: 新值或 null}}`，条件名同 `preferences`）改长期资料，只写入给出的字段，来源记为个人资料页；开关关着时返回 409，开关未开启时保存会同时打开。`PUT /api/me/memory`（`{"on": true/false}`）开关长期记忆，`PUT /api/me/auto-save`（`{"on": true/false}`）开关自动保存（打开时长期记忆未开启也会一起打开），`DELETE /api/me/auto-save/offer` 关掉提示条（以后不再出现），`DELETE /api/me/profile` 删除保存的条件，都返回同样的长期资料。
- 把对话的条件存为长期资料：`GET /api/conversations/{id}/profile` 返回 `{"memory", "changes"}`，`changes` 是保存后长期资料会怎么改（每行 `field`，`label`、`before`、`after` 各有 `zh` / `en`）；`POST /api/conversations/{id}/profile`（`{"switch_on": false}`）保存，返回 `{"changes", "profile"}`。开关关着时要带 `"switch_on": true`（用户同意打开后），否则返回 409。`POST /api/conversations/{id}/auto-save` 是提示条上的“自动保存”：打开自动保存，并马上保存这段对话到目前为止的改动，返回 `{"changes", "profile"}`；长期记忆关着时返回 409。
- 删除全部数据：`DELETE /api/me/data`，见上面的“删除”。

## Agent 的边界

- 事实只来自工具结果或会话状态。回复里的房源编号、金额、分钟数、套数必须出现在本轮工具输出中，否则回退为模板草稿；提出联系房东、确认可租、预约看房等超出能力的动作也会回退。
- 保存条件变更时，工具参数必须引用用户本轮原话（`user_quote`）；`preview=true` 只看不改。`set` 里只放要改成新值的字段，空值和默认值会被忽略（模型有时会把所有字段都带上，否则会清掉已保存的条件）；要去掉某个已保存条件，用 `clear` 列出字段名。条件变更、收藏和排除以固定文字显示给用户。
- 数据未注明不再等同于不符合：其他条件都符合、只是部分要求未注明的房源单独列为“需确认”，并说明是哪个条件卡住了结果。
- 已保存的搜索没有严格匹配时，按原 workflow 的单项放宽规则（预算约 +10%、MRT +5 分钟，设了租期时再试签 1 年、2 年，结果经过链接检查）在回复末尾固定附上让步建议；设了通勤上限时，每个目的地各再试放宽 10 分钟。没有找到建议、但已经列出“需确认”的房源时，不再加“放宽后也没找到”那句（卡住的是数据未注明，放宽别的条件也没用）。
- 整租 / 合租使用 `rental_scope`（entire_unit / room），取 v2 数据的出租方式；未注明的房源列为“需确认”，不当作整租。引导用户补充条件时先问整租还是合租，选了合租再问房型。用户没选、而完全符合的房源里两种都有时，回复末尾固定提示展示的是哪一种，以及另一种的套数和最低月租。
- 排序：MRT 步行距离始终参与（米数 ÷ 参考距离，参考距离 = 步行上限 × 85 米，没给上限时 850 米），有预算时再加月租 ÷ 预算；吃饭方便、到 NUS 通勤只在用户提出时参与。`ranking_priority` 最多保存 3 个偏好，点名的几项平分 70%，其余因素平分 30%，但其余每项不超过任何一个点名项（例如点名 3 项、只剩 1 项时四项各 25%）；没点名时等权。多轮对话中用户说“还 / 也 / 另外”时追加偏好，说“算了 / 改成 / 只要”时替换；分不清时追加，并以固定文字显示变更，用户可以直接纠正。超过 3 个时先问用户哪三个最重要。点名的每一项都需要数据，缺任何一项的房源列为“需确认”。没有 MRT 数据或最近的站尚未通车按参考距离计（比值 1）；但用户点名在意 MRT 时，这类房源列为“需确认”。并列时先比权重最高的一项，再比下一项，最后才比月租。
- 入住人数（`occupant_count`）：系统找不到同一套里的几个单间，所以默认一人一间。2 人及以上时，Agent 的代码（`agent.occupant_rules`，不靠模型）把出租方式存成整租、最少卧室数设成人数（已经存了更多卧室时不动，用户同一句里自己说了卧室数时用他说的），回复末尾固定说明“按整套、一人一间找了至少 N 个卧室”，并请用户在有人合住一间时说一共需要几个卧室；原来选的是合租时说明为什么改找整租。唯一的例外是选了合租的 2 个人：按两人合住一个单间找，末尾说明想各住一间可以改找 2 房整租。卧室数正好等于原来的人数时算作按人数设的：人数改成 2 及以上就跟着改；改成 1 人或不再按人数找时一起去掉，整租保留，末尾问要不要也看看单间。模型只设 `occupant_count`，提示词要求它不自己设卧室数、整租或“空间大”的排序偏好。workflow baseline 不做这些换算，只共用下面的判断。
- 入住人数的判断：整租 6 人及以下算符合（私人住宅和 3 房式以上组屋的法定上限，URA / HDB），超过 6 人列为“需确认”。单间 1 个人算符合；2 人及以上时，广告写 1 pax 的不符合，写 2 pax 及以上或没写的列为“需确认”，并附上“广告标注 N pax，能住几个人要问房东”。数据里的“N pax”只是 PropertyGuru 卡片上的标签，有的是整套房的人数（字段说明写着范围未确认），所以不当作房间能住几个人的依据；整租房源都没有这个标签。
- 回复里的粗体：后端在保存和发出回复前，把粗体两头的标点移到 `**` 外面（`**主要取舍：**第1套` 改成 `**主要取舍**：第1套`），否则 Markdown 会把星号原样显示。
- 限制条件（符合 / 不符合 / 未注明三态，未注明一律列为“需确认”，整租也一样）：`tenant_gender`（用户自己说明的住户性别：female / male / mixed，对照数据的 gender_restriction）、`landlord_not_living_in`（不要房东同住）、`furnished_required`、`air_conditioning_required`。
- 通勤时间：`max_commute_minutes` 和排序偏好 `commute` 指从房源到用户账号里“我的学院”的时间：公共交通按工作日早上 8:30 出发（OneMap 路线，含步行段）；学院在直线 1.5 公里以内时，再查 OneMap 步行路线，取更快的一种，回复里写“步行约 X 分钟”或“公共交通约 X 分钟（工作日 8:30 出发）”。数据来自数据库的 `listing_commutes`，由 `build_commutes.py` 生成，同时存成 `commute_faculty.csv`（列 listing_id、faculty、minutes、mode、departure；mode 是 transit、walk 或 transit_google（见下一条），minutes 为空表示没有可用路线）。这个文件在项目根目录，是唯一提交到 Git 的 CSV（`.gitignore` 忽略其他 CSV，用 `!commute_faculty.csv` 单独放行），组员拉取后运行 `build_commutes.py --import`（或 `setup_database.py`）写入自己的数据库即可，不需要 OneMap 账号。由一个人重跑脚本并提交，免得几个人各自重算、提交时冲突；房源数据换版本后要重跑，新房源才有通勤时间，没有通勤记录的房源显示为没有数据。重跑只补缺的部分：新房源、旧文件缺的步行检查、上次中断后没算的路线；OneMap 连续超时三次时脚本停下，已算好的都保存，再运行一次接着算，不会把超时记成“没有路线”。这套房没有通勤数据或用户没设学院时，通勤一律算“未注明”：设了通勤条件的房源列为“需确认”，没设学院时回复末尾固定提示去设置；用户问“去学校要多久”时，没有数据就明说，并给出到学院的直线距离和最近 MRT 步行时间作参考，不估算分钟。学院以外的地点见下一条“另一个通勤目的地”。测试用 fixture 里的模拟分钟数。
- 另一个通勤目的地：除了账号里的学院，对话的条件里还能再有一个目的地 `other_destination`（`query` 是学院的英文名或英文地名 / 地址 / 邮编，`name` 是它对用户是什么，比如“室友的学院”“健身房”；系统定位后补上 `faculty` 和坐标），上限是 `max_other_commute_minutes`（额外条件，没有数据时列为“需确认”）。
  - 学院直接用 `listing_commutes` 里已经算好的时间；其他地点由 `place_routes.py` 第一次用时向 OneMap 现场算（工作日 8:30 出发，1.5 公里内再比较步行，和 `build_commutes.py` 一样），存进 `agent.place_routes`（按坐标到约 1 米的 `place_key`，没有路线时 minutes 为空），视图的 `place_commutes` 列按地点给出每套房的时间。
  - 只算可能展示的房源（`decision.route_candidates`：数据总会注明的条件都满足、预算放宽 10% 的房源，有坐标的才算）。超过 120 套时工具先停下，让模型按固定文字问用户要不要等，用户同意后带 `wait_for_routes=true` 再搜。6 个请求并发，整个后端共用一个限速（`ONEMAP_CALLS_PER_MINUTE`，默认每分钟 240 次）；OneMap 回 HTTP 429 时所有请求暂停 10 秒再试。算失败的不保存，下次搜索再算，回复末尾固定说明有几套暂时算不出。
  - 排序偏好 `commute` 有两个目的地时，取两段里各自除以上限（没给上限时 45 分钟）后较大的一个，也就是按较长的那段排；两段都需要数据。没设学院、只有另一个目的地时，只看那一段，不再提示去设学院。
  - 只能有一个：已经有了、用户又说一个新的地方时，工具不保存，让模型按固定文字提醒“除了你的学院，最多只能再加一个目的地”并问要不要换，用户同意后带 `replace_destination=true` 再搜；换了地方，原来的上限一起去掉（同一次给了新上限时用新的）。去掉目的地时上限也一起去掉。目的地就是用户自己的学院时不保存。
  - 和其他条件一样可以存进长期资料，新对话会带上；房源卡片、回复、详情、解释排名和对比表都同时显示两段时间。脚本需要 `.env` 里的 `ONEMAP_EMAIL` / `ONEMAP_PASSWORD`。
- 2026-10-07 核对 OneMap 结果时发现：49 Normanton Park 的两套房（24611200、24666342）到 1.5–4.6 公里外的学院公共交通要 81–110 分钟，同距离的其他房源只要 25–37 分钟，所以这两套到 16 个学院的时间改用 Google Routes API 的公共交通路线（`fix_transit_google.py`，工作日 8:30 出发，mode 为 `transit_google`）。回复里同样写“公共交通约 X 分钟（工作日 8:30 出发）”，解释排名时数据来源写“Google 公共交通路线”。`build_commutes.py` 的 `UNRELIABLE_TRANSIT` 记下了这两套，重跑时不向 OneMap 查询，也不覆盖这些行；重算它们需要 `.env` 里的 `GOOGLE_MAPS_API_KEY`。圣淘沙湾的房源普遍比距离推算慢 45–50 分钟，其中两套没有公共交通路线，看起来是那里公共交通确实不便，暂时保留。
- 面积：明确的最低面积用 `min_area_sqm`（平方米；sqft × 0.09290304）筛选；“空间大一点 / 宽敞”在 `ranking_priority` 中加入 `space`，无需先给预算或整租方式。空间偏好按上面的规则分到权重，按同一出租方式和面积口径内的面积百分位排序，不把房间与整套平方米直接比较。整租使用 `floor_reported`，房间使用 `room_reported`；未注明、出租方式未知或房间只报整套面积的房源列为“需确认”。搜索结果和详情显示面积口径。
- 其余数据中的租房需求也已接入（缺失仍为“需确认”）：卫生间数 `min_bathrooms`、独立卫浴 `private_bathroom_required`、宠物 `pets_allowed_required`、报价性质 `rent_price_types`、项目/地址/街道/邮编 `title_keyword` / `address_keyword` / `street_name` / `postcode`、最近运营 MRT `mrt_station`、周边站数 `min_mrt_stations`、步行米数上限 `max_mrt_distance_m`、挂牌日期下限 `listed_after`、房东明确的性别偏好 `gender_preference`。
- 家具程度用 `furnishing_types`（全家具/部分家具/无家具/带家具但程度未注明），做饭强度用 `cooking_level`（light 接受轻炊或不限烹饪；full 仅接受不限烹饪；none 要求禁止做饭）。旧的 `furnished_required`、`cooking_required` 继续兼容；改成无家具/禁止做饭时需清掉冲突的旧条件，否则工具报错且不保存。
- 周边数量下限：`min_food_places`、`min_hawker_centres`、`min_libraries`、`min_sports_facilities`、`min_healthcare_places`、`min_community_centres`、`min_schools`。前六项是直线 1 公里内计数，学校和 MRT 使用 PropertyGuru 的周边统计；医疗计数混合医院和药店，不能据此承诺附近一定有医院。只想“多一些”时用排序偏好 `food_places` / `hawker` / `libraries` / `sports` / `healthcare` / `community` / `schools`，不凭空设置数量门槛。
- 最近学校步行上限使用 `max_school_walk_m` / `max_school_walk_minutes`；“学校近”用排序偏好 `school_distance`。这些指最近广告学校，不特指 NUS 或其他指定学校。`pg_mrt_nearest_walk_m` 作为 MRT 米数的后备来源，但仍排除未通车站；周边 MRT 总数不代表所有站均已运营。
- 地点范围使用 `nearby_location`（`query` 或用户提供的 `latitude` / `longitude`，以及明确的 `radius_m`）。地名用现有 OneMap 配置解析，NUS 学院除外（见下一条）；多地点歧义或 API 失败时不保存位置条件，要求更明确地址/邮编/坐标。坐标距离为直线距离，使用房源的 `coord_error_m` 判断边界，误差跨过范围上限时列为“需确认”。位置和新增条件支持保存、清除和不改原条件的预览，Agent 与 workflow 共用规则。
- NUS 学院地址：`faculties.py` 记录了 `facultyaddress.docx` 里的 16 个学院 / 学校（名称、代表建筑、地址、校区），坐标是 2026-10-06 按地址查到的 OneMap 结果（同一邮编有多栋楼时取文档写的那栋）。用户说学院的英文名、中文名或缩写（如 School of Computing、商学院、SoC）时直接用记录的坐标，不调用 OneMap，也不会因为同一邮编有多栋楼而被判为地点不唯一。离学院多远仍然需要用户给出范围。每个学院都是独立的通勤目的地，所以武吉知马的李光耀公共政策学院、欧南的 Duke-NUS 也有各自的通勤时间。改地址或加学院时编辑 `faculties.py`（坐标需要重新按 OneMap 查询），再重跑 `build_commutes.py`；改的是已有学院的地址时，先删掉 `commute_faculty.csv` 里这个学院的行，否则会被当成已算过而跳过。
- 房源照片：2026-10-23 的 V2 数据加了 `photos` 列（每套最多 6 个 PropertyGuru 图片链接，JSON 列表，都在 sg1-cdn.pgimgs.com）。`migration_photos.sql` 给 `listings` 加 `photos TEXT[]`，`sync_v2.py` 把列表写进去（旧文件没有这一列时为空），`agent_listings` 视图带出 `photos`（没有时是空列表），房源接口原样返回。网页卡片先用 `photos`，没有时再用 `source_evidence_v1.json` 的图片；房子本身的照片在前，小区照片在后，中介头像和网站图标不显示。卡片和首页面板只显示第一张：由 Streamlit 服务器下载（2 秒超时，缓存 1 小时，加载不了就显示占位提示），下面写“图片来自 PropertyGuru 原房源”并链接到原房源；收藏页的详情再用一排小图显示全部照片，由浏览器直接按链接加载。图片只引用不保存；照片属于 PropertyGuru 和发布的中介，公开发布前要先得到授权。
- 租期：2026-10-09 的 V2 数据加了 `lease_term`（"1 year"、"2 years"、"Flexible"、"Short Term"、"Prefer not to say" 或空，约三分之一未注明），当作房东接受的最短租期。用户说“只租 6 个月 / 租一年 / 签两年”时保存为 `lease_months`（月数，和其他条件一样记下原话，存为长期资料时一起保存），筛选规则：1 year 要求至少 12 个月、2 years 至少 24 个月，想租得更久也算符合；Flexible 都符合；Short Term 只对 12 个月以下算符合，12 个月以上列为“需确认”；未注明列为“需确认”。用户要的租期短于 6 个月时，回复开头固定提示法定最短租期（私人住宅 3 个月、HDB 组屋和组屋房间 6 个月，URA / HDB 规定）。每套房源的展示、详情和网页卡片都显示租期。
- 费用：`estimate_costs` 算一套或几套房源（最多 3 套，或候选清单）、用户给的月租（可换币种）或保存的预算的费用：整个租期总租金、印花税（租期 4 年以内为总租金 × 0.4%，向下取整、最少 S$1；平均年租 S$1,000 以下免征）、押金（每年租期 1 个月）、签约时预付（押金 + 第一个月租金 + 印花税 + 中介费）和不含押金的总花费，并说明定金签约后转为押金、不另外计入。租期依次用用户说的、房源要求的（比用户说的长时以房源为准并写明）、12 个月。中介费只在用户说用了中介时计算，默认每年租期半个月租金另加 9% GST（惯例，可协商）。明细以固定文字显示，第一行写明假设，最后一句请用户补充租期、押金或中介后重算；用户说的押金月数、是否用中介、中介费在这段对话里沿用，说的租期保存为搜索条件。规则来源见 `costs.py` 开头（2026-10-10 核对）。
- 物业类型使用 `property_types`：“公寓”对应 condominium、executive_condominium、apartment、walk_up_apartment，“组屋”对应 hdb_flat。保存时会显示实际使用的类型，说得不对可以直接纠正。
- 用户愿意加预算或问“有没有更好的”却没给数字时，agent 调用 `explore_budgets` 比较几个价位（只查数据库、不检查链接、不保存条件），说明预算是不是瓶颈，再问用户选哪个方向。
- 预算：保存的是每月租金上限。用户说一年 / 每年 / 整个租期的预算时，Agent 的 `budget.months`（workflow 为 `budget_months`）记为 12 或租期月数，先换算币种、再除以月数，新币的年预算也一样；回复开头的固定换算文字会写出计算过程。Agent 新保存的月租上限如果高于数据中 90% 房源的月租，会固定提醒用户确认是不是年预算或总预算。反过来，换算后的月租上限不到数据中最便宜房源月租的十分之一时（比如“一年30rmb”，多半少写了“万”“千”），这个预算不使用也不保存，回复开头固定提示并请用户给出正确金额，其他条件照常保存和搜索；只是略低一些的预算仍照常搜索，没有结果时给出放宽建议。
- 工具出错时，错误信息会写明哪里错了、下一步怎么做（例如换成 ISO 4217 币种代码再调用，或询问用户）；提示词要求模型能改正的先改正参数重试，再回答用户。币种别名 RMB 在换算前自动转成 CNY。
- 回复没通过检查时，会把原因反馈给模型重试一次；仍不通过才退回模板，没有模板时显示当前保存的条件和展示过的房源。`--trace` 会显示被拦原因。
- 链接检查沿用 workflow 规则：搜索、详情、比较、查看候选清单时，对要展示的房源检查原网址（active / inactive / unknown，不改变排序，inactive 排除，原因写入 `listing_health.error_reason`）；`explore_budgets` 只统计数据库，不检查链接。模型拿到每套房源的 `link_note`（与 workflow 相同的说明句）和 `availability_note`，要求分开说明；链接无法确认的房源由系统在回复末尾固定列出原因。
