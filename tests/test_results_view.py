"""app/views/results.py 的 AppTest 冒烟（不测跳转，测默认选中 + 详情渲染 + JD 回显）。"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from streamlit.testing.v1 import AppTest

import app.storage as storage
from core.models import Report, SalaryAnalysis, SkillMatchResult

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
    # JD 原文回显
    all_code = " ".join(str(c.value) for c in at.code)
    assert "JD原文B" in all_code


def test_results_page_empty(db):
    uid = storage.get_or_create_user("wechat", "wx-empty")
    at = AppTest.from_string(_SCRIPT, default_timeout=20)
    at.session_state["user_id"] = uid
    at.session_state["user_display"] = "测试用户"
    at.run()
    assert not at.exception
    all_info = " ".join(str(i.value) for i in at.info)
    assert "还没有分析结果" in all_info
