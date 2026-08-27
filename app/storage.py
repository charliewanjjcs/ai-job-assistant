"""可切换持久化层（纯存储，不依赖 streamlit）。

存储后端选择（按优先级）：
  1. 若环境变量 DATABASE_URL 以 "postgresql" 开头且 psycopg2 可用 → 走 Postgres（云端，重部署不丢）。
  2. 否则退回本地 SQLite（data/app.db，或测试用临时库 / 部署用 APP_DB_PATH）。

切换对业务代码完全透明：所有函数签名与返回结构不变，仅底层连接/方言不同。
SQLite 路径保持与历史完全一致（DDL 不改），确保既有测试零回归。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time

# 项目根（app/ 的上级目录）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
DEFAULT_DB = os.path.join(ROOT, "data", "app.db")

# 模块级可覆盖的 SQLite 数据库路径（测试用 set_db_path 覆盖；部署时用环境变量 APP_DB_PATH 覆盖，
# 指向持久卷或外部存储，避免云平台重启/重新部署丢数据）
DB_PATH = os.getenv("APP_DB_PATH", DEFAULT_DB)

# 云端 Postgres 连接串（Streamlit Cloud 由 Secrets 注入；本地不设则退回 SQLite）
DATABASE_URL = os.getenv("DATABASE_URL")

# psycopg2 仅在需要 Postgres 时加载；SQLite 环境不要求安装
try:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool

    _HAS_PG = True
except Exception:  # pragma: no cover - 取决于运行环境是否安装 psycopg2
    _HAS_PG = False

from core.models import Report  # noqa: E402


def is_postgres() -> bool:
    """当前是否使用 Postgres 后端。"""
    return bool(_HAS_PG and DATABASE_URL and DATABASE_URL.startswith("postgresql"))


def set_db_path(path: str) -> None:
    """覆盖默认 SQLite 数据库路径（测试时指向临时文件）。对 Postgres 后端无影响。"""
    global DB_PATH
    DB_PATH = path


def get_db_path() -> str:
    return DB_PATH


# ─────────────────────────────────────────────────────────────────────────────
# DDL（两套方言；SQLite 保持历史原样以零回归，Postgres 用 SERIAL + CURRENT_TIMESTAMP）
# ─────────────────────────────────────────────────────────────────────────────
_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    provider          TEXT NOT NULL,
    provider_user_id  TEXT NOT NULL,
    email             TEXT,
    phone             TEXT,
    password_hash     TEXT,
    display_name      TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_provider
    ON users(provider, provider_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email
    ON users(email) WHERE email IS NOT NULL;

CREATE TABLE IF NOT EXISTS profiles (
    user_id            INTEGER PRIMARY KEY,
    resume             TEXT,
    ideal_job          TEXT,
    personality        TEXT,
    city               TEXT,
    exp_period_label   TEXT,
    exp_currency_label TEXT,
    exp_value          REAL,
    lang_list          TEXT,
    availability       TEXT,
    jd_text            TEXT,
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS skill_library (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    skill      TEXT NOT NULL,
    is_custom  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_user
    ON skill_library(user_id, skill);

CREATE TABLE IF NOT EXISTS verification_codes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    phone      TEXT NOT NULL,
    code       TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_vc_phone
    ON verification_codes(phone, used);

CREATE TABLE IF NOT EXISTS analysis_results (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    role           TEXT,
    company        TEXT,
    generated_at   TEXT,
    skill_score    REAL,
    salary_verdict TEXT,
    jd_text        TEXT,
    report_json    TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_analysis_user
    ON analysis_results(user_id, id);
"""

