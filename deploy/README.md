# Deploying to AWS

English | [中文](README.zh-CN.md)

This puts the web version (the Streamlit front end, the agent backend and PostgreSQL) on an AWS server for the instructors, teaching assistants and the group to use. Local development is not affected: on your own computer, keep using `.env` and the commands in `README.md`.

## Architecture and cost

- One EC2 instance (Singapore region ap-southeast-1, t4g.small: ARM, 2 GB of memory), running 4 containers with Docker Compose:
  - `caddy`: the only one facing the internet, on ports 80 and 443; it gets and renews the HTTPS certificate automatically and passes requests on to the front end;
  - `frontend`: Streamlit (`app/`);
  - `backend`: `server.py`, reachable only from the front end;
  - `db`: PostgreSQL 17, with its data in a Docker volume on the server's disk.
- The address uses sslip.io: the IP's four numbers joined with `-`, for example `13-250-1-2.sslip.io`, so no domain needs to be bought.
- Registering needs an invite code (`REGISTRATION_CODE` in `server.env`). Signing in does not.
- It costs about $21 a month: about $15 for the machine, about $3.6 for the public IP, about $2 for the 20 GB disk and about $1 for daily snapshots. A new account's free credits can cover it. OpenAI costs come on top, capped by the monthly limit of a key used only for the online site.

The files:

