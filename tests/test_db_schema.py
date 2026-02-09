import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from adaspeas.common import db as db_mod


@pytest.mark.asyncio
async def test_schema_init_and_user_upsert():
    with tempfile.NamedTemporaryFile(suffix='.sqlite') as tmp:
        db = await db_mod.connect(tmp.name)
        await db_mod.ensure_schema(db)
        uid = await db_mod.upsert_user(db, 123)
        uid2 = await db_mod.upsert_user(db, 123)
        assert uid == uid2
        u = await db_mod.fetch_user_by_tg_user_id(db, 123)
        assert u and u['status'] in {'guest','pending','active','expired','blocked'}
        await db.close()

@pytest.mark.asyncio
async def test_schema_upgrade_tolerates_existing_status_column():
    # Repro for prod: DB already has users.status but schema_version < 6, so v6 used to crash with
    # sqlite3.OperationalError: duplicate column name: status.
    with tempfile.NamedTemporaryFile(suffix='.sqlite') as tmp:
        db = await db_mod.connect(tmp.name)

        # create schema_version + v1 tables
        await db.executescript(db_mod.SCHEMA_V1)
        await db.execute("INSERT INTO schema_version(version) VALUES (1)")
        await db.commit()

        # apply migrations up to v5
        for ver in range(2, 6):
            await db.executescript(db_mod.MIGRATIONS[ver])
            await db.execute("UPDATE schema_version SET version=?", (ver,))
            await db.commit()

        # simulate pre-existing column created out-of-band
        await db.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'guest'")
        await db.execute("UPDATE schema_version SET version=?", (5,))
        await db.commit()

        # should not raise
        await db_mod.ensure_schema(db)

        v = await db_mod._get_schema_version(db)
        assert v == db_mod.TARGET_SCHEMA_VERSION
        await db.close()


@pytest.mark.asyncio
async def test_search_fallback_matches_path_when_fts_missing():
    # When FTS table is missing/broken, fallback LIKE search must still match both title and path.
    with tempfile.NamedTemporaryFile(suffix='.sqlite') as tmp:
        db = await db_mod.connect(tmp.name)
        await db_mod.ensure_schema(db)

        # Seed catalog
        await db_mod.upsert_catalog_item(
            db,
            path="/",
            kind="folder",
            title="Каталог",
            yandex_id="/",
            parent_path=None,
        )
        await db_mod.upsert_catalog_item(
            db,
            path="/docs",
            kind="folder",
            title="Документы",
            yandex_id="/docs",
            parent_path="/",
        )
        await db_mod.upsert_catalog_item(
            db,
            path="/docs/foo_report.pdf",
            kind="file",
            title="Отчёт",
            yandex_id="/docs/foo_report.pdf",
            parent_path="/docs",
            size_bytes=123,
        )
        await db.commit()

        # Force fallback branch: remove FTS table
        await db.execute("DROP TABLE IF EXISTS catalog_items_fts")
        await db.commit()

        items, _has_more = await db_mod.search_catalog_items(
            db,
            query="foo",
            scope_path="/",
            limit=10,
            offset=0,
        )
        assert any(i.get("path") == "/docs/foo_report.pdf" for i in items)

        await db.close()
