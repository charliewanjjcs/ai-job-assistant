"""端到端基本功能联调（Phase 6 前半段）。

目标：在「不依赖任何外部 API Key」的前提下，验证整套基本功能能真正跑通：
- 简历 + JD → CoreAnalyzer → Report 九大板块都非空/有效
- 分析结果能持久化保存、再读取、反序列化一致（round-trip）
- 真实 UI 接线：职位分析页「开始分析」点击后确实落库
- 真实 UI 接线：分析结果页能渲染完整报告（八标签页）

无需 DeepSeek Key：分析链路的 LLM 部分用 DemoLLM 兜底（career/interview 返回固定文本）。

注意（AppTest 坑）：必须在首次 at.run() 初始化之后再写 session_state，否则会被运行时清空。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from streamlit.testing.v1 import AppTest

import app.auth as auth
import app.state as m
import app.storage as storage
from app.state import DemoLLM, build_jd, build_profile
from core.analyzer import CoreAnalyzer

_JOB_SCRIPT = """
import streamlit as st
import app.auth as auth
import app.storage as storage
from app.views.job_analysis import render
render()
"""

_RESULTS_SCRIPT = """
import streamlit as st
import app.auth as auth
import app.storage as storage
from app.views.results import render
render()
"""

# 路由脚本：在同一 AppTest 会话里切换「个人资料」与「职位分析」页，
# 共用 session_state（真实模拟用户从资料页填完薪资再点进职位分析页的导航）。
_ROUTER_SCRIPT = """
import streamlit as st
import app.auth as auth
import app.storage as storage
from app.views.profile import render as profile_render
from app.views.job_analysis import render as job_render
page = st.session_state.get("_nav", "profile")
if page == "profile": profile_render()
elif page == "job_analysis": job_render()
"""


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "app.db")
    storage.set_db_path(path)
    storage.init_db(path)
    yield
    storage.set_db_path(storage.DEFAULT_DB)


def _login(at, uid, display="测试用户"):
    # 先初始化一次运行，再写 session_state（否则会被运行时清空）
    at.run()
    at.session_state["user_id"] = uid
    at.session_state["user_display"] = display


def _click_button(at, label):
    for b in at.button:
        if b.label == label:
            b.click().run()
            return
    raise AssertionError(f"未找到按钮: {label}")


SAMPLE_JD = """职位名称：后端开发工程师
公司：测试科技有限公司
工作城市：深圳
薪资范围：25k-40k
任职要求：
- 精通 Python，熟悉 Go、MySQL、Redis
- 具备 attention to detail 与团队合作能力
- 良好的沟通能力
- 英语可作为工作语言
- 能尽快到岗"""


def _set_session(monkeypatch):
    """将候选人 + JD 全部字段合并进同一个 session_state（避免互相覆盖）。

    注意：LanguageLevel 仅接受 基础/熟练/母语，Availability 仅接受 立刻/一周内/一个月/...，
    故此处务必使用合法枚举值（非法值会触发 ValueError，正如集成联调时踩到的坑）。
    """
    d = {
        # 候选人
        "resume": "",
        "skills": "Python, Go, MySQL",
        "personality": "细心",
        "ideal_job": "后端开发",
        "city": "深圳",
        "exp_period_label": "年薪",
        "exp_currency_label": "¥ 人民币 (CNY)",
        "exp_value": 350000.0,
        "lang_list": [{"id": "x", "language": "英语", "level": "熟练"}],
        "availability": "一个月",
        # JD
        "jd_text": SAMPLE_JD,
        "jd_title": "后端开发工程师",
        "jd_company": "测试科技有限公司",
        "jd_city": "深圳",
        "jd_req": "Python, Go, MySQL, Redis",
        "jd_pref": "attention to detail, 团队合作, 沟通能力",
        "jd_lang_list": [{"id": "y", "language": "英语", "level": "熟练"}],
        "jd_prefers_immediate": True,
    }
    monkeypatch.setattr(m.st, "session_state", dict(d))


# ── A. 逻辑全链路：analyze → 九大板块非空 → 持久化 round-trip ──────────────
def test_e2e_logic_pipeline_full_report_and_persist(db, monkeypatch):
    _set_session(monkeypatch)

    profile = build_profile()
    jd = build_jd()
    report = CoreAnalyzer(llm=DemoLLM()).analyze(profile, jd)

    # 九大板块都应有效产出
    assert 0 <= report.skill_match.match_score <= 100
    assert report.skill_match.matched, "应有已匹配技能"
    assert report.salary_analysis is not None
    assert report.salary_analysis.market_low and report.salary_analysis.market_high, "应有市场区间"
    assert report.language_match is not None
    assert report.availability_match is not None
    assert report.improvement_suggestions, "应有提升建议"
    assert any([report.career_prospect.promotion, report.career_prospect.raise_outlook,
                report.career_prospect.jump_outlook]), "岗位前景应非空"
    assert report.daily_work, "日常工作应非空"
    assert report.interview_qa, "面试问答应非空"
    assert report.interview_qa[0].question and report.interview_qa[0].direction, "问答应有内容"

    # 持久化 + 回读一致性
    uid = storage.get_or_create_user("wechat", "wx-e2e")
    new_id = storage.save_analysis_result(uid, report, jd_text=jd.raw_text)
    row = storage.get_analysis_result(uid, new_id)
    assert row is not None
    back = storage.deserialize_report(row["report_json"])
    assert back.role == report.role == "后端开发工程师"
    assert back.company == report.company == "测试科技有限公司"
    assert back.skill_match.match_score == report.skill_match.match_score
    assert back.salary_analysis.verdict == report.salary_analysis.verdict
    assert len(back.interview_qa) == len(report.interview_qa)


# ── B. 真实 UI：职位分析页「开始分析」点击后落库 ───────────────────────────
def test_e2e_job_analysis_click_persists(db):
    uid = storage.get_or_create_user("wechat", "wx-e2e-job")
    at = AppTest.from_string(_JOB_SCRIPT, default_timeout=20)
    _login(at, uid)
    at.run()
    assert not at.exception, f"职位分析页渲染异常: {at.exception}"

    # 仅粘贴 JD 原文，走真实 on_change → parse_jd_text 回填路径
    at.text_area(key="jd_text").set_value(SAMPLE_JD).run()
    assert not at.exception, f"粘贴 JD 后异常: {at.exception}"

    before = len(storage.list_analysis_results(uid))
    _click_button(at, "开始分析")
    after = len(storage.list_analysis_results(uid))

    # 关键断言：点击「开始分析」确实把分析结果写入了 SQLite（哪怕 AppTest 不支持 switch_page）
    assert after == before + 1, f"点击后应有 1 条新记录，before={before} after={after}"
    rows = storage.list_analysis_results(uid)
    assert rows[0]["role"], "保存的记录应有职位名"


# ── C. 真实 UI：分析结果页渲染完整报告（八标签页）─────────────────────────
def test_e2e_results_page_renders_report(db, monkeypatch):
    uid = storage.get_or_create_user("wechat", "wx-e2e-res")
    # 仅在构建报告的瞬间 patch session_state，随后立刻还原——
    # 否则全局 patch 会污染 AppTest 运行时，使 results 脚本读不到注入的 user_id。
    with monkeypatch.context() as mp:
        mp.setattr(m.st, "session_state", dict({
            "resume": "", "skills": "Python, Go, MySQL", "personality": "细心",
            "ideal_job": "后端开发", "city": "深圳",
            "exp_period_label": "年薪", "exp_currency_label": "¥ 人民币 (CNY)",
            "exp_value": 350000.0,
            "lang_list": [{"id": "x", "language": "英语", "level": "熟练"}],
            "availability": "一个月",
            "jd_text": SAMPLE_JD, "jd_title": "后端开发工程师",
            "jd_company": "测试科技有限公司", "jd_city": "深圳",
            "jd_req": "Python, Go, MySQL, Redis",
            "jd_pref": "attention to detail, 团队合作, 沟通能力",
            "jd_lang_list": [{"id": "y", "language": "英语", "level": "熟练"}],
            "jd_prefers_immediate": True,
        }))
        report = CoreAnalyzer(llm=DemoLLM()).analyze(build_profile(), build_jd())
    new_id = storage.save_analysis_result(uid, report, jd_text=SAMPLE_JD)

    at = AppTest.from_string(_RESULTS_SCRIPT, default_timeout=20)
    _login(at, uid)
    at.session_state["_pending_result_id"] = new_id  # 模拟「开始分析」跳转带来标志
    at.run()
    assert not at.exception, f"分析结果页渲染异常: {at.exception}"

    # 八标签页板块标题都应出现
    subs = " ".join(str(s.value) for s in at.subheader)
    for label in ["薪资匹配结论", "能力匹配度", "语言匹配度", "到岗匹配",
                  "提升建议", "岗位前景", "日常工作", "面试高频问题"]:
        assert label in subs, f"结果页缺少板块「{label}」"


# ── D. 端到端回归：个人资料填「月薪港币」后导航到职位分析页，薪资不应丢 ──────
def test_e2e_salary_survives_page_navigation(db):
    """回归：填好月薪港币后，跨页导航到职位分析页会让 widget 键被裁剪；

    build_profile 必须靠非 widget 缓存回退，否则结果显示「你的预期（年薪）未填」。
    """
    uid = storage.get_or_create_user("wechat", "wx-nav-salary")
    at = AppTest.from_string(_ROUTER_SCRIPT, default_timeout=30)
    at.run()
    at.session_state["user_id"] = uid
    at.session_state["user_display"] = "test"
    at.session_state["_nav"] = "profile"
    at.run()
    assert not at.exception, f"profile 渲染异常: {at.exception}"

    at.selectbox(key="exp_period_label").set_value("月薪").run()
    at.selectbox(key="exp_currency_label").set_value("HK$ 港币 (HKD)").run()
    at.number_input(key="exp_value").set_value(20000).run()
    # 保存到 DB（真实用户行为之一）；即便不保存，缓存也应兜底
    for b in at.button:
        if b.label == "保存资料":
            b.click().run()
            break

    # 切换到职位分析页（真实导航，共享 session_state；此时薪资 widget 键会被 Streamlit 裁剪）
    at.session_state["_nav"] = "job_analysis"
    at.run()
    assert not at.exception, f"job 渲染异常: {at.exception}"
    at.text_area(key="jd_text").set_value(
        "职位名称：后端工程师\n公司：某科技公司\n薪资：25k-40k").run()
    for b in at.button:
        if b.label == "开始分析":
            b.click().run()
            break

    rows = storage.list_analysis_results(uid)
    assert rows, "开始分析后应落库一条结果"
    row = storage.get_analysis_result(uid, rows[0]["id"])
    sa = storage.deserialize_report(row["report_json"]).salary_analysis
    assert sa.expected is not None, "月薪港币应被识别，不应是「未填」"
    assert sa.display_period.value == "monthly"
    assert sa.display_currency.value == "HKD"
