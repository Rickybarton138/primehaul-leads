#!/usr/bin/env python3
"""Production startup script - handles database migrations safely."""
import os
import sys
import subprocess
from sqlalchemy import create_engine, text


def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

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
                subprocess.run(["alembic", "stamp", "head"], check=True)
            elif not tables_exist:
                print("Fresh database - running all migrations...")
                subprocess.run(["alembic", "upgrade", "head"], check=True)
            else:
                print("Running pending migrations...")
                subprocess.run(["alembic", "upgrade", "head"], check=True)

    except Exception as e:
        print(f"FATAL: Database setup error: {e}")
        sys.exit(1)

    print("Database ready!")


if __name__ == "__main__":
    main()
