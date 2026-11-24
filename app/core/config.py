from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "dev-secret-key-change-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    DATABASE_URL: str
    # Log every SQL statement; useful when debugging, noisy and slow otherwise
    DB_ECHO: bool = False
    # "development" or "production"; production refuses to start with an
    # unsafe SECRET_KEY or a wildcard CORS origin
    ENVIRONMENT: str = "development"
    # Browsers may call the API (with credentials) only from these sites
    ORIGINS: list[str] = ["http://localhost:3000"]
    # Override in every deployed environment; tokens signed with this are forgeable
    SECRET_KEY: str = DEV_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # Refresh tokens keep a session (e.g. a check-in shift) alive; each use
    # returns a new pair, and sign-out or a password change revokes them
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = 24
    # Checkout: how long a pending order holds its places
    CHECKOUT_HOLD_MINUTES: int = 10
    # Simulated processor charge, deducted from the organizer's payout
    PROCESSING_FEE_PERCENT: float = 2.5
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30

    # Brute-force and email-flood protection (kept in memory per process)
    RATE_LIMIT_ENABLED: bool = True
    LOGIN_MAX_FAILURES: int = 10
    LOGIN_WINDOW_MINUTES: int = 15
    AUTH_EMAILS_PER_WINDOW: int = 3
    AUTH_EMAIL_WINDOW_MINUTES: int = 15

    # Links in emails point at the web frontend, e.g. /verify-email?token=...
    FRONTEND_URL: str = "http://localhost:3000"

    # Local development uses Mailpit (see docker-compose.yml, UI on :8025).
    # With EMAIL_ENABLED=false, emails are written to the log instead of sent.
    EMAIL_ENABLED: bool = True
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_USE_TLS: bool = False
    EMAIL_FROM: str = "BiletFlow <no-reply@biletflow.local>"

    # Uploads: "local" (MEDIA_DIR, served at /api/v1/media) or "s3"
    STORAGE_BACKEND: str = "local"
    MEDIA_DIR: str = "media"
    # Where this API is reachable from browsers; used for local media URLs
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    MAX_IMAGE_BYTES: int = 5 * 1024 * 1024
    MAX_IMAGES_PER_EVENT: int = 10
    S3_ENDPOINT_URL: str | None = None
    S3_BUCKET: str = "biletflow"
    S3_ACCESS_KEY: str | None = None
    S3_SECRET_KEY: str | None = None
    S3_REGION: str = "us-east-1"
    S3_PUBLIC_BASE_URL: str | None = None

    # Unicode TTF fonts for PDF tickets; found automatically when left empty
    # (DejaVu in Docker, Arial on Windows)
    TICKET_FONT_PATH: str | None = None
    TICKET_FONT_BOLD_PATH: str | None = None

    @model_validator(mode="after")
    def _check_production_safety(self) -> "Settings":
        if self.ENVIRONMENT.lower() != "production":
            return self
        if self.SECRET_KEY == DEV_SECRET_KEY or len(self.SECRET_KEY) < 32:
            raise ValueError(
                "SECRET_KEY must be set to a random value of at least 32 characters "
                "in production"
            )
        if "*" in self.ORIGINS:
            raise ValueError("ORIGINS must list the real site addresses in production")
        return self

    @property
    def sync_database_url(self) -> str:
        return self.DATABASE_URL.replace(
            "postgresql+asyncpg", "postgresql+psycopg2"
        ).replace("ssl=require", "sslmode=require")


settings = Settings()
