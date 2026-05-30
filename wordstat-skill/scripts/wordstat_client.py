#!/usr/bin/env python3
"""
wordstat_client.py — детерминированный клиент Яндекс Wordstat (Yandex Direct API v4 Live).

Принцип WAT: AI-решения (подбор засева, кластеризация, выводы) — в чате.
Этот инструмент только дёргает API и пишет файлы.

Формат вывода ИДЕНТИЧЕН gkp_client.py (навык google-kwp), чтобы два .xlsx можно было
сравнивать и склеивать в один анализ Google vs Яндекс.

Авторизация: OAuth-токен Яндекс.Директа через ~/yandex-direct.yaml (ключ token:)
или переменную окружения YANDEX_DIRECT_TOKEN. Настройка — см. references/setup.md.

Команды:
  ideas   — расширяет засев связанными запросами (SearchedWith/SearchedAlso) + частоты [API]
  volume  — только частоты по самим фразам, без расширения                        [API]
  import  — выгрузка «Скачать» из веба Wordstat (.xlsx/.csv) → наша схема     [БЕЗ API/токена]

Гео по умолчанию: Казахстан (GeoID 159). Wordstat выводит язык из региона — параметра
языка нет. Другие GeoID — references/geo_targets.md.

ВНИМАНИЕ про API-команды (ideas/volume): используется Yandex Direct API v4 Live (метод
Wordstat-отчётов) — требует реального доступа к API Директа. Регистрация приложения Директа
упирается в Госуслуги РФ и из Казахстана недоступна.

РАБОЧИЙ ПУТЬ — команда `import`: веб-интерфейс https://wordstat.yandex.ru работает с обычным
аккаунтом Яндекса (без Директа и Госуслуг) и даёт абсолютные числа + разбивку по регионам KZ.
Ставишь регион = Казахстан, жмёшь «Скачать», прогоняешь файл через `import` — он приводит
выгрузку к той же схеме, что gkp_client.py, для прямого сравнения Google vs Яндекс.
"""

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

API_URL = "https://api.direct.yandex.ru/live/v4/json/"
PHRASE_CHUNK = 10          # лимит фраз в одном Wordstat-отчёте (v4)
DEFAULT_GEO = "159"        # Казахстан
POLL_INTERVAL = 5          # сек между опросами статуса отчёта
POLL_TIMEOUT = 300         # сек ожидания готовности отчёта
YAML_DEFAULT = os.path.expanduser("~/yandex-direct.yaml")


# ---------------------------------------------------------------------------
# Авторизация
# ---------------------------------------------------------------------------

def _load_token(arg: Optional[str]) -> str:
    if arg:
        return arg.strip()
    env = os.environ.get("YANDEX_DIRECT_TOKEN", "").strip()
    if env:
        return env
    yaml_path = os.environ.get("YANDEX_DIRECT_CONFIGURATION_FILE_PATH", YAML_DEFAULT)
    if os.path.exists(yaml_path):
        token = _read_yaml_token(yaml_path)
        if token:
            return token
    sys.exit(
        "[ОШИБКА] Не найден OAuth-токен Яндекс.Директа.\n"
        f"Ожидался --token, env YANDEX_DIRECT_TOKEN или файл {yaml_path} с полем token:.\n"
        "См. references/setup.md."
    )


