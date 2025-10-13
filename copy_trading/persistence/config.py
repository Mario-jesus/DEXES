# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv

load_dotenv()

def build_database_url():
    """Build the async database URL from environment variables."""
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "12345678")
    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    database = os.getenv("PGDATABASE", "postgres")

    # Use postgresql+asyncpg for async SQLAlchemy
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"

# Build URL from individual PostgreSQL variables (same as alembic migrations)
DATABASE_URL = build_database_url()
ECHO_SQL = os.getenv("ECHO_SQL", "false").lower() == "true"
