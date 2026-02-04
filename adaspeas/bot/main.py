from __future__ import annotations

import asyncio
import os
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import structlog

from adaspeas.common.logging import setup_logging
from adaspeas.common.settings import Settings
from adaspeas.common import db as db_mod
from adaspeas.common.queue import get_redis, enqueue
from adaspeas.storage.yandex_disk import YandexDiskClient

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

    app.router.add_get("/health", health)
    app.router.add_get("/metrics", metrics)
    return app


async def main() -> None:
    settings = Settings()
    setup_logging(settings.log_level)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    db = await db_mod.connect(settings.sqlite_path)
    await db_mod.ensure_schema(db)

    r = await get_redis(settings.redis_url)

    yd = YandexDiskClient(settings.yandex_oauth_token)

    async def show_folder(m: Message | None, cq: CallbackQuery | None, folder_path: str) -> None:
        """List a Yandex folder and show inline navigation."""
        items = await yd.list_dir(folder_path, limit=200, offset=0)
        # sort: folders first, then files; by name
        def key(it):
            t = it.get("type")
            return (0 if t == 'dir' else 1, str(it.get('name') or '').lower())
        items_sorted = sorted(items, key=key)
        kb = InlineKeyboardBuilder()
        # upsert children into catalog_items and add buttons
        for it in items_sorted[:50]:
            name = str(it.get('name') or '')
            if not name:
                continue
            kind = 'folder' if it.get('type') == 'dir' else 'file'
            child_path = str(it.get('path') or '')
            # Yandex often returns 'disk:/...' paths; normalize to '/...'
            
            if child_path.startswith('disk:'):
                child_path = child_path[len('disk:'):]
            item_id = await db_mod.upsert_catalog_item(
                db, path=child_path, kind=kind, title=name, yandex_id=child_path, size_bytes=it.get('size')
            )
            if kind == 'folder':
                kb.button(text=f"📁 {name}", callback_data=f"open:{item_id}")
            else:
                kb.button(text=f"📄 {name}", callback_data=f"dl:{item_id}")
        kb.adjust(1)
        # Back button if not root
        if folder_path.rstrip('/') != settings.yandex_base_path.rstrip('/'):
            parent = folder_path.rstrip('/')
            parent = parent[: parent.rfind('/')] if '/' in parent[1:] else settings.yandex_base_path
            # normalize parent
            parent_item = await db_mod.upsert_catalog_item(db, path=parent, kind='folder', title='..', yandex_id=parent)
            kb.button(text='⬅️ Назад', callback_data=f"open:{parent_item}")
            kb.adjust(1)
        text = f"Папка: {folder_path}\nВыбери папку или файл:"
        markup = kb.as_markup()
        if cq is not None:
            await cq.message.edit_text(text, reply_markup=markup)
            await cq.answer()
        elif m is not None:
            await m.answer(text, reply_markup=markup)

    @dp.message(Command("start"))
    async def start(m: Message) -> None:
        REQ_TOTAL.labels(command="start").inc()
        await db_mod.upsert_user(db, m.from_user.id)
        await m.answer(
            "Привет. Это Adaspeas MVP.\n\n"
            "Команды:\n"
            "/seed - (admin) добавить тестовый файл в каталог\n"
            "/list - показать тестовый каталог\n"
            "/download <id> - поставить задачу на отправку файла"
        )

    @dp.message(Command("categories"))
    async def categories(m: Message) -> None:
        REQ_TOTAL.labels(command="categories").inc()
        await show_folder(m=m, cq=None, folder_path=settings.yandex_base_path)

    @dp.callback_query(F.data.startswith("open:"))
    async def cb_open(cq: CallbackQuery) -> None:
        try:
            item_id = int((cq.data or '').split(':', 1)[1])
            item = await db_mod.fetch_catalog_item(db, item_id)
            await show_folder(m=None, cq=cq, folder_path=item['path'])
        except Exception as e:
            log.warning('cb_open_failed', err=str(e))
            await cq.answer('Не удалось открыть папку', show_alert=True)

    @dp.callback_query(F.data.startswith("dl:"))
    async def cb_download(cq: CallbackQuery) -> None:
        try:
            item_id = int((cq.data or '').split(':', 1)[1])
        except Exception:
            await cq.answer('Некорректный id', show_alert=True)
            return
        request_id = str(uuid.uuid4())
        try:
            job_id = await db_mod.insert_job(
                db, tg_chat_id=cq.message.chat.id, tg_user_id=cq.from_user.id, catalog_item_id=item_id, request_id=request_id
            )
            await enqueue(r, job_id)
            JOB_ENQUEUE_TOTAL.inc()
            await cq.answer(f"Ок. Задача #{job_id}.")
        except Exception as e:
            log.warning('cb_download_failed', err=str(e))
            await cq.answer('Не удалось создать задачу', show_alert=True)

    @dp.message(Command("seed"))
    async def seed(m: Message) -> None:
        REQ_TOTAL.labels(command="seed").inc()
        if settings.admin_ids_set() and m.from_user.id not in settings.admin_ids_set():
            await m.answer("Недостаточно прав.")
            return
        # Create a single demo item if not exists
        await db.execute(
            """
            INSERT INTO catalog_items(path, kind, title, yandex_id)
            VALUES (?, 'file', ?, ?)
            ON CONFLICT(path) DO NOTHING
            """,
            ("/demo.pdf", "Demo PDF", "/demo.pdf"),
        )
        await db.commit()
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
        text = "Каталог:\n" + "\n".join([f"{r[0]}: {r[1]} ({r[2]})" for r in rows])
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
    finally:
        await bot.session.close()
        await db.close()
        await r.close()


if __name__ == "__main__":
    asyncio.run(main())