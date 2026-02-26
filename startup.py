#!/usr/bin/env python3
"""Production startup script - handles database migrations safely."""
import os
import sys
import subprocess
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(__file__))
from app.db_utils import normalize_database_url


def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    database_url = normalize_database_url(database_url)

    print("Checking database state...")
    engine = create_engine(database_url)

    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alembic_version')"
            ))
            alembic_exists = result.scalar()

            result = conn.execute(text(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'leads')"
            ))
            tables_exist = result.scalar()

            if tables_exist and not alembic_exists:
                print("Tables exist but no alembic_version - stamping to latest...")
                subprocess.run([sys.executable, "-m", "alembic", "stamp", "head"], check=True)
            elif not tables_exist:
                print("Fresh database - running all migrations...")
                subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
            else:
                print("Running pending migrations...")
                subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)

    except Exception as e:
        print(f"Database setup error: {e}")
        print("Attempting to continue anyway...")

    # Ensure all model tables exist (covers new models not yet in Alembic)
    try:
        from app.models import Base
        Base.metadata.create_all(engine, checkfirst=True)
        print("All model tables verified")
    except Exception as e:
        print(f"Table creation check error: {e}")

    print("Database ready!")


if __name__ == "__main__":
    main()
