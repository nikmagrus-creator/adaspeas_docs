from __future__ import annotations

import asyncio
import os
from pathlib import Path
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
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

    # Fail fast on missing storage credentials only when needed.
    if settings.storage_mode.strip().lower() == "yandex" and not settings.yandex_oauth_token:
        raise RuntimeError("Storage mode 'yandex' requires YANDEX_OAUTH_TOKEN. Set STORAGE_MODE=local for local runs.")

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

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
            "/seed - (admin) добавить тестовый файл в каталог\n"
            "/list - показать тестовый каталог\n"
            "/download <id> - поставить задачу на отправку файла
/job <job_id> - статус задачи
/jobs - последние задачи в этом чате"
        )

    @dp.message(Command("seed"))
    async def seed(m: Message) -> None:
        REQ_TOTAL.labels(command="seed").inc()
        if settings.admin_ids_set() and m.from_user.id not in settings.admin_ids_set():
            await m.answer("Недостаточно прав.")
            return
        demo_path = "/demo.pdf"

        # In local mode, ensure a demo file exists inside the shared /data volume.
        if settings.storage_mode.strip().lower() == "local":
            root = Path(settings.local_storage_root)
            root.mkdir(parents=True, exist_ok=True)
            demo_file = root / demo_path.lstrip("/")
            if not demo_file.exists():
                # Small valid-ish PDF so Telegram previews don't get weird.
                demo_file.write_bytes(
                    b"%PDF-1.4\n1 0 obj<<>>endobj\n"
                    b"2 0 obj<< /Type /Catalog /Pages 3 0 R >>endobj\n"
                    b"3 0 obj<< /Type /Pages /Kids [4 0 R] /Count 1 >>endobj\n"
                    b"4 0 obj<< /Type /Page /Parent 3 0 R /MediaBox [0 0 200 200] /Contents 5 0 R >>endobj\n"
                    b"5 0 obj<< /Length 44 >>stream\nBT /F1 12 Tf 20 100 Td (Adaspeas demo) Tj ET\nendstream endobj\n"
                    b"xref\n0 6\n0000000000 65535 f \n"
                    b"trailer<< /Root 2 0 R /Size 6 >>\nstartxref\n0\n%%EOF\n"
                )

        # Create a single demo item if not exists
        await db.execute(
            """
            INSERT INTO catalog_items(path, kind, title, yandex_id)
            VALUES (?, 'file', ?, ?)
            ON CONFLICT(path) DO NOTHING
            """,
            (demo_path, "Demo PDF", demo_path),
        )
        await db.commit()
        mode = settings.storage_mode.strip().lower()
        await m.answer(f"Ок. Добавил {demo_path} как тестовый элемент каталога. storage_mode={mode}")

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

    @dp.message(Command("job"))
    async def job_status(m: Message) -> None:
        REQ_TOTAL.labels(command="job").inc()
        parts = (m.text or "").split()
        if len(parts) != 2 or not parts[1].isdigit():
            await m.answer("Использование: /job <job_id>")
            return
        job_id = int(parts[1])
        try:
            job = await db_mod.fetch_job(db, job_id)
        except Exception:
            await m.answer("Задача не найдена.")
            return
        if job["tg_chat_id"] != m.chat.id:
            await m.answer("Задача из другого чата.")
            return
        msg = f"Задача #{job_id}: state={job['state']}, attempt={job['attempt']}"
        if job.get("last_error"):
            msg += f"\nlast_error: {job['last_error']}"
        await m.answer(msg)

    @dp.message(Command("jobs"))
    async def jobs_recent(m: Message) -> None:
        REQ_TOTAL.labels(command="jobs").inc()
        jobs = await db_mod.fetch_jobs_for_chat(db, m.chat.id, limit=10)
        if not jobs:
            await m.answer("В этом чате пока нет задач.")
            return
        lines = []
        for j in jobs:
            line = f"#{j['id']}: item={j['catalog_item_id']} state={j['state']} attempt={j['attempt']}"
            if j.get("last_error"):
                line += " (err)"
            lines.append(line)
        await m.answer("Последние задачи:\n" + "\n".join(lines))


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
