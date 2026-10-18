import os
import psycopg2.pool

DSN = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ledger")
_pool = None


def pool(maxconn: int = 64):
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, maxconn, DSN)
    return _pool
