from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
import tempfile
import uuid

from aiohttp import web
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramNetworkError, TelegramServerError
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import FSInputFile
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
import structlog

from tenacity import AsyncRetrying, stop_after_attempt, wait_random_exponential, retry_if_exception_type
import httpx

from adaspeas.common.logging import setup_logging
from adaspeas.common.settings import Settings
from adaspeas.common import db as db_mod
from adaspeas.common.queue import get_redis, enqueue, dequeue
from adaspeas.storage import StorageClient, make_storage_client

log = structlog.get_logger()

# --- Network retry/backoff (IDEA-004) ---
_RETRIABLE_SEND = (TelegramRetryAfter, TelegramNetworkError, TelegramServerError, httpx.HTTPError, asyncio.TimeoutError, ConnectionError)

async def _call_with_retry(coro_factory, *, attempts: int, max_wait_sec: int) -> object:
    # Retry external I/O with exponential jitter. For Telegram flood control respect retry_after.
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max(1, int(attempts))),
        wait=wait_random_exponential(multiplier=1, max=max(1, int(max_wait_sec))),
        retry=retry_if_exception_type(_RETRIABLE_SEND),
        reraise=True,
    ):
        with attempt:
            try:
                return await coro_factory()
            except TelegramRetryAfter as e:
                # aiogram exposes retry_after seconds
                ra = int(getattr(e, "retry_after", 0) or 0)
                await asyncio.sleep(max(1, ra))
                raise



JOBS_RUNNING = Gauge("jobs_running", "Number of jobs running")
JOBS_SUCCEEDED = Counter("jobs_succeeded_total", "Jobs succeeded")
JOBS_FAILED = Counter("jobs_failed_total", "Jobs failed")
JOBS_RETRIED = Counter("jobs_retried_total", "Jobs retried")
JOB_ENQUEUE_TOTAL = Counter("jobs_enqueued_total", "Jobs enqueued total")


async def notify_admins(bot: Bot, settings: Settings, text: str) -> None:
    admins = settings.admin_ids_set()
    chat_id = int(getattr(settings, "admin_notify_chat_id", 0) or 0)
    targets: list[int] = []
    if chat_id:
        targets.append(chat_id)
    else:
        targets.extend(sorted(list(admins)))
    for t in targets:
        try:
            await _call_with_retry(lambda: bot.send_message(chat_id=int(t), text=text), attempts=int(getattr(settings, 'net_retry_attempts', 3) or 3), max_wait_sec=int(getattr(settings, 'net_retry_max_sec', 30) or 30))
        except Exception:
            continue