| File | What it does |
|---|---|
| `deploy.py` | Runs on your computer: packs the code, uploads it to the server, then runs `remote.sh` |
| `remote.sh` | Runs on the server: the first time, installs Docker and adds swap space; each time, puts the code in place, imports the data when asked, and builds and restarts the containers |
| `docker-compose.yml` | How the 4 containers run |
| `backend.Dockerfile`, `frontend.Dockerfile` | How the two images are built (each one's `.dockerignore` keeps `.env` and the like out of the image) |
| `Caddyfile` | HTTPS and forwarding |
| `server.env.example` | The template for the server's settings; copy it to `server.env` and fill it in |

The code `deploy.py` uploads is exactly the files Git would commit: the tracked files, plus new files that `.gitignore` does not exclude. It leaves out `output-final-delivery`, `tmp` and `Claude outputs`. If a file such as `.env` would be included, the script stops right away. So changes that are not committed yet go online too, and nothing needs to be committed first.

## First-time preparation (once)

### 1. AWS account, region, cost alerts

1. Sign up at [aws.amazon.com](https://aws.amazon.com) (a credit card is needed). A new account can choose the free plan, which comes with free credits.
2. After signing in to the console, choose **Asia Pacific (Singapore) ap-southeast-1** as the region at the top right; do everything that follows in this region.
3. Set up cost alerts: search for and open **Budgets** → **Create budget** → choose **Customize (advanced)** → **Cost budget**.
   - Set the amount to **25 USD** a month;
   - Add two alerts, both sent to your email: **Actual** reaching 80%, and **Forecasted** reaching 100%.

### 2. An OpenAI key just for the online site

At [platform.openai.com](https://platform.openai.com), create a new project (for example `dss5105-online`):
- In this project's limits settings, set the monthly budget to **$20** (the exact names are as the OpenAI dashboard has them);
- Create an API key in this project and put it in `server.env` in step 5 below.

Don't use the key you develop with on your own computer. This way, even if someone abuses the online site, costs stay under the limit.

### 3. Start the machine

EC2 → **Launch instance**:

- Name: `dss5105`
- Application and OS Images: **Ubuntu Server 24.04 LTS**, with **64-bit (Arm)** as the Architecture
- Instance type: **t4g.small**
- Key pair: **Create new key pair**, type RSA, format `.pem`. After downloading it, put it at `C:\Users\<your user name>\.ssh\dss5105.pem`. Without this file you cannot sign in to the server, and don't send it to anyone.
- Network settings → **Create security group**, and tick:
  - **Allow SSH traffic from** → **My IP** (only your current network can connect);
  - **Allow HTTPS traffic from the internet**;
  - **Allow HTTP traffic from the internet** (needed to get the certificate; after that it redirects to HTTPS automatically).
- Configure storage: **20 GiB gp3**
- Click **Launch instance**.

### 4. Fixed IP and daily snapshots

1. **Fixed IP**: EC2 → **Elastic IPs** → **Allocate Elastic IP address** → **Allocate**. Select this IP → **Actions** → **Associate Elastic IP address** → choose the `dss5105` machine → **Associate**. Note the IP, for example `13.250.1.2`; the address is then `13-250-1-2.sslip.io`.
2. **Daily snapshots**: EC2 → **Lifecycle Manager** → **Create lifecycle policy** → **EBS snapshot policy**.
   - For Target resource types choose **Instance**, and for target tags enter `Name` = `dss5105`;
   - Use the default IAM role;
   - Schedule: once every 24 hours, keeping 7 (Retention type: Count, 7);
   - Set the status to Enabled, then create it.

### 5. Fill in `deploy/server.env`

Copy `deploy/server.env.example` to `deploy/server.env` and fill it in as its comments say. `SITE_ADDRESS` is the sslip.io address from the previous step, and `SSH_KEY` the full path of the `.pem` file. For `DB_PASSWORD`, generate any string of at least 20 letters and digits, for example by running this in PowerShell:

```powershell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
```

`server.env` is in `deploy/.gitignore`, so it is never committed.

## Going online the first time

Run this from the project root (`--data` also uploads `output-final-delivery` and imports it into the database):

```powershell
.\.venv\Scripts\python.exe deploy\deploy.py --data
```

The first time takes about 10 minutes: installing Docker, building the two images, and importing the listings and commute times. At the end it prints the containers' status and the backend's log. `Uvicorn running` in the backend's log means the backend is up. Then:

1. Open `https://<your address>.sslip.io`. The certificate takes about half a minute; if the page does not open at first, wait a little and refresh.
2. Enter the invite code under "Register", register your own account and send a message to try it.
3. Send the address and the invite code to the instructors and the group.

Once it is online, check two things first: whether photos show on the listing cards, and the results of the link checks. Both need to reach outside websites from an AWS IP, which may be blocked. Being blocked does not affect anything else; tell Claude what happens, and change it then.

## Updating later

- **After changing the code**: `.\.venv\Scripts\python.exe deploy\deploy.py`. It builds the new images in the background first and then replaces the running containers, so the site is down for only a few seconds.
- **When the group shares a new version of the data**: put the new files in `output-final-delivery`, then run `deploy.py --data`.
- **After changing `server.env`** (for example a new invite code or OpenAI key): run `deploy.py` once in the same way.
- The online accounts, conversations and favorites are in the server's database, and updating the code or the data does not touch them.

## Looking around on the server

```powershell
ssh -i C:\Users\<your user name>\.ssh\dss5105.pem ubuntu@<your address>.sslip.io
```

Commands often used once signed in:

```bash
sudo docker ps                                    # whether all 4 containers are running (STATUS is Up)
sudo docker logs --tail 100 dss5105-backend-1     # the backend's log; replace backend with frontend, caddy or db for the other containers
sudo docker logs -f dss5105-backend-1             # follow the log, Ctrl+C to stop
sudo docker restart dss5105-backend-1             # restart the backend
df -h /                                           # how much disk space is left
```

## When something goes wrong

- **`deploy.py` says it cannot connect over SSH**:
  - Most often your network has changed (a dorm, the school Wi-Fi and a hotspot all have different IPs). Go to EC2 → Security Groups → this machine's security group → Edit inbound rules, change the Source of the SSH rule to **My IP**, save, and run it again.
  - If it reports `UNPROTECTED PRIVATE KEY FILE`, tighten the key file's permissions in PowerShell:
    ```powershell
    icacls C:\Users\<your user name>\.ssh\dss5105.pem /inheritance:r
    icacls C:\Users\<your user name>\.ssh\dss5105.pem /grant:r "$($env:USERNAME):(R)"
    ```
  - If it reports `REMOTE HOST IDENTIFICATION HAS CHANGED` (the machine was rebuilt and kept its IP), run `ssh-keygen -R <your address>.sslip.io`, then deploy.
- **The page does not open, or there is a certificate error**:
  - Right after going online, wait a minute.
  - If that does not help, read `sudo docker logs dss5105-caddy-1`, and make sure the security group allows ports 80 and 443.
  - Make sure `SITE_ADDRESS` matches the Elastic IP.
- **The page says it cannot reach the backend**: read the backend's log. There are three common causes:
  - The first deployment was run without `--data` (the script points this out);
  - A required setting is missing from `server.env`;
  - `DB_USER` or `DB_PASSWORD` was changed. The database was set up with the values it had when it first started, and changing `server.env` later does not change the database, so change them back to the original values.
- **The agent's replies fail**: read the backend's log. Most likely the OpenAI key is wrong, or the monthly limit has been reached.
- **The build says the disk is full**: sign in to the server and run `sudo docker system prune` to clear old images and the build cache.
- **To go back to the data of a few days ago**: EC2 → Snapshots has the daily snapshots, from which the disk can be restored. This is rarely needed; ask Claude before doing it.

## When it is no longer needed (end of the semester)

Do these in order, so nothing keeps being charged:

1. To keep the online accounts and conversations: EC2 → Volumes, select this machine's disk → **Actions → Create snapshot**.
2. EC2 → Instances, select `dss5105` → **Instance state → Terminate instance**.
3. Elastic IPs → select that IP → **Release Elastic IP addresses**. An Elastic IP not attached to a machine is still charged.
4. Delete the daily snapshot policy in Lifecycle Manager, and delete snapshots you don't need (about $0.05 per GB per month).
5. Delete the online-only key in the OpenAI dashboard.
