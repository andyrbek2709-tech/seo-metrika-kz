# Telegram-бот спроса (KZ) — запуск и деплой

Бот-витрина аналитики проекта: по командам в Telegram отдаёт кластеры спроса,
топ-запросы и съём по фразе. Подробное описание команд — в [`SKILL.md`](SKILL.md).

## 1. Получить токен

Открой [@BotFather](https://t.me/BotFather) → `/newbot` → имя и username →
получишь токен вида `123456:ABC-DEF...`.

## 2. Локальный запуск

```bash
pip install -r telegram-bot-skill/requirements.txt
export TELEGRAM_BOT_TOKEN=123456:ABC...
python telegram-bot-skill/scripts/bot.py
```

Напиши боту `/start`, затем пришли CSV-экспорт из веб-Планировщика Google
(кнопка «Скачать варианты ключевых слов») или готовый `.xlsx` — и зови `/themes`.

## 3. Деплой на Railway

В корне репозитория уже есть `requirements.txt` и `railway.json` — Railway
соберёт проект через Nixpacks и запустит бота командой
`python telegram-bot-skill/scripts/bot.py` (это worker на long-polling, **домен не
нужен** — кнопку *Generate Domain* нажимать не надо).

Шаги в Railway (проект → сервис `seo-metrika-kz`):

1. **Variables** → добавь переменную:
   - `TELEGRAM_BOT_TOKEN` = токен от BotFather
   - (опц.) `ALLOWED_USERS` = твой Telegram id, чтобы ботом не пользовались чужие
   - (опц., для `/demand … live`) `DATAFORSEO_LOGIN` и `DATAFORSEO_PASSWORD`
2. **Settings → Source** — убедись, что ветка production указывает на ветку, где
   лежат эти файлы. Сейчас подключён `master`: либо влей сюда ветку с ботом, либо
   переключи «Branch connected to production» на неё.
3. Railway пере-деплоит автоматически после push (Auto deploys включён). Логи —
   вкладка **Deployments** → последний деплой → *View Logs*. Должна появиться
   строка `Запуск long-polling…`.

### Сохранение загруженных выгрузок между деплоями (опционально)

Контейнер Railway пересоздаётся при каждом деплое — присланные боту `.xlsx`
по умолчанию не переживут редеплой. Чтобы сохранять:

1. В сервисе → **+ Add** → **Volume**, точка монтирования, например `/data`.
2. **Variables** → `BOT_DATA_DIR=/data`.

После этого активная выгрузка и состояние (`state.json`) переживают редеплои.

## Почему сборка падала раньше

В репозитории не было ни корневого `requirements.txt`, ни start-команды, поэтому
Nixpacks не понимал, что и как запускать (`Build failed`). Файлы `requirements.txt`
и `railway.json` в корне это чинят.
