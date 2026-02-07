from __future__ import annotations

import asyncio
import os
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import Command
from aiogram.types import Message, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.exceptions import TelegramUnauthorizedError
from aiohttp import web
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import structlog

from adaspeas.common.logging import setup_logging
from adaspeas.common.settings import Settings
from adaspeas.common import db as db_mod
from adaspeas.common.queue import get_redis, enqueue

log = structlog.get_logger()

REQ_TOTAL = Counter("bot_requests_total", "Bot requests total", ["command"])
JOB_ENQUEUE_TOTAL = Counter("jobs_enqueued_total", "Jobs enqueued total")


async def make_app() -> web.Application:
    app = web.Application()

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def metrics(_request: web.Request) -> web.Response:
        payload = generate_latest()
        return web.Response(body=payload, content_type=CONTENT_TYPE_LATEST)

    async def root(_request: web.Request) -> web.StreamResponse:
        raise web.HTTPFound("/health")

    app.router.add_get("/", root)
    app.router.add_get("/health", health)
    app.router.add_get("/metrics", metrics)
    return app


async def main() -> None:
    settings = Settings()
    setup_logging(settings.log_level)

    if getattr(settings, "use_local_bot_api", 0):
        api = TelegramAPIServer.from_base(getattr(settings, "local_bot_api_base", "http://local-bot-api:8081"), is_local=True)
        session = AiohttpSession(api=api)
        bot = Bot(token=settings.bot_token, session=session)
    else:
        bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    # Publish command list in Telegram UI
    try:
        await bot.set_my_commands([
            BotCommand(command='start', description='Показать справку'),
            BotCommand(command='id', description='Показать свой Telegram ID'),
            BotCommand(command='categories', description='Каталог'),
            BotCommand(command='list', description='Тестовый каталог (SQLite)'),
            BotCommand(command='download', description='Скачать файл по id из /list'),
            BotCommand(command='sync', description='(admin) Синхронизировать каталог')
        ])
    except Exception:
        # Never fail bot startup because of Telegram UI cosmetics
        pass

    db = await db_mod.connect(settings.sqlite_path)
    await db_mod.ensure_schema(db)

    r = await get_redis(settings.redis_url)

    # Catalog navigation root (UI читает только SQLite; синхронизацию делает worker по /sync).
    storage_mode = (getattr(settings, "storage_mode", "yandex") or "yandex").strip().lower()
    root_path = (settings.yandex_base_path or "/").strip() if storage_mode != "local" else "/"
    if not root_path:
        root_path = "/"

    def parent_of(path: str) -> str | None:
        p = (path or "/").rstrip("/")
        if p == "":
            p = "/"
        # Do not navigate above configured root.
        if p == root_path.rstrip("/") or p == "/":
            return None
        i = p.rfind("/")
        if i <= 0:
            return root_path
        parent = p[:i]
        # Clamp to root
        if root_path != "/" and len(parent) < len(root_path.rstrip("/")):
            return None
        return parent

    def title_of(path: str) -> str:
        if path == root_path or path == "/":
            return "Каталог"
        p = (path or "").rstrip("/")
        return p.rsplit("/", 1)[-1] or "Каталог"

    # Ensure root folder exists in DB (even before first sync).
    await db_mod.upsert_catalog_item(
        db,
        path=root_path,
        kind="folder",
        title=title_of(root_path),
        yandex_id=root_path,
        parent_path=None,
    )

    async def render_dir(
        path: str,
        *,
        page: int = 0,
        viewer_tg_user_id: int | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        page_size = int(getattr(settings, "catalog_page_size", 25) or 25)
        # Telegram inline keyboards are limited; keep it sane.
        if page_size < 5:
            page_size = 5
        if page_size > 50:
            page_size = 50

        total = await db_mod.count_children(db, path)
        max_page = 0 if total <= 0 else max(0, (total - 1) // page_size)
        if page < 0:
            page = 0
        if page > max_page:
            page = max_page

        children = await db_mod.fetch_children(db, path, limit=page_size, offset=page * page_size)
        kb: list[list[InlineKeyboardButton]] = []
        for ch in children:
            is_folder = ch.get("kind") == "folder"
            cb = f"nav:{ch['id']}:0" if is_folder else f"dl:{ch['id']}"
            label = ("📁 " if is_folder else "📄 ") + str(ch.get("title") or "")
            kb.append([InlineKeyboardButton(text=label[:64], callback_data=cb)])

        # Paging controls for the current directory
        self_item = await db_mod.fetch_catalog_item_by_path(db, path)
        self_id = int(self_item["id"]) if self_item else None
        if self_id is not None and max_page > 0:
            row: list[InlineKeyboardButton] = []
            if page > 0:
                row.append(InlineKeyboardButton(text="◀️", callback_data=f"nav:{self_id}:{page - 1}"))
            if page < max_page:
                row.append(InlineKeyboardButton(text="▶️", callback_data=f"nav:{self_id}:{page + 1}"))
            if row:
                kb.append(row)

        # Nav controls
        back = parent_of(path)
        if back is not None:
            parent_item = await db_mod.fetch_catalog_item_by_path(db, back)
            if parent_item is None:
                await db_mod.upsert_catalog_item(
                    db,
                    path=back,
                    kind="folder",
                    title=title_of(back),
                    yandex_id=back,
                    parent_path=parent_of(back),
                )
                parent_item = await db_mod.fetch_catalog_item_by_path(db, back)
            if parent_item is not None:
                kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"nav:{parent_item['id']}")])

        # Root shortcut
        if path != root_path:
            root_item = await db_mod.fetch_catalog_item_by_path(db, root_path)
            if root_item is None:
                await db_mod.upsert_catalog_item(
                    db,
                    path=root_path,
                    kind="folder",
                    title=title_of(root_path),
                    yandex_id=root_path,
                    parent_path=None,
                )
                root_item = await db_mod.fetch_catalog_item_by_path(db, root_path)
            if root_item is not None:
                kb.append([InlineKeyboardButton(text="🏠 В корень", callback_data=f"nav:{root_item['id']}")])

        text = f"{title_of(path)}"
        last_sync = await db_mod.get_meta(db, 'catalog_last_sync_at')
        if last_sync:
            text += f"\n\nОбновлено: {last_sync}"
            deleted = await db_mod.get_meta(db, 'catalog_last_sync_deleted')
            if deleted is not None:
                text += f"\nУдалено: {deleted}"

        if max_page > 0:
            text += f"\nСтраница: {page + 1}/{max_page + 1} (элементов: {total})"
        admins = settings.admin_ids_set()
        is_admin = bool(viewer_tg_user_id and admins and viewer_tg_user_id in admins)
        # Admins can see the underlying path for debugging.
        if is_admin:
            text += f"\n\n(путь: {path})"

        if not children:
            if is_admin:
                text += "\n\nКаталог пока пуст. Запусти /sync, чтобы worker наполнил SQLite."
            else:
                text += "\n\nКаталог пока пуст. Обновление выполняет админ."

        return text, InlineKeyboardMarkup(inline_keyboard=kb)

    @dp.message(Command("start"))
    async def start(m: Message) -> None:
        REQ_TOTAL.labels(command="start").inc()
        await db_mod.upsert_user(db, m.from_user.id)
        await m.answer(
            "Привет. Это Adaspeas MVP.\n\n"
            "Команды:\n"
            "/categories - показать каталог\n"
            "/seed - (admin) добавить тестовый файл в каталог (локальный режим)\n"
            "/sync - (admin) синхронизировать каталог в фоне (worker)\n"
            "/list - показать тестовый каталог\n"
            "/download <id> - поставить задачу на отправку файла"
        )


    @dp.message(Command("categories"))
    async def categories(m: Message) -> None:
        REQ_TOTAL.labels(command="categories").inc()
        # Inline navigation UI (no long callback_data, only numeric ids).
        text, markup = await render_dir(root_path, viewer_tg_user_id=m.from_user.id if m.from_user else None)
        await m.answer(text, reply_markup=markup)

    

