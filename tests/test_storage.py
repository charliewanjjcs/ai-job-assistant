"""app/storage.py 的单元测试（不依赖 Streamlit，用临时 SQLite）。

覆盖：用户创建/幂等、邮箱注册/登录失败、密码哈希、资料存读、技能库增/列/删、
验证码过期/复用。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app.storage as storage


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "app.db")
    storage.set_db_path(path)
    storage.init_db(path)
    yield
    storage.set_db_path(storage.DEFAULT_DB)


def test_get_or_create_user_idempotent(db):
    uid1 = storage.get_or_create_user("wechat", "wx-123")
    uid2 = storage.get_or_create_user("wechat", "wx-123")
    assert uid1 == uid2
    # 不同 provider_user_id 应为不同用户
    uid3 = storage.get_or_create_user("wechat", "wx-456")
    assert uid3 != uid1


def test_email_register_and_authenticate(db):
    uid = storage.create_email_user("alice@example.com", "secret123", "Alice")
    assert uid > 0
    # 重复注册应抛错
    with pytest.raises(ValueError):
        storage.create_email_user("alice@example.com", "secret123")
    # 正确密码登录
    assert storage.authenticate_email("alice@example.com", "secret123") == uid
    # 错误密码登录失败
    assert storage.authenticate_email("alice@example.com", "wrong") is None
    # 不存在的邮箱登录失败
    assert storage.authenticate_email("nobody@example.com", "x") is None


def test_password_hash_not_plaintext(db):
    uid = storage.create_email_user("bob@example.com", "pw")
    u = storage.get_user(uid)
    assert u["password_hash"] != "pw"
    assert "$" in u["password_hash"]


def test_profile_save_and_load(db):
    uid = storage.get_or_create_user("google", "g-1")
    langs = [{"id": "x", "language": "英语", "level": "母语"}]
    storage.save_profile(uid, {
        "resume": "简历内容",
        "ideal_job": "想赚钱",
        "personality": "外向",
        "city": "深圳",
        "exp_period_label": "年薪",
        "exp_currency_label": "¥ 人民币 (CNY)",
        "exp_value": 300000.0,
        "lang_list": langs,
        "availability": "一个月",
        "jd_text": "",
    })
    loaded = storage.load_profile(uid)
    assert loaded["resume"] == "简历内容"
    assert loaded["ideal_job"] == "想赚钱"
    assert loaded["exp_value"] == 300000.0
    assert loaded["lang_list"] == langs  # JSON 往返保持结构
    # 再次保存应覆盖而非新增
    storage.save_profile(uid, {"resume": "新简历"})
    loaded2 = storage.load_profile(uid)
    assert loaded2["resume"] == "新简历"
    assert loaded2["ideal_job"] == "想赚钱"  # 其它字段保留


def test_profile_missing_returns_none(db):
    uid = storage.get_or_create_user("phone", "13800000000")
    assert storage.load_profile(uid) is None


def test_skill_library_add_list_remove(db):
    uid = storage.get_or_create_user("email", "u@e.com", email="u@e.com")
    assert storage.add_skill(uid, "Excel", is_custom=False) is True
    assert storage.add_skill(uid, "excel", is_custom=False) is False  # 大小写不敏感去重
    assert storage.add_skill(uid, "detail-oriented", is_custom=True) is True
    skills = storage.list_skills(uid)
    assert "Excel" in skills and "detail-oriented" in skills
    assert storage.is_custom_skill(uid, "detail-oriented") is True
    assert storage.is_custom_skill(uid, "Excel") is False
    storage.remove_skill(uid, "Excel")
    assert "Excel" not in storage.list_skills(uid)
    # 删除大小写不敏感
    storage.remove_skill(uid, "DETAIL-ORIENTED")
    assert "detail-oriented" not in storage.list_skills(uid)


def test_verification_code_expire_and_reuse(db):
    phone = "13900000000"
    storage.save_verification_code(phone, "123456", ttl_seconds=-1)  # 已过期
    assert storage.verify_code(phone, "123456") is False
    storage.save_verification_code(phone, "654321", ttl_seconds=300)
    assert storage.verify_code(phone, "654321") is True
    # 同一码不可重复使用
    assert storage.verify_code(phone, "654321") is False
    # 错误码失败
    assert storage.verify_code(phone, "000000") is False
