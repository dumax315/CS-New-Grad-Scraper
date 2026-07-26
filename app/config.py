from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./jobs.db")
    timezone: str = os.getenv("APP_TIMEZONE", "America/Los_Angeles")
    public_url: str = os.getenv("APP_PUBLIC_URL", "").rstrip("/")
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")
    alert_recipient: str = os.getenv("ALERT_RECIPIENT", "")
    smtp_use_tls: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    subscription_token_secret: str = os.getenv("SUBSCRIPTION_TOKEN_SECRET", "")
    send_initial_digest: bool = os.getenv("SEND_INITIAL_DIGEST", "false").lower() == "true"
    lifecycle_visibility: bool = os.getenv(
        "APPLY_LIFECYCLE_VISIBILITY",
        "true",
    ).lower() == "true"
    codex_model: str = os.getenv("CODEX_MODEL", "gpt-5.6-luna")
    codex_timeout_seconds: int = int(os.getenv("CODEX_TIMEOUT_SECONDS", "120"))
    codex_home: str = os.getenv("CODEX_HOME", "/var/lib/codex")


settings = Settings()