@dp.message(Command("id"))
async def show_id(m: Message) -> None:
    REQ_TOTAL.labels(command="id").inc()
    if not m.from_user:
        await m.answer("Не удалось определить ваш ID.")
        return
    await m.answer(f"Ваш Telegram ID: {m.from_user.id}")
@dp.message(Command("sync"))
    async def sync_catalog(m: Message) -> None:
        REQ_TOTAL.labels(command="sync").inc()
        admins = settings.admin_ids_set()
        uid = m.from_user.id if m.from_user else 0
        if admins and uid not in admins:
            await m.answer(
                f"Недостаточно прав. Ваш ID: {uid}. "
                "Добавьте его в переменную ADMIN_USER_IDS (через запятую) в .env и перезапустите сервисы."
            )
            return

        request_id = str(uuid.uuid4())
        # Root folder item must exist (it is created on startup), but be defensive.
        root_item = await db_mod.fetch_catalog_item_by_path(db, root_path)
        if root_item is None:
            root_id = await db_mod.upsert_catalog_item(
                db,
                path=root_path,
                kind="folder",
                title=title_of(root_path),
                yandex_id=root_path,
                parent_path=None,
            )
        else:
            root_id = int(root_item["id"])

        job_id = await db_mod.insert_job(
            db,
            tg_chat_id=m.chat.id,
            tg_user_id=m.from_user.id,
            catalog_item_id=root_id,
            request_id=request_id,
            job_type='sync_catalog',
        )
        await enqueue(r, job_id)
        JOB_ENQUEUE_TOTAL.inc()
        await m.answer(f"Ок. Запустил синхронизацию каталога в фоне: задача #{job_id}.")

    @dp.callback_query(F.data.startswith("nav:"))
    async def nav_cb(q: CallbackQuery) -> None:
        raw = (q.data or "")
        parts = raw.split(":")
        # nav:<id> or nav:<id>:<page>
        try:
            item_id = int(parts[1])
        except Exception:
            await q.answer("Некорректная команда")
            return

        page = 0
        if len(parts) >= 3:
            try:
                page = int(parts[2])
            except Exception:
                page = 0

        try:
            item = await db_mod.fetch_catalog_item(db, item_id)
        except Exception:
            await q.answer("Элемент не найден")
            return

        if item.get("kind") != "folder":
            await q.answer("Это не папка")
            return

        text, markup = await render_dir(
            str(item.get("path") or root_path),
            page=page,
            viewer_tg_user_id=q.from_user.id,
        )
        if q.message:
            await q.message.edit_text(text, reply_markup=markup)
        await q.answer()

    @dp.callback_query(F.data.startswith("dl:"))
    async def dl_cb(q: CallbackQuery) -> None:
        try:
            item_id = int((q.data or "").split(":", 1)[1])
        except Exception:
            await q.answer("Некорректная команда")
            return

        request_id = str(uuid.uuid4())
        try:
            job_id = await db_mod.insert_job(
                db,
                tg_chat_id=q.message.chat.id if q.message else q.from_user.id,
                tg_user_id=q.from_user.id,
                catalog_item_id=item_id,
                request_id=request_id,
            )
        except Exception:
            await q.answer("Не удалось создать задачу")
            return
        await enqueue(r, job_id)
        JOB_ENQUEUE_TOTAL.inc()
        await q.answer(f"Ок, задача #{job_id}")

    @dp.message(Command("seed"))
    async def seed(m: Message) -> None:
        REQ_TOTAL.labels(command="seed").inc()
        admins = settings.admin_ids_set()
        uid = m.from_user.id if m.from_user else 0
        if admins and uid not in admins:
            await m.answer(
                f"Недостаточно прав. Ваш ID: {uid}. "
                "Добавьте его в переменную ADMIN_USER_IDS (через запятую) в .env и перезапустите сервисы."
            )
            return

        if getattr(settings, "storage_mode", "yandex") != "local":
            await m.answer("Команда /seed доступна только в local режиме.")
            return

        # In local mode, create a tiny demo.pdf once.
        import os as _os
        root_dir = getattr(settings, "local_storage_root", "/data/storage")
        _os.makedirs(root_dir, exist_ok=True)
        demo_path = _os.path.join(root_dir, "demo.pdf")
        if not _os.path.exists(demo_path):
            # Minimal PDF file (enough for most viewers)
            payload = b"""%PDF-1.1
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 44>>stream
BT /F1 18 Tf 20 100 Td (Adaspeas demo) Tj ET
endstream endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f 
0000000010 00000 n 
0000000062 00000 n 
0000000117 00000 n 
0000000241 00000 n 
0000000334 00000 n 
trailer<</Size 6/Root 1 0 R>>
startxref
404
%%EOF
"""
            with open(demo_path, "wb") as f:
                f.write(payload)

        # Create a single demo item as child of catalog root.
        await db_mod.upsert_catalog_item(
            db,
            path="/demo.pdf",
            kind="file",
            title="Demo PDF",
            yandex_id="/demo.pdf",
            parent_path=root_path,
        )
        await m.answer("Ок. Добавил /demo.pdf как тестовый элемент каталога.")


    @dp.message(Command("list"))
    async def list_catalog(m: Message) -> None:
        REQ_TOTAL.labels(command="list").inc()
        cur = await db.execute(
            "SELECT id, title, path FROM catalog_items ORDER BY id LIMIT 50"
        )
        rows = await cur.fetchall()
        if not rows:
            await m.answer("Каталог пуст. Админ может вызвать /seed.")
            return
        admins = settings.admin_ids_set()
        is_admin = bool(admins and m.from_user and m.from_user.id in admins)

        if is_admin:
            text = "Каталог (с путями для админа):\n" + "\n".join([f"{r[0]}: {r[1]} ({r[2]})" for r in rows])
        else:
            text = "Каталог:\n" + "\n".join([f"{r[0]}: {r[1]}" for r in rows])
        await m.answer(text)

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
        try:
            if storage is not None:
                await storage.close()
        except Exception:
            pass
        await bot.session.close()
        await db.close()
        await r.close()


if __name__ == "__main__":
    asyncio.run(main())