#!/usr/bin/env python3
"""
bot.py — Telegram-бот-витрина для съёма спроса Google (KZ).

Что делает. По командам в Telegram отдаёт аналитику конвейера проекта:
  /themes  — кластеры спроса по темам рынка (через product-discovery-skill)
  /top     — топ-запросы по частоте из текущей выгрузки
  /demand  — расширить фразу в кандидатов + найти её в выгрузке (бесплатно);
             с опцией `live` — снять свежий спрос через DataForSEO (если есть креды)
  /report  — прислать текущий .xlsx файлом
  /status  — что сейчас в работе и какая выгрузка активна

Бесплатный путь (без платного API). Бот работает поверх ГОТОВЫХ выгрузок .xlsx.
Их можно получить даром: в веб-Планировщике Google нажать «Скачать варианты
ключевых слов» → прислать CSV боту документом → бот сам импортирует его в .xlsx
(режим import из gkp_client, без аккаунта Ads и без карты) и сделает активным.
Можно прислать и готовый .xlsx — бот возьмёт его как текущий датасет.

Очередь. Долгий live-съём через DataForSEO троттлится (5 c между запросами и
лимит live-эндпоинтов), поэтому такие задачи ставятся в ОЧЕРЕДЬ и выполняются по
одной — бот пишет позицию в очереди и статус. Быстрые команды (themes/top/report)
исполняются сразу.

Принцип проекта (WAT): механика (раскрытие шаблонов, кластеризация, парсинг) —
в переиспользуемых скриптах навыков; этот файл лишь связывает их с Telegram.

Запуск:
  pip install -r telegram-bot-skill/requirements.txt
  export TELEGRAM_BOT_TOKEN=123:ABC...      # токен от @BotFather
  # (опционально) export ALLOWED_USERS=11111111,22222222   # белый список id
  # (опционально, для /demand live) ~/dataforseo.yaml с login/password
  python telegram-bot-skill/scripts/bot.py

Хостинг бесплатный: long-polling не требует публичного домена/сервера — бот
крутится хоть на ноутбуке, хоть на бесплатном VPS. Контейнер Claude эфемерный,
постоянно держать бота в нём нельзя — запускай у себя.
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

# --- подключаем переиспользуемые скрипты навыков -----------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # корень репозитория
sys.path.insert(0, os.path.join(ROOT, "google-kwp-skill", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "product-discovery-skill", "scripts"))

import gkp_client          # noqa: E402  import_csv / write_xlsx / _dfs_auth / _generate_dfs
import cluster_demand      # noqa: E402  read_xlsx / cluster / DEFAULT_THEMES
import expand_seeds        # noqa: E402  expand_one / with_geo / dedup

try:
    from telegram import Update
    from telegram.constants import ChatAction, ParseMode
    from telegram.ext import (
        Application, CommandHandler, ContextTypes, MessageHandler, filters,
    )
except ImportError:
    sys.exit("[ОШИБКА] Нет python-telegram-bot. Установи: "
             "pip install -r telegram-bot-skill/requirements.txt")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# httpx на уровне INFO пишет полный URL запроса — а в нём токен бота. Приглушаем,
# чтобы токен не утекал в логи (Railway/stdout).
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("seo-bot")

DATA_DIR = os.environ.get("BOT_DATA_DIR", os.path.join(ROOT, "bot_data"))
STATE_FILE = os.path.join(DATA_DIR, "state.json")
DEFAULT_GEO = gkp_client.DEFAULT_GEO            # 2398 = Казахстан
DEFAULT_LANG_CODE = gkp_client.DEFAULT_LANG_CODE  # ru
TG_LIMIT = 3900  # запас под лимит сообщения Telegram (4096)


# --- ошибки и «обёртка» вокруг скриптов, которые зовут sys.exit --------------
class SkillError(Exception):
    """Ошибка переиспользуемого скрипта (он зовёт sys.exit — перехватываем)."""


def guard(fn: Callable, *args, **kwargs):
    """Вызвать функцию навыка, превратив её sys.exit(...) в SkillError."""
    try:
        return fn(*args, **kwargs)
    except SystemExit as exc:
        msg = exc.code if isinstance(exc.code, str) else "инструмент завершился с ошибкой"
        raise SkillError(str(msg)) from exc


# --- состояние (какая выгрузка активна) --------------------------------------
def load_state() -> Dict[str, Any]:
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def current_xlsx(app) -> Optional[str]:
    """Путь к активной выгрузке: из состояния, иначе свежайший .xlsx в DATA_DIR/корне."""
    path = app.bot_data["state"].get("xlsx")
    if path and os.path.exists(path):
        return path
    candidates: List[str] = []
    for d in (DATA_DIR, ROOT):
        if os.path.isdir(d):
            candidates += [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".xlsx")]
    candidates = [c for c in candidates if os.path.exists(c)]
    if not candidates:
        return None
    newest = max(candidates, key=os.path.getmtime)
    set_current_xlsx(app, newest)
    return newest


def set_current_xlsx(app, path: str) -> None:
    app.bot_data["state"]["xlsx"] = path
    save_state(app.bot_data["state"])


# --- доступ (белый список) ----------------------------------------------------
def allowed(update: Update) -> bool:
    ids = os.environ.get("ALLOWED_USERS", "").replace(" ", "")
    if not ids:
        return True  # список не задан — доступ всем
    user = update.effective_user
    return bool(user) and str(user.id) in set(ids.split(","))


# === ВЫЧИСЛЕНИЯ (синхронные, гоняем в asyncio.to_thread) =====================

def do_cluster(xlsx_path: str, top_themes: int) -> str:
    """Кластеры спроса по темам из текущей выгрузки → текст для Telegram."""
    items = guard(cluster_demand.read_xlsx, xlsx_path)
    summary, other = guard(cluster_demand.cluster, items, cluster_demand.DEFAULT_THEMES, 3)
    if not summary:
        return "Темы не выделились — в выгрузке нет распознанных запросов."
    lines = [f"📊 <b>Темы спроса</b> ({os.path.basename(xlsx_path)})", ""]
    for r in summary[:top_themes]:
        lines.append(
            f"• <b>{esc(r['тема'])}</b> — {r['суммарная_частота']} /мес "
            f"({r['доля_%']}%), запросов: {r['запросов']}"
        )
        if r["топ_запросы"]:
            lines.append(f"   <i>{esc(r['топ_запросы'][:180])}</i>")
    if other:
        head = ", ".join(q for q, _ in other[:5])
        lines.append("")
        lines.append(f"🗂 Прочее (не попало в темы): {len(other)} — {esc(head)}")
    return clip("\n".join(lines))


def do_top(xlsx_path: str, n: int) -> str:
    """Топ-N запросов по частоте из текущей выгрузки → текст."""
    items = guard(cluster_demand.read_xlsx, xlsx_path)
    best: Dict[str, float] = {}
    case: Dict[str, str] = {}
    for q, f in items:
        k = q.lower()
        case.setdefault(k, q)
        if k not in best or f > best[k]:
            best[k] = f
    rows = sorted(((case[k], v) for k, v in best.items()), key=lambda x: -x[1])[:n]
    if not rows:
        return "В выгрузке нет запросов."
    lines = [f"🔝 <b>Топ-{len(rows)} запросов</b> ({os.path.basename(xlsx_path)})", ""]
    for i, (q, f) in enumerate(rows, 1):
        lines.append(f"{i:>2}. {esc(q)} — <b>{round(f)}</b>/мес")
    return clip("\n".join(lines))


def do_expand(phrase: str) -> List[str]:
    """Бесплатно: раскрыть фразу в кандидатов (коммерция + боль + гео РК)."""
    phrases = guard(expand_seeds.expand_one, phrase, ["cost", "service", "problem"])
    phrases = guard(expand_seeds.with_geo, phrases)
    return guard(expand_seeds.dedup, phrases)


def do_search(xlsx_path: Optional[str], phrase: str, limit: int = 15) -> List[Tuple[str, float]]:
    """Найти фразу (подстрокой) в текущей выгрузке → [(запрос, частота)]."""
    if not xlsx_path:
        return []
    items = guard(cluster_demand.read_xlsx, xlsx_path)
    needle = phrase.lower().strip()
    hits = [(q, f) for q, f in items if needle in q.lower()]
    hits.sort(key=lambda x: -x[1])
    return hits[:limit]


def do_live_demand(phrase: str, geo: str, lang_code: str) -> Tuple[str, str]:
    """Платный/live: снять свежий спрос по фразе через DataForSEO. → (текст, путь_xlsx)."""
    auth = guard(gkp_client._dfs_auth, None, None)  # креды из ~/dataforseo.yaml или env
    seeds = do_expand(phrase)[:50]                  # ограничим, чтобы не жечь лимиты
    rows = guard(gkp_client._generate_dfs, auth, seeds, int(geo), lang_code, True)
    os.makedirs(DATA_DIR, exist_ok=True)
    safe = "".join(c if c.isalnum() else "_" for c in phrase)[:40] or "demand"
    out = os.path.join(DATA_DIR, f"demand_{safe}_{int(time.time())}.xlsx")
    guard(gkp_client.write_xlsx, out, "Съём по фразе", rows)
    top = sorted(rows, key=lambda r: -(r.get("ср_частота_мес") or 0))[:12]
    lines = [f"✅ <b>Live-съём «{esc(phrase)}»</b>: {len(rows)} запросов", ""]
    for r in top:
        lines.append(f"• {esc(str(r['запрос']))} — <b>{r.get('ср_частота_мес') or 0}</b>/мес")
    lines.append("")
    lines.append("Файл стал текущим. /themes — кластеры, /report — выгрузка.")
    return clip("\n".join(lines)), out


def do_import_csv(csv_path: str) -> Tuple[str, int]:
    """Бесплатно: CSV из веб-Планировщика → .xlsx нашей схемы. → (путь, число_строк)."""
    rows = guard(gkp_client.import_csv, csv_path)
    os.makedirs(DATA_DIR, exist_ok=True)
    out = os.path.join(DATA_DIR, f"import_{int(time.time())}.xlsx")
    guard(gkp_client.write_xlsx, out, "Импорт KWP", rows)
    return out, len(rows)


# --- утилиты форматирования ---------------------------------------------------
def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clip(text: str) -> str:
    return text if len(text) <= TG_LIMIT else text[:TG_LIMIT] + "\n…(обрезано)"


def parse_int_arg(args: List[str], default: int) -> int:
    for a in args:
        if a.isdigit():
            return max(1, min(int(a), 100))
    return default


# === ОЧЕРЕДЬ ЗАДАЧ ============================================================
async def queue_worker(app) -> None:
    """Фоновый исполнитель: тянет задачи из очереди и выполняет ПО ОДНОЙ."""
    q: asyncio.Queue = app.bot_data["queue"]
    while True:
        job = await q.get()
        app.bot_data["busy"] = True
        try:
            await job()
        except SkillError as exc:
            log.warning("job SkillError: %s", exc)
            await _safe_send(app, job, f"❌ {exc}")
        except Exception:  # noqa: BLE001
            log.exception("job упала")
            await _safe_send(app, job, "❌ Внутренняя ошибка задачи (см. логи бота).")
        finally:
            app.bot_data["busy"] = False
            q.task_done()


async def _safe_send(app, job, text: str) -> None:
    chat_id = getattr(job, "chat_id", None)
    if chat_id is not None:
        try:
            await app.bot.send_message(chat_id, text)
        except Exception:  # noqa: BLE001
            pass


async def enqueue(context: ContextTypes.DEFAULT_TYPE, chat_id: int, coro_factory) -> int:
    """Поставить задачу в очередь, вернуть её позицию (1 = выполнится следующей/сейчас)."""
    q: asyncio.Queue = context.application.bot_data["queue"]
    busy = context.application.bot_data["busy"]

    async def job():
        await coro_factory()
    job.chat_id = chat_id  # для _safe_send при падении

    position = q.qsize() + (1 if busy else 0) + 1
    await q.put(job)
    return position


# === ХЕНДЛЕРЫ КОМАНД ==========================================================
HELP = (
    "🤖 <b>Бот съёма спроса Google (KZ)</b>\n\n"
    "Я отдаю аналитику по выгрузкам поискового спроса. Конвейер проекта:\n"
    "<code>засев → расширение → съём → кластеры → отчёт</code>\n\n"
    "<b>Команды</b>\n"
    "/themes [N] — кластеры спроса по темам (топ N тем, по умолч. 10)\n"
    "/top [N] — топ-N запросов по частоте (по умолч. 15)\n"
    "/demand &lt;фраза&gt; — расширить фразу и найти её в выгрузке (бесплатно)\n"
    "/demand &lt;фраза&gt; live — снять свежий спрос через DataForSEO (в очередь)\n"
    "/report — прислать текущую выгрузку .xlsx файлом\n"
    "/status — что в работе и какая выгрузка активна\n\n"
    "<b>Загрузка данных (бесплатно)</b>\n"
    "Пришли мне <b>CSV</b> из веб-Планировщика Google (кнопка «Скачать варианты "
    "ключевых слов») — я импортирую его в .xlsx и сделаю активным. Можно прислать "
    "и готовый <b>.xlsx</b> нашей схемы."
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    await update.message.reply_text(HELP, parse_mode=ParseMode.HTML)


async def cmd_themes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    path = current_xlsx(context.application)
    if not path:
        await update.message.reply_text(_no_data(), parse_mode=ParseMode.HTML)
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    n = parse_int_arg(context.args, 10)
    text = await asyncio.to_thread(_run_guarded, do_cluster, path, n)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    path = current_xlsx(context.application)
    if not path:
        await update.message.reply_text(_no_data(), parse_mode=ParseMode.HTML)
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    n = parse_int_arg(context.args, 15)
    text = await asyncio.to_thread(_run_guarded, do_top, path, n)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_demand(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    args = list(context.args)
    is_live = bool(args) and args[-1].lower() == "live"
    if is_live:
        args = args[:-1]
    phrase = " ".join(args).strip()
    if not phrase:
        await update.message.reply_text(
            "Укажи фразу: <code>/demand госэкспертиза</code> или "
            "<code>/demand госэкспертиза live</code>", parse_mode=ParseMode.HTML)
        return

    if is_live:
        await _demand_live(update, context, phrase)
    else:
        await _demand_free(update, context, phrase)


async def _demand_free(update: Update, context: ContextTypes.DEFAULT_TYPE, phrase: str) -> None:
    """Бесплатно: раскрыть фразу + найти в текущей выгрузке + прислать кандидатов файлом."""
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    path = current_xlsx(context.application)
    candidates: List[str] = await asyncio.to_thread(_run_guarded_list, do_expand, phrase)
    hits: List[Tuple[str, float]] = await asyncio.to_thread(do_search, path, phrase)

    lines = [f"🔎 <b>«{esc(phrase)}»</b>", ""]
    if hits:
        lines.append("Найдено в текущей выгрузке:")
        for q, f in hits:
            lines.append(f"• {esc(q)} — <b>{round(f)}</b>/мес")
    else:
        lines.append("В текущей выгрузке совпадений нет"
                     + ("." if path else " (выгрузка не загружена)."))
    lines.append("")
    lines.append(f"Сгенерировал <b>{len(candidates)}</b> кандидатов для съёма "
                 f"(коммерция + боль + гео РК) — файл ниже.")
    lines.append("Снять по ним свежий спрос: <code>/demand "
                 f"{esc(phrase)} live</code> (нужны креды DataForSEO).")
    await update.message.reply_text(clip("\n".join(lines)), parse_mode=ParseMode.HTML)

    # кандидаты — отдельным .txt, чтобы их можно было прогнать вручную в Планировщике
    if candidates:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                         encoding="utf-8") as fh:
            fh.write("\n".join(candidates) + "\n")
            tmp = fh.name
        try:
            with open(tmp, "rb") as doc:
                await context.bot.send_document(
                    update.effective_chat.id, doc,
                    filename=f"candidates_{phrase[:30].strip().replace(' ', '_')}.txt",
                    caption="Кандидаты для съёма (вставь в веб-Планировщик Google)")
        finally:
            os.unlink(tmp)


async def _demand_live(update: Update, context: ContextTypes.DEFAULT_TYPE, phrase: str) -> None:
    """Live-съём через DataForSEO — ставим в ОЧЕРЕДЬ (долго и троттлится)."""
    if not _dfs_creds_present():
        await update.message.reply_text(
            "⚠️ Для <code>live</code> нужны креды DataForSEO "
            "(<code>~/dataforseo.yaml</code> или env DATAFORSEO_LOGIN/PASSWORD).\n"
            "Без них работает бесплатный путь: <code>/demand "
            f"{esc(phrase)}</code> + импорт CSV из веб-Планировщика.",
            parse_mode=ParseMode.HTML)
        return

    chat_id = update.effective_chat.id
    status = await update.message.reply_text("⏳ ставлю в очередь…")

    async def task():
        await context.bot.edit_message_text(
            "⏳ Снимаю свежий спрос через DataForSEO… это может занять минуту.",
            chat_id=chat_id, message_id=status.message_id)
        text, out = await asyncio.to_thread(do_live_demand, phrase, DEFAULT_GEO, DEFAULT_LANG_CODE)
        set_current_xlsx(context.application, out)
        await context.bot.edit_message_text(text, chat_id=chat_id,
                                             message_id=status.message_id,
                                             parse_mode=ParseMode.HTML)

    pos = await enqueue(context, chat_id, task)
    if pos > 1:
        await context.bot.edit_message_text(
            f"⏳ В очереди, позиция {pos}. Выполню, как освобожусь.",
            chat_id=chat_id, message_id=status.message_id)


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    path = current_xlsx(context.application)
    if not path:
        await update.message.reply_text(_no_data(), parse_mode=ParseMode.HTML)
        return
    with open(path, "rb") as doc:
        await context.bot.send_document(
            update.effective_chat.id, doc, filename=os.path.basename(path),
            caption="Текущая выгрузка спроса (.xlsx)")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    app = context.application
    path = current_xlsx(app)
    qsize = app.bot_data["queue"].qsize()
    busy = app.bot_data["busy"]
    lines = [
        "📟 <b>Статус</b>",
        f"Активная выгрузка: <code>{esc(os.path.basename(path)) if path else '— нет —'}</code>",
        f"В очереди задач: {qsize}",
        f"Сейчас выполняется: {'да' if busy else 'нет'}",
        f"DataForSEO (live): {'доступен' if _dfs_creds_present() else 'нет кредов'}",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Приём файла: CSV → импорт в .xlsx (бесплатно); .xlsx → сделать активным."""
    if not allowed(update):
        return
    doc = update.message.document
    name = (doc.file_name or "").lower()
    if not (name.endswith(".csv") or name.endswith(".xlsx")):
        await update.message.reply_text(
            "Пришли .csv (экспорт Планировщика) или .xlsx нашей схемы.")
        return

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    os.makedirs(DATA_DIR, exist_ok=True)
    tg_file = await doc.get_file()
    local = os.path.join(DATA_DIR, f"upload_{int(time.time())}_{os.path.basename(name)}")
    await tg_file.download_to_drive(local)

    try:
        if name.endswith(".csv"):
            out, n = await asyncio.to_thread(do_import_csv, local)
            set_current_xlsx(context.application, out)
            msg = (f"✅ Импортировал CSV → {n} запросов. Выгрузка стала активной.\n"
                   "Дальше: /themes — кластеры, /top — топ-запросы.")
        else:
            set_current_xlsx(context.application, local)
            msg = ("✅ Принял .xlsx как текущую выгрузку.\n"
                   "Дальше: /themes — кластеры, /top — топ-запросы.")
    except SkillError as exc:
        msg = f"❌ {exc}"
    await update.message.reply_text(msg)


