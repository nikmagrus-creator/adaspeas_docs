from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    bot_token: str
    admin_user_ids: str = ""

    # Storage
    yandex_oauth_token: str
    yandex_base_path: str = "/Zkvpr"

    # DB
    sqlite_path: str = "/data/adaspeas.sqlite"

    # Queue
    redis_url: str = "redis://redis:6379/0"

    # Local Bot API (optional)
    local_bot_api_base: str = "http://local-bot-api:8082"
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
