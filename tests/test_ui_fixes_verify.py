"""针对 7 项 UI 修复的真机验证（AppTest 跑真实 Streamlit 运行时）。

重点证明运行时行为修复：
- #2 到岗时间：保存后「切换页面再回来」仍显示最新值（entry-detection 守卫从 DB 重载）
- #3 预计薪资：初始为空（None，不显示 0.00），填入后保留整数
- #4 「重新载入已保存资料」：不再报 StreamlitAPIException
- #1/#5 元素存在性：性格描述/期望城市加粗 markdown、职位详情/JD 二级标题、无大标题
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from streamlit.testing.v1 import AppTest

import app.storage as storage
from core.parsers import extract_skills

_PROFILE_SCRIPT = """
import streamlit as st
import app.auth as auth
import app.storage as storage
from app.views.profile import render
render()
"""

_JOB_SCRIPT = """
import streamlit as st
import app.auth as auth
import app.storage as storage
from app.views.job_analysis import render
render()
"""


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "app.db")
    storage.set_db_path(path)
    storage.init_db(path)
    yield
    storage.set_db_path(storage.DEFAULT_DB)


def _login(at, uid, display="测试用户"):
    at.session_state["user_id"] = uid
    at.session_state["user_display"] = display


def _click_button(at, label):
    """按 label 点击按钮（生产按钮未设 key，AppTest 的 at.button(key=...) 按 key 查找会 KeyError）。"""
    for b in at.button:
        if b.label == label:
            b.click().run()
            return
    raise AssertionError(f"未找到按钮: {label}")


def test_salary_input_empty_then_integer(db):
    """#3 预计薪资：初始为空（None），填入 300000 后保留整数。"""
    uid = storage.get_or_create_user("wechat", "wx-salary")
    at = AppTest.from_string(_PROFILE_SCRIPT, default_timeout=20)
    _login(at, uid)
    at.run()
    assert not at.exception, f"profile 渲染异常: {at.exception}"

    # 初始应为空（不显示 0.00）
    sal = at.number_input(key="exp_value")
    assert sal.value is None, f"初始薪资应为空，实际={sal.value!r}"

    # 填入整数后仍应为整数 300000（不显示小数）
    at.number_input(key="exp_value").set_value(300000).run()
    assert not at.exception, f"填入薪资后异常: {at.exception}"
    assert at.number_input(key="exp_value").value == 300000, "填入后应为整数 300000"


def test_availability_persists_across_page_switch(db):
    """#2 到岗时间：选值→保存→模拟切页再回来，仍显示已保存值。"""
    uid = storage.get_or_create_user("wechat", "wx-avail")
    at = AppTest.from_string(_PROFILE_SCRIPT, default_timeout=20)
    _login(at, uid)
    at.run()
    assert not at.exception

    # 选「一个月」并保存
    at.selectbox(key="availability").set_value("一个月").run()
    _click_button(at, "保存资料")
    assert not at.exception, f"保存异常: {at.exception}"

    # 模拟「切到别的页再回来」：离开本页（_active_page 不再是 profile），重新 run
    at.session_state["_active_page"] = "home"
    at.run()
    assert not at.exception, f"切页回来异常: {at.exception}"

    # 关键断言：回到本页后从 DB 重载，selectbox 应显示已保存的「一个月」
    assert at.selectbox(key="availability").value == "一个月", \
        f"切页后到岗时间未保留，实际={at.selectbox(key='availability').value!r}"


def test_reload_button_no_error(db):
    """#4 「重新载入已保存资料」不应再报 StreamlitAPIException。"""
    uid = storage.get_or_create_user("wechat", "wx-reload")
    at = AppTest.from_string(_PROFILE_SCRIPT, default_timeout=20)
    _login(at, uid)
    at.run()
    assert not at.exception

    # 先保存一次，确保有可重载的数据
    _click_button(at, "保存资料")
    assert not at.exception

    # 点「重新载入已保存资料」：旧实现会在 widget 实例化后改 session_state 而报错
    _click_button(at, "重新载入已保存资料")
    assert not at.exception, f"重新载入报异常: {at.exception}"


def test_profile_bold_fields_present(db):
    """#1 性格描述 / 期望工作城市 以加粗 markdown 渲染。"""
    uid = storage.get_or_create_user("wechat", "wx-bold")
    at = AppTest.from_string(_PROFILE_SCRIPT, default_timeout=20)
    _login(at, uid)
    at.run()
    assert not at.exception
    md = " ".join(str(m.value) for m in at.markdown)
    assert "**性格描述**" in md, "缺少加粗的「性格描述」"
    assert "**期望工作城市**" in md, "缺少加粗的「期望工作城市」"


def test_job_analysis_header_renamed_no_big_title(db):
    """#5 职位分析页：改用二级标题「职位详情/JD」，且去掉了顶部大标题「职位分析」。"""
    uid = storage.get_or_create_user("wechat", "wx-job")
    at = AppTest.from_string(_JOB_SCRIPT, default_timeout=20)
    _login(at, uid)
    at.run()
    assert not at.exception

    # 二级标题应为「职位详情/JD」
    headers = " ".join(str(h.value) for h in at.header)
    assert "职位详情/JD" in headers, f"缺少二级标题「职位详情/JD」，实际 headers={headers}"

    # 不应再有大标题「职位分析」
    titles = " ".join(str(t.value) for t in at.title)
    assert "职位分析" not in titles, f"不应再有大标题「职位分析」，实际 titles={titles}"

    # 提示句应位于其下方（caption 中）
    captions = " ".join(str(c.value) for c in at.caption)
    assert "已自动载入你的个人资料" in captions, "缺少提示句"


def test_microsoft_applications_recognized(db):
    """#6 JD 技能应能识别 Microsoft Applications。"""
    text = "Proficient in Microsoft Applications including Word, Excel and PowerPoint."
    skills = extract_skills(text)
    assert "Microsoft Applications" in skills, f"未识别 Microsoft Applications，实际={skills}"


def test_salary_float_from_db_coerced_to_int(db):
    """#3 防止 NumberInput float 告警：从 DB 读出的 float 薪资应被规范为 int。"""
    uid = storage.get_or_create_user("wechat", "wx-float")
    storage.save_profile(uid, {"exp_value": 300000.0})  # DB 存 float
    at = AppTest.from_string(_PROFILE_SCRIPT, default_timeout=20)
    _login(at, uid)
    at.run()
    assert not at.exception, f"profile 渲染异常: {at.exception}"
    assert at.number_input(key="exp_value").value == 300000, \
        f"从 DB 读出的薪资应规范为 int 300000，实际={at.number_input(key='exp_value').value!r}"
