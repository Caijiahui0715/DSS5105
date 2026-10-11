# 前后端打通：改动清单（给 Fangyue）

页面布局、样式和交互都按你的设计保留，改的是数据从哪来。默认模式下，账号、房源、聊天、推荐、通勤、对话记录和收藏都来自后端 `server.py`（仓库根目录）；设 `AGENT_MODE=mock` 时还是原来的离线演示，你的测试就在这个模式下跑。

## 怎么运行

```powershell
.\.venv\Scripts\python.exe .\server.py                     # 终端 1：后端
uv run --project app streamlit run app/streamlit_app.py    # 终端 2：前端
uv run --project app pytest app/tests                      # 测试（离线模式，不需要后端）
```

前端设置写在 `app/.env`（不提交）：`BACKEND_URL`（默认 `http://127.0.0.1:8000`），可选 `DEMO_USERNAME` / `DEMO_PASSWORD`（配了才显示 “Continue with demo account”），可选 `AGENT_MODE=mock`。

## 各页面的变化（连后端时）

- **登录 / 注册**：用户名（3–20 个字母、数字或下划线，不区分大小写，已被注册的不能再用）+ 密码（至少 8 位，注册时要输入两次），注册时可以选 NUS 学院（通勤时间按它算）。注册表单里的硬性条件和偏好保留，提交后作为第一条消息发给 agent，回复里能看到 agent 理解成了什么。“Remember me on this device” 默认勾选，把登录令牌存在 cookie 里 7 天；退出时删掉 cookie 并作废令牌。顶部有 English / 中文 切换。
- **首页**：聊天走真正的 agent，发出的消息马上显示，下面是 agent 的处理进度；每条回复可以展开看“这条回复是怎么得出的”。右侧列表就是 agent 这次搜索展示的房源；一轮没有搜索时列表保持不变。地图的学士帽是用户的学院；右上角的地图铺满整个框（固定 350px 高，下面的房源面板占剩下的高度），原来地图上方那行 “V2 data locations · inferred positions approximate” 去掉了，位置是推断的近似值时每个标记的提示里仍会写明（`scripts/verify_browser.py` 里对这行文字的检查也相应改成检查地图）。对话栏里的对话都存在账号里，重新登录还在；对话栏底部也有语言切换。
- **卡片 / 详情**：不再显示 0–100 分。显示排名、状态（符合条件 / 待确认）、待确认时还缺哪些条件、月租、MRT、到学院的通勤时间、链接检查结果。
- **收藏**：就是 agent 在这段对话里的候选清单，agent 也看得到，可以直接让它比较。比较表只是展示。
- **个人资料**：学院直接保存到账号；条件表单只把改动过的字段写成一条消息发给 agent（例如 “Please update my search criteria: a monthly rent of at most SGD 2,000.”），然后回到首页看回复。区只能选一个，因为 agent 一次只按一个区搜索。
- **Recommendations / Rental Map / Conversation History / Evaluation**：文件都在，连后端时不加载（它们用的是离线演示的打分），离线模式下照旧可用，留给你之后接。

## 文件

新增：

- `adapters/backend_client.py`：调后端的全部接口（标准库 HTTP、Bearer 令牌、回复用 Server-Sent Events）。
- `domain/criteria.py`：agent 保存的条件 ↔ 表单的值，以及把表单改动写成消息。
- `content/i18n.py`、`content/labels.py`：界面语言（`t(英文, 中文)`）和数据值的中文。
- `state/cookies.py`：记住登录的 cookie。
- `tests/test_criteria.py`：条件消息的测试。
- 仓库根目录 `tests/test_frontend_client.py`：用 `backend_client.py` 调 `server.py`，两边接口对不上时这里会失败。

修改：

- `adapters/configuration.py`：默认连后端，`AGENT_MODE=mock` 离线；读 `app/.env`。`RENTAL_DATA_MODE` 不再使用。
- `adapters/http_rental_api.py`、`http_agent_api.py`：原来的占位换成真正的实现。
- `domain/models.py`：`Recommendation.score` 可以为空，加了 `facts`（agent 给的这套房源的信息）；`AgentResponse` 加了 `steps`、`shortlist`、`preview`。
- `state/session_store.py`：登录后从后端加载对话、打开时读取消息和条件、收藏走后端、退出时作废令牌。
- `streamlit_app.py`：cookie 自动登录、只路由三个主页面（离线时加上另外四个）、错误提示按界面语言。
- `views/auth.py`、`home.py`、`profile.py`、`favorites.py`，`components/*`：上面说的行为，以及界面文字的中英文。
- `domain/provenance.py`：`display()` 只把 `fully_furnished` 这类编码转成文字，站名、地址、日期原样显示（之前会被 `capitalize()` 改成 “Cc26 pasir panjang mrt”）。
- `domain/location.py`：位置说明的中英文。
- `tests/conftest.py`：设 `AGENT_MODE=mock`，你原来的测试都没改。
- `README.md`、`API_CONTRACT.md`：按现在的接口重写了相关部分。

