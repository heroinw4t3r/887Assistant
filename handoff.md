# Handoff — 887Assistant

## Цель проекта
Telegram-бот «887Assistant» с четырьмя функциями:
1. **Файлы** — приём/список/скачивание/переименование/удаление/поиск; хранение в объектном хранилище.
2. **Календарь** — события по дням, напоминания, синхронизация с телефоном через персональную `.ics`/`webcal`-ленту (read-only).
3. **ИИ-чат** — диалог с контекстом; провайдер по умолчанию Kimi (Moonshot), бесплатные альтернативы (Gemini/Groq/OpenRouter); веб-поиск через Tavily.
4. **FACEIT** — проверка доступности ников: одиночная/несколько + массовый перебор всех 3-символьных (буквы a–z, цифры 0–9), копируемый список свободных.

Деплой: **Railway** (long polling, деплой с ветки `main`). Хранение: **Postgres** (метаданные) + **Storj EU** (S3-совместимое, файлы).

## Текущее состояние
- `main` содержит полностью рабочий проект (4 модуля + персистентность + UX). Тесты: ~83 зелёные, `ruff` чист, `import app.main` ок.
- **Уже влито в `main`:** базовый бот, персистентность (Postgres + Storj/S3), фикс `message_tracking`, поддержка Storj (`S3_FORCE_PATH_STYLE`), UX-переделка (inline-only, без эмодзи, командное меню), кэш FACEIT, веб-поиск Tavily.
- **Открытая ветка/PR (НЕ влита):** `cursor/storage-connectivity-check-cf7c` — стартовая проверка подключения хранилища (логирует активный backend и результат healthcheck). Ждёт слияния по команде пользователя.
- **Известный нюанс деплоя:** при редеплоях бывает транзиентный `TelegramConflictError` (кратковременное перекрытие старого и нового инстанса при long polling). Безопасно, само проходит; радикально решается переходом на webhooks (не реализовано).

## Файлы, над которыми идёт работа (последняя задача)
- `app/storage/base.py`, `app/storage/local.py`, `app/storage/s3.py`, `app/storage/__init__.py` — backend + `healthcheck()`, `check_storage()`, `storage_status()`.
- `app/main.py` — вызов `check_storage(settings, logger)` при старте.
- `tests/test_storage.py`.

Ключевые файлы проекта:
- `app/config.py` — все настройки из env; нормализация DSN (`postgres://` → `postgresql+asyncpg://`); поля `S3_*` (вкл. `S3_FORCE_PATH_STYLE`), `web_search_*`, `tavily_api_key`, `faceit_*`, `llm_*`.
- `app/db/models.py` — `User`, `FileFolder`, `StoredFile` (поля `storage_backend`, `storage_key`), `BotChatMessage`, `CalendarEvent`, `AISession`, `FaceitNickCache`.
- `app/db/base.py` — async engine (`sqlalchemy_url`, `pool_pre_ping`), `init_db`, `session_scope`.
- `app/storage/*` — подключаемое хранилище (`local` | `s3`/Storj).
- `app/modules/{files,calendar,ai,faceit}/` — модули (handlers/service + специфичные файлы).
- `app/bot/message_tracking.py` — трекинг сообщений (фикс bound-method уже внесён).

## Что изменилось (последние итерации)
- **Персистентность:** Postgres под метаданные + Storj EU (S3) под файлы; `S3_FORCE_PATH_STYLE=true` для Storj-шлюза.
- **ИИ веб-поиск:** дефолт переключён на **Tavily** (DuckDuckGo зависал на хостинге); поиск больше не вешает и не валит запрос; переиспользуемый `httpx`-клиент.
- **FACEIT:** персистентный кэш в БД (`faceit_nick_cache`); подняты `FACEIT_RATE_LIMIT_RPS=10`, `FACEIT_CACHE_TTL=86400`, `LLM_MAX_HISTORY_MESSAGES=50`.
- **UX:** убрана нижняя Reply-клавиатура и навязчивое сообщение «⌨️»; убраны все эмодзи; добавлено меню команд (`setMyCommands`: `/start`, `/menu`, `/help`); навигация через inline и редактирование сообщений.
- **Фикс багов:** `patch_bot_for_message_tracking` оборачивал НЕсвязанный метод класса `Bot` → терялся `chat_id` (`TypeError`), из-за чего ломались скачивание медиафайлов и напоминания календаря. Исправлено на bound-метод + идемпотентность + best-effort трекинг.
- **Диагностика хранилища:** добавлена стартовая проверка подключения (в открытой ветке).

## Что пробовал и что не сработало
- **DuckDuckGo** для веб-поиска ИИ — таймауты 10–40 c с дата-центровых IP Railway. Убрано из дефолта → Tavily.
- **Cloudflare R2** — пользователь использовать не может → выбран **Storj EU** (S3-совместимый, требует path-style).
- **Railway Volume** под файлы — на тарифе Hobby максимум 5 ГБ, под «10 ГБ» не подходит → объектное хранилище (Storj).
- **Текущая незакрытая проблема:** на сервере файлы, судя по всему, пишутся в **локальное (эфемерное)** хранилище, а не в Storj, хотя переменные Storj заданы. Гипотеза — «тихий откат» фабрики на `local` из-за несовпадения одной из переменных (`STORAGE_BACKEND`/`S3_BUCKET`/ключи) или неверного типа ключей Storj. Стартовая проверка добавлена именно для подтверждения по логам; **ещё не подтверждено** на сервере.

## Что сделать сразу после создания нового чата
1. Влить ветку `cursor/storage-connectivity-check-cf7c` в `main` (по команде пользователя) и дождаться деплоя, чтобы увидеть стартовые логи хранилища.
2. Запросить у пользователя список Railway-переменных (секреты замазать): `STORAGE_BACKEND`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET`, `S3_FORCE_PATH_STYLE`, и факт наличия `S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY` (и их тип).
3. По стартовым логам определить, активен ли backend `s3` или произошёл откат на `local` (лог укажет, какой переменной не хватает).
4. Проверить Storj-специфику: `STORAGE_BACKEND=s3`; `S3_ENDPOINT_URL=https://gateway.storjshare.io`; ключи — именно **S3 Credentials** (Access Key + Secret), а не Access Grant/API-key; bucket создан; доступ создан на **сателлите EU1**; `S3_REGION=eu1`; `S3_FORCE_PATH_STYLE=true`.
5. После фикса убедиться, что работают: скачивание файла, загрузка файла в Storj, напоминания календаря, ИИ-чат.

## Полезный контекст
- Репозиторий: `heroinw4t3r/887Assistant`. Деплой: Railway с `main`.
- Переменные окружения и инструкции — в `.env.example` и `README.md` (раздел «Развёртывание на Railway»).
- Локальная разработка: venv в `.venv`; `python -m pytest -q`, `ruff check .`.
- Только файлы до лимита скачивания Telegram (~20 МБ) загружаются в Storj; более крупные остаются «telegram-only» (пересылаются по `file_id`) — это ожидаемо.
- Правило чата: обращаться к пользователю по имени «887» в начале каждого ответа.