async def notify_user(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await _call_with_retry(lambda: bot.send_message(chat_id=int(chat_id), text=text), attempts=int(getattr(settings, 'net_retry_attempts', 3) or 3), max_wait_sec=int(getattr(settings, 'net_retry_max_sec', 30) or 30))
    except Exception:
        pass


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


async def sync_catalog(settings: Settings, storage: StorageClient, db, root_path: str, *, max_nodes: int = 5000) -> tuple[int, int]:
    # Walk storage tree and upsert items into SQLite.
    # Designed for background execution in worker; bot UI reads only SQLite.
    root = (root_path or '/').rstrip('/') or '/'

    def clamp_child(p: str) -> bool:
        if root == '/':
            return p.startswith('/')
        rp = root.rstrip('/')
        return p == rp or p.startswith(rp + '/')

    sync_started = await db_mod.db_now(db)

    queue = deque([root])
    seen: set[str] = set()
    upserted = 0

    # Ensure root exists
    await db_mod.upsert_catalog_item(
        db,
        path=root,
        kind='folder',
        title='Каталог',
        yandex_id=root,
        parent_path=None,
    )

    while queue and upserted < max_nodes:
        cur_path = (queue.popleft() or '/').rstrip('/') or '/'
        if cur_path in seen:
            continue
        seen.add(cur_path)

        items = await _call_with_retry(lambda: storage.list_dir(cur_path), attempts=int(getattr(settings, 'net_retry_attempts', 3) or 3), max_wait_sec=int(getattr(settings, 'net_retry_max_sec', 30) or 30))
        for it in items:
            typ = str(it.get('type') or '').strip().lower()
            kind = 'folder' if typ == 'dir' else 'file'
            child_path = str(it.get('path') or '').strip()
            if not child_path:
                continue
            if not clamp_child(child_path):
                continue

            title = str(it.get('name') or '')
            if not title:
                title = child_path.rstrip('/').rsplit('/', 1)[-1] or child_path

            yandex_id = it.get('resource_id') or child_path
            size = it.get('size')

            await db_mod.upsert_catalog_item(
                db,
                path=child_path,
                kind=kind,
                title=title,
                yandex_id=str(yandex_id),
                size_bytes=int(size) if isinstance(size, int) else None,
                parent_path=cur_path,
            )
            upserted += 1

            if kind == 'folder':
                queue.append(child_path)

            if upserted >= max_nodes:
                break

    deleted = 0
    if sync_started:
        deleted = await db_mod.mark_deleted_not_seen(db, root, sync_started)

    return upserted, deleted


async def periodic_sync_scheduler(settings: Settings, db, r) -> None:
    """Periodically enqueue catalog sync jobs.

    Runs entirely in the worker container; it does not talk to Telegram.
    """
    interval = int(getattr(settings, 'catalog_sync_interval_sec', 0) or 0)
    if interval <= 0:
        return

    storage_mode = (getattr(settings, 'storage_mode', 'yandex') or 'yandex').strip().lower()
    root_path = (getattr(settings, 'yandex_base_path', '/') or '/').strip() if storage_mode != 'local' else '/'
    root_path = root_path or '/'

    # Small startup delay to let redis/db settle.
    await asyncio.sleep(5)

    while True:
        try:
            if await db_mod.has_active_sync_job(db):
                await asyncio.sleep(interval)
                continue

            root_item = await db_mod.fetch_catalog_item_by_path(db, root_path)
            if root_item is None:
                root_id = await db_mod.upsert_catalog_item(
                    db,
                    path=root_path,
                    kind='folder',
                    title='Каталог',
                    yandex_id=root_path,
                    parent_path=None,
                )
            else:
                root_id = int(root_item['id'])

            job_id = await db_mod.insert_job(
                db,
                tg_chat_id=0,
                tg_user_id=0,
                catalog_item_id=root_id,
                request_id=str(uuid.uuid4()),
                job_type='sync_catalog',
            )
            await enqueue(r, job_id)
            JOB_ENQUEUE_TOTAL.inc()
            log.info('sync_scheduled', job_id=job_id, interval_s=interval)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning('sync_scheduler_error', err=str(e))

        await asyncio.sleep(interval)


async def process_one(settings: Settings, bot: Bot, storage: StorageClient, db, r, job_id: int) -> None:
    job = await db_mod.fetch_job(db, job_id)

    # Skip if already terminal
    if job["state"] in {"succeeded", "failed", "cancelled"}:
        return

    job_type = (job.get('job_type') or 'download').strip().lower()

    await db_mod.set_job_state(db, job_id, "running")
    JOBS_RUNNING.inc()

    try:
        if job_type == 'sync_catalog':
            # Root path is stored in catalog_items.path for the root folder job.
            try:
                root_item = await db_mod.fetch_catalog_item(db, job["catalog_item_id"])
                root_path = str(root_item.get('path') or settings.yandex_base_path or '/')
            except Exception:
                root_path = str(settings.yandex_base_path or '/')

            max_nodes = int(getattr(settings, 'catalog_sync_max_nodes', 5000) or 5000)
            n, deleted = await sync_catalog(settings, storage, db, root_path, max_nodes=max_nodes)
            ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            await db_mod.set_meta(db, 'catalog_last_sync_at', ts)
            await db_mod.set_meta(db, 'catalog_last_sync_deleted', str(deleted))
            # Optional: notify the requester (admin). Never fail the job because of Telegram send.
            if int(job.get("tg_chat_id") or 0) > 0:
                try:
                    await bot.send_message(
                        chat_id=job["tg_chat_id"],
                        text=(
                            f"Синхронизация каталога завершена.\n"
                            f"Обработано: {n}.\n"
                            f"Удалено (soft-delete): {deleted}.\n"
                            f"Обновлено: {ts}"
                        ),
                    )
                except Exception:
                    pass

            await db_mod.set_job_state(db, job_id, "succeeded")
            JOBS_SUCCEEDED.inc()
            log.info('job_succeeded', job_id=job_id, mode='sync_catalog', items=n, deleted=deleted)
            return

        # Default: download job
        item = await db_mod.fetch_catalog_item(db, job["catalog_item_id"])
        if item["kind"] != "file":
            raise RuntimeError("catalog item is not a file")

        # Download to a temporary file (spool). Deleted immediately after send.
        # Fast-path: if Telegram file_id is cached, send without re-downloading.
        if item.get("tg_file_id"):
            try:
                msg = await bot.send_document(
                    chat_id=job["tg_chat_id"],
                    document=item["tg_file_id"],
                    caption=item["title"],
                )
                # Refresh cache from Telegram response (file_id may change).
                if getattr(msg, "document", None):
                    await db_mod.set_catalog_item_tg_file(
                        db,
                        item_id=item["id"],
                        tg_file_id=msg.document.file_id,
                        tg_file_unique_id=getattr(msg.document, "file_unique_id", None),
                    )
                await db_mod.set_job_state(db, job_id, "succeeded")
                JOBS_SUCCEEDED.inc()
                log.info("job_succeeded", job_id=job_id, mode="tg_file_id")
                try:
                    await db_mod.insert_download_audit(
                        db,
                        job_id=job_id,
                        tg_chat_id=int(job["tg_chat_id"]),
                        tg_user_id=int(job["tg_user_id"]),
                        catalog_item_id=int(job["catalog_item_id"]),
                        result="succeeded",
                        mode="tg_file_id",
                        bytes_sent=int(item.get("size_bytes") or 0) or None,
                        error=None,
                    )
                except Exception:
                    pass
                return
            except Exception as e:
                # If cached file_id became invalid, drop it and retry via download/upload.
                log.warning("tg_file_id_failed", job_id=job_id, err=str(e))
                await db_mod.set_catalog_item_tg_file(db, item_id=item["id"], tg_file_id=None, tg_file_unique_id=None)

        with tempfile.NamedTemporaryFile(prefix="adaspeas_", suffix=".bin", delete=True) as tmp:
            async for chunk in storage.stream_download(item["yandex_id"]):
                tmp.write(chunk)
            tmp.flush()

            msg = await bot.send_document(
                chat_id=job["tg_chat_id"],
                document=FSInputFile(tmp.name),
                caption=item["title"],
            )
            if getattr(msg, "document", None):
                await db_mod.set_catalog_item_tg_file(
                    db,
                    item_id=item["id"],
                    tg_file_id=msg.document.file_id,
                    tg_file_unique_id=getattr(msg.document, "file_unique_id", None),
                )

        await db_mod.set_job_state(db, job_id, "succeeded")
        JOBS_SUCCEEDED.inc()
        try:
            await db_mod.insert_download_audit(
                db,
                job_id=job_id,
                tg_chat_id=int(job["tg_chat_id"]),
                tg_user_id=int(job["tg_user_id"]),
                catalog_item_id=int(job["catalog_item_id"]),
                result="succeeded",
                mode="upload",
                bytes_sent=int(item.get("size_bytes") or 0) or None,
                error=None,
            )
        except Exception:
            pass
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

            # Final failure: record audit + notify.
            if job_type == "download":
                try:
                    await db_mod.insert_download_audit(
                        db,
                        job_id=job_id,
                        tg_chat_id=int(job["tg_chat_id"]),
                        tg_user_id=int(job["tg_user_id"]),
                        catalog_item_id=int(job["catalog_item_id"]),
                        result="failed",
                        mode=None,
                        bytes_sent=int(item.get("size_bytes") or 0) if "item" in locals() else None,
                        error=err,
                    )
                except Exception:
                    pass
                await notify_user(
                    bot,
                    int(job.get("tg_chat_id") or job.get("tg_user_id") or 0),
                    f"❌ Не удалось отправить файл (задача #{job_id}). Сообщение: {err}",
                )
                await notify_admins(
                    bot,
                    settings,
                    f"❌ Ошибка доставки файла: job=#{job_id}, user_id={job.get('tg_user_id')}, item_id={job.get('catalog_item_id')}. err={err}",
                )
            elif job_type == "sync_catalog":
                await notify_admins(
                    bot,
                    settings,
                    f"❌ Ошибка sync_catalog: job=#{job_id}. err={err}",
                )

    finally:
        JOBS_RUNNING.dec()


async def worker_loop(settings: Settings) -> None:
    setup_logging(settings.log_level)

    if getattr(settings, "use_local_bot_api", 0):
        api = TelegramAPIServer.from_base(getattr(settings, "local_bot_api_base", "http://local-bot-api:8081"), is_local=True)
        session = AiohttpSession(api=api)
        bot = Bot(token=settings.bot_token, session=session)
    else:
        bot = Bot(token=settings.bot_token)
    storage = make_storage_client(settings)

    db = await db_mod.connect(settings.sqlite_path)
    await db_mod.ensure_schema(db)
    r = await get_redis(settings.redis_url)

    scheduler_task: asyncio.Task | None = None
    if int(getattr(settings, 'catalog_sync_interval_sec', 0) or 0) > 0:
        scheduler_task = asyncio.create_task(periodic_sync_scheduler(settings, db, r), name='periodic_sync')

    try:
        while True:
            job_id = await dequeue(r, timeout_s=5)
            if job_id is None:
                await asyncio.sleep(0)
                continue
            await process_one(settings, bot, storage, db, r, job_id)
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except Exception:
                pass
        try:
            await storage.close()
        except Exception:
            pass
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