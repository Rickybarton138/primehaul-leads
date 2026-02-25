"""Database URL normalisation for psycopg compatibility."""


def _detect_driver() -> str:
    """Return the best available psycopg SQLAlchemy driver prefix."""
    try:
        import psycopg  # noqa: F401
        return "postgresql+psycopg"
    except ImportError:
        pass
    try:
        import psycopg2  # noqa: F401
        return "postgresql+psycopg2"
    except ImportError:
        pass
    return "postgresql"


def normalize_database_url(url: str) -> str:
    """Rewrite a PostgreSQL URL to use the best available driver.

    Tries psycopg3 first, falls back to psycopg2, then plain postgresql.
    Handles common prefixes from hosting providers:
      - ``postgresql://``
      - ``postgres://`` (legacy)
      - ``postgresql+psycopg2://``
      - ``postgresql+psycopg://``
    """
    driver = _detect_driver()

    # Strip any existing driver suffix to normalise
    for prefix in (
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
        "postgresql://",
        "postgres://",
    ):
        if url.startswith(prefix):
            return url.replace(prefix, f"{driver}://", 1)

    return url
