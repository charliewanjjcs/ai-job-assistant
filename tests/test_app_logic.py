"""app/main.py 的数据层逻辑测试（不依赖 Streamlit 运行期，仅 monkeypatch session_state）。

覆盖：年薪按「元」存储、到岗「未填写」应映射为 None、JD 原文 on_change 回调正确回填技能/语言。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app.main as m


def _set_session(monkeypatch, d):
    # build_profile / build_jd / on_jd_text_change 都只读 st.session_state.get(...)
    # 用 monkeypatch.setattr 保证测试结束后自动恢复，避免污染其它测试（尤其 AppTest）
    monkeypatch.setattr(m.st, "session_state", dict(d))


def test_build_profile_annual_stored_in_yuan(monkeypatch):
    _set_session(monkeypatch, {
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


def test_build_profile_availability_unfilled_is_none(monkeypatch):
    _set_session(monkeypatch, {
        "resume": "", "skills": "", "personality": None, "ideal_job": None, "city": None,
        "exp_period_label": "月薪", "exp_currency_label": "¥ 人民币 (CNY)", "exp_value": 0.0,
        "lang_list": [], "availability": "未填写",
    })
    p = m.build_profile()
    # 「未填写」不能拿去构造 Availability 枚举，应为 None
    assert p.availability is None


def test_build_profile_falls_back_to_cache_when_widget_keys_pruned(monkeypatch):
    """回归：个人资料页填的薪资是 widget 键，跨页导航到职位分析页会被 Streamlit 裁剪掉。

    build_profile 必须能从非 widget 缓存（candidate_profile_cache）回退，否则月薪港币会变「未填/年薪」。
    本测试故意只放缓存、不放任何 widget 键，模拟被裁剪后的状态。
    """
    _set_session(monkeypatch, {
        # 注意：故意不设置 exp_value / resume / skills 等 widget 键，仅放缓存
        "candidate_profile_cache": {
            "resume": "", "skills": "Python", "ideal_job": "后端", "personality": "细心",
            "city": "深圳",
            "exp_period_label": "月薪", "exp_currency_label": "HK$ 港币 (HKD)",
            "exp_value": 20000, "lang_list": [], "availability": "未填写",
        },
    })
    p = m.build_profile()
    assert p.expected_salary is not None
    assert p.expected_salary.period.value == "monthly"
    assert p.expected_salary.currency.value == "HKD"
    assert p.expected_salary.value == 20000
    # 其它字段也应能从缓存回退
    assert p.skills == ["Python"]
    assert p.availability is None


def test_job_analysis_keeps_unsaved_salary(monkeypatch):
    """进入职位分析页加载候选人资料时，不得把「已填但未保存」的月薪/港币覆盖成 DB 空值。"""
    import app.views.job_analysis as ja

    # DB 视为未保存（exp_value 为空）
    monkeypatch.setattr(ja.storage, "load_profile", lambda uid: {
        "resume": "", "ideal_job": "", "personality": "", "city": "",
        "exp_period_label": None, "exp_currency_label": None, "exp_value": None,
    })
    monkeypatch.setattr(ja.storage, "list_skills", lambda uid: [])
    # 用户在个人资料页已输入但未保存的「月薪 20000 港币」
    monkeypatch.setattr(ja.st, "session_state", {
        "exp_period_label": "月薪", "exp_currency_label": "HK$ 港币 (HKD)", "exp_value": 20000,
        "_active_page": "job_analysis",
    })
    ja._load_candidate_to_session(1)
    ss = ja.st.session_state
    assert ss["exp_value"] == 20000                 # 未被 DB 空值冲掉
    assert ss["exp_period_label"] == "月薪"
    assert ss["exp_currency_label"] == "HK$ 港币 (HKD)"


def test_job_analysis_loads_salary_from_db_when_session_empty(monkeypatch):
    """全新会话（session_state 无薪资）应从 DB 载入已保存的月薪港币。"""
    import app.views.job_analysis as ja

    monkeypatch.setattr(ja.storage, "load_profile", lambda uid: {
        "resume": "", "ideal_job": "", "personality": "", "city": "",
        "exp_period_label": "月薪", "exp_currency_label": "HK$ 港币 (HKD)", "exp_value": 25000,
    })
    monkeypatch.setattr(ja.storage, "list_skills", lambda uid: [])
    monkeypatch.setattr(ja.st, "session_state", {"_active_page": "job_analysis"})
    ja._load_candidate_to_session(1)
    ss = ja.st.session_state
    assert ss["exp_value"] == 25000
    assert ss["exp_period_label"] == "月薪"


def test_on_jd_text_change_autofills_skills_and_languages(monkeypatch):
    jd = ("任职要求：精通Python，熟悉MySQL、Redis，有Docker、Kubernetes经验者优先；"
          "需具备 attention to detail 与团队合作能力；"
          "英语可作为工作语言，要求尽快到岗")
    _set_session(monkeypatch, {"jd_text": jd})
    m.on_jd_text_change()
    s = m.st.session_state
    assert "Python" in s["jd_req"] and "MySQL" in s["jd_req"]
    # 「加分技能」栏已改为「软技能/特质」：回填 JD 中的软技能，而非技术加分项
    assert "attention to detail" in s["jd_pref"]
    assert "团队合作" in s["jd_pref"]
    # 原「加分技能」里的技术项（Docker/Kubernetes）不再进此栏
    assert "Docker" not in s["jd_pref"]
    langs = s["jd_lang_list"]
    assert any(l["language"] == "英语" for l in langs)
    # 每条语言都带稳定 id（供前端增删而不错位）
    assert all("id" in l for l in langs)
    assert s["jd_prefers_immediate"] is True


def test_on_jd_text_change_empty_no_crash(monkeypatch):
    _set_session(monkeypatch, {"jd_text": ""})
    m.on_jd_text_change()  # 空文本应直接返回，不抛异常
    assert m.st.session_state.get("jd_req") is None
