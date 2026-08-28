"""app/google_oauth.py 的单元测试（不依赖 Streamlit 运行期/不依赖真实 Google）。

覆盖：
- decode_id_token：合法伪 JWT 解析、非法格式抛错；
- upsert_google_user：按 (google, sub) 创建且幂等、按邮箱合并已有账户；
- is_configured：缺配置时返回 False（应用其余功能不受影响）。
"""
import base64
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app.google_oauth as google_oauth  # noqa: E402
import app.storage as storage  # noqa: E402


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "app.db")
    storage.set_db_path(path)
    storage.init_db(path)
    yield
    storage.set_db_path(storage.DEFAULT_DB)


def _fake_id_token(payload: dict) -> str:
    """构造一个格式合法的伪 JWT（不校验签名，仅用于解码测试）。"""
    def b64(d: bytes) -> str:
        return base64.urlsafe_b64encode(d).rstrip(b"=").decode("ascii")
    header = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    body = b64(json.dumps(payload).encode())
    return f"{header}.{body}.signature"


def test_decode_id_token():
    tok = _fake_id_token({"sub": "g-123", "email": "a@b.com", "name": "Test"})
    payload = google_oauth.decode_id_token(tok)
    assert payload["sub"] == "g-123"
    assert payload["email"] == "a@b.com"
    assert payload["name"] == "Test"


def test_decode_id_token_invalid():
    with pytest.raises(ValueError):
        google_oauth.decode_id_token("not-a-jwt")


def test_upsert_creates_and_idempotent(db):
    uid1 = google_oauth.upsert_google_user({"sub": "g-1", "email": "x@y.com", "name": "X"})
    uid2 = google_oauth.upsert_google_user({"sub": "g-1", "email": "x@y.com", "name": "X"})
    assert uid1 == uid2
    u = storage.get_user_by_provider("google", "g-1")
    assert u is not None
    assert u["email"] == "x@y.com"
    assert u["display_name"] == "X"


def test_upsert_merges_by_email(db):
    email_uid = storage.create_email_user("same@mail.com", "pw123", "Mail User")
    # 谷歌登录返回相同邮箱 → 合并到同一账户，不新建 google 行（避免 users.email 唯一索引冲突）
    gid = google_oauth.upsert_google_user(
        {"sub": "g-different", "email": "same@mail.com", "name": "G User"}
    )
    assert gid == email_uid
    assert storage.get_user_by_provider("google", "g-different") is None


def test_is_configured_false_without_secrets(monkeypatch):
    monkeypatch.setattr(google_oauth, "_cfg", lambda key: None)
    assert google_oauth.is_configured() is False
