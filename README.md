# 🎬 TicToc — Telegram Video Downloader & Processor Bot

A modern, fully-asynchronous, production-ready Telegram bot that **downloads
TikTok videos by link (without the TikTok watermark)** — and YouTube,
Instagram and hundreds of other sources too — then, on request, **uniquifies**
them or adds your own **text watermark**.

Built with a clean, modular architecture on top of
[**aiogram 3**](https://docs.aiogram.dev/) and
[**yt-dlp**](https://github.com/yt-dlp/yt-dlp). **ffmpeg is bundled** via
`imageio-ffmpeg` and the watermark font ships with the package, so the bot runs
anywhere — no system dependencies to install.

> ⚠️ **Use responsibly.** Only download and process content you have the rights
> to. The maintainers are not responsible for misuse.

---

## ✨ Features

| Feature | Description |
| --- | --- |
| 📥 **TikTok download (no watermark)** | Send a TikTok link (incl. `vm.`/`vt.tiktok.com` short links) and get the clean, watermark-free video. YouTube, Instagram and hundreds more also work via `yt-dlp`. |
| 🖼 **TikTok photo slideshows** | Image-only posts are downloaded too — all pictures are sent back as Telegram album(s), plus the background track as an audio file. |
| 🎲 **Uniquify** | Subtle, randomised transformations (stripped metadata, micro crop/scale, colour tweaks, faint noise, micro speed change, fresh timestamp, full re-encode) so the result differs from the source. |
| 💧 **Watermark** | Renders your text with Pillow and overlays it in the bottom-right corner (works without ffmpeg's `drawtext`). |
| ⚡ **Fully async** | Non-blocking downloads (`asyncio.to_thread`) and ffmpeg jobs (`asyncio` subprocesses) with a concurrency semaphore. |
| 🚦 **Rate limiting** | Per-user throttling middleware. |
| 🧱 **Self-contained** | Bundled ffmpeg + font; in-memory or Redis FSM storage. |
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
├── assets/                # Bundled watermark font (DejaVuSans-Bold.ttf)
├── handlers/
│   ├── common.py          # /start, /help, /cancel
│   ├── download.py        # link -> download -> action menu (+ slideshows)
│   └── processing.py      # original / uniquify / watermark flows
├── services/
│   ├── downloader.py      # yt-dlp wrapper (async)
│   ├── processor.py       # ffmpeg uniquify + Pillow/overlay watermark (async)
│   └── session_store.py   # active-video-per-chat tracking + cleanup
├── middlewares/
│   └── throttling.py      # per-user rate limiting
└── utils/
    ├── ffmpeg.py          # resolve system ffmpeg, else imageio-bundled binary
    └── helpers.py         # URL/platform detection, formatting, file cleanup
```

**Request flow**

1. User sends a link → `download.py` calls `VideoDownloader.download()`
   (or downloads a photo slideshow).
2. The file is saved and registered in `SessionStore`; an inline action menu is shown.
3. User picks an action → `processing.py` runs `VideoProcessor` and sends the result.
4. Transient outputs are cleaned up automatically.

---

## ☁️ Deploy

**Bothost.ru** (RU bot hosting, deploy from Git) — see
**[DEPLOY_BOTHOST.md](DEPLOY_BOTHOST.md)** for the step-by-step guide. The bot
works on Bothost's Python auto-build out of the box (ffmpeg is bundled). Ships
`main.py`, `Procfile`, `runtime.txt`.

---

## 🛠 Local development

Requires only **Python 3.11+** (ffmpeg comes bundled via pip).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# minimal config
export BOT_TOKEN=123:ABC   # from @BotFather
export STORAGE_TYPE=memory

python -m app
```

> A system `ffmpeg` on PATH is used automatically if present (full build);
> otherwise the bundled `imageio-ffmpeg` binary is used.

---

## ⚙️ Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Description |
| --- | --- | --- |
| `BOT_TOKEN` | — | **Required.** Telegram bot token from @BotFather. |
| `ADMIN_IDS` | _empty_ | Comma-separated admin user IDs. |
| `STORAGE_TYPE` | `memory` | `memory` or `redis` (FSM storage). |
| `REDIS_DSN` | `redis://localhost:6379/0` | Redis connection string (also accepts `REDIS_URL`). |
| `DOWNLOAD_DIR` | `downloads` | Temp media directory. |
| `MAX_FILE_SIZE_MB` | `50` | Max upload size (Telegram Bot API limit is 50 MB). |
| `MAX_DURATION_SECONDS` | `1800` | Reject videos longer than this (`0` = no limit). |
| `THROTTLE_RATE` | `2.0` | Min seconds between heavy actions per user. |
| `MAX_CONCURRENT_JOBS` | `2` | Max simultaneous ffmpeg jobs. |
| `WATERMARK_FONT` | bundled DejaVu Sans Bold | TTF font path for watermarks. |
| `LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`. |

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
