#!/usr/bin/env python3
"""
gkp_client.py — детерминированный клиент Google Keyword Planner (Google Ads API).

Принцип WAT: AI-решения (подбор засева, кластеризация, выводы) — в чате.
Этот инструмент только дёргает API и пишет файлы.

Формат вывода (7-колоночная .xlsx) подхватывает product-discovery-skill
для кластеризации спроса по темам рынка.

Авторизация: через google-ads.yaml (по умолчанию ~/google-ads.yaml) или переменные
окружения GOOGLE_ADS_*. Customer ID — флаг --customer или env GOOGLE_ADS_CUSTOMER_ID.
Настройка — см. references/setup.md.

Команды:
  ideas   — идеи ключевых слов из засева (расширяет семантику) + объёмы
  volume  — исторические метрики по фиксированному списку фраз (без расширения)

Гео по умолчанию: Казахстан (geoTargetConstants/2398). Язык: русский (languageConstants/1031).
Другие ID — references/geo_targets.md.
"""

import argparse
import base64
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

# Лимит сид-фраз в одном запросе GenerateKeywordIdeas
SEED_CHUNK = 20
DEFAULT_GEO = "2398"       # Казахстан
DEFAULT_LANG = "1031"      # русский (languageConstants для Google Ads API)
DEFAULT_LANG_CODE = "ru"   # language_code для DataForSEO
GAYAML_DEFAULT = os.path.expanduser("~/google-ads.yaml")

# DataForSEO (Путь C — без аккаунта Google Ads и без карты)
DFS_API = "https://api.dataforseo.com/v3"
DFS_YAML_DEFAULT = os.path.expanduser("~/dataforseo.yaml")
DFS_VOLUME_MAX = 1000      # лимит фраз на search_volume/live
DFS_THROTTLE = 5           # сек между запросами (лимит live-эндпоинтов ~12/мин)


def _load_client():
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError:
        sys.exit("[ОШИБКА] Нет библиотеки google-ads. Установи: pip install google-ads")

    yaml_path = os.environ.get("GOOGLE_ADS_CONFIGURATION_FILE_PATH", GAYAML_DEFAULT)
    if os.path.exists(yaml_path):
        return GoogleAdsClient.load_from_storage(yaml_path)
    # запасной вариант — из переменных окружения GOOGLE_ADS_*
    try:
        return GoogleAdsClient.load_from_env()
    except Exception as exc:  # noqa: BLE001
        sys.exit(
            f"[ОШИБКА] Не удалось загрузить конфигурацию Google Ads.\n"
            f"Ожидался файл {yaml_path} или переменные GOOGLE_ADS_*.\n"
            f"См. references/setup.md. Детали: {exc}"
        )


def _customer_id(arg: Optional[str]) -> str:
    cid = (arg or os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "")).replace("-", "").strip()
    if not cid:
        sys.exit("[ОШИБКА] Укажи --customer XXXXXXXXXX или env GOOGLE_ADS_CUSTOMER_ID (без дефисов).")
    return cid


def _micros_to_unit(micros: Optional[int]) -> Optional[float]:
    if micros is None:
        return None
    return round(micros / 1_000_000, 2)