没动：`data/*`、`domain/recommendation.py`、`adapters/static_rental_api.py`、`mock_agent_api.py`、`backend_mapper.py`、另外四个页面、`scripts/verify_browser.py`、`UX_HANDOFF.md`、`FILE_MANIFEST.md`（后两份描述的是离线演示）。

## 需要知道的

- 记住登录原来打算用 `extra-streamlit-components` 的 CookieManager，但它每次读写 cookie 都会让页面重跑一遍，正在显示的 agent 回复会被打断，所以改用 Streamlit 自带的 `components.html` 写 cookie。`pyproject.toml` 里的 `extra-streamlit-components` 用不到了，可以 `uv remove --project app extra-streamlit-components`。这个 cookie 页面脚本读得到（不是 HttpOnly），是演示项目可以接受的取舍。
- agent 回复时点别的按钮会让页面重跑、打断显示，但后端会把这一轮做完；下次页面运行时会从后端重新读这段对话。还没等到回复时，对话里会提示并给一个 Refresh 按钮。
- agent 按每条消息本身的语言回复（中文消息回中文），界面语言只在消息看不出语言时使用（例如只发了 `1000`）。
- 聊天消息显示前会把 `$` 转义（否则 Streamlit 会把 “S$2,999 … S$3,100” 当成数学公式），并保留换行（agent 的回复每套房源的月租、MRT、通勤各占一行）。
- 卡片上的“待确认的条件”和链接说明是 agent 搜索那一轮的语言，切换语言后要等下一次搜索才会变。
- 我这边装不了真的 Streamlit，页面流程是用一个简化的替身跑过的；请在本地跑一遍 `uv run --project app pytest app/tests`，再连后端实际点一遍。

## 2026-10-10：租期和费用

房源数据换成了 10/9 的新版 `rental_data_v2.csv`（327 套，多了 `lease_term` 租期一列；`removed_listings.csv` 266 条）。

- **注册 / 个人资料**：连后端时多了一个 “Lease length you will sign / 打算签多久的租约” 下拉（不限、6 个月、1 年、2 年），和其他条件一样，改动作为一条消息发给 agent（例如 “Please update my search criteria: a 6-month lease.”）。`RentalRequirements` 加了 `lease_months`（默认 `None`），`domain/criteria.py` 加了对应的文字。离线演示不显示这个字段，因为演示打分不按租期筛选。
- **卡片 / 详情**：显示 “Lease: at least 2 years / 租期：至少 2 年”（`components/listing_card.py` 的 `lease_text()`，文字在 `content/i18n.py` 的 `lease_term_label()`），没写租期的显示“未注明”。
- **聊天**：用户问费用时，agent 的回复里会有一段固定格式的费用明细，不需要前端处理。
- **因为数据更新改的测试**：`test_source_loader.py`（327 套、移除 266 条、推断坐标 11 个）、`test_v2_snapshot.py`（327）、`test_data_contract.py`（家具未注明 1 套）、`test_recommendation.py`（改为找一套家具未注明的房源，而不是固定用第一套）。离线演示的 `data/demo_enrichment.py` 里 500253628 已下架，换成 500252277，`test_app_smoke.py` 里选这套房源的地方同步改了。
- 我这边只跑了不需要真 Streamlit 的测试（40 个里 39 个通过，剩下一个缺 `folium`）；`test_app_smoke.py` 请在本地跑一遍。

## 2026-10-10：后端只用 PostgreSQL

前端代码没有改，离线演示（`AGENT_MODE=mock`）也不受影响。连后端时要注意：

- 后端的房源、账号和对话现在都在 PostgreSQL 里，第一次要在根目录运行一次 `.\.venv\Scripts\python.exe .\setup_database.py`，再启动 `server.py`。PostgreSQL 没开时后端启动不了，会直接说明要检查什么。
- 以前的 `sessions.sqlite` 不再使用，里面的账号没有搬过来：演示账号（例如 `demo_user`）要在应用里用同样的用户名和密码重新注册一次，`app/.env` 不用改。
- 聊天中途数据库断开时，这一轮的错误消息是“数据库暂时连不上，请稍后再试。”（流里的 `error` 事件），其他接口返回 HTTP 503 和同样的 `detail`；前端照原来的方式显示错误即可，下一条消息会自动重连。
