from __future__ import annotations

import asyncio
import os
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, BotCommand
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

    app.router.add_get("/health", health)
    app.router.add_get("/metrics", metrics)
    return app


async def main() -> None:
    settings = Settings()
    setup_logging(settings.log_level)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    # Publish command list in Telegram UI
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Показать справку"),
            BotCommand(command="categories", description="Каталог из Яндекс.Диска"),
            BotCommand(command="list", description="Тестовый каталог (SQLite)"),
            BotCommand(command="download", description="Скачать файл по id из /list"),
        ])
    except Exception:
        log.exception("Failed to set bot commands")

    db = await db_mod.connect(settings.sqlite_path)
    await db_mod.ensure_schema(db)

    r = await get_redis(settings.redis_url)

    @dp.message(Command("start"))
    async def start(m: Message) -> None:
        REQ_TOTAL.labels(command="start").inc()
        await db_mod.upsert_user(db, m.from_user.id)
        await m.answer(
            "Привет. Это Adaspeas MVP.\n\n"
            "Команды:\n"
            "/categories - показать каталог из Яндекс.Диска (/Zkvpr)\n"
            "/seed - (admin) добавить тестовый файл в каталог (локальный режим)\n"
            "/list - показать тестовый каталог\n"
            "/download <id> - поставить задачу на отправку файла"
        )

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
