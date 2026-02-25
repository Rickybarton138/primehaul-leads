"""Unit tests for database URL normalisation."""

from app.db_utils import normalize_database_url


class TestNormalizeDatabaseUrl:
    def test_postgresql_prefix(self):
        assert normalize_database_url(
            "postgresql://user:pass@host/db"
        ) == "postgresql+psycopg://user:pass@host/db"

    def test_postgres_legacy_prefix(self):
        assert normalize_database_url(
            "postgres://user:pass@host/db"
        ) == "postgresql+psycopg://user:pass@host/db"

    def test_psycopg2_prefix(self):
        assert normalize_database_url(
            "postgresql+psycopg2://user:pass@host/db"
        ) == "postgresql+psycopg://user:pass@host/db"

    def test_already_correct(self):
        url = "postgresql+psycopg://user:pass@host/db"
        assert normalize_database_url(url) == url

    def test_unknown_scheme_unchanged(self):
        url = "mysql://user:pass@host/db"
        assert normalize_database_url(url) == url
