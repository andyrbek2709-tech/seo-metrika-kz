# Навык: Telegram-бот-витрина спроса (KZ)

Telegram-бот, который по командам отдаёт аналитику конвейера проекта (съём спроса
Google KZ → кластеры → продуктовые идеи). Бот — тонкая обёртка: вся механика берётся
из существующих скриптов навыков `google-kwp-skill` и `product-discovery-skill`.

## Что делает

| Команда | Что делает | Источник |
|---|---|---|
| `/themes [N]` | Кластеры спроса по темам рынка (топ N тем) | `cluster_demand.cluster` |
| `/top [N]` | Топ-N запросов по частоте из текущей выгрузки | `cluster_demand.read_xlsx` |
| `/demand <фраза>` | Бесплатно: раскрыть фразу в кандидатов + найти её в выгрузке | `expand_seeds` |
| `/demand <фраза> live` | Снять свежий спрос через DataForSEO (в очередь) | `gkp_client._generate_dfs` |
| `/report` | Прислать текущую выгрузку `.xlsx` файлом | — |
| `/status` | Что в работе, какая выгрузка активна, есть ли креды | — |

Приём файлов:
- **CSV** из веб-Планировщика Google → бот импортирует его в `.xlsx` нашей схемы
  (`gkp_client.import_csv`) и делает активным — **бесплатный путь без API и карты**.
- **`.xlsx`** нашей схемы → бот берёт его как текущий датасет.

## Очередь

Долгий `live`-съём через DataForSEO троттлится (5 c между запросами, лимит
live-эндпоинтов). Поэтому такие задачи ставятся в **очередь** (`asyncio.Queue`,
один фоновый воркер) и выполняются по одной — бот пишет позицию и статус.
Быстрые команды (`/themes`, `/top`, `/report`) исполняются сразу.

## Бесплатно ли это

Да. Платный тут только опциональный DataForSEO (`/demand … live`). Базовый сценарий —
бесплатный: экспортируешь CSV из веб-Планировщика Google (без карты, без аккаунта Ads),
присылаешь боту — он сам импортирует и отдаёт кластеры/топы. Telegram Bot API,
`python-telegram-bot` и long-polling — бесплатны и не требуют публичного домена.

## Запуск локально

```bash
pip install -r telegram-bot-skill/requirements.txt
export TELEGRAM_BOT_TOKEN=123:ABC...           # токен от @BotFather
# (опционально) export ALLOWED_USERS=11111111  # белый список Telegram id
# (опционально, для live) ~/dataforseo.yaml с login/password
python telegram-bot-skill/scripts/bot.py
```

## Переменные окружения

| Переменная | Назначение | Обяз. |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен бота от @BotFather | да |
| `ALLOWED_USERS` | Белый список Telegram user id через запятую (пусто = всем) | нет |
| `BOT_DATA_DIR` | Куда складывать выгрузки/состояние (по умолч. `./bot_data`) | нет |
| `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` | Креды для `live`-съёма | нет |

## Деплой на Railway

В корне репозитория лежат `requirements.txt` и `railway.json`
(`startCommand: python telegram-bot-skill/scripts/bot.py`). Railway собирает через
Nixpacks и запускает бота как worker (домен не нужен — long-polling).

Шаги: см. `README.md` этого навыка, раздел «Деплой на Railway».
```
