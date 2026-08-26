"""app/views/results.py 的 AppTest 冒烟（不测跳转，测默认选中 + 详情渲染 + JD 回显）。"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from streamlit.testing.v1 import AppTest

import app.storage as storage
from app.views.results import HISTORY_COLUMN_WIDTHS
from core.models import Report, SalaryAnalysis, SkillMatchResult, Currency, PayPeriod

_SCRIPT = """
import streamlit as st
import app.auth as auth
import app.storage as storage
from app.components.result_tabs import render_report
from app.views.results import render
render()
"""


def _make_report(role="后端", company="A", score=88.0, verdict="符合预期"):
    return Report(
        role=role,
        company=company,
        skill_match=SkillMatchResult(
            match_score=score,
            matched=["Python"],
            missing_required=["Go"],
            missing_preferred=["沟通能力"],
        ),
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


def test_results_page_smoke(db):
    uid = storage.get_or_create_user("wechat", "wx-t")
    storage.save_analysis_result(uid, _make_report(role="后端", company="A"), jd_text="JD原文A")
    rid2 = storage.save_analysis_result(uid, _make_report(role="前端", company="B"), jd_text="JD原文B")

    at = AppTest.from_string(_SCRIPT, default_timeout=20)
    at.session_state["user_id"] = uid
    at.session_state["user_display"] = "测试用户"
    at.session_state["_pending_result_id"] = rid2  # 模拟“刚分析完跳转”，应默认选中 rid2
    at.run()

    assert not at.exception
    # 右侧详情应渲染出被默认选中的 rid2 的 role（前端）
    all_md = " ".join(str(m.value) for m in at.markdown)
    assert "前端" in all_md
    # 能力匹配栏标签已对齐「职位详情」页术语：技能匹配 / 缺失-必需技能 / 缺失-软技能/特质
    assert "技能匹配" in all_md
    assert "缺失-必需技能" in all_md
    assert "缺失-软技能/特质" in all_md


def test_results_page_salary_hkd_display(db):
    """预期填港币 -> 薪资三栏应按港币展示（HK$ 20,000），而非人民币/年化。"""
    uid = storage.get_or_create_user("wechat", "wx-hkd")
    report = Report(
        role="后端", company="A",
        skill_match=SkillMatchResult(match_score=80.0, matched=["Python"]),
        salary_analysis=SalaryAnalysis(
            verdict="符合预期",
            expected=20000 * 12 * 0.92,  # 港币 20000/月 -> 年化 CNY
            display_period=PayPeriod.MONTHLY,
            display_currency=Currency.HKD,
        ),
        generated_at="2026-08-25T10:00:00",
    )
    storage.save_analysis_result(uid, report, jd_text="JD原文")
    at = AppTest.from_string(_SCRIPT, default_timeout=20)
    at.session_state["user_id"] = uid
    at.session_state["user_display"] = "测试用户"
    at.run()
    assert not at.exception
    all_md = " ".join(str(m.value) for m in at.markdown)
    assert "HK$" in all_md
    assert "20,000" in all_md
    # 历史表「分析时间」应在最右列（列序由 HISTORY_COLUMN_WIDTHS 决定）
    cols = list(HISTORY_COLUMN_WIDTHS.keys())
    assert cols[-1] == "分析时间", f"分析时间应在最右列，实际列序={cols}"
    # 「当时粘贴的 JD 原文」回显已移除（不再展示 JD 原文）
    all_code = " ".join(str(c.value) for c in at.code)
    assert "JD原文B" not in all_code


def test_results_page_empty(db):
    uid = storage.get_or_create_user("wechat", "wx-empty")
    at = AppTest.from_string(_SCRIPT, default_timeout=20)
    at.session_state["user_id"] = uid
    at.session_state["user_display"] = "测试用户"
    at.run()
    assert not at.exception
    all_info = " ".join(str(i.value) for i in at.info)
    assert "还没有分析结果" in all_info


def test_history_table_fixed_widths():
    """历史表列宽（像素，由 column_config.width 应用）：职位/公司 150、薪资结论 95、技能匹配/分析时间 75。"""
    assert HISTORY_COLUMN_WIDTHS == {
        "职位": 150,
        "公司": 150,
        "技能匹配": 75,
        "薪资结论": 95,
        "分析时间": 75,
    }
    # 列顺序保持一致
    assert list(HISTORY_COLUMN_WIDTHS.keys()) == [
        "职位", "公司", "技能匹配", "薪资结论", "分析时间"
    ]


def test_history_table_renders_with_fixed_columns(db):
    """冒烟：带数据时历史表以原生 dataframe（可点击选中）渲染，列序与预期一致。"""
    uid = storage.get_or_create_user("wechat", "wx-cols")
    storage.save_analysis_result(uid, _make_report(role="后端", company="A"), jd_text="JD")
    at = AppTest.from_string(_SCRIPT, default_timeout=20)
    at.session_state["user_id"] = uid
    at.session_state["user_display"] = "测试用户"
    at.run()
    assert not at.exception
    df = at.dataframe[0]
    assert list(df.value.columns) == [
        "职位", "公司", "技能匹配", "薪资结论", "分析时间"
    ]
    # 列宽（像素）配置存在且为 5 列
    assert len(HISTORY_COLUMN_WIDTHS) == 5


def test_detail_title_role_and_company_on_separate_lines(db):
    """详情大标题：岗位名称与公司在两行，不得用「@」连接。"""
    uid = storage.get_or_create_user("wechat", "wx-title")
    rid = storage.save_analysis_result(
        uid, _make_report(role="后端开发工程师", company="测试科技有限公司"), jd_text="JD")
    at = AppTest.from_string(_SCRIPT, default_timeout=20)
    at.session_state["user_id"] = uid
    at.session_state["user_display"] = "测试用户"
    at.session_state["_pending_result_id"] = rid
    at.run()
    assert not at.exception
    md = " ".join(str(x.value) for x in at.markdown)
    assert "#### 后端开发工程师" in md
    assert "##### 测试科技有限公司" in md
    assert "@" not in md


def test_render_personality_tab():
    """新增「性格匹配」栏目应渲染匹配分 + 维度理由。"""
    script = """
import streamlit as st
from app.components.result_tabs import render_personality
from core.models import Report, PersonalityMatchResult, PersonalityDimension
r = Report(personality_match=PersonalityMatchResult(
    score=85, summary="外向且求稳，匹配良好",
    dimensions=[PersonalityDimension(name="沟通协作", fit="高", note="外向匹配频繁沟通"),
                PersonalityDimension(name="稳定性", fit="高", note="求稳匹配")]))
render_personality(r)
"""
    at = AppTest.from_string(script, default_timeout=20)
    at.run()
    assert not at.exception
    md = " ".join(str(m.value) for m in at.markdown)
    # subheader 不进 at.markdown（与其它 tab 一致），故断言 write 出的正文与维度
    assert "外向且求稳，匹配良好" in md
    assert "沟通协作" in md
    assert "稳定性" in md
    assert "外向匹配频繁沟通" in md
