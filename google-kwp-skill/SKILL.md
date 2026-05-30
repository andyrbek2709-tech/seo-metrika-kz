---
name: google-kwp
description: |
  Навык для сбора спроса из Google Keyword Planner через Google Ads API: объёмы поисковых запросов, идеи ключевых слов, конкуренция и ставки — с гео-таргетом на Казахстан и другие страны. Используй навык, когда пользователь:
  - просит объём/частотность запросов в Google, «сколько ищут в Google»
  - собирает семантическое ядро или расширяет список ключей под Google
  - анализирует спрос/потребности аудитории по Google (discovery, идея продукта)
  - хочет сравнить спрос между странами (KZ vs РФ vs СНГ)
  - упоминает Keyword Planner, планировщик ключевых слов, Google Ads, объём поиска Google
  По умолчанию работает через DataForSEO (без аккаунта Google Ads и без карты, нужен лишь
  логин/пароль DataForSEO); опционально — официальный Google Ads API. См. references/setup.md.
---

# Навык: Google Keyword Planner (Google Ads API)

## Назначение

Получение оценки спроса в поиске Google: среднемесячные объёмы запросов, идеи
ключевых слов, уровень конкуренции и ставки. Гео-таргет на Казахстан (по умолчанию),
РФ и страны СНГ. Применяется для семантического ядра и **discovery-исследования
спроса** на рынках, где Google доминирует (включая KZ).

Принцип WAT: AI-решения — в чате; вызовы API и запись Excel делает
`scripts/gkp_client.py`. Вывод (.xlsx) подхватывает `product-discovery-skill`
для кластеризации спроса по темам рынка.

---

## Предварительные требования (один раз)

Зависит от бэкенда (см. `references/setup.md`):
- **`dataforseo` (по умолчанию):** логин/пароль DataForSEO в `~/dataforseo.yaml` или
  env `DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`. Аккаунт Google Ads и карта не нужны.
  Зависимостей нет (stdlib + openpyxl).
- **`ads`:** `pip install google-ads`, developer-токен (Basic access), OAuth и `customer_id`
  боевого аккаунта Google Ads. Важно: тестовый аккаунт = нули; без активных кампаний —
  диапазоны.

---

## Инструмент

`scripts/gkp_client.py` — 3 подкоманды. Вывод только `.xlsx`.

| Команда | Что делает | Доступ |
|---|---|---|
| `ideas` | расширяет засев идеями ключей + объёмы (семантическое ядро) | DataForSEO (по умолч.) или Google Ads API |
| `volume` | объёмы только по своим фразам, без расширения | DataForSEO (по умолч.) или Google Ads API |
| `import` | CSV-экспорт из **веб-Планировщика** → наша схема `.xlsx` | без API, только аккаунт Ads |

**Рекомендуемый путь для автоматизации — `--backend dataforseo`** (стоит по умолчанию):
те же объёмы Keyword Planner по KZ без аккаунта Google и без карты. Полностью бесплатный
ручной вариант — `import` (CSV из веб-Планировщика).

Флаги `import`: `--csv путь.csv`, `--out path.xlsx`.

Флаги `ideas`/`volume`: `--phrases "a" "b"` / `--phrases-file f.txt`, `--out path.xlsx`,
`--geo <id...>` (по умолч. 2398 = Казахстан),
`--backend dataforseo|ads` (по умолч. `dataforseo`).
- для `dataforseo`: `--lang-code ru` (язык), креды `--dfs-login`/`--dfs-password` или env/yaml;
  `--geo` = `location_code` DataForSEO.
- для `ads`: `--customer <ID>`, `--lang <id>` (по умолч. 1031); `--geo` = geoTargetConstants.
  ID гео/языков — `references/geo_targets.md`.

Колонки вывода: запрос, тип (засев/идея), ср_частота_мес, конкуренция,
индекс_конкуренции, ставка_низ_TOP, ставка_верх_TOP. Сортировка по объёму.

---

## Сценарии

### 0. Автоматический путь: DataForSEO (рекомендуется)
Нужны только логин/пароль DataForSEO в `~/dataforseo.yaml` (см. `references/setup.md`).
```bash
# семантическое ядро по KZ (объёмы + идеи)
python scripts/gkp_client.py ideas --phrases-file seeds_discovery.txt \
  --geo 2398 --lang-code ru --out kz_google.xlsx

# только объёмы по своим фразам
python scripts/gkp_client.py volume \
  --phrases "пожарная сигнализация" "проектная документация" \
  --geo 2398 --lang-code ru --out core_google.xlsx
```

### 1. Бесплатный ручной путь: импорт CSV из веб-Планировщика
1. В веб-Планировщике задай гео = Казахстан, язык = русский, вставь засев
   (`seeds_discovery.txt`) в «Узнать количество запросов и прогнозы» или открой
   «Найти ключевые слова».
2. Нажми «Скачать варианты ключевых слов» → CSV.
3. Приведи к нашей схеме:
```bash
python scripts/gkp_client.py import --csv ~/Downloads/keyword_ideas.csv --out kz_google.xlsx
```
Парсер понимает русские и английские заголовки, диапазоны («1 тыс. – 10 тыс.»),
UTF-8/UTF-16. Дальше — тот же сравнительный анализ, что и для остальных путей.

### 2. Discovery: сравнить спрос KZ vs РФ (DataForSEO)
```bash
python scripts/gkp_client.py ideas --phrases-file seeds_discovery.txt \
  --geo 2398 --lang-code ru --out kz.xlsx   # Казахстан
python scripts/gkp_client.py ideas --phrases-file seeds_discovery.txt \
  --geo 2643 --lang-code ru --out ru.xlsx   # Россия
```
Дальше в чате: сопоставить объёмы по аренам → найти «gap»-запросы → гипотезы продукта.
(Через официальный API — добавь `--backend ads --customer <ID> --lang 1031`.)

### 3. От спроса к продуктовым идеям
Выход `.xlsx` передай в `product-discovery-skill`:
`cluster_demand.py --xlsx kz_google.xlsx --out themes.xlsx` — кластеризация в темы
рынка, дальше отчёт идей продуктов по `assets/report_template.md`.

---

## Интерпретация

- Keyword Planner — оценка для рекламы, не точный счётчик. Без spend — диапазоны.
- `индекс_конкуренции` и ставки отражают рекламный, а не органический спрос —
  высокая ставка часто = деньги в нише.
- Для KZ начинай с русского (1031); казахский (1064) — отдельным срезом.
- Низкий объём в узкой B2G-нише ≠ нет рынка; смотри относительно и на состав идей.

---

## Ссылки
- `references/setup.md` — авторизация Google Ads API (developer-токен, OAuth, customer_id).
- `references/geo_targets.md` — ID стран и языков, примеры сравнительных прогонов.
- `seeds_discovery.txt` — общий засев по трём аренам (A/B/C); фокус-засевы — `seeds_*.txt`.
