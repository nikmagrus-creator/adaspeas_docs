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

