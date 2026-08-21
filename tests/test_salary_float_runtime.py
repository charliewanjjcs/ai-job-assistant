"""运行时验证：用户填入数字后 Streamlit 把值存成 float，rerun 时不应再触发 float 告警/崩溃。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from streamlit.testing.v1 import AppTest

import app.storage as storage

_PROFILE_SCRIPT = """
import streamlit as st
import app.auth as auth
import app.storage as storage
from app.views.profile import render
render()
"""


def _login(at, uid, display="测试用户"):
    at.session_state["user_id"] = uid
    at.session_state["user_display"] = display


def test_salary_float_rerun_no_exception():
    uid = storage.get_or_create_user(
        "salary_float_rt", "salary_float_rt@example.com", "salary_float_rt@example.com"
    )
    at = AppTest.from_string(_PROFILE_SCRIPT)
    _login(at, uid)
    at.run()  # 首次：进入页守卫从 DB 载入（空），exp_value=None
    assert not at.exception, f"首次渲染异常: {at.exception}"

    # 模拟「用户在薪资框输入 300000」后 Streamlit 内部把值存为 float，并触发 rerun
    at.number_input(key="exp_value").set_value(300000.0).run()
    assert not at.exception, f"rerun 渲染异常（应为 float 修复后无错）: {at.exception}"
    val = at.session_state["exp_value"]
    assert val == 300000, f"exp_value 应被规范为 int 300000，实际={val!r}"
    assert isinstance(val, int)


def test_salary_no_float_warning():
    """真机验证：用户填入数字后，不应再出现 format=%d 的 float 告警。"""
    uid = storage.get_or_create_user(
        "salary_no_warn", "salary_no_warn@example.com", "salary_no_warn@example.com"
    )
    at = AppTest.from_string(_PROFILE_SCRIPT)
    _login(at, uid)
    at.run()
    assert not at.exception, f"首次渲染异常: {at.exception}"
    at.number_input(key="exp_value").set_value(300000).run()
    assert not at.exception, f"rerun 渲染异常: {at.exception}"
    warn_text = " ".join(str(w.value) for w in at.warning)
    assert "format %d" not in warn_text, f"薪资 float 告警未消除: {warn_text}"
