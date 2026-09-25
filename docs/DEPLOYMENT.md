# Deployment

<p align="center">
  <a href="../README.md"><img alt="YaeMiko wordmark" src="assets/wordmark-dark.svg" width="420"></a>
</p>

Back to [README](../README.md).

## Contents

- [Before you start](#before-you-start)
- [Pick a platform](#pick-a-platform)
- [Render](#render)
- [Railway](#railway)
- [Heroku](#heroku)
- [VPS](#vps)
- [Docker anywhere](#docker-anywhere)
- [Troubleshooting](#troubleshooting)

## Before you start

YaeMiko needs four things. Gather them first, because every platform below asks for the same set.

| What | Where to get it | Notes |
| --- | --- | --- |
| `API_ID` and `API_HASH` | [my.telegram.org/apps](https://my.telegram.org/apps) | Create an application, keep both values |
| `TOKEN` | [@BotFather](https://t.me/BotFather) | Send `/newbot`, copy the token |
| `OWNER_ID` | Your Telegram user ID | [userid.bot](https://t.me/userid_bot) reports it |
| `MONGO_DB_URI` | [MongoDB Atlas](https://www.mongodb.com/atlas) | The free M0 tier is enough. Copy the SRV string |
| PostgreSQL connection | Provided by the platform, or your own | Free tier is enough |

Two more IDs come from the group you want the bot to log into:

- `EVENT_LOGS`: a channel ID where the bot posts events.
- `MESSAGE_DUMP`: a chat ID used as a dump.
- `SUPPORT_CHAT` and `SUPPORT_ID`: your support group username and numeric ID.

Get numeric IDs by adding the bot to the group and sending `/id`, or by forwarding a message to
[@userid_bot](https://t.me/userid_bot).

A full list with defaults: [CONFIGURATION.md](CONFIGURATION.md).

## Pick a platform

| Platform | Cheapest tier | Persistent state | Blueprint in this repo | Difficulty |
| --- | --- | --- | --- | --- |
| [Render](https://render.com) | Paid worker, about 7 USD per month | Ephemeral disk | [`render.yaml`](../render.yaml) | Easiest |
| [Railway](https://railway.app) | Trial credit, then usage based | Ephemeral, volumes available | [`railway.json`](../railway.json) | Easy |
| [Heroku](https://heroku.com) | Free dynos discontinued, about 5 USD per month | Ephemeral | [`app.json`](../app.json) | Easy |
| [VPS](https://www.digitalocean.com/pricing/droplets) | From 4 USD per month | Full disk | systemd unit below | Medium |
| Any Docker host | Host dependent | Host dependent | [`Dockerfile`](../Dockerfile) | Medium |

YaeMiko is a long running process, not an HTTP server. It does not listen on a port, so on Render it
must be a background worker, never a web service. A web service would sit behind health checks
waiting for a port that never opens.

## Render

Render builds the [Dockerfile](../Dockerfile) and runs the process as a background worker.

### Step 1: open the Blueprint

Go to [dashboard.render.com/blueprint/new](https://dashboard.render.com/blueprint/new), connect
`bisug/YaeMiko-V2`, and Render will read [`render.yaml`](../render.yaml) from the repository root.

### Step 2: pick a plan

Render Free instances cover web services, Postgres and Key Value only, so the worker needs a paid
plan. `render.yaml` already requests `0.5c-512mb`, the smallest one at roughly 7 USD per month.
The included Postgres uses the Free plan, which is limited to 1 GB and expires after 30 days, so
upgrade it if you expect to keep data.

### Step 3: fill the prompts

Render asks for every variable marked `sync: false`. Paste the values you gathered:

```text
API_ID, API_HASH, TOKEN, OWNER_ID,
SUPPORT_CHAT, SUPPORT_ID, EVENT_LOGS, MESSAGE_DUMP,
MONGO_DB_URI, GEMINI_API_KEY (optional),
DEV_USERS, DRAGONS, DEMONS, WOLVES, TIGERS, BL_CHATS (optional, space separated IDs)
```

Leave the optional ones empty. `DATABASE_URL` is wired automatically from the Postgres instance, so
never type it by hand.

### Step 4: deploy

Press Apply. The first build installs every wheel in `requirements.txt`, so allow 5 to 10 minutes.
When the deploy log shows `Mikobot is starting`, send `/start` to the bot.

### Manual alternative

If you prefer the dashboard, choose New, then Background Worker, set Runtime to Docker, leave the
Dockerfile path as `./Dockerfile`, and copy the environment variables from
[CONFIGURATION.md](CONFIGURATION.md). Do not use a free web service, it will never pass health checks.

## Railway

Railway also builds the [Dockerfile](../Dockerfile). Configuration lives in
[`railway.json`](../railway.json).

### Step 1: create the project

At [railway.app/new](https://railway.app/new), choose Empty Project, then Deploy from GitHub repo and
select `bisug/YaeMiko-V2`. Railway detects the Dockerfile automatically and the log will say
`Using detected Dockerfile`.

### Step 2: add PostgreSQL

In the project canvas, click New, then Database, then PostgreSQL. Railway injects the connection
string as `DATABASE_URL`, which YaeMiko already reads, so no extra variable is needed.

### Step 3: add the environment variables

Open the service, then Variables, and add:

```text
ENV              = True
API_ID           = <from my.telegram.org>
API_HASH         = <from my.telegram.org>
TOKEN            = <from BotFather>
OWNER_ID         = <your numeric id>
MONGO_DB_URI     = <Atlas SRV string>
DB_NAME          = MikoDB
EVENT_LOGS       = <-100...>
MESSAGE_DUMP     = <-100...>
SUPPORT_CHAT     = <group username>
SUPPORT_ID       = <-100...>
DEL_CMDS         = True
STRICT_GBAN      = True
LOGGER           = True
GEMINI_API_KEY   = <optional>
```

### Step 4: deploy

Railway redeploys automatically. Watch the deploy log for `Mikobot is starting`.

### Notes

- Railway MongoDB is available as a plugin, but any MongoDB works. Atlas M0 is free and reachable
  from anywhere, which is the simpler path.
- The container filesystem is ephemeral. `ptb_persistence.pickle` is recreated empty on every
  deploy, so moderation state that lives in `context.chat_data` resets. Attach a Railway volume
  mounted at `/root/Mikobot` if you want it to survive.
- `restartPolicyType` is `ON_FAILURE` with 10 retries, so a clean stop is respected but a crash loops.

## Heroku

The repository ships [`app.json`](../app.json), which declares the worker dyno, the PostgreSQL 16
addon, and every required variable.

<p align="center">
  <a href="https://dashboard.heroku.com/apps/new?template=https://github.com/bisug/YaeMiko-V2">
    <img src="https://www.herokucdn.com/deploy/button.svg" alt="Deploy to Heroku" width="220">
  </a>
</p>

[`heroku.yml`](../heroku.yml) pins the Docker build. [`Procfile`](../Procfile) declares
`worker: python -m Mikobot` for non Docker builds.

1. Create the Telegram application and the bot as described in
   [Before you start](#before-you-start).
2. Create a free [MongoDB Atlas](https://www.mongodb.com/atlas) cluster.
3. Press the deploy button and fill the prompted variables.
4. Confirm the dyno, then check the startup banner in the support chat.

## VPS

A VPS gives you the most control and the only setup that keeps a full filesystem. The steps below
work on Debian and Ubuntu.

### Step 1: create the server

Any provider works. Use Ubuntu 24.04 or Debian 12, at least 1 GB RAM, and a public IPv4 address.

### Step 2: install the system packages

```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y python3 python3-venv python3-pip git ffmpeg libgomp1 tmux
```

`ffmpeg` is needed for media features. `libgomp1` is needed by ONNX Runtime for the NSFW check.

### Step 3: create a dedicated user

Running the bot as root is unnecessary and risky.

```bash
sudo adduser --disabled-password --gecos "" yaemiko
sudo mkdir -p /home/yaemiko/YaeMiko
sudo chown -R yaemiko:yaemiko /home/yaemiko
```

### Step 4: install the code

```bash
sudo -u yaemiko -H git clone https://github.com/bisug/YaeMiko-V2.git /home/yaemiko/YaeMiko
cd /home/yaemiko/YaeMiko
sudo -u yaemiko -H python3 -m venv .venv
sudo -u yaemiko -H .venv/bin/pip install --upgrade pip
sudo -u yaemiko -H .venv/bin/pip install -r requirements.txt
```

### Step 5: write the configuration

```bash
cd /home/yaemiko/YaeMiko
sudo -u yaemiko -H vi .env
```

Press `I` to insert, type the variables, then press `Esc`, `:wq`, and `Enter` to save.

```dotenv
ENV=True
API_ID=123456
API_HASH=0123456789abcdef0123456789abcdef
TOKEN=123456:AAyourtokenhere
OWNER_ID=123456789

DATABASE_URL=postgresql://user:pass@localhost:5432/yaemiko
MONGO_DB_URI=mongodb+srv://user:pass@cluster.mongodb.net
DB_NAME=MikoDB

EVENT_LOGS=-1001234567890
MESSAGE_DUMP=-1001234567890
SUPPORT_CHAT=MySupportGroup
SUPPORT_ID=-1001234567890

DEL_CMDS=True
STRICT_GBAN=True
LOGGER=True
LOG_LEVEL=INFO
```

Keep the file readable only by its owner:

```bash
sudo -u yaemiko -H chmod 600 /home/yaemiko/YaeMiko/.env
```

### Step 6: install PostgreSQL locally

Atlas only covers MongoDB, so PostgreSQL has to come from somewhere.

```bash
sudo apt-get install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql
sudo -u postgres psql -c "CREATE USER yaemiko WITH PASSWORD 'choose-a-strong-password';"
sudo -u postgres psql -c "CREATE DATABASE yaemiko OWNER yaemiko;"
```

Use that password in `DATABASE_URL` in the `.env` file.

### Step 7: test the bot in the foreground first

```bash
cd /home/yaemiko/YaeMiko
sudo -u yaemiko -H .venv/bin/python -m Mikobot
```

Send `/start` to the bot. If it replies, stop the process with `Ctrl+C` and continue. If it does
not, the log already printed the reason, for example a bad `OWNER_ID` or an unreachable database.

### Step 8: run it as a service

```bash
sudo tee /etc/systemd/system/yaemiko.service > /dev/null <<'UNIT'
[Unit]
Description=YaeMiko Telegram bot
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=yaemiko
Group=yaemiko
WorkingDirectory=/home/yaemiko/YaeMiko
Environment=ENV=True
ExecStart=/home/yaemiko/YaeMiko/.venv/bin/python -m Mikobot
Restart=always
RestartSec=10
StandardOutput=append:/home/yaemiko/YaeMiko/Logs.txt
StandardError=append:/home/yaemiko/YaeMiko/Logs.txt

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now yaemiko
sudo systemctl status yaemiko
```

| Command | What it does |
| --- | --- |
| `sudo systemctl status yaemiko` | Shows whether it is running and the last log lines |
| `sudo systemctl restart yaemiko` | Applies a code or config change |
| `sudo systemctl stop yaemiko` | Stops the bot |
| `sudo journalctl -u yaemiko -f` | Follows the system journal |
| `tail -f /home/yaemiko/YaeMiko/Logs.txt` | Follows the file log |

### Step 9: update later

```bash
cd /home/yaemiko/YaeMiko
sudo systemctl stop yaemiko
sudo -u yaemiko -H git pull
sudo -u yaemiko -H .venv/bin/pip install -r requirements.txt
sudo systemctl start yaemiko
```

### Firewall

The bot only makes outbound connections, so no inbound port needs to be open. If you also run a web
service on the same box, open only the ports that service needs.

## Docker anywhere

The [Dockerfile](../Dockerfile) is a two stage build. The builder installs the wheels, and the
runtime stage is `python:3.14.7-slim` with `ffmpeg`, `curl` and `libgomp1`.

```bash
docker build -t yaemiko .
docker run -d --name yaemiko --restart unless-stopped --env-file .env yaemiko
```

`ENV` must be `True` inside the container, otherwise the bot reads `variables.py` instead of the
environment.

```bash
docker logs -f yaemiko     # follow the log
docker restart yaemiko     # apply a config change
docker stop yaemiko        # stop the bot
```

To run behind Docker Compose with a local PostgreSQL, add a `compose.yaml` next to the bot:

```yaml
services:
  bot:
    build: .
    restart: unless-stopped
    env_file: .env
    depends_on:
      - postgres
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: yaemiko
      POSTGRES_PASSWORD: change-me
      POSTGRES_DB: yaemiko
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
```

MongoDB still comes from Atlas, so `MONGO_DB_URI` stays in `.env`.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `TypeError: ... takes no keyword arguments` at import | A class keyword was added to a Telegram object subclass | Class keywords go to `__init_subclass__`. Pass `style` to the constructor instead |
| Bot starts, no replies | The bot is not an admin, or lacks the message content permission | Promote it and grant the permissions the module needs |
| `[PostgreSQL] Failed to connect` then exit | Bad `DATABASE_URL`, or the database is not reachable | Check the scheme is `postgresql://`, and that the host is public or on the same network |
| `Error in Mongodb` then exit | Bad `MONGO_DB_URI` | Copy the SRV string again, it usually ends with `?retryWrites=true&w=majority` |
| `Your OWNER_ID env variable is not a valid integer` | A stray space or text in the value | It must be digits only |
| Module does not appear in `/help` | `__mod_name__` missing, or the file ends in `.txt` | Set `__mod_name__` and rename the file to `.py` |
| Deploys fine, then restarts repeatedly | Crash loop, usually a database or token problem | Read the deploy log, the first traceback is the cause |
| `Could not find a version that satisfies the requirement` | Python version mismatch outside Docker | Use Python 3.14, check with `python3 --version` |
| Bot works locally, fails on the platform | `ENV` not set, so `variables.py` was read | Set `ENV=True` on the service |

Logs never contain your token. `RedactingFormatter` rewrites anything shaped like a bot token to
`bot<redacted>`, and the `httpx` loggers are pinned to `WARNING` for the same reason.
