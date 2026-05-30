#!/usr/bin/env python3
"""
expand_seeds.py — из коротких «семян» строит расширенный список ПОИСКОВЫХ КАНДИДАТОВ
для съёма спроса (Wordstat / Keyword Planner / Trends).

Зачем. Проектировщики и эксперты Госэкспертизы формулируют один и тот же интерес
по-разному: «госэкспертиза» / «как пройти госэкспертизу» / «сроки госэкспертизы рк» /
«стоимость экспертизы проекта». Чтобы измерить рынок целиком, мало одного слова —
нужен веер формулировок по типам намерения (intent). Этот скрипт строит такой веер
механически, по шаблонам. Кандидаты с нулевой частотой потом сами отсеются при
съёме (Wordstat вернёт 0) — поэтому «лишние» комбинации не вредят, важна полнота.

Принцип WAT: смысловые решения (какие семена, какой регион, что строить) — в чате;
скрипт лишь раскрывает шаблоны и чистит дубли. Где провести границу «осмысленных»
комбинаций — решает человек, отобрав строки из вывода перед съёмом.

Намерения (intent), под которые строятся варианты:
  info       — что это/состав/требования/пример  (информационный спрос, верх воронки)
  howto      — как сделать/пройти/оформить       (процессный спрос — «хотят сделать сами»)
  cost       — цена/стоимость/сроки               (коммерческий спрос — «готовы платить»)
  service    — заказать/услуги/под ключ           (прямой коммерческий спрос)
  problem    — ошибки/замечания/проверка/отказ    (боль — самый ценный сигнал для продукта)
  geo        — рк/казахстан/алматы/астана         (локализация спроса под KZ)

Использование:
  # все intent-категории, плоский список в файл
  python expand_seeds.py --seeds seeds_pd_gosexpertiza.txt --out candidates.txt

  # только коммерческий спрос и боль, сгруппировать по семени, добавить гео РК
  python expand_seeds.py --seeds seeds.txt --intents cost service problem --geo \
      --group --out candidates.txt

  # вывести в stdout (без --out)
  python expand_seeds.py --seeds seeds.txt --intents problem
"""

import argparse
import sys
from typing import Dict, List

# Шаблоны вариантов по намерению. {q} — семя.
# Префиксные и суффиксные формы намеренно разделены: так фразы звучат естественнее.
INTENTS: Dict[str, List[str]] = {
    "info": [
        "что такое {q}", "{q} это", "состав {q}", "{q} состав",
        "требования {q}", "{q} требования", "{q} пример", "виды {q}",
    ],
    "howto": [
        "как пройти {q}", "как сделать {q}", "как оформить {q}",
        "{q} этапы", "{q} порядок", "{q} пошагово", "{q} инструкция",
    ],
    "cost": [
        "{q} цена", "{q} стоимость", "сколько стоит {q}",
        "{q} сроки", "{q} срок", "{q} расценки",
    ],
    "service": [
        "{q} заказать", "{q} услуги", "{q} под ключ", "{q} компания",
        "{q} специалист", "заказать {q}",
    ],
    "problem": [
        "ошибки {q}", "замечания {q}", "{q} замечания", "проверка {q}",
        "{q} проверка", "отказ {q}", "{q} отклонили", "доработка {q}",
    ],
    # geo обрабатывается отдельно: суффикс к семени И к уже расширенным вариантам.
}

GEO_SUFFIXES = ["рк", "казахстан", "алматы", "астана"]


def read_seeds(path: str) -> List[str]:
    seeds: List[str] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s and not s.startswith("#"):
                seeds.append(s)
    if not seeds:
        sys.exit(f"[ОШИБКА] {path}: не нашёл ни одного семени (все строки пусты/комментарии).")
    return seeds


def expand_one(seed: str, intents: List[str]) -> List[str]:
    out = [seed]
    for intent in intents:
        for tmpl in INTENTS[intent]:
            out.append(tmpl.format(q=seed))
    return out


def with_geo(phrases: List[str]) -> List[str]:
    out: List[str] = []
    for p in phrases:
        out.append(p)
        for g in GEO_SUFFIXES:
            out.append(f"{p} {g}")
    return out


def dedup(phrases: List[str]) -> List[str]:
    seen = set()
    out = []
    for p in phrases:
        key = " ".join(p.lower().split())
        if key not in seen:
            seen.add(key)
            out.append(" ".join(p.split()))
    return out


def main():
    ap = argparse.ArgumentParser(
        description="Расширить семена в поисковые кандидаты по типам намерения")
    ap.add_argument("--seeds", required=True, help="файл семян (по фразе на строку, # — комментарий)")
    ap.add_argument("--intents", nargs="+", default=list(INTENTS.keys()),
                    choices=list(INTENTS.keys()),
                    help=f"какие намерения раскрывать (по умолч. все: {', '.join(INTENTS)})")
    ap.add_argument("--geo", action="store_true",
                    help="добавить гео-суффиксы РК (рк/казахстан/алматы/астана)")
    ap.add_argument("--group", action="store_true",
                    help="сгруппировать вывод по семени (с заголовками-комментариями)")
    ap.add_argument("--out", default=None, help="файл результата (по умолч. stdout)")
    args = ap.parse_args()

    seeds = read_seeds(args.seeds)
    blocks: List[tuple] = []  # (seed, [phrases])
    for seed in seeds:
        phrases = expand_one(seed, args.intents)
        if args.geo:
            phrases = with_geo(phrases)
        blocks.append((seed, dedup(phrases)))

    lines: List[str] = []
    if args.group:
        for seed, phrases in blocks:
            lines.append(f"# --- {seed} ---")
            lines.extend(phrases)
            lines.append("")
    else:
        flat = dedup([p for _, ph in blocks for p in ph])
        lines.extend(flat)

    text = "\n".join(lines).rstrip() + "\n"
    total = sum(len(ph) for _, ph in blocks)
    uniq = len(dedup([p for _, ph in blocks for p in ph]))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"[OK] {len(seeds)} семян → {uniq} уникальных кандидатов "
              f"(намерения: {', '.join(args.intents)}{', +гео' if args.geo else ''}) → {args.out}")
    else:
        sys.stdout.write(text)
        print(f"\n[OK] {len(seeds)} семян → {uniq} уникальных кандидатов", file=sys.stderr)


if __name__ == "__main__":
    main()
