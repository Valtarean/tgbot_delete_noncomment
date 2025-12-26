from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    bot_token: str = Field(..., env="BOT_TOKEN")
    admin_id: int = Field(..., env="ADMIN_ID")
    group_id: int = Field(..., env="GROUP_ID")
    channel_id: int = Field(..., env="CHANNEL_ID")

    auto_delete_delay: int = Field(10, env="AUTO_DELETE_DELAY")
    warning_cooldown: int = Field(180, env="WARNING_COOLDOWN")
    admin_cache_ttl_minutes: int = Field(600, env="ADMIN_CACHE_TTL_MINUTES")
    max_chain_depth: int = Field(20, env="MAX_CHAIN_DEPTH")

    # Persistence
    db_path: str = Field("data/bot.sqlite3", env="DB_PATH")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"