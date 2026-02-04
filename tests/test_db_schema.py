import asyncio
import os
import tempfile
import sys
from pathlib import Path

# Allow running tests without installing the package
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


import pytest

from adaspeas.common import db as db_mod


@pytest.mark.asyncio
async def test_schema_init_and_user_upsert():
    with tempfile.NamedTemporaryFile(suffix='.sqlite') as tmp:
        db = await db_mod.connect(tmp.name)
        await db_mod.ensure_schema(db)
        uid = await db_mod.upsert_user(db, 123)
        uid2 = await db_mod.upsert_user(db, 123)
        assert uid == uid2
        await db.close()
