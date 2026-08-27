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
from core.models import Report, SalaryAnalysis, SkillMatchResult


def _make_report(role="后端工程师", company="Acme", score=88.0, verdict="符合预期"):
    return Report(
        role=role,
        company=company,
        skill_match=SkillMatchResult(match_score=score, matched=["Python"]),
        salary_analysis=SalaryAnalysis(verdict=verdict, expected=300000.0),
        generated_at="2026-08-19T10:00:00",
    )


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


def test_has_profile_data(db):
    uid = storage.get_or_create_user("wechat", "wx-pd")
    # 空用户：无资料无技能 → False
    assert storage.has_profile_data(uid) is False
    # 仅有性格/城市（无简历、无理想工作）→ 仍 False
    storage.save_profile(uid, {"personality": "外向", "city": "深圳"})
    assert storage.has_profile_data(uid) is False
    # 有简历 → True
    storage.save_profile(uid, {"resume": "Python 3 年"})
    assert storage.has_profile_data(uid) is True
    # 仅理想工作（无简历）→ True
    uid2 = storage.get_or_create_user("wechat", "wx-pd2")
    storage.save_profile(uid2, {"ideal_job": "稳定"})
    assert storage.has_profile_data(uid2) is True
    # 仅技能（无资料）→ True
    uid3 = storage.get_or_create_user("wechat", "wx-pd3")
    storage.add_skill(uid3, "Excel", is_custom=False)
    assert storage.has_profile_data(uid3) is True


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


# ─────────────────────────────────────────────────────────────────────────────
# 分析结果（analysis_results 表）
# ─────────────────────────────────────────────────────────────────────────────
def test_analysis_save_and_get_roundtrip(db):
    uid = storage.get_or_create_user("wechat", "wx-ar")
    rid = storage.save_analysis_result(uid, _make_report(), jd_text="JD 原文内容")
    row = storage.get_analysis_result(uid, rid)
    assert row is not None
    assert row["role"] == "后端工程师"
    assert row["company"] == "Acme"
    assert row["skill_score"] == 88.0
    assert row["salary_verdict"] == "符合预期"
    assert row["jd_text"] == "JD 原文内容"
    # 反序列化还原
    report = storage.deserialize_report(row["report_json"])
    assert isinstance(report, Report)
    assert report.role == "后端工程师"
    assert report.skill_match.match_score == 88.0


def test_analysis_json_unicode(db):
    uid = storage.get_or_create_user("wechat", "wx-ar2")
    rid = storage.save_analysis_result(
        uid, _make_report(verdict="数据不足"), jd_text="需要 3 年 Python 经验"
    )
    row = storage.get_analysis_result(uid, rid)
    # ensure_ascii=False：中文原样入库
    assert "数据不足" in row["report_json"]
    assert "需要 3 年 Python 经验" in row["jd_text"]
    report = storage.deserialize_report(row["report_json"])
    assert report.salary_analysis.verdict == "数据不足"


def test_analysis_list_desc_order(db):
    uid = storage.get_or_create_user("wechat", "wx-ar3")
    id1 = storage.save_analysis_result(uid, _make_report(role="岗位1"))
    id2 = storage.save_analysis_result(uid, _make_report(role="岗位2"))
    id3 = storage.save_analysis_result(uid, _make_report(role="岗位3"))
    rows = storage.list_analysis_results(uid)
    assert [r["id"] for r in rows] == [id3, id2, id1]  # 最新在前


def test_analysis_list_columns_only(db):
    uid = storage.get_or_create_user("wechat", "wx-ar4")
    storage.save_analysis_result(uid, _make_report(), jd_text="x")
    row = storage.list_analysis_results(uid)[0]
    assert "id" in row and "role" in row and "skill_score" in row
    assert "report_json" not in row  # 列表轻量，不含大字段
    assert "jd_text" not in row


def test_analysis_report_excludes_jd_text(db):
    """get_analysis_report 只取详情渲染所需列，不取 jd_text 等大字段（减小跨网传输体积）。"""
    uid = storage.get_or_create_user("wechat", "wx-ar5")
    rid = storage.save_analysis_result(uid, _make_report(), jd_text="应被省略的 JD 原文")
    row = storage.get_analysis_report(uid, rid)
    assert row is not None
    assert row["role"] == "后端工程师"
    assert row["company"] == "Acme"
    assert "report_json" in row
    # 关键：不取 jd_text / skill_score / salary_verdict
    assert "jd_text" not in row
    assert "skill_score" not in row
    assert "salary_verdict" not in row
    # 反序列化仍可用
    report = storage.deserialize_report(row["report_json"])
    assert isinstance(report, Report)
    assert report.role == "后端工程师"


def test_analysis_user_isolation(db):
    a = storage.get_or_create_user("wechat", "wx-a")
    b = storage.get_or_create_user("wechat", "wx-b")
    storage.save_analysis_result(a, _make_report(role="A1"))
    storage.save_analysis_result(a, _make_report(role="A2"))
    bid = storage.save_analysis_result(b, _make_report(role="B1"))
    assert len(storage.list_analysis_results(a)) == 2
    assert len(storage.list_analysis_results(b)) == 1
    # 跨用户不可读
    assert storage.get_analysis_result(a, bid) is None


def test_analysis_delete(db):
    uid = storage.get_or_create_user("wechat", "wx-ar5")
    rid = storage.save_analysis_result(uid, _make_report())
    assert storage.delete_analysis_result(uid, rid) is True
    assert storage.get_analysis_result(uid, rid) is None
    assert storage.list_analysis_results(uid) == []
    # 不存在/已删 → False
    assert storage.delete_analysis_result(uid, rid) is False


def test_analysis_clear(db):
    a = storage.get_or_create_user("wechat", "wx-c1")
    b = storage.get_or_create_user("wechat", "wx-c2")
    storage.save_analysis_result(a, _make_report(role="A1"))
    storage.save_analysis_result(a, _make_report(role="A2"))
    storage.save_analysis_result(b, _make_report(role="B1"))
    storage.clear_analysis_results(a)
    assert storage.list_analysis_results(a) == []
    assert len(storage.list_analysis_results(b)) == 1  # 仅清空 a