def _read_yaml_token(path: str) -> Optional[str]:
    """Минимальный парсер 'token: VALUE' без зависимости от PyYAML."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("#") or ":" not in s:
                    continue
                key, _, value = s.partition(":")
                if key.strip() == "token":
                    return value.strip().strip('"').strip("'")
    except OSError as exc:
        sys.exit(f"[ОШИБКА] Не удалось прочитать {path}: {exc}")
    return None


# ---------------------------------------------------------------------------
# Транспорт API
# ---------------------------------------------------------------------------

def _call(token: str, method: str, param: Any = None) -> Any:
    body: Dict[str, Any] = {"method": method, "token": token, "locale": "ru"}
    if param is not None:
        body["param"] = param
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=data, headers={"Content-Type": "application/json; charset=utf-8"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        sys.exit(f"[ОШИБКА] HTTP {exc.code} при вызове {method}: {exc.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as exc:
        sys.exit(f"[ОШИБКА] Сеть при вызове {method}: {exc.reason}")

    if isinstance(payload, dict) and payload.get("error_code"):
        sys.exit(
            f"[ОШИБКА] Yandex Direct API {method}: "
            f"{payload.get('error_str')} — {payload.get('error_detail')} "
            f"(код {payload['error_code']})"
        )
    return payload.get("data") if isinstance(payload, dict) else payload


def _chunks(seq: List[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _wait_report(token: str, report_id: int) -> None:
    waited = 0
    while waited < POLL_TIMEOUT:
        reports = _call(token, "GetWordstatReportList") or []
        for r in reports:
            if r.get("ReportID") == report_id:
                status = r.get("StatusReport")
                if status == "Done":
                    return
                if status in ("Pending", "Processing", "Calculating"):
                    break
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
    sys.exit(f"[ОШИБКА] Wordstat-отчёт {report_id} не готов за {POLL_TIMEOUT} c.")


# ---------------------------------------------------------------------------
# Сбор данных
# ---------------------------------------------------------------------------

def _row(phrase: str, is_seed: bool, shows: Optional[int]) -> Dict[str, Any]:
    # Та же схема, что в gkp_client.py. У Wordstat нет рекламных метрик → пусто.
    return {
        "запрос": phrase,
        "тип": "засев" if is_seed else "идея",
        "ср_частота_мес": shows,
        "конкуренция": None,
        "индекс_конкуренции": None,
        "ставка_верх_TOP": None,
        "ставка_низ_TOP": None,
    }


def _generate(token: str, phrases: List[str], geo_ids: List[str],
              with_ideas: bool) -> List[Dict[str, Any]]:
    geo_int = [int(g) for g in geo_ids]
    rows: List[Dict[str, Any]] = []

    for chunk in _chunks(phrases, PHRASE_CHUNK):
        param = {"Phrases": chunk, "GeoID": geo_int}
        report_id = _call(token, "CreateNewWordstatReport", param)
        try:
            _wait_report(token, report_id)
            report = _call(token, "GetWordstatReport", report_id) or []
        finally:
            _call(token, "DeleteWordstatReport", report_id)

        seed_set = {c.lower() for c in chunk}
        for item in report:
            seed_phrase = item.get("Phrase", "")
            searched_with = item.get("SearchedWith") or []
            # Частота самого засева: строка SearchedWith, совпадающая с фразой засева,
            # иначе максимум показов (самая широкая форма).
            seed_shows = None
            for sw in searched_with:
                if sw.get("Phrase", "").lower() == seed_phrase.lower():
                    seed_shows = sw.get("Shows")
                    break
            if seed_shows is None and searched_with:
                seed_shows = max((sw.get("Shows") or 0) for sw in searched_with)
            rows.append(_row(seed_phrase, True, seed_shows))

            if with_ideas:
                extras = list(searched_with) + list(item.get("SearchedAlso") or [])
                for sw in extras:
                    txt = sw.get("Phrase", "")
                    if not txt or txt.lower() in seed_set:
                        continue
                    rows.append(_row(txt, False, sw.get("Shows")))

    # дедуп по тексту запроса, сортировка по частоте
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for r in sorted(rows, key=lambda x: -(x["ср_частота_мес"] or 0)):
        if r["запрос"] in seen:
            continue
        seen.add(r["запрос"])
        uniq.append(r)
    return uniq


# ---------------------------------------------------------------------------
# Импорт веб-выгрузки Wordstat («Скачать») — без API и токена
# ---------------------------------------------------------------------------
# wordstat.yandex.ru работает с обычным аккаунтом Яндекса. Кнопка «Скачать» отдаёт
# .xlsx (иногда .csv) текущей вкладки. Самая полезная для нашей схемы — «Топы запросов»:
# таблица «фраза → запросов в месяц» (и часто рядом второй блок «похожие запросы»).
# Числа берутся по тому региону, что выставлен в интерфейсе (ставь Казахстан).

def _norm(s: str) -> str:
    return (s or "").replace("﻿", "").replace("\xa0", " ").strip().lower()


def _to_int(raw: Any) -> Optional[int]:
    """«1 234», «1 234», 1234.0 → 1234. Не число → None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    digits = re.sub(r"[^\d]", "", str(raw))
    return int(digits) if digits else None