# --- мелкие помощники для хендлеров -------------------------------------------
def _run_guarded(fn: Callable, *args) -> str:
    try:
        return fn(*args)
    except SkillError as exc:
        return f"❌ {exc}"


def _run_guarded_list(fn: Callable, *args) -> list:
    try:
        return fn(*args)
    except SkillError:
        return []


def _no_data() -> str:
    return ("Нет активной выгрузки. Пришли мне <b>CSV</b> из веб-Планировщика "
            "Google или готовый <b>.xlsx</b> — и я начну отдавать аналитику. "
            "Подробнее: /start")


def _dfs_creds_present() -> bool:
    if os.environ.get("DATAFORSEO_LOGIN") and os.environ.get("DATAFORSEO_PASSWORD"):
        return True
    path = os.environ.get("DATAFORSEO_CONFIGURATION_FILE_PATH", gkp_client.DFS_YAML_DEFAULT)
    return os.path.exists(path)


# === ТОЧКА ВХОДА =============================================================
async def on_startup(app) -> None:
    app.bot_data["state"] = load_state()
    app.bot_data["queue"] = asyncio.Queue()
    app.bot_data["busy"] = False
    app.bot_data["worker"] = asyncio.create_task(queue_worker(app))
    log.info("Бот запущен. DATA_DIR=%s", DATA_DIR)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        sys.exit("[ОШИБКА] Нет TELEGRAM_BOT_TOKEN. Получи токен у @BotFather и задай "
                 "переменную окружения TELEGRAM_BOT_TOKEN.")
    os.makedirs(DATA_DIR, exist_ok=True)

    app = Application.builder().token(token).post_init(on_startup).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("themes", cmd_themes))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("demand", cmd_demand))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))

    log.info("Запуск long-polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
