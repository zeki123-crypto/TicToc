# 🎬 TicToc — Telegram Video Downloader & Processor Bot

A modern, fully-asynchronous, production-ready Telegram bot that **downloads
TikTok videos by link (without the TikTok watermark)** — and YouTube,
Instagram and hundreds of other sources too — then, on request, **uniquifies**
them or adds your own **text watermark**.

Built with a clean, modular architecture on top of
[**aiogram 3**](https://docs.aiogram.dev/), [**yt-dlp**](https://github.com/yt-dlp/yt-dlp)
and **ffmpeg**.

> ⚠️ **Use responsibly.** Only download and process content you have the rights
> to. The maintainers are not responsible for misuse.

---

## ✨ Features

| Feature | Description |
| --- | --- |
| 📥 **TikTok download (no watermark)** | Send a TikTok link (incl. `vm.`/`vt.tiktok.com` short links) and get the clean, watermark-free video. YouTube, Instagram and hundreds more also work via `yt-dlp`. |
| 🖼 **TikTok photo slideshows** | Image-only posts are downloaded too — all pictures are sent back as Telegram album(s), plus the background track as an audio file. |
| 🎲 **Uniquify** | Subtle, randomised transformations (stripped metadata, micro crop/scale, colour tweaks, faint noise, micro speed change, fresh timestamp, full re-encode) so the result differs from the source. |
| 💧 **Watermark** | Burns a semi-transparent text watermark into the bottom-right corner. |
| ⚡ **Fully async** | Non-blocking downloads (`asyncio.to_thread`) and ffmpeg jobs (`asyncio` subprocesses) with a concurrency semaphore. |
| 🚦 **Rate limiting** | Per-user throttling middleware. |
| 🧱 **Scalable** | Redis-backed FSM storage, stateless handlers, Docker-ready. |
| 🪵 **Structured logging** | `structlog` for clean, queryable logs. |

---

## 🏗 Architecture

```
app/
├── __main__.py            # Entry point (python -m app)
├── bot.py                 # Bot/Dispatcher factory, DI wiring, lifecycle
├── config.py              # Pydantic settings (env-driven)
├── logging_config.py      # structlog setup
├── texts.py               # User-facing messages (RU)
├── states.py              # FSM states
├── keyboards.py           # Inline keyboards + callback data
├── handlers/
│   ├── common.py          # /start, /help, /cancel
│   ├── download.py        # link -> download -> action menu
│   └── processing.py      # original / uniquify / watermark flows
├── services/
│   ├── downloader.py      # yt-dlp wrapper (async)
│   ├── processor.py       # ffmpeg uniquify + watermark (async)
│   └── session_store.py   # active-video-per-chat tracking + cleanup
├── middlewares/
│   └── throttling.py      # per-user rate limiting
└── utils/
    └── helpers.py         # URL extraction, formatting, file cleanup
```

**Request flow**

1. User sends a link → `download.py` calls `VideoDownloader.download()`.
2. The file is saved and registered in `SessionStore`; an inline action menu is shown.
3. User picks an action → `processing.py` runs `VideoProcessor` and sends the result.
4. Transient outputs are cleaned up automatically.

---

## ☁️ Deploy

- **Bothost.ru (RU bot hosting, free tier, deploy from Git):** see
  **[DEPLOY_BOTHOST.md](DEPLOY_BOTHOST.md)**. Use the **Dockerfile** build so
  ffmpeg is available. Ships `main.py`, `Procfile`, `runtime.txt`.
- **VPS (Hetzner / any Ubuntu server) — most reliable 24/7:**
  see **[DEPLOY_VPS.md](DEPLOY_VPS.md)**. One-command Docker setup
  (`deploy/setup.sh`), update script (`deploy/deploy.sh`) and an optional
  systemd unit.
- **Railway (PaaS, deploy from GitHub):** see **[DEPLOY.md](DEPLOY.md)**.
  Ships `railway.json`; the bot auto-detects Railway's `REDIS_URL`.

---

## 🚀 Quick start (Docker, recommended)

```bash
# 1. Configure
cp .env.example .env
#    -> set BOT_TOKEN (from @BotFather)

# 2. Launch bot + Redis
docker compose up -d --build

# 3. Watch logs
docker compose logs -f bot
```

That's it — open Telegram and send your bot a video link.

---

## 🛠 Local development

Requires **Python 3.11+** and **ffmpeg** installed on your system.

```bash
# install ffmpeg (Debian/Ubuntu)
sudo apt-get install -y ffmpeg fonts-dejavu-core

# python deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# configure
cp .env.example .env        # set BOT_TOKEN; set STORAGE_TYPE=memory for no Redis

# run
python -m app
```

A `Makefile` provides shortcuts: `make install`, `make run`, `make up`,
`make down`, `make logs`, `make clean`.

---

## ⚙️ Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Description |
| --- | --- | --- |
| `BOT_TOKEN` | — | **Required.** Telegram bot token from @BotFather. |
| `ADMIN_IDS` | _empty_ | Comma-separated admin user IDs. |
| `STORAGE_TYPE` | `memory` | `memory` or `redis` (FSM storage). |
| `REDIS_DSN` | `redis://localhost:6379/0` | Redis connection string. |
| `DOWNLOAD_DIR` | `downloads` | Temp media directory. |
| `MAX_FILE_SIZE_MB` | `50` | Max upload size (50 MB via Bot API; up to 2000 MB with a local Bot API server). |
| `MAX_DURATION_SECONDS` | `1800` | Reject videos longer than this (`0` = no limit). |
| `THROTTLE_RATE` | `2.0` | Min seconds between heavy actions per user. |
| `MAX_CONCURRENT_JOBS` | `2` | Max simultaneous ffmpeg jobs. |
| `WATERMARK_FONT` | DejaVu Sans Bold | TTF font path for text watermarks. |
| `LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`. |

---

## 📈 Scaling notes

- **State** lives in Redis (`STORAGE_TYPE=redis`), so the bot can run multiple
  instances behind Telegram's long-polling or a webhook.
- **Heavy work** (download + ffmpeg) is bounded by `MAX_CONCURRENT_JOBS` to
  protect CPU; raise it on bigger machines.
- For files >50 MB, run a
  [local Bot API server](https://core.telegram.org/bots/api#using-a-local-bot-api-server)
  and bump `MAX_FILE_SIZE_MB`.

---

## 🧾 Commands

| Command | Description |
| --- | --- |
| `/start` | Welcome message & instructions |
| `/help` | Usage help |
| `/cancel` | Cancel the current action and clear state |

---

## 📜 License

MIT — see `LICENSE`. Provided as-is; respect the terms of service of any
platform you download from.
