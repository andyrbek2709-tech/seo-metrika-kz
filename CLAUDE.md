# CLAUDE.md

Памятка для Claude Code по этому репозиторию. Подробности для человека — в `README.md`.

## Что это за проект

Коллекция из **трёх парных навыков (skills)** для съёма поискового спроса и
discovery-исследования рынка KZ/СНГ. Главный исследовательский вопрос:

> Где KZ-инженеры, проектировщики и эксперты Госэкспертизы делают больше поисковых
> запросов — в Google или в Яндексе, и в каких темах?

Итог сводится в `АНАЛИЗ_KZ_Google_vs_Yandex.md`.

Это **не приложение и не сервис** — здесь нет точки входа `main`, сервера или тестов.
«Запуск» = прогон одного из CLI-скриптов над выгруженным вручную CSV/XLSX.

## Структура

```
gtrends-skill/      Google Trends — относительный интерес 0–100 (без аккаунта/карты)
  scripts/trends_import.py
  SKILL.md, references/, seeds_discovery.txt
google-kwp-skill/   Google Keyword Planner — абсолютные объёмы, конкуренция, ставки
  scripts/gkp_client.py      (режимы: import / ideas / volume)
  SKILL.md, references/, seeds_discovery.txt
wordstat-skill/     Яндекс Wordstat — точная частотность показов
  scripts/wordstat_client.py (режим: import — рабочий; ideas/volume через API заблокированы)
  SKILL.md, references/, seeds_discovery.txt
README.md
АНАЛИЗ_KZ_Google_vs_Yandex.md   итоговый сравнительный разбор (шаблон)
```

Каждый навык описан в своём `SKILL.md` — **читай его перед работой с навыком**.
`references/setup.md` внутри навыка — как получить доступы (токены/OAuth).

## Рабочий статус источников (на 2026-05-30)

Оба источника рабочие через **ручную веб-выгрузку**, без API-токенов и без карты:

- **Google Trends** (`gtrends-skill`) — `trends.google.com`, регион Казахстан, без аккаунта.
- **Яндекс Wordstat** (`wordstat-skill import`) — `wordstat.yandex.ru` под обычным
  аккаунтом Яндекса, даёт абсолютные числа + разбивку по регионам KZ.
- **Google Keyword Planner** (`google-kwp-skill`) — абсолютные числа Google **снимаются
  автоматически через DataForSEO** (бэкенд `--backend dataforseo`, стоит по умолчанию):
  объёмы/конкуренция/ставки по KZ **без аккаунта Google Ads и без карты**, нужен лишь
  логин/пароль DataForSEO в `~/dataforseo.yaml`. Официальный Google Ads API (`--backend ads`,
  требует карту) и ручной `import` CSV остаются как опции.
- API-пути Яндекс.Директа (`wordstat ideas/volume`) **заблокированы** (регистрация
  API Директа недоступна). Веб-Wordstat это не затрагивает.

## Как запускать

Все скрипты — на Python 3, ставятся обычные пакеты (`pandas`, `openpyxl`, `requests`,
`pytrends`). В репозитории нет `requirements.txt` — устанавливай зависимости по факту
импортов в скрипте. Рекомендуется venv:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install pandas openpyxl requests pytrends python-dotenv
```

Основной (бесплатный, без карты) сценарий:

```bash
# Google Trends: выгрузить A.csv/B.csv/C.csv (каждый батч с анкором «проектная документация»),
# затем свести в единую шкалу по анкору:
python gtrends-skill/scripts/trends_import.py --csv A.csv B.csv C.csv \
  --anchor "проектная документация" --out kz_trends.xlsx

# Яндекс Wordstat: выгрузить phrase.xlsx (регион Казахстан, вкладка «Топы запросов»):
python wordstat-skill/scripts/wordstat_client.py import --file phrase.xlsx --out kz_yandex.xlsx

# Google Keyword Planner через DataForSEO (без карты, нужен ~/dataforseo.yaml):
python google-kwp-skill/scripts/gkp_client.py ideas --phrases-file google-kwp-skill/seeds_discovery.txt \
  --geo 2398 --lang-code ru --out kz_google.xlsx
# (или бесплатно вручную: import CSV из веб-Планировщика — gkp_client.py import --csv keyword_ideas.csv --out kz_google.xlsx)
```

Точные флаги уточняй через `--help` у каждого скрипта или загляни в `SKILL.md` навыка —
README мог отстать от кода.

## Схема вывода

**Wordstat + Keyword Planner** пишут `.xlsx` с **идентичными колонками**, чтобы файлы
сливались в один сравнительный разбор:

```
запрос, тип, ср_частота_мес, конкуренция, индекс_конкуренции, ставка_верх_TOP, ставка_низ_TOP
```

При правке `wordstat_client.py` или `gkp_client.py` **сохраняй эту схему** — на ней
держится сравнение источников.

**Google Trends** по своей природе даёт относительный интерес, поэтому у него своя схема:

```
запрос, относит_интерес, нормировано
```

## Засев

`seeds_discovery.txt` (своя копия в каждом навыке) — общий список фраз по трём аренам:
A — экспертиза/нормоконтроль, B — широкий инженерный, C — AI-автоматизация.
Правится под конкретный discovery-вопрос.

## Конвенции

- **Язык:** весь проект и общение — на русском. Имена колонок и доменные термины — русские.
- **Секреты не коммитим:** токены и `*.yaml` закрыты `.gitignore`. Не добавляй ключи,
  developer-токены, OAuth-данные и `customer_id` в код или в git.
- Ветка по умолчанию для PR — `main` (работа идёт в `master`).
