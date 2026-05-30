# Гео-таргеты и языки (Google Ads API)

В запросах используются критерии-константы. В клиенте задаются голыми ID:
`--geo 2398` → `geoTargetConstants/2398`, `--lang 1031` → `languageConstants/1031`.

## Страны (geoTargetConstants)
| Страна | ID |
|---|---|
| Казахстан | 2398 |
| Россия | 2643 |
| Узбекистан | 2860 |
| Кыргызстан | 2417 |
| Беларусь | 2112 |
| Украина | 2804 |

Города и регионы внутри страны имеют свои ID. Полный список — официальный CSV
Google «Geographical targeting» (geo target constants). Можно также получить
программно через `GeoTargetConstantService.SuggestGeoTargetConstants`.

## Языки (languageConstants)
| Язык | ID |
|---|---|
| Русский | 1031 |
| Английский | 1000 |
| Казахский | 1064 |

Примечание для KZ: профессиональные инженерные запросы в Казахстане в основном
русскоязычные — для discovery начинай с `--lang 1031`. Казахский (1064) бери
отдельным прогоном, если нужен срез по госязыку.

## Примеры сравнительных прогонов
```bash
# Казахстан, русский
python scripts/gkp_client.py ideas --phrases-file seeds_discovery.txt \
  --geo 2398 --lang 1031 --out kz_ru.xlsx

# Россия, русский — для сравнения объёма рынка
python scripts/gkp_client.py ideas --phrases-file seeds_discovery.txt \
  --geo 2643 --lang 1031 --out ru_ru.xlsx

# Несколько стран сразу (агрегированный спрос по русскоязычному рынку)
python scripts/gkp_client.py ideas --phrases-file seeds_discovery.txt \
  --geo 2398 2643 2860 2417 --lang 1031 --out cis_ru.xlsx
```
