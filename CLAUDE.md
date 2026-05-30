# CLAUDE.md

Памятка для Claude Code по этому репозиторию. Подробности для человека — в `README.md`.

## Что это за проект

Коллекция из **двух навыков (skills)** для съёма поискового спроса в **Google** и
discovery-исследования рынка KZ/СНГ. Главный исследовательский вопрос:

> Что и сколько ищут в Google KZ-инженеры, проектировщики и эксперты Госэкспертизы —
> и какие из этих тем стоит закрывать продуктом?

Итог сводится в `АНАЛИЗ_KZ_Google_спрос.md`.

Это **не приложение и не сервис** — здесь нет точки входа `main`, сервера или тестов.
«Запуск» = прогон одного из CLI-скриптов над засевом или выгруженным CSV/XLSX.

## Структура

```
google-kwp-skill/        Google Keyword Planner — абсолютные объёмы, конкуренция, ставки
  scripts/gkp_client.py  (режимы: ideas / volume / import; бэкенды: dataforseo / ads)
  SKILL.md, references/, seeds_discovery.txt, seeds_*.txt
product-discovery-skill/ оркестратор: спрос → продуктовые идеи
  scripts/expand_seeds.py, scripts/cluster_demand.py
  SKILL.md, assets/report_template.md
README.md
АНАЛИЗ_KZ_Google_спрос.md   итоговый разбор спроса по аренам (шаблон)
```

Каждый навык описан в своём `SKILL.md` — **читай его перед работой с навыком**.
`references/setup.md` внутри навыка — как получить доступы (логин/пароль DataForSEO).

## Рабочий статус источника (на 2026-05-30)

**Google Keyword Planner** (`google-kwp-skill`) — абсолютные числа Google **снимаются
автоматически через DataForSEO** (бэкенд `--backend dataforseo`, стоит по умолчанию):
объёмы/конкуренция/ставки по KZ **без аккаунта Google Ads и без карты**, нужен лишь
логин/пароль DataForSEO в `~/dataforseo.yaml`. Официальный Google Ads API (`--backend ads`,
требует карту) и ручной `import` CSV из веб-Планировщика остаются как опции.

Почему только Google: он занимает ~95% поискового рынка Казахстана и отражает реальный
спрос KZ-аудитории профессионалов.

## Как запускать

Все скрипты — на Python 3, ставятся обычные пакеты (`openpyxl`, плюс stdlib). В репозитории
нет `requirements.txt` — устанавливай зависимости по факту импортов в скрипте. Рекомендуется
venv:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install openpyxl
```

Основной сценарий (DataForSEO, без аккаунта Google и без карты — нужен `~/dataforseo.yaml`):

```bash
# объёмы + расширение семантики (идеи) по KZ
python google-kwp-skill/scripts/gkp_client.py ideas \
  --phrases-file google-kwp-skill/seeds_discovery.txt \
  --geo 2398 --lang-code ru --out kz_google.xlsx

# только объёмы по точным фразам
python google-kwp-skill/scripts/gkp_client.py volume \
  --phrases "проектная документация" "госэкспертиза" \
  --geo 2398 --lang-code ru --out kz_google.xlsx

# бесплатно вручную: import CSV из веб-Планировщика Google
python google-kwp-skill/scripts/gkp_client.py import --csv keyword_ideas.csv --out kz_google.xlsx
```

Сравнить KZ vs РФ — тот же засев, другое гео (`--geo 2643` = Россия).

Точные флаги уточняй через `--help` у каждого скрипта или загляни в `SKILL.md` навыка —
README мог отстать от кода.

## Схема вывода

`gkp_client.py` пишет `.xlsx` со схемой:

```
запрос, тип, ср_частота_мес, конкуренция, индекс_конкуренции, ставка_верх_TOP, ставка_низ_TOP
```

При правке `gkp_client.py` **сохраняй эту схему** — на ней держится downstream-кластеризация
(`product-discovery-skill/scripts/cluster_demand.py` определяет источник по колонкам
`запрос` + `ср_частота_мес`).

## Засев

`seeds_discovery.txt` (в `google-kwp-skill/`) — общий список фраз по трём аренам:
A — экспертиза/нормоконтроль, B — широкий инженерный, C — AI-автоматизация. Дополнительные
фокус-засевы там же: `seeds_gosexpertiza.txt` (расчёты/МОПБ/замечания), `seeds_pd_gosexpertiza.txt`
(разработка ПД + Госэкспертиза), `seeds_problem_sections.txt` (проблемные разделы ПД).
Правятся под конкретный discovery-вопрос.

## Конвенции

- **Язык:** весь проект и общение — на русском. Имена колонок и доменные термины — русские.
- **Секреты не коммитим:** токены и `*.yaml` закрыты `.gitignore`. Не добавляй ключи,
  логин/пароль DataForSEO, developer-токены, OAuth-данные и `customer_id` в код или в git.
- Ветка по умолчанию для PR — `main` (работа идёт в `master`).
