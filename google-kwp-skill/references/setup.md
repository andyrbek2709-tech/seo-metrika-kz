# Настройка доступа: Google Keyword Planner

Есть три пути:
- **Путь C — DataForSEO (рекомендуется для автоматизации):** те же объёмы Keyword Planner
  по KZ, но **без аккаунта Google Ads и без карты** — только логин/пароль DataForSEO.
  Это бэкенд по умолчанию (`--backend dataforseo`).
- **Путь A — ручной веб-Планировщик + `import`:** бесплатно, без API, но выгрузка руками.
- **Путь B — официальный Google Ads API:** полная автоматизация, но требует developer-токен,
  OAuth и боевой аккаунт Ads с картой.

## Путь C — DataForSEO (без аккаунта Google и без карты)

DataForSEO проксирует данные Google Ads Keyword Planner: отдаёт search volume,
конкуренцию (LOW/MEDIUM/HIGH), индекс конкуренции и ставки — по любой локации, включая
Казахстан. Собственный аккаунт Google Ads подключать **не нужно**.

1. Зарегистрируйся на [dataforseo.com], возьми логин/пароль на
   https://app.dataforseo.com/api-access (Basic-auth, оплата по факту запросов).
2. Положи креды в `~/dataforseo.yaml` (файл закрыт в `.gitignore` маской `*.yaml`):
   ```yaml
   login: "ВАШ_ЛОГИН"
   password: "ВАШ_ПАРОЛЬ"
   ```
   Альтернатива — переменные окружения `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD`
   или флаги `--dfs-login` / `--dfs-password`. Путь к файлу можно переопределить
   через `DATAFORSEO_CONFIGURATION_FILE_PATH`.
3. Запуск (бэкенд `dataforseo` стоит по умолчанию):
   ```bash
   # только объёмы по своим фразам (до 1000 за запрос)
   python scripts/gkp_client.py volume --phrases-file seeds_discovery.txt \
     --geo 2398 --lang-code ru --out kz_google.xlsx

   # объёмы + расширение семантики (идеи; до 20 сид-фраз на запрос)
   python scripts/gkp_client.py ideas --phrases-file seeds_discovery.txt \
     --geo 2398 --lang-code ru --out kz_google_ideas.xlsx
   ```
   - `--geo` здесь — это `location_code` DataForSEO (для KZ = `2398`, совпадает с
     Google geo target). Проверить/найти код локации:
     ```bash
     curl -s -u "ЛОГИН:ПАРОЛЬ" \
       https://api.dataforseo.com/v3/keywords_data/google_ads/locations | less
     ```
   - `--lang-code` — `language_code` (русский = `ru`).
   - Ставки приходят в **USD** (не микро-единицы).

Минусы пути C: платный по запросам (хотя дёшево), лимит live-эндпоинтов ~12 запросов/мин
(клиент сам выдерживает паузу между чанками).

## Путь A — веб-Планировщик + import (бесплатно, без API)

**Начни с пути A**, если не хочешь платить за DataForSEO — он даёт реальные цифры по KZ
без developer-токена и без ожидания одобрения.

## Путь A — веб-Планировщик + import (рекомендуется, без API)

1. Создай (если нет) бесплатный аккаунт **Google Ads** на ads.google.com. Платить и
   запускать кампании не нужно — Планировщик доступен и так (без активных кампаний
   объёмы показываются диапазонами, например «1 тыс. – 10 тыс.»).
2. Инструменты → **Планировщик ключевых слов** → «Найти ключевые слова».
3. Гео = **Казахстан**, язык = **русский**. Вставь засев из `seeds_discovery.txt`.
4. Кнопка **«Скачать варианты ключевых слов»** → CSV.
5. Приведи к нашей схеме `.xlsx`:
   ```bash
   python scripts/gkp_client.py import --csv ~/Downloads/keyword_ideas.csv --out kz_google.xlsx
   ```
   Никаких токенов и `google-ads.yaml` не требуется.

Минусы пути A: ручная выгрузка (не автоматизируется), объёмы часто диапазонами.
Для разового анализа спроса этого достаточно.

## Путь B — Google Ads API (автоматизация, требует одобрения)

Это самая трудоёмкая часть. Делается один раз. Без боевого аккаунта Ads
Keyword Planner отдаёт нули или диапазоны — учитывай это.

## Что нужно собрать (4 секрета)

| Секрет | Где взять |
|---|---|
| `developer_token` | Google Ads → Инструменты → Центр API. Запросить **Basic access** (одобрение) |
| `client_id`, `client_secret` | Google Cloud Console → APIs & Services → Credentials → OAuth client (тип Desktop) |
| `refresh_token` | сгенерировать через OAuth flow (см. ниже) |
| `customer_id` | 10-значный ID аккаунта Google Ads (без дефисов) |

Дополнительно включи **Google Ads API** в Google Cloud проекте.
Если используешь управляющий аккаунт (MCC) — понадобится ещё `login_customer_id`.

## 1. Установка
```bash
pip install google-ads
```

## 2. Получение refresh-token
Самый простой путь — официальный пример из библиотеки:
```bash
# в репозитории google-ads-python: examples/authentication/generate_user_credentials.py
python generate_user_credentials.py \
  --client_id=ВАШ_CLIENT_ID --client_secret=ВАШ_CLIENT_SECRET
```
Скрипт откроет браузер, после авторизации вернёт `refresh_token`.

## 3. Файл конфигурации `~/google-ads.yaml`
```yaml
developer_token: "ВАШ_DEVELOPER_TOKEN"
client_id: "ВАШ_CLIENT_ID"
client_secret: "ВАШ_CLIENT_SECRET"
refresh_token: "ВАШ_REFRESH_TOKEN"
# login_customer_id: "1234567890"   # только если работаешь через MCC
use_proto_plus: true
```
Клиент ищет файл по пути `~/google-ads.yaml` или в переменной
`GOOGLE_ADS_CONFIGURATION_FILE_PATH`. Альтернатива — переменные `GOOGLE_ADS_*`.

Customer ID передаётся отдельно: флаг `--customer` или env `GOOGLE_ADS_CUSTOMER_ID`.

## Подводные камни
- **Тестовый аккаунт** Keyword Planner = нули. Нужен боевой аккаунт с доступом к API.
- **Без активных кампаний** объём показывается диапазонами («1K–10K»), а не точно.
- Запрос `GenerateKeywordIdeas` принимает максимум **20 сид-фраз** — клиент чанкует сам.
- Не коммить `google-ads.yaml` и токены в git. Добавь в `.gitignore`.
