"""Database URL normalisation for psycopg3 compatibility."""


def normalize_database_url(url: str) -> str:
    """Rewrite a PostgreSQL URL to use the psycopg3 (psycopg) driver.

    Handles the common prefixes emitted by hosting providers:
      - ``postgresql://``  -> ``postgresql+psycopg://``
      - ``postgresql+psycopg2://`` -> ``postgresql+psycopg://``
      - ``postgres://`` (legacy) -> ``postgresql+psycopg://``

    Already-correct URLs (``postgresql+psycopg://``) are returned unchanged.
    """
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url
