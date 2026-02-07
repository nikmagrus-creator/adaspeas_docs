from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator, Protocol


class StorageClient(Protocol):
    async def stream_download(self, path: str, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        ...

    async def list_dir(self, path: str) -> list[dict]:
        ...

    async def close(self) -> None:
        ...


class LocalDiskClient:
    def __init__(self, root: str):
        self._root = Path(root)


    async def list_dir(self, path: str) -> list[dict]:
        rel = path.lstrip("/")
        base = (self._root / rel).resolve()
        if self._root.resolve() not in base.parents and base != self._root.resolve():
            raise RuntimeError("Local storage: invalid path")
        if not base.exists() or not base.is_dir():
            raise FileNotFoundError(str(base))

        import os
        out: list[dict] = []
        for name in sorted(os.listdir(base))[:500]:
            full = (base / name)
            if full.is_dir():
                out.append({"name": name, "type": "dir", "path": (path.rstrip("/") + "/" + name) if path != "/" else "/" + name})
            elif full.is_file():
                try:
                    st = full.stat()
                    out.append({
                        "name": name,
                        "type": "file",
                        "path": (path.rstrip("/") + "/" + name) if path != "/" else "/" + name,
                        "size": int(st.st_size),
                        "modified": None,
                    })
                except Exception:
                    out.append({"name": name, "type": "file", "path": (path.rstrip("/") + "/" + name) if path != "/" else "/" + name})
        return out

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

    async def close(self) -> None:
        # No resources to close.
        return


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

