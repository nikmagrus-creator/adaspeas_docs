from __future__ import annotations

import asyncio
import os
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import Command
from aiogram.types import Message, BotCommand
from aiogram.exceptions import TelegramUnauthorizedError
from aiohttp import web
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import structlog

from adaspeas.common.logging import setup_logging
from adaspeas.common.settings import Settings
from adaspeas.common import db as db_mod
from adaspeas.common.queue import get_redis, enqueue
from adaspeas.storage import make_storage_client

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
            BotCommand(command='start', description='Показать справку'),
            BotCommand(command='categories', description='Каталог'),
            BotCommand(command='list', description='Тестовый каталог (SQLite)'),
            BotCommand(command='download', description='Скачать файл по id из /list')
        ])
    except Exception:
        # Never fail bot startup because of Telegram UI cosmetics
        pass

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
            "/categories - показать каталог\n"
            "/seed - (admin) добавить тестовый файл в каталог (локальный режим)\n"
            "/list - показать тестовый каталог\n"
            "/download <id> - поставить задачу на отправку файла"
        )


    @dp.message(Command("categories"))
    async def categories(m: Message) -> None:
        REQ_TOTAL.labels(command="categories").inc()
        # Sync listing from storage into SQLite and show top level.
        try:
            storage = make_storage_client(settings)
        except Exception as e:
            await m.answer(f"Хранилище не настроено: {e}")
            return

        base = (settings.yandex_base_path or "/").strip() if getattr(settings, "storage_mode", "yandex") != "local" else "/"

        # (path, kind, title, storage_id, size, modified, md5)
        items: list[tuple[str, str, str, str | None, int | None, str | None, str | None]] = []

        if getattr(settings, "storage_mode", "yandex") == "local":
            import os as _os

            root_dir = getattr(settings, "local_storage_root", "/data/storage")
            try:
                for name in sorted(_os.listdir(root_dir))[:200]:
                    full = _os.path.join(root_dir, name)
                    if _os.path.isdir(full):
                        kind = "folder"
                        size = None
                    else:
                        kind = "file"
                        size = _os.path.getsize(full)
                    path = "/" + name
                    items.append((path, kind, name, path, size, None, None))
            except Exception as e:
                await m.answer(f"Не удалось прочитать локальное хранилище: {e}")
                return
        else:
            try:
                raw_items = await storage.list_dir(base)  # type: ignore[attr-defined]
            except Exception as e:
                await m.answer(f"Не удалось получить каталог: {e}")
                return

            for it in raw_items:
                kind = "folder" if it.get("type") == "dir" else "file"
                path = it.get("path") or it.get("name") or ""
                title = it.get("name") or path
                storage_id = path
                size = it.get("size")
                modified = it.get("modified")
                md5 = it.get("md5")
                items.append((path, kind, title, storage_id, size, modified, md5))

        for path, kind, title, storage_id, size, modified, md5 in items:
            if not path:
                continue
            await db_mod.upsert_catalog_item(
                db,
                path=path,
                kind=kind,
                title=title,
                yandex_id=storage_id,
                size_bytes=size,
                yandex_modified=modified,
                yandex_md5=md5,
            )

        # Show first 50 entries
        cur = await db.execute(
            "SELECT id, kind, title, path FROM catalog_items ORDER BY kind DESC, title LIMIT 50"
        )
        rows = await cur.fetchall()
        if not rows:
            await m.answer("Каталог пуст.")
            return

        text = "Каталог (первые 50):\n" + "\n".join([f"{r[0]} [{r[1]}]: {r[2]} ({r[3]})" for r in rows])
        await m.answer(text)

    @dp.message(Command("seed"))
    async def seed(m: Message) -> None:
        REQ_TOTAL.labels(command="seed").inc()
        if settings.admin_ids_set() and m.from_user.id not in settings.admin_ids_set():
            await m.answer("Недостаточно прав.")
            return

        # In local mode, create a tiny demo.pdf once.
        if getattr(settings, "storage_mode", "yandex") == "local":
            import os as _os
            root_dir = getattr(settings, "local_storage_root", "/data/storage")
            _os.makedirs(root_dir, exist_ok=True)
            demo_path = _os.path.join(root_dir, "demo.pdf")
            if not _os.path.exists(demo_path):
                # Minimal PDF file (enough for most viewers)
                payload = b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n4 0 obj<</Length 44>>stream\nBT /F1 18 Tf 20 100 Td (Adaspeas demo) Tj ET\nendstream endobj\n5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\nxref\n0 6\n0000000000 65535 f \n0000000010 00000 n \n0000000062 00000 n \n0000000117 00000 n \n0000000241 00000 n \n0000000334 00000 n \ntrailer<</Size 6/Root 1 0 R>>\nstartxref\n404\n%%EOF\n"
                with open(demo_path, "wb") as f:
                    f.write(payload)

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
