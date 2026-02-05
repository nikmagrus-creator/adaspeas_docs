from __future__ import annotations

import asyncio
import os
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiohttp import web
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import structlog

from adaspeas.common.logging import setup_logging
from adaspeas.common.settings import Settings
from adaspeas.common import db as db_mod
from adaspeas.common.queue import get_redis, enqueue
from adaspeas.storage import make_storage_client, StorageClient

log = structlog.get_logger()

REQ_TOTAL = Counter("bot_requests_total", "Bot requests total", ["command"])
JOB_ENQUEUE_TOTAL = Counter("jobs_enqueued_total", "Jobs enqueued total")

PAGE_SIZE = 10


async def make_app() -> web.Application:
    app = web.Application()

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def metrics(_request: web.Request) -> web.Response:
        payload = generate_latest()
        return web.Response(body=payload, content_type=CONTENT_TYPE_LATEST)

    app.router.add_get("/health", health)
    app.router.add_get("/metrics", metrics)
    return app


def _mk_kb(
    rows: list[dict],
    folder: dict,
    folder_id: int,
    page: int,
    has_next: bool,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []

    for r in rows:
        if r["kind"] == "folder":
            buttons.append([InlineKeyboardButton(text=f"📁 {r['title']}", callback_data=f"nav:{r['id']}:0")])
        else:
            buttons.append([InlineKeyboardButton(text=f"📄 {r['title']}", callback_data=f"dl:{r['id']}")])

    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"nav:{folder_id}:{page-1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"nav:{folder_id}:{page+1}"))
    if nav_row:
        buttons.append(nav_row)

    # Actions
    buttons.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"sync:{folder_id}:{page}"),
        InlineKeyboardButton(text="❌ Закрыть", callback_data="close:0"),
    ])

    # Back
    if folder.get("parent_id") is not None:
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"nav:{folder['parent_id']}:0")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _sync_folder(
    *,
    settings: Settings,
    storage: StorageClient,
    db,
    folder_id: int,
    root_id: int,
) -> None:
    mode = (settings.storage_mode or "yandex").strip().lower()

    if folder_id == root_id:
        internal_parent = "/"
        storage_path = "/" if mode == "local" else (settings.yandex_base_path or "/")
    else:
        folder = await db_mod.fetch_catalog_item(db, folder_id)
        internal_parent = folder["path"] or "/"
        # In local mode we keep yandex_id as an internal path.
        if mode == "local":
            storage_path = folder.get("yandex_id") or internal_parent
        else:
            storage_path = folder.get("yandex_id") or (settings.yandex_base_path.rstrip("/") + internal_parent)

    raw_items = await storage.list_dir(storage_path)

    keep_paths: list[str] = []
    for it in raw_items:
        name = (it.get("name") or "").strip()
        if not name:
            continue

        it_type = (it.get("type") or "").strip().lower()
        kind = "folder" if it_type == "dir" else "file"

        if internal_parent == "/":
            internal_path = "/" + name
        else:
            internal_path = internal_parent.rstrip("/") + "/" + name

        if mode == "local":
            yandex_id = internal_path
            y_modified = None
            y_md5 = None
        else:
            yandex_id = it.get("path") or internal_path
            y_modified = it.get("modified")
            y_md5 = it.get("md5")

        size_bytes = it.get("size")

        await db_mod.upsert_catalog_item(
            db,
            path=internal_path,
            parent_id=folder_id,
            kind=kind,
            title=name,
            yandex_id=yandex_id,
            size_bytes=size_bytes,
            yandex_modified=y_modified,
            yandex_md5=y_md5,
        )
        keep_paths.append(internal_path)

    # Best-effort cleanup of deleted items (only if folder isn't huge).
    if keep_paths and len(keep_paths) <= 900:
        placeholders = ",".join(["?"] * len(keep_paths))
        await db.execute(
            f"DELETE FROM catalog_items WHERE parent_id=? AND path NOT IN ({placeholders})",
            (folder_id, *keep_paths),
        )
        await db.commit()


