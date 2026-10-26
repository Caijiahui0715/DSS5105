# 部署到 AWS

[English](README.md) | 中文

把网页版（Streamlit 前端 + agent 后端 + PostgreSQL）放到一台 AWS 服务器上，给老师、助教和组员用。本机开发不受影响：本机照旧用 `.env` 和 `README.zh-CN.md` 里的命令。

## 架构和费用

- 一台 EC2（新加坡区 ap-southeast-1，t4g.small：ARM、2 GB 内存），用 Docker Compose 跑 4 个容器：
  - `caddy`：对外只有它，开 80 和 443 端口，自动申请和续期 HTTPS 证书，把请求转给前端；
  - `frontend`：Streamlit（`app/`）；
  - `backend`：`server.py`，只有前端能访问；
  - `db`：PostgreSQL 17，数据存在服务器磁盘上的 Docker 卷里。
- 网址用 sslip.io：把 IP 的四段数字用 `-` 连起来，例如 `13-250-1-2.sslip.io`，不用买域名。
- 注册要填邀请码（`server.env` 里的 `REGISTRATION_CODE`）。登录不需要邀请码。
- 每月费用大约 $21：机器约 $15，公网 IP 约 $3.6，20 GB 磁盘约 $2，每日快照约 $1。新账号的免费额度可以抵扣。OpenAI 的费用另算，由线上专用 key 的每月上限兜底。

文件说明：

| 文件 | 作用 |
|---|---|
| `deploy.py` | 在你电脑上运行：打包代码，上传到服务器，再运行 `remote.sh` |
| `remote.sh` | 在服务器上运行：第一次装 Docker、加交换空间；每次放好代码，按需导入数据，构建并重启容器 |
| `docker-compose.yml` | 4 个容器怎么跑 |
| `backend.Dockerfile`、`frontend.Dockerfile` | 两个镜像怎么构建（各自的 `.dockerignore` 保证 `.env` 等不会进镜像） |
| `Caddyfile` | HTTPS 和转发 |
| `server.env.example` | 服务器设置的模板，复制成 `server.env` 再填 |

`deploy.py` 上传的代码就是 Git 会提交的那些文件：已跟踪的文件，加上 `.gitignore` 没排除的新文件。不包括 `output-final-delivery`、`tmp`、`Claude outputs`。如果有 `.env` 这类文件会被带上，脚本会直接停下。所以没提交的改动也会上线，不需要先提交。

## 第一次准备（一次就好）

### 1. AWS 账号、区域、费用提醒

