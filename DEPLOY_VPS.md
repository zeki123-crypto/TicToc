# 🖥 Деплой TicToc на VPS (Hetzner Cloud и любой Ubuntu-сервер)

Надёжный способ держать бота онлайн 24/7. Инструкция под **Hetzner Cloud**, но
подходит для любого VPS с Ubuntu/Debian (Aeza, Timeweb, DigitalOcean, Vultr…).

> Время: ~15 минут. Стоимость Hetzner CX22 ≈ €4.5/мес.

---

## Шаг 1. Создать сервер

1. Зарегистрируйся: https://accounts.hetzner.com/signUp
2. **Cloud → New Project → Add Server**.
3. Параметры:
   - **Location:** любой (Falkenstein / Nuremberg / Helsinki)
   - **Image:** **Ubuntu 24.04**
   - **Type:** **CX22** (2 vCPU / 4 ГБ) — с запасом для ffmpeg
   - **SSH key:** добавь свой публичный ключ (рекомендуется) или задай пароль
4. **Create & Buy now**. Через ~30 секунд получишь **IP-адрес** сервера.

---

## Шаг 2. Подключиться по SSH

```bash
ssh root@ВАШ_IP
```

---

## Шаг 3. Установить Docker (один скрипт)

Клонируй репозиторий и запусти установщик:

```bash
git clone https://github.com/zeki123-crypto/TicToc.git
cd TicToc
git checkout claude/telegram-video-download-bot-gab72t   # или main, если уже смержено
bash deploy/setup.sh
```

Скрипт поставит Docker + Compose и включит автозапуск при перезагрузке.

---

## Шаг 4. Настроить токен

```bash
cp .env.example .env
nano .env
```

Заполни как минимум:

```ini
BOT_TOKEN=твой_токен_от_BotFather
STORAGE_TYPE=redis
REDIS_DSN=redis://redis:6379/0
```

(остальное можно оставить по умолчанию). Сохрани: `Ctrl+O`, `Enter`, `Ctrl+X`.

> Redis уже включён в `docker-compose.yml` — отдельный сервер ставить не нужно.

---

## Шаг 5. Запуск

```bash
docker compose up -d --build
```

Проверь логи:

```bash
docker compose logs -f bot
```

Должно появиться:

```
storage.redis  dsn=redis://redis:6379/0
bot.started    username=<твой_бот>  id=...
```

Открывай бота в Telegram, жми **Start** и кидай ссылку на TikTok 🎉

---

## Автозапуск и устойчивость

- В `docker-compose.yml` стоит `restart: unless-stopped` — бот сам поднимется
  после краша и после **перезагрузки сервера** (Docker стартует на буте).
- Дополнительный systemd-юнит (по желанию) — в `deploy/tictoc.service`.

---

## Обновление бота

```bash
cd ~/TicToc
bash deploy/deploy.sh
```

Скрипт подтянет свежий код, пересоберёт и перезапустит контейнеры.

---

## Полезные команды

| Команда | Что делает |
| --- | --- |
| `docker compose ps` | статус контейнеров |
| `docker compose logs -f bot` | живые логи бота |
| `docker compose restart bot` | перезапустить бота |
| `docker compose down` | остановить всё |
| `docker compose up -d --build` | запустить/обновить |

---

## Безопасность (рекомендуется)

```bash
# простой фаервол: оставить только SSH
ufw allow OpenSSH
ufw enable
```

Боту не нужны открытые порты (он сам ходит к Telegram), так что наружу ничего
публиковать не требуется.

---

## Частые вопросы

**`bot.started` не появляется, ошибка токена**
→ Проверь `BOT_TOKEN` в `.env` (без пробелов) и `docker compose up -d --build`.

**Видео не отправляется, «слишком большое»**
→ Лимит Telegram 50 МБ. Для TikTok обычно ок. Для больших — нужен self-hosted
Bot API сервер.

**Сервер перезагрузился — бот сам поднялся?**
→ Да, благодаря `restart: unless-stopped`. Проверить: `docker compose ps`.
