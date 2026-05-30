# Гео-таргеты (Yandex GeoID)

Wordstat/Директ используют собственные числовые GeoID — они **отличаются** от Google
(`geoTargetConstants`). В клиенте задаются голыми ID: `--geo 159` → Казахстан.

## Страны (GeoID)
| Регион | ID |
|---|---|
| Россия | 225 |
| Казахстан | 159 |
| Узбекистан | 171 |
| Кыргызстан | 207 |
| Беларусь | 149 |
| Украина | 187 |

## Города (GeoID, при необходимости среза)
| Город | ID |
|---|---|
| Москва | 213 |
| Санкт-Петербург | 2 |
| Алматы | 162 |
| Астана | 163 |

Полное дерево регионов — справочник Яндекса «Геобаза» (geo regions tree) или метод
API `Dictionaries.GetDictionaries(GeoRegions)`.

## Соответствие с google-kwp (для кросс-прогонов)
| Регион | Yandex GeoID | Google geoTarget |
|---|---|---|
| Казахстан | 159 | 2398 |
| Россия | 225 | 2643 |
| Узбекистан | 171 | 2860 |
| Кыргызстан | 207 | 2417 |
| Беларусь | 149 | 2112 |
| Украина | 187 | 2804 |

## Примеры сравнительных прогонов
```bash
# Казахстан
python scripts/wordstat_client.py ideas --phrases-file seeds_discovery.txt \
  --geo 159 --out kz.xlsx

# Россия — для сравнения объёма рынка
python scripts/wordstat_client.py ideas --phrases-file seeds_discovery.txt \
  --geo 225 --out ru.xlsx

# Несколько регионов сразу (агрегированный спрос по русскоязычному рынку)
python scripts/wordstat_client.py ideas --phrases-file seeds_discovery.txt \
  --geo 159 225 171 207 --out cis.xlsx
```