1. 在 [aws.amazon.com](https://aws.amazon.com) 注册账号（要绑信用卡）。新账号可以选免费计划，有免费额度。
2. 登录控制台后，右上角的区域选 **Asia Pacific (Singapore) ap-southeast-1**，后面所有操作都在这个区域里做。
3. 设费用提醒：搜索并打开 **Budgets** → **Create budget** → 选 **Customize (advanced)** → **Cost budget**。
   - 金额填每月 **25 USD**；
   - 加两条提醒，都发到你的邮箱：**Actual** 达到 80%，以及 **Forecasted** 达到 100%。

### 2. OpenAI 线上专用 key

在 [platform.openai.com](https://platform.openai.com) 新建一个 project（比如 `dss5105-online`）：
- 在这个 project 的 limits 设置里，把每月预算设为 **$20**（具体名称以 OpenAI 后台为准）；
- 在这个 project 下新建 API key，填进下面第 5 步的 `server.env`。

不要用你本机开发用的 key。这样线上被人刷了，也不会超过上限。

### 3. 开机器

EC2 → **Launch instance**：

- Name：`dss5105`
- Application and OS Images：**Ubuntu Server 24.04 LTS**，Architecture 选 **64-bit (Arm)**
- Instance type：**t4g.small**
- Key pair：**Create new key pair**。类型 RSA，格式 `.pem`。下载后放到 `C:\Users\你的用户名\.ssh\dss5105.pem`。这个文件丢了就登录不了服务器，也不要发给别人。
- Network settings → **Create security group**，勾选：
  - **Allow SSH traffic from** → **My IP**（只有你现在的网络能连）；
  - **Allow HTTPS traffic from the internet**；
  - **Allow HTTP traffic from the internet**（申请证书要用，之后会自动跳转到 HTTPS）。
- Configure storage：**20 GiB gp3**
- 点 **Launch instance**。

### 4. 固定 IP 和每日快照

1. **固定 IP**：EC2 → **Elastic IPs** → **Allocate Elastic IP address** → **Allocate**。选中这个 IP → **Actions** → **Associate Elastic IP address** → 选 `dss5105` 这台机器 → **Associate**。记下这个 IP，例如 `13.250.1.2`，网址就是 `13-250-1-2.sslip.io`。
2. **每日快照**：EC2 → **Lifecycle Manager** → **Create lifecycle policy** → **EBS snapshot policy**。
   - Target resource types 选 **Instance**，target tags 填 `Name` = `dss5105`；
   - IAM role 用默认的；
   - Schedule：每 24 小时一次，保留 7 份（Retention type: Count, 7）；
   - 状态选 Enabled，然后创建。

### 5. 填 `deploy/server.env`

把 `deploy/server.env.example` 复制为 `deploy/server.env`，按里面的注释填。`SITE_ADDRESS` 填上一步的 sslip.io 地址，`SSH_KEY` 填 `.pem` 文件的完整路径。`DB_PASSWORD` 随便生成一串至少 20 位的字母和数字，例如在 PowerShell 里运行：

```powershell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
```

`server.env` 在 `deploy/.gitignore` 里，不会被提交。

## 第一次上线

在项目根目录运行（加 `--data` 会同时上传 `output-final-delivery` 并导入数据库）：

```powershell
.\.venv\Scripts\python.exe deploy\deploy.py --data
```

第一次要 10 分钟左右：装 Docker、构建两个镜像、导入房源和通勤时间。最后会打印容器状态和后端日志。后端日志里出现 `Uvicorn running` 就说明后端起来了。然后：

1. 打开 `https://你的地址.sslip.io`。证书要等半分钟左右，刚开始打不开就稍等再刷新。
2. 在“注册”里填邀请码，注册你自己的账号，发一条消息试试。
3. 把网址和邀请码发给老师和组员。

上线后先检查两件事：房源卡片上的照片能不能显示，以及链接检查的结果。这两项都要从 AWS 的 IP 访问外部网站，可能会被拦。被拦了不影响其他功能，把情况告诉 Claude 再改。

## 以后更新

- **改了代码**：`.\.venv\Scripts\python.exe deploy\deploy.py`。会先在后台构建新镜像，再替换正在运行的容器，网站只会中断几秒。
- **组里发了新版本的数据**：把新文件放进 `output-final-delivery`，再运行 `deploy.py --data`。
- **改了 `server.env`**（比如换邀请码、换 OpenAI key）：同样运行一次 `deploy.py`。
- 线上的账号、对话、收藏都在服务器的数据库里，更新代码和数据都不会动它们。

## 在服务器上查看

```powershell
ssh -i C:\Users\你的用户名\.ssh\dss5105.pem ubuntu@你的地址.sslip.io
```

登录后常用的命令：

```bash
sudo docker ps                                    # 4 个容器是否都在运行（STATUS 是 Up）
sudo docker logs --tail 100 dss5105-backend-1     # 后端日志；把 backend 换成 frontend、caddy、db 看其他容器
sudo docker logs -f dss5105-backend-1             # 持续看日志，Ctrl+C 退出
sudo docker restart dss5105-backend-1             # 重启后端
df -h /                                           # 磁盘还剩多少
```

## 出了问题

- **`deploy.py` 说连不上 SSH**：
  - 最常见的是你换了网络（宿舍、学校 Wi-Fi、热点的 IP 都不一样）。到 EC2 → Security Groups → 这台机器的安全组 → Edit inbound rules，把 SSH 那条的 Source 改成 **My IP**，保存后再运行。
  - 如果报 `UNPROTECTED PRIVATE KEY FILE`，在 PowerShell 里收紧密钥文件的权限：
    ```powershell
    icacls C:\Users\你的用户名\.ssh\dss5105.pem /inheritance:r
    icacls C:\Users\你的用户名\.ssh\dss5105.pem /grant:r "$($env:USERNAME):(R)"
    ```
  - 如果报 `REMOTE HOST IDENTIFICATION HAS CHANGED`（重建过机器，IP 没变），运行 `ssh-keygen -R 你的地址.sslip.io` 再部署。
- **网页打不开或证书报错**：
  - 刚上线等 1 分钟。
  - 还不行就看 `sudo docker logs dss5105-caddy-1`，确认安全组开了 80 和 443。
  - 确认 `SITE_ADDRESS` 和 Elastic IP 对得上。
- **网页提示连不上后端**：看后端日志。常见原因有三个：
  - 第一次部署没加 `--data`（脚本会提示）；
  - `server.env` 少填了必填项；
  - 改过 `DB_USER` 或 `DB_PASSWORD`。数据库第一次启动时就按当时的值建好了，之后改 `server.env` 不会改数据库，要改回原来的值。
- **Agent 回复出错**：看后端日志。多半是 OpenAI 的 key 不对，或者已经到了每月上限。
- **构建时提示磁盘满**：登录服务器运行 `sudo docker system prune`，清掉旧镜像和构建缓存。
- **要退回到前几天的数据**：EC2 → Snapshots 里有每日快照，可以用它恢复磁盘。这一步比较少见，做之前先问 Claude。

## 用完以后（学期结束）

按顺序做，免得继续扣费：

1. 想留着线上的账号和对话：EC2 → Volumes，选中这台机器的磁盘 → **Actions → Create snapshot**。
2. EC2 → Instances，选中 `dss5105` → **Instance state → Terminate instance**。
3. Elastic IPs → 选中那个 IP → **Release Elastic IP addresses**。没绑定到机器的 Elastic IP 也照样收费。
4. Lifecycle Manager 里删掉每日快照的策略；不需要的快照也删掉（每 GB 每月约 $0.05）。
5. OpenAI 后台删掉线上专用的 key。