def _chunks(seq: List[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _generate(client, customer_id: str, phrases: List[str],
              geo_ids: List[str], lang_id: str,
              with_ideas: bool) -> List[Dict[str, Any]]:
    service = client.get_service("KeywordPlanIdeaService")
    rows: List[Dict[str, Any]] = []

    # GenerateKeywordIdeas с keyword_seed возвращает И сами фразы, И идеи.
    # Чанкуем засев по 20 фраз на запрос.
    for chunk in _chunks(phrases, SEED_CHUNK):
        request = client.get_type("GenerateKeywordIdeasRequest")
        request.customer_id = customer_id
        request.language = f"languageConstants/{lang_id}"
        for gid in geo_ids:
            request.geo_target_constants.append(f"geoTargetConstants/{gid}")
        request.keyword_plan_network = (
            client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
        )
        request.keyword_seed.keywords.extend(chunk)

        try:
            response = service.generate_keyword_ideas(request=request)
        except Exception as exc:  # GoogleAdsException и пр.
            sys.exit(f"[ОШИБКА] GenerateKeywordIdeas: {exc}")

        seed_set = {c.lower() for c in chunk}
        for idea in response:
            m = idea.keyword_idea_metrics
            text = idea.text
            is_seed = text.lower() in seed_set
            # Если запросили только объёмы по своим фразам — отдаём только их.
            if not with_ideas and not is_seed:
                continue
            rows.append({
                "запрос": text,
                "тип": "засев" if is_seed else "идея",
                "ср_частота_мес": m.avg_monthly_searches,
                "конкуренция": m.competition.name if m.competition else None,
                "индекс_конкуренции": m.competition_index,
                "ставка_верх_TOP": _micros_to_unit(m.high_top_of_page_bid_micros),
                "ставка_низ_TOP": _micros_to_unit(m.low_top_of_page_bid_micros),
            })

    # дедуп по тексту запроса, сортировка по объёму
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for r in sorted(rows, key=lambda x: -(x["ср_частота_мес"] or 0)):
        if r["запрос"] in seen:
            continue
        seen.add(r["запрос"])
        uniq.append(r)
    return uniq


# ---------------------------------------------------------------------------
# Бэкенд DataForSEO (Путь C — те же объёмы Keyword Planner по KZ,
# но без аккаунта Google Ads и без карты; нужен только логин/пароль DataForSEO).
# Выдаёт ту же 7-колоночную схему, что и Google Ads API.
# ---------------------------------------------------------------------------

def _read_yaml_kv(path: str, keys: set) -> Dict[str, str]:
    # минимальный парсер «ключ: значение» без PyYAML
    out: Dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                k, _, v = line.partition(":")
                k = k.strip().lower()
                if k in keys:
                    out[k] = v.strip().strip('"').strip("'")
    except OSError:
        return {}
    return out


def _dfs_auth(arg_login: Optional[str], arg_password: Optional[str]) -> str:
    login = arg_login or os.environ.get("DATAFORSEO_LOGIN", "")
    password = arg_password or os.environ.get("DATAFORSEO_PASSWORD", "")
    if not (login and password):
        path = os.environ.get("DATAFORSEO_CONFIGURATION_FILE_PATH", DFS_YAML_DEFAULT)
        if os.path.exists(path):
            kv = _read_yaml_kv(path, {"login", "password"})
            login = login or kv.get("login", "")
            password = password or kv.get("password", "")
    if not (login and password):
        sys.exit("[ОШИБКА] Нет кредов DataForSEO. Укажи --dfs-login/--dfs-password, "
                 "env DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD или ~/dataforseo.yaml. "
                 "См. references/setup.md.")
    return base64.b64encode(f"{login}:{password}".encode("utf-8")).decode("ascii")


def _dfs_post(auth: str, path: str, payload: Any) -> List[Dict[str, Any]]:
    url = f"{DFS_API}/{path}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        sys.exit(f"[ОШИБКА] DataForSEO HTTP {exc.code}: {detail[:300]}")
    except urllib.error.URLError as exc:
        sys.exit(f"[ОШИБКА] DataForSEO сеть: {exc}")
    if data.get("status_code") != 20000:
        sys.exit(f"[ОШИБКА] DataForSEO: {data.get('status_code')} {data.get('status_message')}")
    tasks = data.get("tasks") or []
    if not tasks:
        return []
    task = tasks[0]
    if task.get("status_code") != 20000:
        sys.exit(f"[ОШИБКА] DataForSEO task: {task.get('status_code')} {task.get('status_message')}")
    return task.get("result") or []


def _dfs_row(item: Dict[str, Any], seed_set: set) -> Dict[str, Any]:
    kw = (item.get("keyword") or "").strip()
    comp = item.get("competition")
    if isinstance(comp, str):
        comp = comp.upper()
    high = item.get("high_top_of_page_bid")
    low = item.get("low_top_of_page_bid")
    return {
        "запрос": kw,
        "тип": "засев" if _norm(kw) in seed_set else "идея",
        "ср_частота_мес": item.get("search_volume"),
        "конкуренция": comp,
        "индекс_конкуренции": item.get("competition_index"),
        "ставка_верх_TOP": round(high, 2) if isinstance(high, (int, float)) else None,
        "ставка_низ_TOP": round(low, 2) if isinstance(low, (int, float)) else None,
    }


def _generate_dfs(auth: str, phrases: List[str], location_code: int,
                  lang_code: str, with_ideas: bool) -> List[Dict[str, Any]]:
    seed_set = {_norm(p) for p in phrases}
    rows: List[Dict[str, Any]] = []

    if with_ideas:
        # keywords_for_keywords: до 20 сид-фраз на запрос, отдаёт И засев, И идеи.
        endpoint = "keywords_data/google_ads/keywords_for_keywords/live"
        chunk_size = SEED_CHUNK
    else:
        # search_volume: только объёмы по своим фразам, до 1000 за запрос.
        endpoint = "keywords_data/google_ads/search_volume/live"
        chunk_size = DFS_VOLUME_MAX

    for i, chunk in enumerate(_chunks(phrases, chunk_size)):
        if i:
            time.sleep(DFS_THROTTLE)
        payload = [{
            "keywords": chunk,
            "location_code": location_code,
            "language_code": lang_code,
        }]
        for item in _dfs_post(auth, endpoint, payload):
            rows.append(_dfs_row(item, seed_set))

    # дедуп по тексту запроса, сортировка по объёму (как в _generate)
    seen: set = set()
    uniq: List[Dict[str, Any]] = []
    for r in sorted(rows, key=lambda x: -(x["ср_частота_мес"] or 0)):
        if not r["запрос"] or r["запрос"] in seen:
            continue
        seen.add(r["запрос"])
        uniq.append(r)
    return uniq


# ---------------------------------------------------------------------------
# Импорт CSV-экспорта из веб-Планировщика (Путь A — без API/токена)
#
# Веб-Планировщик (ads.google.com → Инструменты → Планировщик ключевых слов)
# работает с любым бесплатным аккаунтом Google Ads, без developer-токена и без
# одобрения Basic access. Кнопка «Скачать варианты ключевых слов» отдаёт CSV.
# Этот режим приводит такой CSV к нашей схеме .xlsx (как у API-пути).
# ---------------------------------------------------------------------------

# Алиасы заголовков Google Keyword Planner (en + ru-локаль экспорта).
# Резолвятся от самого специфичного к общему, чтобы «Конкуренция» не перехватила
# «Конкуренция (индексированное значение)».
def _norm(s: str) -> str:
    return (s or "").replace("﻿", "").replace("\xa0", " ").strip().lower()


def _read_csv_text(path: str) -> str:
    for enc in ("utf-16", "utf-8-sig", "utf-8", "cp1251"):
        try:
            with open(path, "r", encoding=enc, newline="") as fh:
                return fh.read()
        except (UnicodeError, LookupError):
            continue
    sys.exit(f"[ОШИБКА] Не смог прочитать {path} (кодировка). "
             f"Пересохрани экспорт как UTF-8 или UTF-16.")


def _csv_rows(text: str) -> List[List[str]]:
    sample = "\n".join(text.splitlines()[:8])
    delim = "\t" if sample.count("\t") >= sample.count(",") else ","
    return list(csv.reader(io.StringIO(text), delimiter=delim))


def _find_header(rows: List[List[str]]) -> int:
    # Заголовок — первая многоколоночная строка с ячейкой про ключевое слово
    # (однострочный титул отчёта вида «Keyword Stats report» пропускаем).
    for i, row in enumerate(rows):
        if len(row) < 2:
            continue
        for cell in row:
            n = _norm(cell)
            if n in ("keyword", "ключевое слово", "ключевые слова") or n.startswith("keyword"):
                return i
    sys.exit("[ОШИБКА] В CSV не нашёл строку-заголовок со столбцом «Ключевое слово»/«Keyword». "
             "Это точно экспорт вариантов ключей из Планировщика?")


def _map_columns(header: List[str]) -> Dict[str, int]:
    cols = {i: _norm(h) for i, h in enumerate(header)}
    used: set = set()

    def pick(pred) -> Optional[int]:
        for i, n in cols.items():
            if i in used or not n:
                continue
            if pred(n):
                used.add(i)
                return i
        return None

    idx: Dict[str, int] = {}
    # порядок важен: специфичные раньше общих
    m = pick(lambda n: "indexed" in n or "индексир" in n)
    if m is not None:
        idx["индекс_конкуренции"] = m
    m = pick(lambda n: ("low" in n or "минимум" in n or "нижн" in n)
             and ("bid" in n or "ставк" in n))
    if m is not None:
        idx["ставка_низ_TOP"] = m
    m = pick(lambda n: ("high" in n or "максимум" in n or "верхн" in n)
             and ("bid" in n or "ставк" in n))
    if m is not None:
        idx["ставка_верх_TOP"] = m
    m = pick(lambda n: "competition" in n or "конкуренц" in n)
    if m is not None:
        idx["конкуренция"] = m
    m = pick(lambda n: "monthly searches" in n or "запросов в месяц" in n
             or n.startswith("avg") or "среднее число" in n or "ср. число" in n)
    if m is not None:
        idx["ср_частота_мес"] = m
    m = pick(lambda n: "keyword" in n or "ключев" in n)
    if m is not None:
        idx["запрос"] = m

    if "запрос" not in idx or "ср_частота_мес" not in idx:
        sys.exit("[ОШИБКА] Не распознал столбцы «запрос» и «частота» в заголовке CSV. "
                 f"Заголовок: {header}")
    return idx


def _num(val: Any) -> float:
    if val is None:
        return 0.0
    s = str(val).replace("\xa0", " ").replace(" ", "").replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*([kmкм]?)", s.lower())
    if not m:
        return 0.0
    n = float(m.group(1))
    suf = m.group(2)
    if suf in ("k", "к"):
        n *= 1_000
    elif suf in ("m", "м"):
        n *= 1_000_000
    return n


def _freq_value(raw: str) -> Any:
    # Чистое целое (точный объём) → int; диапазон/прочее («1 тыс. – 10 тыс.») → строка.
    s = (raw or "").replace("\xa0", " ").replace(" ", "").replace(",", "")
    if s.isdigit():
        return int(s)
    return (raw or "").strip() or None


def import_csv(csv_path: str) -> List[Dict[str, Any]]:
    rows = _csv_rows(_read_csv_text(csv_path))
    h = _find_header(rows)
    idx = _map_columns(rows[h])
    out: List[Dict[str, Any]] = []
    for row in rows[h + 1:]:
        if not row:
            continue
        kw = row[idx["запрос"]].strip() if idx["запрос"] < len(row) else ""
        if not kw:
            continue

        def cell(key: str) -> Optional[str]:
            j = idx.get(key)
            if j is None or j >= len(row):
                return None
            v = row[j].strip()
            return v or None

        out.append({
            "запрос": kw,
            "тип": "идея",
            "ср_частота_мес": _freq_value(cell("ср_частота_мес")),
            "конкуренция": cell("конкуренция"),
            "индекс_конкуренции": cell("индекс_конкуренции"),
            "ставка_верх_TOP": cell("ставка_верх_TOP"),
            "ставка_низ_TOP": cell("ставка_низ_TOP"),
        })

    seen: set = set()
    uniq: List[Dict[str, Any]] = []
    for r in sorted(out, key=lambda x: -_num(x["ср_частота_мес"])):
        if r["запрос"] in seen:
            continue
        seen.add(r["запрос"])
        uniq.append(r)
    return uniq


# ---------------------------------------------------------------------------
# Excel (7-колоночная схема навыка)
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
        ws["A1"] = "нет данных (проверь доступ к API и гео/язык)"
        wb.save(path)
        print(f"[OK] Пустой результат → {path}")
        return

    headers = list(rows[0].keys())
    ws.append(headers)
    fill = PatternFill("solid", fgColor="2E7D32")
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
    phrases = _phrases(args)
    if args.backend == "dataforseo":
        auth = _dfs_auth(args.dfs_login, args.dfs_password)
        try:
            location_code = int(args.geo[0])
        except (ValueError, IndexError):
            sys.exit("[ОШИБКА] Для DataForSEO --geo должен быть числовым location_code "
                     "(по умолч. 2398=Казахстан).")
        rows = _generate_dfs(auth, phrases, location_code, args.lang_code, with_ideas)
    else:
        client = _load_client()
        cid = _customer_id(args.customer)
        rows = _generate(client, cid, phrases, args.geo, args.lang, with_ideas)
    write_xlsx(args.out, sheet, rows)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Google Keyword Planner (Google Ads API)")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--phrases", nargs="+")
        sp.add_argument("--phrases-file")
        sp.add_argument("--backend", choices=["dataforseo", "ads"], default="dataforseo",
                        help="Источник: dataforseo (по умолч., без аккаунта Google/карты) "
                             "или ads (официальный Google Ads API)")
        sp.add_argument("--customer", help="Customer ID для backend=ads (без дефисов)")
        sp.add_argument("--dfs-login", help="Логин DataForSEO (или env DATAFORSEO_LOGIN)")
        sp.add_argument("--dfs-password", help="Пароль DataForSEO (или env DATAFORSEO_PASSWORD)")
        sp.add_argument("--geo", nargs="+", default=[DEFAULT_GEO],
                        help=f"Гео: location_code для dataforseo / geoTargetConstants для ads "
                             f"(по умолч. {DEFAULT_GEO}=Казахстан)")
        sp.add_argument("--lang", default=DEFAULT_LANG,
                        help=f"ID языка для backend=ads (по умолч. {DEFAULT_LANG}=русский)")
        sp.add_argument("--lang-code", default=DEFAULT_LANG_CODE,
                        help=f"language_code для backend=dataforseo "
                             f"(по умолч. {DEFAULT_LANG_CODE}=русский)")
        sp.add_argument("--out", required=True, help="Путь к .xlsx")

    sp = sub.add_parser("ideas", help="Расширить засев идеями ключей + объёмы")
    common(sp)
    sp.set_defaults(func=lambda a: run(a, with_ideas=True, sheet="Семантическое ядро"))

    sp = sub.add_parser("volume", help="Только объёмы по своим фразам (без расширения)")
    common(sp)
    sp.set_defaults(func=lambda a: run(a, with_ideas=False, sheet="Объёмы"))

    sp = sub.add_parser("import",
                        help="CSV из веб-Планировщика → .xlsx нашей схемы (без API/токена)")
    sp.add_argument("--csv", required=True, help="Путь к CSV-экспорту Keyword Planner")
    sp.add_argument("--out", required=True, help="Путь к .xlsx")
    sp.set_defaults(func=lambda a: write_xlsx(a.out, "Импорт KWP", import_csv(a.csv)))

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
