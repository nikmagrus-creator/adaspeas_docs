import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from adaspeas.common import db as db_mod
from adaspeas.common.settings import Settings


@pytest.mark.asyncio
async def test_schema_version_and_required_columns():
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
        db = await db_mod.connect(tmp.name)
        await db_mod.ensure_schema(db)

        # schema_version must match TARGET_SCHEMA_VERSION
        cur = await db.execute("SELECT version FROM schema_version LIMIT 1")
        row = await cur.fetchone()
        assert row and int(row[0]) == getattr(db_mod, "TARGET_SCHEMA_VERSION")

        # users columns (access control)
        cur = await db.execute("PRAGMA table_info(users)")
        cols = {r[1] for r in await cur.fetchall()}
        for required in {"tg_user_id", "status", "user_note", "expires_at", "warned_24h_at", "updated_at"}:
            assert required in cols

        # catalog_items columns
        cur = await db.execute("PRAGMA table_info(catalog_items)")
        cols = {r[1] for r in await cur.fetchall()}  # name is column 1
        for required in {
            "path",
            "kind",
            "title",
            "parent_path",
            "seen_at",
            "is_deleted",
            "tg_file_id",
            "tg_file_unique_id",
        }:
            assert required in cols

        # jobs columns
        cur = await db.execute("PRAGMA table_info(jobs)")
        cols = {r[1] for r in await cur.fetchall()}
        assert "job_type" in cols

        # download_audit table (Milestone 3)
        cur = await db.execute("PRAGMA table_info(download_audit)")
        cols = {r[1] for r in await cur.fetchall()}
        for required in {"created_at", "job_id", "tg_chat_id", "tg_user_id", "catalog_item_id", "result", "mode", "bytes", "error"}:
            assert required in cols

        await db.close()


@pytest.mark.asyncio
async def test_db_api_contract_for_catalog_jobs_and_audit():
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
        db = await db_mod.connect(tmp.name)
        await db_mod.ensure_schema(db)

        # Minimal tree
        await db_mod.upsert_catalog_item(db, path="/", parent_path=None, kind="folder", title="/")
        await db_mod.upsert_catalog_item(db, path="/A", parent_path="/", kind="folder", title="A")
        await db_mod.upsert_catalog_item(db, path="/A/file.txt", parent_path="/A", kind="file", title="file.txt", size_bytes=123)

        item = await db_mod.fetch_catalog_item_by_path(db, "/A/file.txt")
        assert item and int(item["id"]) > 0
        item_id = int(item["id"])

        jid = await db_mod.insert_job(
            db,
            tg_chat_id=1,
            tg_user_id=42,
            catalog_item_id=item_id,
            request_id="req-1",
            job_type="download",
        )
        job = await db_mod.fetch_job(db, jid)
        assert job["job_type"] == "download"

        await db_mod.insert_download_audit(
            db,
            job_id=jid,
            tg_chat_id=1,
            tg_user_id=42,
            catalog_item_id=item_id,
            result="succeeded",
            mode="upload",
            bytes_sent=123,
            error=None,
        )

        rows = await db_mod.fetch_recent_download_audit(db, limit=10, offset=0)
        assert any(int(r["job_id"]) == jid and r["result"] == "succeeded" for r in rows)

        await db.close()


def test_settings_has_expected_fields():
    s = Settings(bot_token="x", admin_user_ids="")
    assert hasattr(s, "catalog_page_size")
    assert hasattr(s, "catalog_sync_interval_sec")
    assert hasattr(s, "catalog_sync_max_nodes")

    assert hasattr(s, "access_control_enabled")
    assert hasattr(s, "default_user_ttl_days")
    assert hasattr(s, "access_warn_before_sec")
    assert hasattr(s, "access_warn_check_interval_sec")

    assert hasattr(s, "admin_notify_chat_id")
