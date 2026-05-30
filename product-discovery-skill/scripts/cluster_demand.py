#!/usr/bin/env python3
"""
cluster_demand.py — свести съём спроса (.xlsx из навыков wordstat/google-kwp) в
ТЕМЫ с суммарной частотой и топ-запросами. Это «скелет» рыночного анализа: из сотен
строк получаем картину «по каким темам проектировщики и Госэкспертиза реально ищут».

Что делает. Читает один или несколько .xlsx (колонки «запрос» и «ср_частота_мес» —
схема навыков wordstat/google-kwp). Каждый запрос относит к теме по словарю ключевых
слов (тема = намерение рынка, напр. «Госэкспертиза», «Смета», «Чертежи/ГОСТ»).
Суммирует частоту по теме, считает долю, выводит топ-запросы темы. Запрос, не попавший
ни в одну тему, идёт в «прочее» — это сырьё для новых тем (смотри их вручную).

Зачем именно так. Кластеризация по смыслу — задача для чата (там видно нюансы и боль).
Скрипт даёт воспроизводимый, быстрый каркас: ранжирование тем по объёму спроса и
топ-формулировки внутри. Интерпретацию («что они на самом деле ХОТЯТ», какие продукты
строить) делает аналитик в чате поверх этого каркаса — см. assets/report_template.md.

Принцип WAT: числа и группировка — скриптом; смысл и продуктовые выводы — в чате.

Темы по умолчанию заточены под домен «проектирование ПД + Госэкспертиза» (KZ/СНГ).
Свой словарь тем можно передать через --themes theme.json:
  { "Госэкспертиза": ["экспертиз", "госэксперт", "заключени"],
    "Смета":         ["смет", "расцен", "стоимость строит"] }
Ключи сопоставляются как подстроки в нижнем регистре (учитывают словоформы).

Использование:
  python cluster_demand.py --xlsx kz_yandex.xlsx --out themes.xlsx
  python cluster_demand.py --xlsx kz_yandex.xlsx kz_google.xlsx --top 8 --themes my_themes.json
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

# Словарь тем по умолчанию: тема → список ключей-подстрок (нижний регистр, словоформы).
# Порядок ВАЖЕН: запрос относится к ПЕРВОЙ совпавшей теме. Поэтому узкие «проблемные
# разделы» (МОПБ, конструктив…) идут ВЫШЕ широких («экспертиза», «проектная документация»),
# иначе «замечания по мопб» утечёт в «Госэкспертиза» и боль раздела не будет видна.
# Это разрез под главную гипотезу: боль рынка — в конкретных разделах ПД, которые
# труднее всего пройти на экспертизе. См. ../wordstat-skill/seeds_problem_sections.txt.
DEFAULT_THEMES: Dict[str, List[str]] = {
    # --- проблемные разделы ПД (узкие, проверяются первыми) ---
    "Раздел: Пожарная безопасность (МОПБ)": ["мопб", "пожарн", "противопожарн", "пожаротушени",
                                             "эвакуац", "соуэ", "сигнализац"],
    "Раздел: Конструктив / расчёты (КР)":   ["конструктив", "конструкци", "расчет нагруз",
                                             "железобетон", "металлоконструкц", "фундамент",
                                             "основани", "сейсмическ", "обрушени", "поверочн расчет",
                                             "несущ способност", "строительн расч"],
    "Раздел: Смета / стоимость":            ["смет", "расцен", "стоимост строит", "ресурсн метод"],
    "Раздел: Энергоэффективность":          ["энергоэффективн", "теплотехническ", "энергопаспорт"],
    "Раздел: Экология / ООС":               ["охрана окружающ", "оос ", "экологи", "санитарно-защитн", "сзз"],
    "Раздел: Инсоляция / КЕО":              ["инсоляц", "кео", "естественн освещени"],
    "Раздел: Инженерные сети (ИОС)":        ["вентиляц", "отоплени", "электроснаб", "водоснаб",
                                             "канализац", "сетей связ", "слаботоч", "скуд", "газоснаб"],
    "Раздел: Доступ МГН (ОДИ)":             ["маломобильн", "одибис", "одиси", "доступ инвалид"],
    # --- процессы и общие темы (широкие, проверяются после разделов) ---
    "Госэкспертиза (процесс)": ["госэксперт", "экспертиз", "заключени", "согласовани", "замечани"],
    "Проектная документация":  ["проектн", "рабоч документац", "псд", "пд ", "разделы проект"],
    "Чертежи / ГОСТ / СПДС":   ["чертеж", "гост", "спдс", "оформлени"],
    "Нормативы / СН РК":       ["норматив", "сн рк", "сп рк", "снип", "свод правил", "нормоконтрол"],
    "BIM / Revit / САПР":      ["bim", "revit", "ревит", "autocad", "автокад", "сапр", "renga"],
    "AI / автоматизация":      ["нейросет", "искусствен интеллект", " ии ", "автоматизац",
                               "распознавани", "chatgpt", "gpt"],
}


def read_xlsx(path: str) -> List[Tuple[str, float]]:
    """Вернуть [(запрос, частота)] из .xlsx со схемой навыков (колонки «запрос», «ср_частота_мес»)."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    if not rows:
        sys.exit(f"[ОШИБКА] {path}: пустой файл.")
    header = [str(c).strip().lower() if c is not None else "" for c in rows[0]]

    def find(*names):
        for i, h in enumerate(header):
            if any(n in h for n in names):
                return i
        return None

    qi = find("запрос", "фраза", "keyword")
    fi = find("частот", "показ", "volume", "avg_monthly")
    if qi is None or fi is None:
        sys.exit(f"[ОШИБКА] {path}: не нашёл колонки «запрос» и «ср_частота_мес».\n"
                 f"Заголовок: {header}\nЭто .xlsx из навыка wordstat/google-kwp?")

    out: List[Tuple[str, float]] = []
    for r in rows[1:]:
        if qi >= len(r) or r[qi] is None:
            continue
        q = str(r[qi]).strip()
        if not q:
            continue
        freq = 0.0
        if fi < len(r) and r[fi] is not None:
            try:
                freq = float(str(r[fi]).replace(" ", "").replace("\xa0", "").replace(",", "."))
            except ValueError:
                freq = 0.0
        out.append((q, freq))
    return out


