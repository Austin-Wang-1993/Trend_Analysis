from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./data/trend_analysis.db"
    data_source_priority: str = "eastmoney,tonghuashun"
    sync_cron: str = "30 16 * * 1-5"
    api_max_retries: int = 3
    api_retry_wait_seconds: int = 3
    log_level: str = "INFO"
    log_dir: str = "./logs"

    @property
    def data_dir(self) -> Path:
        return Path("data")

    @property
    def source_priority_list(self) -> list[str]:
        return [s.strip() for s in self.data_source_priority.split(",") if s.strip()]


settings = Settings()
