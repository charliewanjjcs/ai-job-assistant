"""本地 SQLite 持久化层（纯存储，不依赖 streamlit）。

负责：用户账户（本地模拟，不接真实 OAuth）、候选人资料、个人技能库、手机验证码。
所有函数均接受可选 db_path；未传时使用模块级默认路径 data/app.db。
测试可通过 storage.set_db_path(...) 切换到临时库。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time

# 项目根（app/ 的上级目录）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, "data", "app.db")

# 模块级可覆盖的数据库路径（测试用）
DB_PATH = DEFAULT_DB


def set_db_path(path: str) -> None:
    """覆盖默认数据库路径（测试时指向临时文件）。"""
    global DB_PATH
    DB_PATH = path


def get_db_path() -> str:
    return DB_PATH


def init_db(db_path: str | None = None) -> None:
    """创建表（若不存在）。"""
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
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
            """
        )
        conn.commit()
    finally:
        conn.close()


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


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_user(user_id: int) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_provider(provider: str, provider_user_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE provider=? AND provider_user_id=?",
            (provider, provider_user_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_email(email: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE email=?", (email.lower(),)
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
        cur = conn.execute(
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
        return int(cur.lastrowid)
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
        row = conn.execute(
            "SELECT * FROM profiles WHERE user_id=?", (user_id,)
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
        row = conn.execute(
            "SELECT 1 FROM profiles WHERE user_id=?", (user_id,)
        ).fetchone()
        if row:
            cols = ", ".join(f"{k}=?" for k in data)
            conn.execute(
                f"UPDATE profiles SET {cols} WHERE user_id=?",
                tuple(data.values()) + (user_id,),
            )
        else:
            cols = ", ".join(data.keys())
            placeholders = ", ".join("?" for _ in data)
            conn.execute(
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
        rows = conn.execute(
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
        exists = conn.execute(
            "SELECT 1 FROM skill_library WHERE user_id=? AND lower(skill)=lower(?)",
            (user_id, skill),
        ).fetchone()
        if exists:
            return False
        conn.execute(
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
        conn.execute(
            "DELETE FROM skill_library WHERE user_id=? AND lower(skill)=lower(?)",
            (user_id, skill),
        )
        conn.commit()
    finally:
        conn.close()


def is_custom_skill(user_id: int, skill: str) -> bool:
    conn = _connect()
    try:
        row = conn.execute(
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
        conn.execute(
            "INSERT INTO verification_codes (phone, code, expires_at) VALUES (?, ?, ?)",
            (phone, code, str(expires_at)),
        )
        conn.commit()
    finally:
        conn.close()


def verify_code(phone: str, code: str) -> bool:
    """校验未过期、未使用的最新一条；通过则标记 used 并返回 True。"""
    conn = _connect()
    try:
        row = conn.execute(
            """SELECT * FROM verification_codes
               WHERE phone=? AND used=0 AND CAST(expires_at AS REAL) > ?
               ORDER BY id DESC LIMIT 1""",
            (phone, str(time.time())),
        ).fetchone()
        if not row or row["code"] != code:
            return False
        conn.execute("UPDATE verification_codes SET used=1 WHERE id=?", (row["id"],))
        conn.commit()
        return True
    finally:
        conn.close()