# Заголовки колонки с частотой (проверяем ПЕРВОЙ — «число запросов» содержит «запрос»).
_FREQ_HDR = ("запросов в месяц", "число запросов", "показов", "показы",
             "частот", "сколько раз искали", "count", "shows", "frequency", "в месяц")
# Заголовки колонки с фразой.
_PHRASE_HDR = ("топ запросов", "запросы, похожие", "похожие запросы", "поисковый запрос",
               "фраза", "запрос", "ключев", "keyword", "phrase", "что искали")


def _classify(h: str) -> str:
    n = _norm(h)
    if not n:
        return "other"
    if any(k in n for k in _FREQ_HDR):
        return "freq"
    if any(k in n for k in _PHRASE_HDR):
        return "phrase"
    return "other"


def _read_table(path: str) -> List[List[Any]]:
    """Прочитать .xlsx/.xls (openpyxl) или .csv (с автоопределением кодировки/разделителя)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        return [list(r) for r in ws.iter_rows(values_only=True)]
    # CSV
    text = None
    for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1251"):
        try:
            with open(path, "r", encoding=enc, newline="") as fh:
                text = fh.read()
            break
        except (UnicodeError, LookupError):
            continue
    if text is None:
        sys.exit(f"[ОШИБКА] Не смог прочитать {path} (кодировка).")
    head = "\n".join(text.splitlines()[:8])
    delim = ";" if head.count(";") >= head.count("\t") and head.count(";") >= head.count(",") \
        else ("\t" if head.count("\t") >= head.count(",") else ",")
    return [row for row in csv.reader(io.StringIO(text), delimiter=delim)]


def _pairs(header: List[Any]) -> List[Tuple[int, int]]:
    """Сопоставить каждую freq-колонку ближайшей phrase-колонке слева (Wordstat кладёт
    два блока «со словом»/«похожие» рядом → несколько пар фраза+частота в одной строке)."""
    kinds = [_classify(str(h) if h is not None else "") for h in header]
    pairs: List[Tuple[int, int]] = []
    for fi, k in enumerate(kinds):
        if k != "freq":
            continue
        pi = next((j for j in range(fi - 1, -1, -1) if kinds[j] == "phrase"), None)
        if pi is None:  # фраза правее? берём ближайшую любую справа
            pi = next((j for j in range(fi + 1, len(kinds)) if kinds[j] == "phrase"), None)
        if pi is not None:
            pairs.append((pi, fi))
    return pairs


def import_web(path: str) -> List[Dict[str, Any]]:
    rows = _read_table(path)
    if not rows:
        sys.exit(f"[ОШИБКА] {path}: пустой файл.")

    # Найти строку-заголовок: первая, где есть и phrase-, и freq-колонка.
    hdr_idx = None
    pairs: List[Tuple[int, int]] = []
    for i, row in enumerate(rows[:25]):
        cells = [c if c is not None else "" for c in row]
        kinds = [_classify(str(c)) for c in cells]
        if "freq" in kinds and "phrase" in kinds:
            hdr_idx = i
            pairs = _pairs(cells)
            break
    if hdr_idx is None or not pairs:
        sys.exit(
            f"[ОШИБКА] {path}: не нашёл колонки «фраза» и «запросов в месяц».\n"
            "Это выгрузка «Скачать» из wordstat.yandex.ru (вкладка «Топы запросов»)?\n"
            "Если формат другой — пришли первые строки файла, подгоню парсер."
        )

    out: Dict[str, Dict[str, Any]] = {}
    for row in rows[hdr_idx + 1:]:
        for pi, fi in pairs:
            if pi >= len(row) or fi >= len(row):
                continue
            phrase = str(row[pi]).strip() if row[pi] is not None else ""
            if not phrase or _classify(phrase) == "freq":
                continue
            shows = _to_int(row[fi])
            if shows is None:
                continue
            prev = out.get(phrase.lower())
            if prev is None or (shows > (prev["ср_частота_мес"] or 0)):
                out[phrase.lower()] = _row(phrase, False, shows)

    result = sorted(out.values(), key=lambda x: -(x["ср_частота_мес"] or 0))
    if not result:
        sys.exit(f"[ОШИБКА] {path}: колонки нашёл, но ни одной пары «фраза+число» не извлёк.")
    return result


# ---------------------------------------------------------------------------
# Excel (тот же формат, что и в gkp_client.py)
# ---------------------------------------------------------------------------

def write_xlsx(path: str, sheet_name: str, rows: List[Dict[str, Any]]) -> None:
    if os.path.splitext(path)[1].lower() != ".xlsx":
        sys.exit("[ОШИБКА] Для этого инструмента --out должен быть .xlsx")
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]
    if not rows:
        ws["A1"] = "нет данных (проверь доступ к API и GeoID)"
        wb.save(path)
        print(f"[OK] Пустой результат → {path}")
        return

    headers = list(rows[0].keys())
    ws.append(headers)
    fill = PatternFill("solid", fgColor="C8102E")  # «яндексовый» красный
    font = Font(bold=True, color="FFFFFF")
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center")
    for r in rows:
        ws.append([r.get(h) for h in headers])
    for c, h in enumerate(headers, start=1):
        width = max(len(str(h)), *(len(str(r.get(h, ""))) for r in rows))
        ws.column_dimensions[get_column_letter(c)].width = min(max(width + 2, 10), 60)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
    wb.save(path)
    print(f"[OK] Записано {len(rows)} строк → {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _phrases(args) -> List[str]:
    out: List[str] = []
    if args.phrases:
        out.extend(args.phrases)
    if args.phrases_file:
        with open(args.phrases_file, encoding="utf-8") as f:
            out.extend(
                line.strip() for line in f
                if line.strip() and not line.strip().startswith("#")
            )
    if not out:
        sys.exit("[ОШИБКА] Укажи --phrases или --phrases-file.")
    return out


def run(args, with_ideas: bool, sheet: str):
    token = _load_token(args.token)
    rows = _generate(token, _phrases(args), args.geo, with_ideas)
    if args.top and args.top > 0:
        rows = rows[:args.top]
    write_xlsx(args.out, sheet, rows)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Яндекс Wordstat (Yandex Direct API v4 Live)")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--phrases", nargs="+")
        sp.add_argument("--phrases-file")
        sp.add_argument("--token", help="OAuth-токен Яндекс.Директа (или env YANDEX_DIRECT_TOKEN)")
        sp.add_argument("--geo", nargs="+", default=[DEFAULT_GEO],
                        help=f"GeoID регионов (по умолч. {DEFAULT_GEO}=Казахстан)")
        sp.add_argument("--top", type=int, default=0,
                        help="ограничить вывод N самыми частотными строками (0 = без лимита)")
        sp.add_argument("--out", required=True, help="Путь к .xlsx")

    sp = sub.add_parser("ideas", help="Расширить засев связанными запросами + частоты")
    common(sp)
    sp.set_defaults(func=lambda a: run(a, with_ideas=True, sheet="Семантическое ядро"))

    sp = sub.add_parser("volume", help="Только частоты по своим фразам (без расширения)")
    common(sp)
    sp.set_defaults(func=lambda a: run(a, with_ideas=False, sheet="Частоты"))

    sp = sub.add_parser(
        "import",
        help="Выгрузка «Скачать» из веба wordstat.yandex.ru → .xlsx нашей схемы (БЕЗ API/токена)")
    sp.add_argument("--file", required=True,
                    help="файл «Скачать» из Wordstat (.xlsx или .csv)")
    sp.add_argument("--out", required=True, help="путь к .xlsx результата")
    sp.set_defaults(func=lambda a: write_xlsx(a.out, "Импорт Wordstat", import_web(a.file)))

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