def assign_theme(query: str, themes: Dict[str, List[str]]) -> Optional[str]:
    q = f" {query.lower()} "
    for theme, keys in themes.items():
        if any(k in q for k in keys):
            return theme
    return None


def cluster(items: List[Tuple[str, float]],
            themes: Dict[str, List[str]], top: int) -> Tuple[List[Dict[str, Any]], List[Tuple[str, float]]]:
    buckets: Dict[str, List[Tuple[str, float]]] = {t: [] for t in themes}
    other: List[Tuple[str, float]] = []
    # дедуп по запросу, берём максимальную частоту
    best: Dict[str, float] = {}
    for q, f in items:
        k = q.lower()
        if k not in best or f > best[k]:
            best[k] = f
    dedup = sorted(((q, f) for q, f in {q.lower(): f for q, f in items}.items()), key=lambda x: -x[1])
    # пересоберём с исходным регистром первого вхождения
    seen_case: Dict[str, str] = {}
    for q, _ in items:
        seen_case.setdefault(q.lower(), q)
    dedup = sorted(((seen_case[k], v) for k, v in best.items()), key=lambda x: -x[1])

    for q, f in dedup:
        t = assign_theme(q, themes)
        (buckets[t] if t else other).append((q, f))

    total = sum(f for _, f in dedup) or 1.0
    summary: List[Dict[str, Any]] = []
    for theme, qs in buckets.items():
        if not qs:
            continue
        qs.sort(key=lambda x: -x[1])
        vol = sum(f for _, f in qs)
        summary.append({
            "тема": theme,
            "запросов": len(qs),
            "суммарная_частота": round(vol),
            "доля_%": round(100 * vol / total, 1),
            "топ_запросы": " | ".join(f"{q} ({round(f)})" for q, f in qs[:top]),
        })
    summary.sort(key=lambda x: -x["суммарная_частота"])
    other.sort(key=lambda x: -x[1])
    return summary, other


def write_xlsx(path: str, summary: List[Dict[str, Any]], other: List[Tuple[str, float]], top: int):
    if os.path.splitext(path)[1].lower() != ".xlsx":
        sys.exit("[ОШИБКА] --out должен быть .xlsx")
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Темы спроса"
    headers = ["тема", "запросов", "суммарная_частота", "доля_%", "топ_запросы"]
    ws.append(headers)
    fill = PatternFill("solid", fgColor="34A853")
    font = Font(bold=True, color="FFFFFF")
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill, cell.font = fill, font
        cell.alignment = Alignment(horizontal="center")
    for r in summary:
        ws.append([r[h] for h in headers])
    widths = [26, 10, 18, 9, 90]
    for c, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A2"

    if other:
        ws2 = wb.create_sheet("Прочее (новые темы?)")
        ws2.append(["запрос", "частота"])
        for q, f in other[:200]:
            ws2.append([q, round(f)])
        ws2.column_dimensions["A"].width = 50
    wb.save(path)
    print(f"[OK] {len(summary)} тем, «прочее»: {len(other)} запросов → {path}")


def main():
    ap = argparse.ArgumentParser(description="Кластеризация съёма спроса по темам рынка")
    ap.add_argument("--xlsx", nargs="+", required=True, help="один/несколько .xlsx из навыков")
    ap.add_argument("--themes", default=None, help="свой словарь тем (JSON: тема→[ключи])")
    ap.add_argument("--top", type=int, default=6, help="сколько топ-запросов показывать в теме")
    ap.add_argument("--out", default=None, help="результат .xlsx (без него — печать в консоль)")
    args = ap.parse_args()

    themes = DEFAULT_THEMES
    if args.themes:
        with open(args.themes, encoding="utf-8") as fh:
            themes = json.load(fh)

    items: List[Tuple[str, float]] = []
    for p in args.xlsx:
        items.extend(read_xlsx(p))

    summary, other = cluster(items, themes, args.top)

    if args.out:
        write_xlsx(args.out, summary, other, args.top)
    else:
        print(f"\n{'тема':<26}{'запр.':>7}{'частота':>12}{'доля%':>8}  топ")
        print("-" * 80)
        for r in summary:
            print(f"{r['тема']:<26}{r['запросов']:>7}{r['суммарная_частота']:>12}"
                  f"{r['доля_%']:>8}  {r['топ_запросы'][:70]}")
        print(f"\nПрочее (не попало в темы): {len(other)} запросов "
              f"(топ: {', '.join(q for q, _ in other[:5])})")


if __name__ == "__main__":
    main()
