import os
import sys
import tempfile

import pytest

# 管理密码无默认值(config 启动时读环境变量);测试统一用它
os.environ.setdefault("BR_ADMIN_PASS", "790923")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    """限速器为进程级内存状态:每例重置,避免跨测试泄漏(同 IP 连续 429)。"""
    from app import ratelimit
    ratelimit._attempts.clear()
    ratelimit._counts.clear()
    yield
    ratelimit._attempts.clear()
    ratelimit._counts.clear()


@pytest.fixture()
def client(tmp_path):
    """独立 DB 的测试客户端:直接改 config.DB_PATH(connect() 调用时求值)。"""
    import app.config as config
    config.DB_PATH = str(tmp_path / "test.db")
    from app import db
    db.init_db(config.DB_PATH)
    from app.main import app
    with TestClient(app) as c:
        yield c
