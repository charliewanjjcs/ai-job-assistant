"""app/main.py 的数据层逻辑测试（不依赖 Streamlit 运行期，仅 monkeypatch session_state）。

覆盖：年薪按「元」存储、到岗「未填写」应映射为 None、JD 原文 on_change 回调正确回填技能/语言。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app.main as m


def _set_session(d):
    # build_profile / build_jd / on_jd_text_change 都只读 st.session_state.get(...)
    m.st.session_state = dict(d)


def test_build_profile_annual_stored_in_yuan():
    _set_session({
        "resume": "",
        "skills": "Python",
        "personality": "细心",
        "ideal_job": None,
        "city": "深圳",
        "exp_period_label": "年薪",
        "exp_currency_label": "¥ 人民币 (CNY)",
        "exp_value": 300000.0,
        "lang_list": [],
        "availability": "一个月",
    })
    p = m.build_profile()
    assert p.expected_salary is not None
    assert p.expected_salary.period.value == "annual"
    # 年薪单位已改为「元」，不应再乘 10000
    assert p.expected_salary.value == 300000.0
    assert p.availability.value == "一个月"


def test_build_profile_availability_unfilled_is_none():
    _set_session({
        "resume": "", "skills": "", "personality": None, "ideal_job": None, "city": None,
        "exp_period_label": "月薪", "exp_currency_label": "¥ 人民币 (CNY)", "exp_value": 0.0,
        "lang_list": [], "availability": "未填写",
    })
    p = m.build_profile()
    # 「未填写」不能拿去构造 Availability 枚举，应为 None
    assert p.availability is None


def test_on_jd_text_change_autofills_skills_and_languages():
    jd = ("任职要求：精通Python，熟悉MySQL、Redis，有Docker、Kubernetes经验者优先；"
          "英语可作为工作语言，要求尽快到岗")
    _set_session({"jd_text": jd})
    m.on_jd_text_change()
    s = m.st.session_state
    assert "Python" in s["jd_req"] and "MySQL" in s["jd_req"]
    assert "Docker" in s["jd_pref"] and "Kubernetes" in s["jd_pref"]
    langs = s["jd_lang_list"]
    assert any(l["language"] == "英语" for l in langs)
    # 每条语言都带稳定 id（供前端增删而不错位）
    assert all("id" in l for l in langs)
    assert s["jd_prefers_immediate"] is True


def test_on_jd_text_change_empty_no_crash():
    _set_session({"jd_text": ""})
    m.on_jd_text_change()  # 空文本应直接返回，不抛异常
    assert m.st.session_state.get("jd_req") is None
