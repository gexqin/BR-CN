"""FastAPI 依赖:每请求独立 SQLite 连接。"""
from .. import db as dbmod  # noqa


def get_conn():
    conn = dbmod.connect()
    try:
        yield conn
    finally:
        conn.close()
