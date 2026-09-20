from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    ORIGINS: list[str]

    @property
    def sync_database_url(self) -> str:
        return self.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")


settings = Settings()
