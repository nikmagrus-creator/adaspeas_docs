from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator, Protocol


class StorageClient(Protocol):
    async def stream_download(self, path: str, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        ...


class LocalDiskClient:
    def __init__(self, root: str):
        self._root = Path(root)

    async def stream_download(self, path: str, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        rel = path.lstrip("/")
        full = (self._root / rel).resolve()
        # Basic guard against path traversal.
        if self._root.resolve() not in full.parents and full != self._root.resolve():
            raise RuntimeError("Local storage: invalid path")
        if not full.exists() or not full.is_file():
            raise FileNotFoundError(str(full))

        with open(full, "rb") as f:
            while True:
                chunk = await asyncio.to_thread(f.read, chunk_size)
                if not chunk:
                    break
                yield chunk


def make_storage_client(settings) -> StorageClient:
    """Small factory to allow end-to-end runs without external storage."""
    mode = (getattr(settings, "storage_mode", "yandex") or "yandex").strip().lower()
    if mode == "local":
        return LocalDiskClient(getattr(settings, "local_storage_root", "/data/storage"))

    # Default: Yandex Disk
    from adaspeas.storage.yandex_disk import YandexDiskClient

    token = getattr(settings, "yandex_oauth_token", "")
    if not token:
        raise RuntimeError("Storage mode 'yandex' requires YANDEX_OAUTH_TOKEN")
    return YandexDiskClient(token)

