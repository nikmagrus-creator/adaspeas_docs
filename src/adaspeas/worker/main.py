from __future__ import annotations

import asyncio
import tempfile

from aiohttp import web
from aiogram import Bot
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
import structlog

from adaspeas.common.logging import setup_logging
from adaspeas.common.settings import Settings
from adaspeas.common import db as db_mod
from adaspeas.common.queue import get_redis, enqueue, dequeue
from adaspeas.storage.yandex_disk import YandexDiskClient

log = structlog.get_logger()

JOBS_RUNNING = Gauge("jobs_running", "Number of jobs running")
JOBS_SUCCEEDED = Counter("jobs_succeeded_total", "Jobs succeeded")
JOBS_FAILED = Counter("jobs_failed_total", "Jobs failed")
JOBS_RETRIED = Counter("jobs_retried_total", "Jobs retried")


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


async def process_one(settings: Settings, bot: Bot, yd: YandexDiskClient, db, r, job_id: int) -> None:
    job = await db_mod.fetch_job(db, job_id)

    # Skip if already terminal
    if job["state"] in {"succeeded", "failed", "cancelled"}:
        return

    await db_mod.set_job_state(db, job_id, "running")
    JOBS_RUNNING.inc()

    try:
        item = await db_mod.fetch_catalog_item(db, job["catalog_item_id"])
        if item["kind"] != "file":
            raise RuntimeError("catalog item is not a file")

        # Download to a temporary file (spool). Deleted immediately after send.
        with tempfile.NamedTemporaryFile(prefix="adaspeas_", suffix=".bin", delete=True) as tmp:
            async for chunk in yd.stream_download(item["yandex_id"]):
                tmp.write(chunk)
            tmp.flush()

            await bot.send_document(chat_id=job["tg_chat_id"], document=tmp.name, caption=item["title"])

        await db_mod.set_job_state(db, job_id, "succeeded")
        JOBS_SUCCEEDED.inc()
        log.info("job_succeeded", job_id=job_id)

    except Exception as e:
        err = str(e)
        attempt = await db_mod.bump_attempt(db, job_id, err)
        log.warning("job_failed", job_id=job_id, attempt=attempt, err=err)

        if attempt < 3:
            await db_mod.set_job_state(db, job_id, "queued", err)
            await enqueue(r, job_id)
            JOBS_RETRIED.inc()
        else:
            await db_mod.set_job_state(db, job_id, "failed", err)
            JOBS_FAILED.inc()

    finally:
        JOBS_RUNNING.dec()


async def worker_loop(settings: Settings) -> None:
    setup_logging(settings.log_level)

    bot = Bot(token=settings.bot_token)
    yd = YandexDiskClient(settings.yandex_oauth_token)

    db = await db_mod.connect(settings.sqlite_path)
    await db_mod.ensure_schema(db)
    r = await get_redis(settings.redis_url)

    try:
        while True:
            job_id = await dequeue(r, timeout_s=5)
            if job_id is None:
                await asyncio.sleep(0)
                continue
            await process_one(settings, bot, yd, db, r, job_id)
    finally:
        await bot.session.close()
        await db.close()
        await r.close()


async def main() -> None:
    settings = Settings()

    app = await make_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=8081)
    await site.start()

    await worker_loop(settings)


if __name__ == "__main__":
    asyncio.run(main())