async def _show_folder(
    *,
    db,
    folder_id: int,
    page: int,
    message: Message | None = None,
    cq: CallbackQuery | None = None,
) -> None:
    folder = await db_mod.fetch_catalog_item(db, folder_id)
    total = await db_mod.count_catalog_children(db, folder_id)

    offset = max(page, 0) * PAGE_SIZE
    rows = await db_mod.fetch_catalog_children(db, folder_id, offset, PAGE_SIZE + 1)
    has_next = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]

    if total == 0:
        text = f"📚 {folder['title']}\n\nКаталог пока не загружен. Нажмите «Обновить»."
    else:
        page_no = page + 1
        text = f"📚 {folder['title']}\n\nСтраница {page_no} · элементов: {total}"

    kb = _mk_kb(rows, folder, folder_id, page, has_next)

    if cq and cq.message:
        await cq.message.edit_text(text, reply_markup=kb)
    elif message:
        await message.answer(text, reply_markup=kb)


async def main() -> None:
    settings = Settings()
    setup_logging(settings.log_level)

    if settings.use_local_bot_api:
        api = TelegramAPIServer.from_base(settings.local_bot_api_base, is_local=True)
        session = AiohttpSession(api=api)
        bot = Bot(token=settings.bot_token, session=session)
    else:
        bot = Bot(token=settings.bot_token)

    dp = Dispatcher()

    # Publish command list in Telegram UI
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Справка"),
            BotCommand(command="categories", description="Каталог (кнопки)"),
            BotCommand(command="download", description="Скачать файл по id (редко нужно)"),
        ])
    except Exception:
        # Never fail bot startup because of Telegram UI cosmetics
        pass

    db = await db_mod.connect(settings.sqlite_path)
    await db_mod.ensure_schema(db)
    root_id = await db_mod.ensure_root_catalog_item(db, title="Каталог")

    r = await get_redis(settings.redis_url)

    storage: StorageClient | None = None
    try:
        storage = make_storage_client(settings)
    except Exception as e:
        log.warning("storage_not_configured", err=str(e))

    @dp.message(Command("start"))
    async def start(m: Message) -> None:
        REQ_TOTAL.labels(command="start").inc()
        await db_mod.upsert_user(db, m.from_user.id)
        await m.answer(
            "Adaspeas. Доступ к библиотеке через Telegram.\n\n"
            "Команды:\n"
            "/categories - каталог (кнопки)\n"
            "/download <id> - скачать по id (если нужно)\n"
        )

    @dp.message(Command("categories"))
    async def categories(m: Message) -> None:
        REQ_TOTAL.labels(command="categories").inc()
        await _show_folder(db=db, folder_id=root_id, page=0, message=m)

    @dp.callback_query(F.data.startswith("close:"))
    async def close_cb(cq: CallbackQuery) -> None:
        await cq.answer()
        if cq.message:
            await cq.message.edit_reply_markup(reply_markup=None)

    @dp.callback_query(F.data.startswith("nav:"))
    async def nav_cb(cq: CallbackQuery) -> None:
        await cq.answer()
        try:
            _p = (cq.data or "").split(":")
            folder_id = int(_p[1])
            page = int(_p[2]) if len(_p) > 2 else 0
        except Exception:
            return
        await _show_folder(db=db, folder_id=folder_id, page=page, cq=cq)

    @dp.callback_query(F.data.startswith("sync:"))
    async def sync_cb(cq: CallbackQuery) -> None:
        await cq.answer("Обновляю…")
        if not storage:
            if cq.message:
                await cq.message.answer("Хранилище не настроено.")
            return
        try:
            _p = (cq.data or "").split(":")
            folder_id = int(_p[1])
            page = int(_p[2]) if len(_p) > 2 else 0
        except Exception:
            return

        # Best effort feedback
        if cq.message:
            try:
                await cq.message.edit_text("🔄 Обновляю каталог…", reply_markup=None)
            except Exception:
                pass

        try:
            await _sync_folder(settings=settings, storage=storage, db=db, folder_id=folder_id, root_id=root_id)
        except Exception as e:
            log.warning("sync_failed", err=str(e), folder_id=folder_id)
            if cq.message:
                await cq.message.answer(f"Не удалось обновить: {e}")
            return

        await _show_folder(db=db, folder_id=folder_id, page=page, cq=cq)

    @dp.callback_query(F.data.startswith("dl:"))
    async def dl_cb(cq: CallbackQuery) -> None:
        await cq.answer()
        if not cq.message:
            return
        try:
            item_id = int((cq.data or "").split(":")[1])
        except Exception:
            return

        request_id = str(uuid.uuid4())
        try:
            job_id = await db_mod.insert_job(
                db,
                tg_chat_id=cq.message.chat.id,
                tg_user_id=cq.from_user.id,
                catalog_item_id=item_id,
                request_id=request_id,
            )
        except Exception as e:
            log.warning("job_insert_failed", err=str(e))
            await cq.message.answer("Не удалось создать задачу. Проверьте каталог.")
            return

        await enqueue(r, job_id)
        JOB_ENQUEUE_TOTAL.inc()
        await cq.message.answer(f"Ок. Поставил задачу #{job_id}.")

    @dp.message(Command("download"))
    async def download(m: Message) -> None:
        REQ_TOTAL.labels(command="download").inc()
        parts = (m.text or "").split()
        if len(parts) != 2 or not parts[1].isdigit():
            await m.answer("Использование: /download <id>")
            return
        item_id = int(parts[1])
        request_id = str(uuid.uuid4())
        try:
            job_id = await db_mod.insert_job(
                db,
                tg_chat_id=m.chat.id,
                tg_user_id=m.from_user.id,
                catalog_item_id=item_id,
                request_id=request_id,
            )
        except Exception as e:
            log.warning("job_insert_failed", err=str(e))
            await m.answer("Не удалось создать задачу. Проверь id.")
            return
        await enqueue(r, job_id)
        JOB_ENQUEUE_TOTAL.inc()
        await m.answer(f"Ок. Поставил задачу #{job_id}.")

    
    @dp.message(Command("seed"))
    async def seed(m: Message) -> None:
        REQ_TOTAL.labels(command="seed").inc()
        if settings.admin_ids_set() and m.from_user.id not in settings.admin_ids_set():
            await m.answer("Недостаточно прав.")
            return
        if (settings.storage_mode or "yandex").strip().lower() != "local":
            await m.answer("seed доступен только в режиме local.")
            return

        # Create a tiny demo.pdf once in local storage root
        import os as _os
        root_dir = getattr(settings, "local_storage_root", "/data/storage")
        _os.makedirs(root_dir, exist_ok=True)
        demo_path = _os.path.join(root_dir, "demo.pdf")
        if not _os.path.exists(demo_path):
            payload = (
                b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
                b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
                b"4 0 obj<</Length 44>>stream\nBT /F1 18 Tf 20 100 Td (Adaspeas demo) Tj ET\nendstream endobj\n"
                b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
                b"xref\n0 6\n0000000000 65535 f \n0000000010 00000 n \n0000000062 00000 n \n0000000117 00000 n \n0000000241 00000 n \n0000000334 00000 n \n"
                b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n404\n%%EOF\n"
            )
            with open(demo_path, "wb") as f:
                f.write(payload)

        # Upsert demo item under root
        await db_mod.upsert_catalog_item(
            db,
            path="/demo.pdf",
            parent_id=root_id,
            kind="file",
            title="demo.pdf",
            yandex_id="/demo.pdf",
            size_bytes=None,
            yandex_modified=None,
            yandex_md5=None,
        )
        await m.answer("Ок. Добавил demo.pdf. Откройте /categories → Обновить.")

    @dp.message(Command("list"))
    async def list_catalog(m: Message) -> None:
        REQ_TOTAL.labels(command="list").inc()
        cur = await db.execute(
            "SELECT id, kind, title, path, parent_id FROM catalog_items ORDER BY id LIMIT 50"
        )
        rows = await cur.fetchall()
        if not rows:
            await m.answer("Каталог пуст.")
            return
        text = "Каталог (debug, первые 50):\n" + "\n".join(
            [f"{r[0]} [{r[1]}] parent={r[4]}: {r[2]} ({r[3]})" for r in rows]
        )
        await m.answer(text)

# Run HTTP + bot polling together
    app = await make_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=8080)
    await site.start()

    try:
        await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        # In CI smoke we use a fake token; keep /health alive instead of crash-looping.
        if os.getenv("CI_SMOKE", "0") == "1":
            log.warning("Telegram token unauthorized in CI_SMOKE; keeping service alive for health checks")
            await asyncio.Event().wait()
        raise
    finally:
        await bot.session.close()
        await db.close()
        await r.close()


if __name__ == "__main__":
    asyncio.run(main())
