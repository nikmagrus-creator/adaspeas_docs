from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    bot_token: str
    admin_user_ids: str = ""

    # Access control (Milestone 2)
    access_control_enabled: int = 0  # 1 = enforce user status/expiry, 0 = allow everyone
    default_user_ttl_days: int = 30
    access_warn_before_sec: int = 86400  # 24h
    access_warn_check_interval_sec: int = 3600
    admin_notify_chat_id: int = 0  # optional: отдельный чат/топик для уведомлений админам

    # Storage
    storage_mode: str = "yandex"  # yandex | local
    yandex_oauth_token: str = ""
    yandex_base_path: str = "/Zkvpr"
    local_storage_root: str = "/data/storage"

    # DB
    sqlite_path: str = "/data/app.db"

    # Catalog UI / sync
    # Page size for inline catalog navigation.
    catalog_page_size: int = 25
    # Periodic background sync in worker (0 disables; recommended in prod: 3600).
    catalog_sync_interval_sec: int = 0
    # Safety cap for nodes visited per sync (prevents endless trees / huge repos).
    catalog_sync_max_nodes: int = 5000

    # Queue
    redis_url: str = "redis://redis:6379/0"

    # Local Bot API (optional)
    local_bot_api_base: str = "http://local-bot-api:8081"
    use_local_bot_api: int = 0

    # Observability
    log_level: str = "INFO"

    def admin_ids_set(self) -> set[int]:
        raw = (self.admin_user_ids or "").strip()
        if not raw:
            return set()
        out: set[int] = set()
        for part in raw.split(","):
            part = part.strip()
            if part:
                out.add(int(part))
        return out
