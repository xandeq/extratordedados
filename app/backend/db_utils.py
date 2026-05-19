"""
Database utilities — connection pool, get_db context manager, DB_CONFIG.
Extracted from app.py to allow import from background threads and blueprints.
"""
import os
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool as _pool

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'port': int(os.environ.get('DB_PORT', 5432)),
    'dbname': os.environ.get('DB_NAME', 'extrator'),
    'user': os.environ.get('DB_USER', 'extrator'),
    'password': os.environ.get('DB_PASSWORD', ''),
}

db_pool = None


def get_pool():
    global db_pool
    if db_pool is None or db_pool.closed:
        db_pool = _pool.ThreadedConnectionPool(1, 10, **DB_CONFIG)
    return db_pool


@contextmanager
def get_db():
    """Get a database connection from the pool."""
    p = get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)
