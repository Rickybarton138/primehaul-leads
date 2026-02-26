import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_VISION_MODEL: str = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")
    MAPBOX_ACCESS_TOKEN: str = os.getenv("MAPBOX_ACCESS_TOKEN", "")
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY: str = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    APP_ENV: str = os.getenv("APP_ENV", "development")
    APP_URL: str = os.getenv("APP_URL", "http://localhost:8000")
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "leads@primehaul.co.uk")
    SMTP_FROM_NAME: str = os.getenv("SMTP_FROM_NAME", "PrimeHaul Leads")

    # Social Media Automation
    META_PAGE_ACCESS_TOKEN: str = os.getenv("META_PAGE_ACCESS_TOKEN", "")
    META_PAGE_ID: str = os.getenv("META_PAGE_ID", "")
    META_INSTAGRAM_ACCOUNT_ID: str = os.getenv("META_INSTAGRAM_ACCOUNT_ID", "")
    X_API_KEY: str = os.getenv("X_API_KEY", "")
    X_API_SECRET: str = os.getenv("X_API_SECRET", "")
    X_ACCESS_TOKEN: str = os.getenv("X_ACCESS_TOKEN", "")
    X_ACCESS_TOKEN_SECRET: str = os.getenv("X_ACCESS_TOKEN_SECRET", "")
    LINKEDIN_ACCESS_TOKEN: str = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    LINKEDIN_ORG_ID: str = os.getenv("LINKEDIN_ORG_ID", "")
    SOCIAL_AUTO_PUBLISH: bool = os.getenv("SOCIAL_AUTO_PUBLISH", "true").lower() == "true"
    SOCIAL_POSTS_PER_DAY: int = int(os.getenv("SOCIAL_POSTS_PER_DAY", "2"))


settings = Settings()

# Validate critical secrets in production
if settings.APP_ENV != "development":
    _missing = [
        name
        for name in ("JWT_SECRET_KEY", "DATABASE_URL")
        if not getattr(settings, name, "")
    ]
    if _missing:
        raise RuntimeError(
            f"Missing required secrets for production: {', '.join(_missing)}"
        )
