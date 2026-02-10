from __future__ import annotations

import asyncio
import os
import uuid
import math

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import Command
from aiogram.types import Message, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.exceptions import TelegramUnauthorizedError, TelegramNetworkError, TelegramServerError
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


async def make_app(state: dict) -> web.Application:
    app = web.Application()

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def ready(_request: web.Request) -> web.Response:
        # Readiness is best-effort and informative.
        # Liveness (/health) must stay simple and fast.
        return web.json_response(
            {
                "ok": True,
                "polling": state.get("polling"),
                "last_poll_error": state.get("last_poll_error"),
                "last_poll_ok_at": state.get("last_poll_ok_at"),
                "db": state.get("db"),
                "redis": state.get("redis"),
                "last_init_error": state.get("last_init_error"),
            }
        )

    async def metrics(_request: web.Request) -> web.Response:
        payload = generate_latest()
        return web.Response(body=payload, content_type=CONTENT_TYPE_LATEST)

    async def root(_request: web.Request) -> web.StreamResponse:
        raise web.HTTPFound("/health")

    app.router.add_get("/", root)
    app.router.add_get("/health", health)
    app.router.add_get("/ready", ready)
    app.router.add_get("/metrics", metrics)
    return app


async def main() -> None:
    settings = Settings()
    setup_logging(settings.log_level)

    state: dict = {
        "polling": "starting",
        "last_poll_error": None,
        "last_poll_ok_at": None,
        "db": "starting",
        "redis": "starting",
        "last_init_error": None,
    }

    # Start liveness endpoints ASAP so Docker healthcheck does not depend on Telegram network.
    # Any Telegram/DB failures should surface in logs, but /health must stay responsive.
    app = await make_app(state)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=8080)
    await site.start()

    if getattr(settings, "use_local_bot_api", 0):
        api = TelegramAPIServer.from_base(getattr(settings, "local_bot_api_base", "http://local-bot-api:8081"), is_local=True)
        session = AiohttpSession(api=api)
        bot = Bot(token=settings.bot_token, session=session)
    else:
        bot = Bot(token=settings.bot_token)
    dp = Dispatcher()


    async def _init_db_with_retry() -> db_mod.Connection:
        backoff = 1
        max_backoff = int(getattr(settings, "net_retry_max_sec", 30) or 30)
        while True:
            try:
                dbi = await db_mod.connect(settings.sqlite_path)
                await db_mod.ensure_schema(dbi)
                state["db"] = "ok"
                state["last_init_error"] = None if state.get("redis") == "ok" else state.get("last_init_error")
                return dbi
            except asyncio.CancelledError:
                raise
            except Exception as e:
                state["db"] = "retrying"
                state["last_init_error"] = f"db: {e}"
                log.error("db_init_retry", err=str(e), backoff_s=backoff)
                # avoid tight crash loops; keep /health alive
                await asyncio.sleep(backoff)
                backoff = min(max_backoff, max(1, backoff * 2))

    async def _init_redis_with_retry() -> object:
        backoff = 1
        max_backoff = int(getattr(settings, "net_retry_max_sec", 30) or 30)
        while True:
            try:
                rr = await get_redis(settings.redis_url)
                try:
                    await rr.ping()
                except Exception:
                    # Some Redis servers delay accept; treat as init failure.
                    raise
                state["redis"] = "ok"
                state["last_init_error"] = None if state.get("db") == "ok" else state.get("last_init_error")
                return rr
            except asyncio.CancelledError:
                raise
            except Exception as e:
                state["redis"] = "retrying"
                state["last_init_error"] = f"redis: {e}"
                log.error("redis_init_retry", err=str(e), backoff_s=backoff)
                await asyncio.sleep(backoff)
                backoff = min(max_backoff, max(1, backoff * 2))

    async def _set_commands_best_effort() -> None:
        # Telegram API may be blocked/slow on some networks; do not block startup.
        try:
            await asyncio.wait_for(bot.set_my_commands([
            BotCommand(command='start', description='Показать справку'),
            BotCommand(command='id', description='Показать ваш Telegram ID'),
            BotCommand(command='categories', description='Каталог'),
            BotCommand(command='search', description='Поиск по каталогу'),
            BotCommand(command='request', description='Запросить доступ (если включён контроль доступа)'),
            BotCommand(command='note', description='Добавить примечание о себе (admin видит)'),
            BotCommand(command='users', description='(admin) Пользователи/доступ'),
            BotCommand(command='list', description='Тестовый каталог (SQLite)'),
            BotCommand(command='download', description='Скачать файл по id из /list'),
            BotCommand(command='sync', description='(admin) Синхронизировать каталог'),
            BotCommand(command='audit', description='(admin) Аудит загрузок'),
            BotCommand(command='stats', description='(admin) Статистика'),
            BotCommand(command='diag', description='(admin) Диагностика')
            ]), timeout=10)
        except Exception:
            # Never fail bot startup because of Telegram UI cosmetics.
            return

    # Fire and forget.
    asyncio.create_task(_set_commands_best_effort(), name="set_my_commands")

    db = await _init_db_with_retry()

    r = await _init_redis_with_retry()

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
    # --- Access control (Milestone 2) ---
    def is_admin(uid: int | None) -> bool:
        if not uid:
            return False
        admins = settings.admin_ids_set()
        return bool(admins and uid in admins)

    @dp.message(Command("diag"))
    async def cmd_diag(m: Message) -> None:
        REQ_TOTAL.labels(command="diag").inc()
        uid = int(getattr(m.from_user, "id", 0) or 0)
        if not is_admin(uid):
            await m.answer("Команда доступна только администратору.")
            return

        lines: list[str] = []
        lines.append("Диагностика (bot)")
        lines.append(f"polling={state.get('polling')} db={state.get('db')} redis={state.get('redis')}")
        if state.get("last_init_error"):
            lines.append(f"last_init_error={state.get('last_init_error')}")
        if state.get("last_poll_error"):
            lines.append(f"last_poll_error={state.get('last_poll_error')}")
        if state.get("last_poll_ok_at"):
            lines.append(f"last_poll_ok_at={state.get('last_poll_ok_at')}")

        # DB diagnostics (best-effort)
        try:
            sv = await db_mod.get_schema_version(db)
            lines.append(f"schema_version={sv}")
            # lightweight counts
            users_by = await db_mod.group_count(db, "users", "status")
            lines.append("users=" + ", ".join([f"{k}:{v}" for k, v in sorted(users_by.items())]) if users_by else "users=0")
            items = await db_mod.count_rows(db, "catalog_items")
            lines.append(f"catalog_items={items}")
        except Exception as e:
            lines.append(f"db_diag_error={e}")

        # Redis diagnostics
        try:
            from adaspeas.common.queue import QUEUE_KEY
            qlen = await r.llen(QUEUE_KEY)
            lines.append(f"queue_len={int(qlen)}")
        except Exception as e:
            lines.append(f"redis_diag_error={e}")

        await m.answer("\n".join(lines))


    async def ensure_user(uid: int) -> dict:
        await db_mod.upsert_user(db, uid)
        u = await db_mod.fetch_user_by_tg_user_id(db, uid)
        return u or {"tg_user_id": uid, "status": "guest", "expires_at": None, "user_note": None}

    async def ensure_active(uid: int, *, reply_chat_id: int, reply_cb) -> bool:
        # Admins bypass.
        if is_admin(uid):
            return True
        if int(getattr(settings, "access_control_enabled", 0) or 0) <= 0:
            return True

        # Expire old users opportunistically.
        try:
            await db_mod.expire_users(db)
        except Exception:
            pass

        u = await ensure_user(uid)
        status = str(u.get("status") or "guest")
        expires_at = u.get("expires_at")

        if status != "active":
            msg = "Доступ не выдан."
            if status == "pending":
                msg = "Заявка на доступ уже отправлена (pending)."
            elif status == "blocked":
                msg = "Доступ заблокирован."
            elif status == "expired":
                msg = "Доступ истёк."
            msg += "\n\nКоманды: /request (заявка), /note <кто вы/зачем нужен доступ>."
            await reply_cb(msg)
            return False

        # Active but may still have expiry for info.
        if expires_at:
            # Show nothing by default, keep UX quiet.
            pass
        return True

    async def notify_admins(text: str) -> None:
        admins = settings.admin_ids_set()
        chat_id = int(getattr(settings, "admin_notify_chat_id", 0) or 0)
        targets = []
        if chat_id:
            targets.append(chat_id)
        else:
            targets.extend(sorted(list(admins)))
        for t in targets:
            try:
                await bot.send_message(chat_id=t, text=text)
            except Exception:
                continue

    async def access_warn_scheduler() -> None:
        if int(getattr(settings, "access_control_enabled", 0) or 0) <= 0:
            return
        interval = int(getattr(settings, "access_warn_check_interval_sec", 3600) or 3600)
        warn_before = int(getattr(settings, "access_warn_before_sec", 86400) or 86400)
        # Small startup delay.
        await asyncio.sleep(5)
        while True:
            try:
                await db_mod.expire_users(db)
                users = await db_mod.fetch_users_expiring_within(db, warn_before)
                for u in users:
                    uid = int(u["tg_user_id"])
                    exp = u.get("expires_at") or "?"
                    try:
                        await bot.send_message(chat_id=uid, text=f"Доступ истекает примерно через 24 часа. Срок: {exp} UTC. Напишите /note, если нужно продление.")
                    except Exception:
                        pass
                    await notify_admins(f"⚠️ Истекает доступ: user_id={uid}, до {exp} UTC, note={u.get('user_note') or ''}")
                    try:
                        await db_mod.mark_user_warned_24h(db, uid)
                    except Exception:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("access_warn_scheduler_error", err=str(e))
            await asyncio.sleep(max(60, interval))


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
        viewer_tg_user_id: int | None = None,
        offset: int = 0,
    ) -> tuple[str, InlineKeyboardMarkup]:
        page_size = int(getattr(settings, "catalog_page_size", 30) or 30)
        offset = max(0, int(offset))

        # Defensive: ensure current folder exists and has an id (needed for pagination callbacks).
        cur_item = await db_mod.fetch_catalog_item_by_path(db, path)
        if cur_item is None:
            await db_mod.upsert_catalog_item(
                db,
                path=path,
                kind="folder",
                title=title_of(path),
                yandex_id=path,
                parent_path=parent_of(path),
            )
            cur_item = await db_mod.fetch_catalog_item_by_path(db, path)

        cur_id = int(cur_item["id"]) if cur_item else None

        total = await db_mod.count_children(db, path)
        children = await db_mod.fetch_children(db, path, limit=page_size, offset=offset)

        kb: list[list[InlineKeyboardButton]] = []
        for ch in children:
            is_folder = ch.get("kind") == "folder"
            cb = f"nav:{ch['id']}:0" if is_folder else f"dl:{ch['id']}"
            label = ("📁 " if is_folder else "📄 ") + str(ch.get("title") or "")
            kb.append([InlineKeyboardButton(text=label[:64], callback_data=cb)])

        # Page controls
        if cur_id is not None and (offset > 0 or (offset + page_size) < total):
            row: list[InlineKeyboardButton] = []
            if offset > 0:
                row.append(InlineKeyboardButton(text="⬅️", callback_data=f"nav:{cur_id}:{max(0, offset - page_size)}"))
            if (offset + page_size) < total:
                row.append(InlineKeyboardButton(text="➡️", callback_data=f"nav:{cur_id}:{offset + page_size}"))
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
                kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"nav:{parent_item['id']}:0")])

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
                kb.append([InlineKeyboardButton(text="🏠 В корень", callback_data=f"nav:{root_item['id']}:0")])

        text = f"{title_of(path)}"
        last_sync = await db_mod.get_meta(db, 'catalog_last_sync_at')
        if last_sync:
            text += f"\n\nОбновлено: {last_sync}"

        if total > 0:
            page = (offset // page_size) + 1
            pages = max(1, math.ceil(total / page_size))
            text += f"\n\nСтраница {page}/{pages} (элементов: {total})"
            text += "\nПоиск: /search <текст>"

        admins = settings.admin_ids_set()
        is_admin = bool(viewer_tg_user_id and admins and viewer_tg_user_id in admins)
        # Admins can see the underlying path for debugging.
        if is_admin:
            text += f"\n\n(путь: {path})"

        if total == 0:
            if is_admin:
                text += "\n\nКаталог пока пуст. Запусти /sync, чтобы worker наполнил SQLite."
            else:
                text += "\n\nКаталог пока пуст. Обновление выполняет админ."

        return text, InlineKeyboardMarkup(inline_keyboard=kb)

    async def render_search(
        token: str,
        *,
        viewer_tg_user_id: int,
        offset: int = 0,
    ) -> tuple[str, InlineKeyboardMarkup]:
        ttl_sec = int(getattr(settings, "search_session_ttl_sec", 3600) or 3600)
        page_size = int(getattr(settings, "search_page_size", 20) or 20)
        offset = max(0, int(offset))

        sess = await db_mod.fetch_search_session(db, token)
        if not sess:
            return "Поиск устарел. Запусти /search ещё раз.", InlineKeyboardMarkup(inline_keyboard=[])

        # Enforce ownership (or allow admin).
        admins = settings.admin_ids_set()
        if int(sess.get("tg_user_id") or 0) != int(viewer_tg_user_id) and not (admins and viewer_tg_user_id in admins):
            return "Поиск недоступен.", InlineKeyboardMarkup(inline_keyboard=[])

        # Best-effort cleanup of old sessions
        try:
            await db_mod.cleanup_search_sessions(db, ttl_sec)
        except Exception:
            pass

        query = str(sess.get("query") or "").strip()
        scope_path = str(sess.get("scope_path") or root_path)

        items, has_more = await db_mod.search_catalog_items(
            db,
            query=query,
            scope_path=scope_path,
            limit=page_size,
            offset=offset,
        )

        kb: list[list[InlineKeyboardButton]] = []
        for it in items:
            is_folder = it.get("kind") == "folder"
            cb = f"nav:{it['id']}:0" if is_folder else f"dl:{it['id']}"
            label = ("📁 " if is_folder else "📄 ") + str(it.get("title") or "")
            kb.append([InlineKeyboardButton(text=label[:64], callback_data=cb)])

        # pagination
        nav_row: list[InlineKeyboardButton] = []
        if offset > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"s:{token}:{max(0, offset - page_size)}"))
        if has_more:
            nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"s:{token}:{offset + page_size}"))
        if nav_row:
            kb.append(nav_row)

        text = f"Результаты: {query}"
        if not items:
            text += "\n\nНичего не найдено."
        else:
            text += f"\nПоказаны {offset + 1}..{offset + len(items)}"

        return text, InlineKeyboardMarkup(inline_keyboard=kb)



    @dp.message(Command("start"))
    async def start(m: Message) -> None:
        REQ_TOTAL.labels(command="start").inc()
        await db_mod.upsert_user(db, m.from_user.id)
        await m.answer(
            "Привет. Это Adaspeas.\n\n"
            "Команды:\n"
            "/categories - каталог\n"
            "/search <текст> - поиск по каталогу\n"
            "/id - показать ваш Telegram ID\n"
            "/note <текст> - добавить примечание о себе (админ видит)\n"
            "/request - запросить доступ (если включён контроль доступа)\n\n"
            "Админ:\n"
            "/users - управление доступом\n"
            "/sync - синхронизация каталога (worker)\n"
            "/audit - аудит загрузок\n"
            "/stats - статистика\n"
            "/seed - (local) добавить демо файл\n\n"
            "Debug:\n"
            "/list, /download <id>\n"
        )



    @dp.message(Command("id"))
    async def whoami(m: Message) -> None:
        REQ_TOTAL.labels(command="id").inc()
        if not m.from_user:
            await m.answer("Не удалось определить ваш Telegram ID.")
            return
        await m.answer(f"Ваш Telegram ID: {m.from_user.id}")



    @dp.message(Command("note"))
    async def note(m: Message) -> None:
        REQ_TOTAL.labels(command="note").inc()
        if not m.from_user:
            await m.answer("Не удалось определить ваш Telegram ID.")
            return
        text = (m.text or "").split(maxsplit=1)
        if len(text) < 2 or not text[1].strip():
            await m.answer("Использование: /note <кто вы/зачем нужен доступ>")
            return
        await db_mod.upsert_user(db, m.from_user.id)
        await db_mod.set_user_note(db, m.from_user.id, text[1].strip())
        await m.answer("Ок. Примечание сохранено.")

    @dp.message(Command("request"))
    async def request_access(m: Message) -> None:
        REQ_TOTAL.labels(command="request").inc()
        if not m.from_user:
            await m.answer("Не удалось определить ваш Telegram ID.")
            return
        uid = int(m.from_user.id)
        await db_mod.upsert_user(db, uid)
        if is_admin(uid) or int(getattr(settings, "access_control_enabled", 0) or 0) <= 0:
            await m.answer("Доступ уже есть (или контроль доступа выключен).")
            return

        u = await db_mod.fetch_user_by_tg_user_id(db, uid)
        status = str((u or {}).get("status") or "guest")
        if status == "active":
            await m.answer("Доступ уже активен.")
            return
        if status == "blocked":
            await m.answer("Доступ заблокирован. Обратитесь к администратору.")
            return

        await db_mod.set_user_status(db, uid, "pending", expires_at=(u or {}).get("expires_at"))
        note = (u or {}).get("user_note") or ""
        await notify_admins(f"🆕 Запрос доступа: user_id={uid}, note={note}")
        await m.answer("Заявка отправлена админам. Добавьте /note, если ещё не добавляли.")

    # --- /users admin UI (Milestone 2): search + sessions + pagination ---

    def _clip_text(s: str, n: int) -> str:
        s = (s or "").strip()
        if len(s) <= n:
            return s
        return s[: max(0, n - 1)] + "…"

    async def _render_users_list(*, token: str, offset: int) -> tuple[str, InlineKeyboardMarkup]:
        sess = await db_mod.fetch_admin_session(db, token)
        if not sess:
            return ("Сессия устарела. Выполните /users заново.", InlineKeyboardMarkup(inline_keyboard=[]))

        qtxt = (sess.get("query") or "").strip()
        page_size = int(getattr(settings, "admin_users_page_size", 20) or 20)
        page_size = max(5, min(25, page_size))
        offset = max(0, int(offset))

        if qtxt:
            users, has_more = await db_mod.search_users(db, query=qtxt, limit=page_size, offset=offset)
        else:
            users, has_more = await db_mod.list_users_page(db, limit=page_size, offset=offset)

        title = "Пользователи"
        if qtxt:
            title += f" (поиск: {qtxt})"

        lines: list[str] = [title, f"Показано {len(users)} (offset={offset})"]
        if not users:
            lines.append("Пусто.")
        else:
            for u in users:
                uid = int(u["tg_user_id"])
                st = str(u.get("status") or "guest")
                exp = u.get("expires_at") or "-"
                note = _clip_text((u.get("user_note") or "").replace("\n", " "), 32)
                if note:
                    lines.append(f"{uid} · {st} · до {exp} · {note}")
                else:
                    lines.append(f"{uid} · {st} · до {exp}")

        kb: list[list[InlineKeyboardButton]] = []
        for u in users:
            uid = int(u["tg_user_id"])
            st = str(u.get("status") or "guest")
            kb.append([InlineKeyboardButton(text=f"👤 {uid} ({st})", callback_data=f"um:{token}:{offset}:{uid}")])

        nav: list[InlineKeyboardButton] = []
        if offset > 0:
            nav.append(InlineKeyboardButton(text="◀", callback_data=f"ul:{token}:{max(0, offset - page_size)}"))
        nav.append(InlineKeyboardButton(text="🔄", callback_data=f"ul:{token}:{offset}"))
        if has_more:
            nav.append(InlineKeyboardButton(text="▶", callback_data=f"ul:{token}:{offset + page_size}"))
        kb.append(nav)

        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb)

    async def _render_user_menu(*, token: str, offset: int, target_uid: int) -> tuple[str, InlineKeyboardMarkup]:
        sess = await db_mod.fetch_admin_session(db, token)
        if not sess:
            return ("Сессия устарела. Выполните /users заново.", InlineKeyboardMarkup(inline_keyboard=[]))

        target_uid = int(target_uid)
        u = await db_mod.fetch_user_by_tg_user_id(db, target_uid)
        if not u:
            await db_mod.upsert_user(db, target_uid)
            u = await db_mod.fetch_user_by_tg_user_id(db, target_uid)

        st = str((u or {}).get("status") or "guest")
        exp = (u or {}).get("expires_at") or "-"
        note = ((u or {}).get("user_note") or "").strip()

        out = [f"Пользователь {target_uid}", f"status={st}", f"expires_at={exp}"]
        if note:
            out.append("note=" + _clip_text(note.replace("\n", " "), 200))

        ttl_default = int(getattr(settings, "default_user_ttl_days", 30) or 30)

        kb: list[list[InlineKeyboardButton]] = []
        if target_uid not in settings.admin_ids_set():
            kb.append([InlineKeyboardButton(text=f"✅ Активировать +{ttl_default}d", callback_data=f"ua:act:{target_uid}:{ttl_default}:{token}:{offset}")])
            kb.append([InlineKeyboardButton(text="➕ Продлить +30d", callback_data=f"ua:ext:{target_uid}:30:{token}:{offset}")])
            kb.append([InlineKeyboardButton(text="⛔ Заблокировать", callback_data=f"ua:block:{target_uid}:0:{token}:{offset}")])

        kb.append([InlineKeyboardButton(text="⬅ Назад", callback_data=f"ul:{token}:{offset}")])
        return "\n".join(out), InlineKeyboardMarkup(inline_keyboard=kb)

    @dp.message(Command("users"))
    async def users_admin(m: Message) -> None:
        REQ_TOTAL.labels(command="users").inc()
        if not m.from_user or not is_admin(int(m.from_user.id)):
            uid = m.from_user.id if m.from_user else 0
            await m.answer(f"Недостаточно прав. Ваш ID: {uid}.")
            return

        # /users [query]
        parts = (m.text or "").split(maxsplit=1)
        qtxt = parts[1].strip() if len(parts) > 1 else ""
        ttl = int(getattr(settings, "admin_session_ttl_sec", 3600) or 3600)
        token = await db_mod.create_admin_session(db, tg_user_id=int(m.from_user.id), query=qtxt, ttl_sec=ttl)

        text, markup = await _render_users_list(token=token, offset=0)
        await m.answer(text, reply_markup=markup)

    @dp.callback_query(F.data.startswith("ul:"))
    async def users_list_cb(q: CallbackQuery) -> None:
        if not is_admin(int(q.from_user.id)):
            await q.answer("Нет прав")
            return
        parts = (q.data or "").split(":")
        if len(parts) != 3:
            await q.answer("Некорректно")
            return
        _tag, token, offset_s = parts
        try:
            offset = int(offset_s)
        except Exception:
            await q.answer("Некорректно")
            return

        sess = await db_mod.fetch_admin_session(db, token)
        if not sess or int(sess.get("tg_user_id") or 0) != int(q.from_user.id):
            await q.answer("Сессия устарела")
            return

        text, markup = await _render_users_list(token=token, offset=offset)
        try:
            await q.message.edit_text(text, reply_markup=markup)
        except Exception:
            pass
        await q.answer()

    @dp.callback_query(F.data.startswith("um:"))
    async def users_menu_cb(q: CallbackQuery) -> None:
        if not is_admin(int(q.from_user.id)):
            await q.answer("Нет прав")
            return
        parts = (q.data or "").split(":")
        if len(parts) != 4:
            await q.answer("Некорректно")
            return
        _tag, token, offset_s, uid_s = parts
        try:
            offset = int(offset_s)
            uid = int(uid_s)
        except Exception:
            await q.answer("Некорректно")
            return

        sess = await db_mod.fetch_admin_session(db, token)
        if not sess or int(sess.get("tg_user_id") or 0) != int(q.from_user.id):
            await q.answer("Сессия устарела")
            return

        text, markup = await _render_user_menu(token=token, offset=offset, target_uid=uid)
        try:
            await q.message.edit_text(text, reply_markup=markup)
        except Exception:
            pass
        await q.answer()

    @dp.callback_query(F.data.startswith("ua:"))
    async def user_admin_cb(q: CallbackQuery) -> None:
        if not is_admin(int(q.from_user.id)):
            await q.answer("Нет прав")
            return
        parts = (q.data or "").split(":")
        token: str | None = None
        offset = 0

        if len(parts) == 4:
            _tag, action, uid_s, days_s = parts
        elif len(parts) == 6:
            _tag, action, uid_s, days_s, token, offset_s = parts
            try:
                offset = int(offset_s)
            except Exception:
                offset = 0
        else:
            await q.answer("Некорректно")
            return

        try:
            uid = int(uid_s)
            days = int(days_s)
        except Exception:
            await q.answer("Некорректно")
            return

        try:
            await db_mod.upsert_user(db, uid)
            if action == "act":
                await db_mod.activate_user(db, uid, days)
                await q.answer("Активировано")
                try:
                    await bot.send_message(chat_id=uid, text=f"Доступ активирован на {days} дней.")
                except Exception:
                    pass
            elif action == "ext":
                await db_mod.extend_user(db, uid, days)
                await q.answer("Продлено")
                try:
                    await bot.send_message(chat_id=uid, text=f"Доступ продлён на {days} дней.")
                except Exception:
                    pass
            elif action == "block":
                await db_mod.set_user_status(db, uid, "blocked", expires_at=None)
                await q.answer("Заблокирован")
            else:
                await q.answer("Неизвестно")
                return

            if token:
                text, markup = await _render_user_menu(token=token, offset=offset, target_uid=uid)
                try:
                    await q.message.edit_text(text, reply_markup=markup)
                except Exception:
                    pass

        except Exception as e:
            await q.answer("Ошибка")
            log.warning("user_admin_action_failed", err=str(e), action=action, uid=uid)

    @dp.message(Command("audit"))
    async def audit_cmd(m: Message) -> None:
        REQ_TOTAL.labels(command="audit").inc()
        uid = m.from_user.id if m.from_user else 0
        if not is_admin(uid):
            await m.answer("Недостаточно прав.")
            return

        parts = (m.text or "").split()
        limit = 20
        if len(parts) >= 2 and parts[1].isdigit():
            limit = int(parts[1])
        limit = max(1, min(limit, 50))

        rows = await db_mod.fetch_recent_download_audit(db, limit=limit, offset=0)
        if not rows:
            await m.answer("Аудит пока пуст.")
            return

        out = ["Аудит скачиваний (последние):"]
        for r in rows:
            ts = str(r.get("created_at") or "")
            res = "✅" if r.get("result") == "succeeded" else "❌"
            title = str(r.get("title") or r.get("path") or "")
            if len(title) > 48:
                title = title[:45] + "..."
            out.append(f"{res} {ts} u={r.get('tg_user_id')} {title}")

        await m.answer("\n".join(out))

    @dp.message(Command("stats"))
    async def stats_cmd(m: Message) -> None:
        REQ_TOTAL.labels(command="stats").inc()
        uid = m.from_user.id if m.from_user else 0
        if not is_admin(uid):
            await m.answer("Недостаточно прав.")
            return

        last_24h = await db_mod.count_download_audit_since(db, since_minutes=24 * 60)
        users = await db_mod.count_users_by_status(db)
        top_7d = await db_mod.top_downloads_since(db, since_minutes=7 * 24 * 60, limit=5)

        text = (
            "Статистика:\n"
            f"Скачивания за 24ч: ✅ {last_24h.get('succeeded', 0)} / ❌ {last_24h.get('failed', 0)}\n"
            "Пользователи: "
            + ", ".join([f"{k}={v}" for k, v in sorted(users.items())])
        )

        if top_7d:
            text += "\n\nТоп файлов (7 дней):"
            for i, r in enumerate(top_7d, 1):
                title = str(r.get("title") or r.get("path") or "")
                if len(title) > 48:
                    title = title[:45] + "..."
                text += f"\n{i}) {r.get('count')} × {title}"

        await m.answer(text)

    @dp.callback_query(F.data.startswith("ua:"))
    async def user_admin_cb(q: CallbackQuery) -> None:
        if not is_admin(int(q.from_user.id)):
            await q.answer("Нет прав")
            return
        parts = (q.data or "").split(":")
        if len(parts) != 4:
            await q.answer("Некорректно")
            return
        _tag, action, uid_s, days_s = parts
        try:
            uid = int(uid_s)
            days = int(days_s)
        except Exception:
            await q.answer("Некорректно")
            return
        try:
            await db_mod.upsert_user(db, uid)
            if action == "act":
                await db_mod.activate_user(db, uid, days)
                await q.answer("Активировано")
                try:
                    await bot.send_message(chat_id=uid, text=f"Доступ активирован на {days} дней.")
                except Exception:
                    pass
            elif action == "ext":
                await db_mod.extend_user(db, uid, days)
                await q.answer("Продлено")
                try:
                    await bot.send_message(chat_id=uid, text=f"Доступ продлён на {days} дней.")
                except Exception:
                    pass
            elif action == "block":
                await db_mod.set_user_status(db, uid, "blocked", expires_at=None)
                await q.answer("Заблокирован")
            else:
                await q.answer("Неизвестно")
                return
        except Exception as e:
            await q.answer("Ошибка")
            log.warning("user_admin_action_failed", err=str(e), action=action, uid=uid)

    @dp.message(Command("categories"))
    async def categories(m: Message) -> None:
        REQ_TOTAL.labels(command="categories").inc()
        if m.from_user and not await ensure_active(int(m.from_user.id), reply_chat_id=m.chat.id, reply_cb=m.answer):
            return
        # Inline navigation UI (no long callback_data, only numeric ids).
        text, markup = await render_dir(root_path, viewer_tg_user_id=m.from_user.id if m.from_user else None, offset=0)
        await m.answer(text, reply_markup=markup)

    @dp.message(Command("search"))
    async def search_cmd(m: Message) -> None:
        REQ_TOTAL.labels(command="search").inc()
        if not m.from_user:
            await m.answer("Не удалось определить ваш Telegram ID.")
            return
        if not await ensure_active(int(m.from_user.id), reply_chat_id=m.chat.id, reply_cb=m.answer):
            return

        parts = (m.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await m.answer("Использование: /search <текст>")
            return
        query = parts[1].strip()

        token = await db_mod.create_search_session(db, tg_user_id=int(m.from_user.id), query=query, scope_path=root_path, ttl_sec=int(getattr(settings, "search_session_ttl_sec", 3600) or 3600))
        text, markup = await render_search(token, viewer_tg_user_id=int(m.from_user.id), offset=0)
        await m.answer(text, reply_markup=markup)



    @dp.message(Command("sync"))
    async def sync_catalog(m: Message) -> None:
        REQ_TOTAL.labels(command="sync").inc()
        admins = settings.admin_ids_set()
        if admins and m.from_user.id not in admins:
            uid = m.from_user.id if m.from_user else 0
            await m.answer(f"Недостаточно прав. Ваш ID: {uid}. Добавьте его в ADMIN_USER_IDS в .env и перезапустите сервисы.")
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
        # callback_data: nav:<folder_id>[:<offset>]
        parts = (q.data or "").split(":")
        if len(parts) < 2:
            await q.answer("Некорректная команда")
            return
        try:
            item_id = int(parts[1])
        except Exception:
            await q.answer("Некорректная команда")
            return
        try:
            offset = int(parts[2]) if len(parts) >= 3 else 0
        except Exception:
            offset = 0


        async def _reply(text: str) -> None:
            try:
                if q.message:
                    await q.message.answer(text)
                else:
                    await bot.send_message(chat_id=q.from_user.id, text=text)
            except Exception:
                pass

        if not await ensure_active(
            int(q.from_user.id),
            reply_chat_id=(q.message.chat.id if q.message else q.from_user.id),
            reply_cb=_reply,
        ):
            await q.answer()
            return

        try:
            item = await db_mod.fetch_catalog_item(db, item_id)
        except Exception:
            await q.answer("Элемент не найден")
            return

        if item.get("kind") != "folder":
            await q.answer("Это не папка")
            return

        text, markup = await render_dir(str(item.get("path") or root_path), viewer_tg_user_id=q.from_user.id, offset=offset)
        if q.message:
            await q.message.edit_text(text, reply_markup=markup)
        await q.answer()



    @dp.callback_query(F.data.startswith("s:"))
    async def search_cb(q: CallbackQuery) -> None:
        parts = (q.data or "").split(":")
        if len(parts) != 3:
            await q.answer()
            return
        _tag, token, offset_s = parts
        try:
            offset = int(offset_s)
        except Exception:
            offset = 0

        async def _reply(text: str) -> None:
            try:
                if q.message:
                    await q.message.answer(text)
                else:
                    await bot.send_message(chat_id=q.from_user.id, text=text)
            except Exception:
                pass

        if not await ensure_active(
            int(q.from_user.id),
            reply_chat_id=(q.message.chat.id if q.message else q.from_user.id),
            reply_cb=_reply,
        ):
            await q.answer()
            return

        text, markup = await render_search(token, viewer_tg_user_id=int(q.from_user.id), offset=offset)
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


        async def _reply(text: str) -> None:
            try:
                if q.message:
                    await q.message.answer(text)
                else:
                    await bot.send_message(chat_id=q.from_user.id, text=text)
            except Exception:
                pass

        if not await ensure_active(
            int(q.from_user.id),
            reply_chat_id=(q.message.chat.id if q.message else q.from_user.id),
            reply_cb=_reply,
        ):
            await q.answer()
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
        if settings.admin_ids_set() and m.from_user.id not in settings.admin_ids_set():
            uid = m.from_user.id if m.from_user else 0
            await m.answer(f"Недостаточно прав. Ваш ID: {uid}. Добавьте его в ADMIN_USER_IDS в .env и перезапустите сервисы.")
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
        if m.from_user and not await ensure_active(int(m.from_user.id), reply_chat_id=m.chat.id, reply_cb=m.answer):
            return
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
        if m.from_user and not await ensure_active(int(m.from_user.id), reply_chat_id=m.chat.id, reply_cb=m.answer):
            return
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

    # Background: warn about expiring access (if enabled)
    warn_task = asyncio.create_task(access_warn_scheduler())

    # Keep the process alive even if Telegram long polling temporarily fails.
    # Otherwise the container may flap (unhealthy) and block deployments.
    backoff = 1
    max_backoff = int(getattr(settings, "net_retry_max_sec", 30) or 30)

    try:
        while True:
            try:
                state["polling"] = "running"
                state["last_poll_error"] = None

                # Quick handshake: makes /ready useful and avoids silent crash-loops.
                # Liveness (/health) stays up regardless.
                try:
                    await asyncio.wait_for(bot.get_me(), timeout=10)
                    from datetime import datetime, timezone

                    state["last_poll_ok_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                except TelegramUnauthorizedError:
                    # fall through to the main handler below
                    raise

                await dp.start_polling(bot)
                # Normal exit (e.g., cancelled/shutdown)
                break
            except asyncio.CancelledError:
                raise
            except TelegramUnauthorizedError:
                # In CI smoke we use a fake token; keep /health alive instead of crash-looping.
                if os.getenv("CI_SMOKE", "0") == "1":
                    log.warning("Telegram token unauthorized in CI_SMOKE; keeping service alive for health checks")
                    await asyncio.Event().wait()
                raise
            except (TelegramNetworkError, TelegramServerError, asyncio.TimeoutError, ConnectionError) as e:
                state["polling"] = "retrying"
                state["last_poll_error"] = str(e)
                log.warning("polling_error_retry", err=str(e), backoff_s=backoff)
                await asyncio.sleep(backoff)
                backoff = min(max_backoff, max(1, backoff * 2))
                continue
            except Exception as e:
                # Unknown error: retry, but keep it visible.
                state["polling"] = "retrying"
                state["last_poll_error"] = str(e)
                log.exception("polling_error_retry_unknown", err=str(e), backoff_s=backoff)
                await asyncio.sleep(backoff)
                backoff = min(max_backoff, max(1, backoff * 2))
                continue
    finally:
        try:
            warn_task.cancel()
        except Exception:
            pass
        await bot.session.close()
        await db.close()
        await r.close()


if __name__ == "__main__":
    asyncio.run(main())
