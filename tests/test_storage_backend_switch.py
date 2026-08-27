"""storage 可切换后端：后端检测与 DDL 差异（不连真实数据库）。

Postgres 路径的真实读写依赖外部 Neon/Supabase，不在 CI 内联测试；
这里只验证「后端选择逻辑正确」与「两套 DDL 方言差异正确」，
确保 DATABASE_URL 一旦设置能正确切到 Postgres、且 SQLite 路径不被破坏。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app.storage as storage


def test_default_is_sqlite_when_no_database_url(monkeypatch):
    """未设置 DATABASE_URL 时应走 SQLite 后端。"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # 重新加载模块以反映环境变量变化（psycopg2 可用性由环境决定，仅验证 URL 维度）
    import importlib

    importlib.reload(storage)
    # 只要 DATABASE_URL 不是 postgresql:// 开头，is_postgres 应为 False
    assert not storage.DATABASE_URL or not storage.DATABASE_URL.startswith("postgresql")
    if not storage.DATABASE_URL:
        assert storage.is_postgres() is False


def test_is_postgres_detects_postgresql_url(monkeypatch):
    """DATABASE_URL 为 postgresql:// 且 psycopg2 可用时，is_postgres 为 True。"""
    if not storage._HAS_PG:
        # 环境未装 psycopg2 时跳过（SQLite-only 环境）
        return
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    import importlib

    importlib.reload(storage)
    assert storage.is_postgres() is True


def test_sqlite_ddl_uses_autoincrement(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import importlib

    importlib.reload(storage)
    assert "AUTOINCREMENT" in storage._SQLITE_DDL
    assert "SERIAL" not in storage._SQLITE_DDL
    # SQLite 历史默认写法保持不变（零回归）
    assert "datetime('now')" in storage._SQLITE_DDL


def test_pg_ddl_uses_serial_and_current_timestamp(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    import importlib

    importlib.reload(storage)
    assert "SERIAL PRIMARY KEY" in storage._PG_DDL
    assert "CURRENT_TIMESTAMP" in storage._PG_DDL
    assert "AUTOINCREMENT" not in storage._PG_DDL
    # 验证码在 Postgres 用 DOUBLE PRECISION（与 SQLite 的 TEXT 区分）
    assert "DOUBLE PRECISION" in storage._PG_DDL


def test_placeholder_transform_for_postgres(monkeypatch):
    """_execute 在 Postgres 下把 ? 转成 %s（验证辅助函数行为）。"""
    if not storage._HAS_PG:
        return
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    import importlib

    importlib.reload(storage)

    class _FakeConn:
        def __init__(self):
            self.last = None

        def execute(self, sql, params=()):
            self.last = (sql, params)
            return None

    conn = _FakeConn()
    storage._execute(conn, "SELECT * FROM users WHERE id=?", (1,))
    assert conn.last[0] == "SELECT * FROM users WHERE id=%s"
    assert conn.last[1] == (1,)
