"""Postgres 路径单元测试（用假 psycopg2，不连真实库）。

覆盖此前线上崩溃的 psycopg2 接口问题：psycopg2 连接本身无 .execute()，
经 _PgConn 包装后业务代码可统一用 conn.execute(...)->cursor。
验证 init_db / _execute / _insert_returning_id 在 Postgres 分支的真实行为，
无需外部 Neon 或安装 psycopg2。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app.storage as storage


class _FakeCursor:
    def __init__(self, owner):
        self.owner = owner
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self.owner.all_calls.append((sql, params))

    def fetchone(self):
        return self.owner.next_row

    def fetchall(self):
        return self.owner.next_rows


class _FakeRawConn:
    def __init__(self):
        self.committed = False
        self.closed = False
        self.cursor_factory = None
        self.next_row = None
        self.next_rows = []
        self.all_calls = []
        self.last_cursor = None

    def cursor(self):
        self.last_cursor = _FakeCursor(self)
        return self.last_cursor

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class _FakeExtras:
    RealDictCursor = object


class _FakePsycopg2:
    extras = _FakeExtras()

    def connect(self, *args, **kwargs):
        return _FakeRawConn()


def _enable_postgres(monkeypatch):
    """把 storage 切到 Postgres 分支（用假 psycopg2，不需要真实驱动或网络）。"""
    monkeypatch.setattr(storage, "_HAS_PG", True, raising=False)
    monkeypatch.setattr(storage, "DATABASE_URL", "postgresql://u:p@host/db", raising=False)
    monkeypatch.setattr(storage, "psycopg2", _FakePsycopg2(), raising=False)
    assert storage.is_postgres() is True


def test_pg_conn_wrapper_exposes_execute(monkeypatch):
    """_PgConn 必须暴露 .execute()/.commit()/.close()，否则业务代码会 AttributeError。"""
    _enable_postgres(monkeypatch)
    raw = _FakeRawConn()
    wrapped = storage._PgConn(raw)
    cur = wrapped.execute("SELECT 1", (1,))
    assert isinstance(cur, _FakeCursor)
    assert cur.calls == [("SELECT 1", (1,))]
    wrapped.commit()
    assert raw.committed is True
    wrapped.close()
    assert raw.closed is True


def test_init_db_executes_ddl_and_commits_on_postgres(monkeypatch):
    """init_db 在 Postgres 分支应通过 execute 执行各 DDL 语句并提交/关闭（不抛 AttributeError）。"""
    _enable_postgres(monkeypatch)
    spy = _FakeRawConn()
    monkeypatch.setattr(storage, "_connect", lambda: storage._PgConn(spy))
    storage.init_db()  # 此前此处因 psycopg2 无 .execute() 而崩溃
    # 每个 DDL 语句都经由 execute 执行（users/profiles/skill_library/verification_codes/analysis_results + 索引）
    assert len(spy.all_calls) >= 5
    assert spy.committed is True
    assert spy.closed is True


def test_execute_transforms_placeholder_on_postgres(monkeypatch):
    """_execute 在 Postgres 下把 ? 转成 %s。"""
    _enable_postgres(monkeypatch)
    conn = storage._connect()
    storage._execute(conn, "SELECT * FROM users WHERE id=?", (1,))
    assert conn._raw.all_calls[0][0] == "SELECT * FROM users WHERE id=%s"
    assert conn._raw.all_calls[0][1] == (1,)


def test_insert_returning_id_on_postgres(monkeypatch):
    """_insert_returning_id 在 Postgres 下拼 RETURNING id 并返回自增 id。"""
    _enable_postgres(monkeypatch)
    conn = storage._connect()
    conn._raw.next_row = {"id": 42}
    new_id = storage._insert_returning_id(
        conn, "INSERT INTO users (provider) VALUES (?)", ("email",)
    )
    assert new_id == 42
    cur = conn._raw.last_cursor
    assert "RETURNING id" in cur.calls[0][0]
    assert cur.calls[0][0].count("%s") == 1