_PG_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id                SERIAL PRIMARY KEY,
    provider          TEXT NOT NULL,
    provider_user_id  TEXT NOT NULL,
    email             TEXT,
    phone             TEXT,
    password_hash     TEXT,
    display_name      TEXT,
    created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_provider
    ON users(provider, provider_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email
    ON users(email) WHERE email IS NOT NULL;

CREATE TABLE IF NOT EXISTS profiles (
    user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    resume             TEXT,
    ideal_job          TEXT,
    personality        TEXT,
    city               TEXT,
    exp_period_label   TEXT,
    exp_currency_label TEXT,
    exp_value          REAL,
    lang_list          TEXT,
    availability       TEXT,
    jd_text            TEXT,
    updated_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS skill_library (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill      TEXT NOT NULL,
    is_custom  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_user
    ON skill_library(user_id, skill);

CREATE TABLE IF NOT EXISTS verification_codes (
    id         SERIAL PRIMARY KEY,
    phone      TEXT NOT NULL,
    code       TEXT NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_vc_phone
    ON verification_codes(phone, used);

CREATE TABLE IF NOT EXISTS analysis_results (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role           TEXT,
    company        TEXT,
    generated_at   TEXT,
    skill_score    REAL,
    salary_verdict TEXT,
    jd_text        TEXT,
    report_json    TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_analysis_user
    ON analysis_results(user_id, id);
"""


def _split_ddl(ddl: str) -> list[str]:
    """把多语句 DDL 拆成单条（按分号），去掉空语句。"""
    return [s.strip() for s in ddl.split(";") if s.strip()]


# 记录「已完成建表」的后端定位，避免每次 Streamlit rerun 都重复执行 DDL。
# Postgres 下 11 条建表/建索引语句 = 11 次到 Neon 的网络往返（约 2 秒），
# 而 run_app 每次 rerun 都调 init_db，会造成全局交互卡顿；这里同进程内只跑一次。
_INIT_DONE_KEY: tuple | None = None


def init_db(db_path: str | None = None) -> None:
    """创建表（若不存在）。幂等；同进程内对同一后端只执行一次 DDL。"""
    global _INIT_DONE_KEY
    if is_postgres():
        key = ("pg", DATABASE_URL)
        if _INIT_DONE_KEY == key:
            return
        conn = _connect()
        try:
            for stmt in _split_ddl(_PG_DDL):
                conn.execute(stmt)
            conn.commit()
        finally:
            conn.close()
        _INIT_DONE_KEY = key
        return

    path = db_path or DB_PATH
    key = ("sqlite", path)
    if _INIT_DONE_KEY == key:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SQLITE_DDL)
        conn.commit()
    finally:
        conn.close()
    _INIT_DONE_KEY = key


# ─────────────────────────────────────────────────────────────────────────────
# 连接与执行辅助
# ─────────────────────────────────────────────────────────────────────────────
class _PgConn:
    """psycopg2 连接的轻量包装，暴露与 sqlite3 一致的接口
    （.execute() / .executemany() / .commit() / .rollback() / .close()），
    使业务代码无需关心后端差异。

    psycopg2 的连接对象本身**没有** .execute() 方法（必须 conn.cursor().execute()），
    而 sqlite3 连接自带 .execute()。这里统一成「连接即执行」的接口，
    execute 内部新建 cursor 并返回它，调用方继续 .fetchone() / .fetchall() / .rowcount 即可。
    """

    def __init__(self, raw, returner=None):
        self._raw = raw
        # 由连接池提供时，close() 应把连接放回池而非真正关闭（否则连接泄漏）
        self._returner = returner

    def execute(self, sql: str, params=None):
        cur = self._raw.cursor()
        cur.execute(sql, params)
        return cur

    def executemany(self, sql: str, seq_of_params=None):
        cur = self._raw.cursor()
        cur.executemany(sql, seq_of_params)
        return cur

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        if self._returner:
            self._returner(self._raw)
        else:
            self._raw.close()


# ── Postgres 连接池（避免每次交互都新建 TLS 连接导致页面卡顿）──
_PG_POOL = None


def _get_pool():
    """惰性创建进程级连接池（线程安全）。同进程内复用，避免反复握手。"""
    global _PG_POOL
    if _PG_POOL is None:
        _PG_POOL = psycopg2.pool.SimpleConnectionPool(
            1, 5, DATABASE_URL, connect_timeout=10,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    return _PG_POOL


def _safe_putconn(raw):
    """把连接放回池；池异常时退化为直接关闭，避免连接泄漏。"""
    try:
        _get_pool().putconn(raw)
    except Exception:
        try:
            raw.close()
        except Exception:
            pass


def _acquire_pg():
    """从池取一个健康连接；若取到的连接已断开，回收后重试一次。"""
    pool = _get_pool()
    raw = pool.getconn()
    try:
        cur = raw.cursor()
        cur.execute("SELECT 1")
        return raw
    except psycopg2.Error:
        try:
            pool.putconn(raw, close=True)
        except Exception:
            pass
        return pool.getconn()


def _connect():
    """返回数据库连接的抽象句柄（SQLite / Postgres 自动适配）。"""
    if is_postgres():
        # 从连接池取已建好的连接（避免每次交互都新建 TLS 连接 → 页面卡顿）
        raw = _acquire_pg()
        # psycopg2 连接无 .execute()，包装为与 sqlite3 一致的接口；
        # close() 通过 returner 把连接放回池而非真正关闭
        return _PgConn(raw, _safe_putconn)

    # SQLite：确保目录可写（避免 "readonly database"）；WAL + busy_timeout 降低写锁冲突
    _db_dir = os.path.dirname(DB_PATH)
    try:
        os.makedirs(_db_dir, exist_ok=True)
    except OSError:
        pass
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.DatabaseError:
        pass
    return conn


def _execute(conn, sql: str, params: tuple = ()):
    """方言无关执行：Postgres 把 ? 转 %s。返回 cursor（行可 dict(row)）。"""
    if is_postgres():
        sql = sql.replace("?", "%s")
    return conn.execute(sql, params)


def _insert_returning_id(conn, sql: str, params: tuple) -> int:
    """插入并返回自增 id：Postgres 用 RETURNING id，SQLite 用 lastrowid。"""
    if is_postgres():
        cur = conn.execute(sql.replace("?", "%s") + " RETURNING id", params)
        return int(cur.fetchone()["id"])
    cur = conn.execute(sql, params)
    return int(cur.lastrowid)


# ─────────────────────────────────────────────────────────────────────────────
# 用户
# ─────────────────────────────────────────────────────────────────────────────
def _hash_password(password: str) -> str:
    """pbkdf2_hmac sha256，salt 16 字节。返回 'salt_hex$hash_hex'。"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"{salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
        return dk.hex() == hash_hex
    except Exception:
        return False


def get_user(user_id: int) -> dict | None:
    conn = _connect()
    try:
        row = _execute(conn, "SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_provider(provider: str, provider_user_id: str) -> dict | None:
    conn = _connect()
    try:
        row = _execute(
            conn,
            "SELECT * FROM users WHERE provider=? AND provider_user_id=?",
            (provider, provider_user_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_email(email: str) -> dict | None:
    conn = _connect()
    try:
        row = _execute(
            conn, "SELECT * FROM users WHERE email=?", (email.lower(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_or_create_user(
    provider: str,
    provider_user_id: str,
    email: str | None = None,
    phone: str | None = None,
    password_hash: str | None = None,
    display_name: str | None = None,
) -> int:
    """按 (provider, provider_user_id) 查找，存在则返回其 id；否则插入并返回新 id。"""
    existing = get_user_by_provider(provider, provider_user_id)
    if existing:
        return existing["id"]
    conn = _connect()
    try:
        new_id = _insert_returning_id(
            conn,
            """INSERT INTO users
               (provider, provider_user_id, email, phone, password_hash, display_name)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                provider,
                provider_user_id,
                email.lower() if email else None,
                phone,
                password_hash,
                display_name,
            ),
        )
        conn.commit()
        return new_id
    finally:
        conn.close()


def create_email_user(email: str, password: str, display_name: str | None = None) -> int:
    """注册邮箱账户（真实密码哈希）。邮箱已存在则抛 ValueError。"""
    if get_user_by_email(email):
        raise ValueError("该邮箱已注册")
    return get_or_create_user(
        provider="email",
        provider_user_id=email.lower(),
        email=email,
        password_hash=_hash_password(password),
        display_name=display_name or email,
    )


def authenticate_email(email: str, password: str) -> int | None:
    """邮箱登录，成功返回 user_id，失败返回 None。"""
    u = get_user_by_email(email)
    if not u or not u.get("password_hash"):
        return None
    if _verify_password(password, u["password_hash"]):
        return u["id"]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 资料（不含技能；技能由 skill_library 权威持有）
# ─────────────────────────────────────────────────────────────────────────────
_PROFILE_FIELDS = (
    "resume", "ideal_job", "personality", "city",
    "exp_period_label", "exp_currency_label", "exp_value",
    "lang_list", "availability", "jd_text",
)


def load_profile(user_id: int) -> dict | None:
    conn = _connect()
    try:
        row = _execute(
            conn, "SELECT * FROM profiles WHERE user_id=?", (user_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        # lang_list 是 JSON 文本，解析为列表
        if d.get("lang_list"):
            try:
                d["lang_list"] = json.loads(d["lang_list"])
            except (json.JSONDecodeError, TypeError):
                d["lang_list"] = []
        else:
            d["lang_list"] = []
        return d
    finally:
        conn.close()


def has_profile_data(user_id: int) -> bool:
    """判断用户是否已完善个人资料（保存过简历/理想工作，或已添加技能）。"""
    p = load_profile(user_id)
    if p and (p.get("resume") or p.get("ideal_job")):
        return True
    return bool(list_skills(user_id))


def save_profile(user_id: int, fields: dict) -> None:
    """upsert 候选人资料（不含 skills）。

    fields 只更新其中**实际传入**的键（与 _PROFILE_FIELDS 求交集），
    未传的字段保持不变（支持局部更新，不会把未传字段置空）。
    """
    conn = _connect()
    try:
        data = {k: fields[k] for k in _PROFILE_FIELDS if k in fields}
        if not data:
            return
        if data.get("lang_list") is not None:
            data["lang_list"] = json.dumps(data["lang_list"], ensure_ascii=False)
        row = _execute(
            conn, "SELECT 1 FROM profiles WHERE user_id=?", (user_id,)
        ).fetchone()
        if row:
            cols = ", ".join(f"{k}=?" for k in data)
            _execute(
                conn,
                f"UPDATE profiles SET {cols} WHERE user_id=?",
                tuple(data.values()) + (user_id,),
            )
        else:
            cols = ", ".join(data.keys())
            placeholders = ", ".join("?" for _ in data)
            _execute(
                conn,
                f"INSERT INTO profiles (user_id, {cols}) VALUES (?, {placeholders})",
                (user_id,) + tuple(data.values()),
            )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 技能库（权威来源；词库内 / 词库外自定义都存这里）
# ─────────────────────────────────────────────────────────────────────────────
def list_skills(user_id: int) -> list[str]:
    """返回该用户全部技能（按插入顺序保序）。"""
    conn = _connect()
    try:
        rows = _execute(
            conn,
            "SELECT skill FROM skill_library WHERE user_id=? ORDER BY id",
            (user_id,),
        ).fetchall()
        return [r["skill"] for r in rows]
    finally:
        conn.close()


def add_skill(user_id: int, skill: str, is_custom: bool = True) -> bool:
    """添加技能（按大小写不敏感去重，避免 Excel/excel 重复）。返回是否新增。"""
    skill = (skill or "").strip()
    if not skill:
        return False
    conn = _connect()
    try:
        exists = _execute(
            conn,
            "SELECT 1 FROM skill_library WHERE user_id=? AND lower(skill)=lower(?)",
            (user_id, skill),
        ).fetchone()
        if exists:
            return False
        _execute(
            conn,
            "INSERT INTO skill_library (user_id, skill, is_custom) VALUES (?, ?, ?)",
            (user_id, skill, 1 if is_custom else 0),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def remove_skill(user_id: int, skill: str) -> None:
    conn = _connect()
    try:
        _execute(
            conn,
            "DELETE FROM skill_library WHERE user_id=? AND lower(skill)=lower(?)",
            (user_id, skill),
        )
        conn.commit()
    finally:
        conn.close()


def is_custom_skill(user_id: int, skill: str) -> bool:
    conn = _connect()
    try:
        row = _execute(
            conn,
            "SELECT is_custom FROM skill_library WHERE user_id=? AND lower(skill)=lower(?)",
            (user_id, skill),
        ).fetchone()
        return bool(row and row["is_custom"])
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 手机验证码（模拟；dev 可显示/固定测试码）
# ─────────────────────────────────────────────────────────────────────────────
def save_verification_code(phone: str, code: str, ttl_seconds: int = 300) -> None:
    conn = _connect()
    try:
        expires_at = time.time() + ttl_seconds
        # Postgres 列是 DOUBLE PRECISION，存 float；SQLite 列是 TEXT，存字符串
        expires_val = float(expires_at) if is_postgres() else str(expires_at)
        _execute(
            conn,
            "INSERT INTO verification_codes (phone, code, expires_at) VALUES (?, ?, ?)",
            (phone, code, expires_val),
        )
        conn.commit()
    finally:
        conn.close()


def verify_code(phone: str, code: str) -> bool:
    """校验未过期、未使用的最新一条；通过则标记 used 并返回 True。"""
    conn = _connect()
    try:
        if is_postgres():
            row = _execute(
                conn,
                """SELECT * FROM verification_codes
                   WHERE phone=? AND used=0 AND expires_at > ?
                   ORDER BY id DESC LIMIT 1""",
                (phone, float(time.time())),
            ).fetchone()
        else:
            row = _execute(
                conn,
                """SELECT * FROM verification_codes
                   WHERE phone=? AND used=0 AND CAST(expires_at AS REAL) > ?
                   ORDER BY id DESC LIMIT 1""",
                (phone, str(time.time())),
            ).fetchone()
        if not row or row["code"] != code:
            return False
        _execute(conn, "UPDATE verification_codes SET used=1 WHERE id=?", (row["id"],))
        conn.commit()
        return True
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 分析结果（职位分析持久化；report_json 存 report.model_dump(mode="json")）
# ─────────────────────────────────────────────────────────────────────────────
def save_analysis_result(user_id: int, report: Report, jd_text: str = "") -> int:
    """持久化一条分析结果，返回新记录 id。

    report_json = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)；
    冗余 role/company/generated_at/skill_score/salary_verdict 供列表展示。
    """
    report_json = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
    conn = _connect()
    try:
        new_id = _insert_returning_id(
            conn,
            """INSERT INTO analysis_results
               (user_id, role, company, generated_at, skill_score, salary_verdict, jd_text, report_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                report.role,
                report.company,
                report.generated_at,
                report.skill_match.match_score,
                report.salary_analysis.verdict,
                jd_text or "",
                report_json,
            ),
        )
        conn.commit()
        return new_id
    finally:
        conn.close()


def list_analysis_results(user_id: int) -> list[dict]:
    """该用户全部分析结果（按 id 倒序，最新在前）。仅返回列表展示所需列。"""
    conn = _connect()
    try:
        rows = _execute(
            conn,
            """SELECT id, role, company, generated_at, skill_score, salary_verdict, created_at
               FROM analysis_results WHERE user_id=? ORDER BY id DESC""",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_analysis_result(user_id: int, analysis_id: int) -> dict | None:
    """返回单条完整记录（含 report_json、jd_text）；无权限或不存在返回 None。"""
    conn = _connect()
    try:
        row = _execute(
            conn,
            "SELECT * FROM analysis_results WHERE id=? AND user_id=?",
            (analysis_id, user_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_analysis_result(user_id: int, analysis_id: int) -> bool:
    """删除单条（仅限本用户），返回是否真的删除了一行。"""
    conn = _connect()
    try:
        cur = _execute(
            conn,
            "DELETE FROM analysis_results WHERE id=? AND user_id=?",
            (analysis_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def clear_analysis_results(user_id: int) -> None:
    """清空该用户全部分析结果。"""
    conn = _connect()
    try:
        _execute(
            conn, "DELETE FROM analysis_results WHERE user_id=?", (user_id,)
        )
        conn.commit()
    finally:
        conn.close()


def deserialize_report(report_json: str) -> Report:
    """把 report_json 反序列化为 Report（详情渲染用）。"""
    return Report.model_validate(json.loads(report_json))
