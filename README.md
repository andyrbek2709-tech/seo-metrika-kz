# SEO метрика — оценка поискового спроса в Google (KZ)

Навыки для съёма поискового спроса в **Google** и **discovery-исследования рынка** KZ/СНГ.
Главная задача проекта — данными ответить на вопрос:

> **Что и сколько ищут в Google KZ-инженеры, проектировщики и эксперты Госэкспертизы —
> и какие из этих тем стоит закрывать продуктом?**

Под это заточен продукт по экспертизе/проверке проектной документации.

> **Статус источника (2026-05-30):** абсолютные числа Google **снимаются автоматически
> через DataForSEO** (бэкенд `--backend dataforseo`, по умолчанию): объёмы поиска,
> конкуренция и ставки по KZ **без аккаунта Google Ads и без карты** — нужен лишь
> логин/пароль DataForSEO. Опционально — официальный Google Ads API (`--backend ads`,
> требует карту) или бесплатный ручной `import` CSV из веб-Планировщика.

## Навыки

| Навык | Что делает |
|---|---|
| `google-kwp-skill/` | Съём спроса Google (Keyword Planner через DataForSEO): объёмы, идеи ключей, конкуренция, ставки. Гео KZ и другие страны. |
| `product-discovery-skill/` | Оркестратор: превращает съём спроса в продуктовые идеи — генерация запросов → кластеризация в темы → отчёт с идеями на Claude. |
| `telegram-bot-skill/` | Telegram-бот-витрина: по командам (`/themes`, `/top`, `/demand`, `/report`) отдаёт аналитику поверх выгрузок; приём CSV/`.xlsx`, очередь для live-съёма. Деплоится на Railway — см. `telegram-bot-skill/README.md`. |

`google-kwp-skill` пишет `.xlsx` со схемой `запрос, тип, ср_частота_мес, конкуренция,
индекс_конкуренции, ставка_верх_TOP, ставка_низ_TOP`. `product-discovery-skill` читает
этот файл и кластеризует спрос по темам рынка.

## Как запустить (DataForSEO, без аккаунта Google и без карты)

Нужен логин/пароль DataForSEO в `~/dataforseo.yaml` (см. `google-kwp-skill/references/setup.md`):

```bash
cd google-kwp-skill

# объёмы + расширение семантики (идеи) по KZ
python scripts/gkp_client.py ideas --phrases-file seeds_discovery.txt \
  --geo 2398 --lang-code ru --out ../kz_google.xlsx

# только объёмы по точным фразам
python scripts/gkp_client.py volume --phrases "проектная документация" "госэкспертиза" \
  --geo 2398 --lang-code ru --out ../kz_google.xlsx
```

Бесплатная альтернатива без API — ручной экспорт CSV из веб-Планировщика Google:
```bash
python scripts/gkp_client.py import --csv ~/Downloads/keyword_ideas.csv --out ../kz_google.xlsx
```

Сравнить спрос KZ vs РФ — тот же засев, другое гео (`--geo 2643` = Россия).

## От спроса к продуктовым идеям

```bash
cd product-discovery-skill
# 1. расширить семена в веер запросов по намерениям (info/howto/cost/problem/geo)
python scripts/expand_seeds.py --seeds ../google-kwp-skill/seeds_pd_gosexpertiza.txt --out candidates.txt
# 2. снять спрос через google-kwp-skill (см. выше) → kz_google.xlsx
# 3. кластеризовать в темы рынка
python scripts/cluster_demand.py --xlsx ../kz_google.xlsx --out themes.xlsx
# 4. заполнить отчёт идей продуктов поверх данных (assets/report_template.md)
```

Итог сводится в `АНАЛИЗ_KZ_Google_спрос.md` (агрегация по трём аренам засева: A —
экспертиза/нормоконтроль, B — широкий инженерный, C — AI-автоматизация).

## Доступы (один раз)

- DataForSEO: `google-kwp-skill/references/setup.md` (логин/пароль, `~/dataforseo.yaml`).

Токены и `*.yaml` закрыты `.gitignore` — не коммитятся.

## Засевы

В `google-kwp-skill/`:
- `seeds_discovery.txt` — общий засев по трём аренам (A/B/C).
- `seeds_gosexpertiza.txt` — расчёты / МОПБ / замечания Госэкспертизы.
- `seeds_pd_gosexpertiza.txt` — разработка ПД + прохождение Госэкспертизы.
- `seeds_problem_sections.txt` — проблемные разделы ПД (МОПБ, конструктив, сметы…).

## Статус

- [x] `google-kwp-skill` — реализован; DataForSEO (по умолч., без карты), Google Ads API, ручной import CSV.
- [x] `product-discovery-skill` — реализован; expand_seeds → cluster_demand → отчёт идей.
- [ ] Положить `~/dataforseo.yaml` и прогнать засевы по KZ → `kz_google.xlsx`.
- [ ] Кластеризовать спрос → `themes.xlsx`, заполнить `АНАЛИЗ_KZ_Google_спрос.md`.
