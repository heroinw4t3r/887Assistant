# 887Assistant

Многофункциональный Telegram-бот:

- 📁 **Хранение файлов** — загрузка, список, скачивание, переименование, удаление, поиск.
- 📅 **Календарь** — события по дням + синхронизация с телефоном через `.ics`/`webcal`.
- 🤖 **ИИ-чат** — общение с нейросетью (Kimi от Moonshot по умолчанию, с бесплатными альтернативами).
- 🎮 **FACEIT ники** — проверка доступности никнеймов (одиночная/массовая, все 3-символьные).

> Архитектура модульная: каждый блок — отдельный пакет в `app/modules/*` с собственным
> aiogram-роутером и сервис-слоем. Общий контракт данных — в `app/db/models.py`.

## Возможности

(заполняется по мере готовности модулей — см. раздел каждого модуля ниже)

## Быстрый старт

```bash
git clone <repo> && cd 887assistant
cp .env.example .env          # заполните TELEGRAM_BOT_TOKEN и остальные ключи
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

Или через Docker:

```bash
cp .env.example .env          # заполните ключи
docker compose up --build
```

## Переменные окружения

См. `.env.example`. Ключевые:

| Переменная | Назначение |
|---|---|
| `TELEGRAM_BOT_TOKEN` | токен бота от [@BotFather](https://t.me/BotFather) |
| `DATABASE_URL` | SQLite (по умолчанию) или PostgreSQL (`postgresql+asyncpg://…`) |
| `FILE_STORAGE_PATH` | каталог для хранения файлов |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` | провайдер и ключ ИИ-чата |
| `FACEIT_API_KEY` | ключ FACEIT Data API ([developers.faceit.com](https://developers.faceit.com)) |
| `BASE_URL` | публичный URL для подписки на календарь (`.ics`/`webcal`) |

### Где взять ключи

- **Telegram:** [@BotFather](https://t.me/BotFather) → `/newbot`.
- **FACEIT:** [developers.faceit.com](https://developers.faceit.com) → App Studio → API Keys → **Server side**.
- **Kimi / Moonshot:** платформа Moonshot AI → API keys (`https://api.moonshot.ai/v1`).
- **Бесплатные альтернативы ИИ:** Google Gemini (AI Studio), Groq, OpenRouter (free-модели).

## Тесты и линт

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

## Модули

### 📁 Файлы
_TODO (subagent-1)._

### 📅 Календарь и синхронизация
_TODO (subagent-2)._ Здесь будет описание `.ics`/`webcal`-подписки и её ограничений
(Google Calendar / Apple Calendar — read-only), а также опционального Google Calendar API.

### 🤖 ИИ-чат
_TODO (subagent-3)._ Провайдер по умолчанию, как получить ключ, бесплатные альтернативы и их лимиты.

### 🎮 FACEIT ники
_TODO (subagent-4)._ Здесь будут зафиксированы результаты ресёрча по правилам смены ника
и IDLE-аккаунтам, а также описание точности проверки.

## Лицензия

MIT (если не указано иное).
