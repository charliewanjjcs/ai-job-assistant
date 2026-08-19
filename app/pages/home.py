"""首页：产品名 + 简介 + 使用流程 + 背景 + 两个入口按钮。

- 「完善个人资料」：未登录 → 弹登录 dialog；已登录 → 跳转个人资料页。
- 「开始职位分析」：未登录 → 弹登录 dialog；未完善资料 → 弹提示 dialog；已就绪 → 跳转职位分析页。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st

import app.auth as auth
import app.storage as storage
from app.components.login_form import render_login_form
from app.pages import job_analysis as job_analysis_page
from app.pages import profile as profile_page


@st.dialog("登录 / 注册")
def _show_login_dialog() -> None:
    render_login_form(prefix="dlg")


@st.dialog("请先完善个人资料")
def _show_need_profile_dialog() -> None:
    st.markdown(
        "开始职位分析前，需要先完善你的个人资料（简历、技能、期望薪资、语言等），"
        "这样系统才能拿它和职位 JD 做匹配对比。"
    )
    if st.button("完善个人资料", type="primary", use_container_width=True):
        st.switch_page(st.Page(profile_page.render, url_path="profile"))


def _render_hero() -> None:
    st.markdown(
        """
        <style>
        .hero { text-align: center; padding: 3rem 1rem 1.5rem; }
        .hero h1 { font-size: 3rem; margin-bottom: 0.5rem; }
        .hero .sub { color: #888; font-size: 1.1rem; }
        .steps { display: flex; gap: 1rem; justify-content: center; margin: 1.5rem 0 2rem; }
        .step { flex: 1; max-width: 220px; background: rgba(255,255,255,0.7);
                border-radius: 12px; padding: 1rem; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
        .step .n { font-size: 1.6rem; font-weight: 700; color: #4f46e5; }
        .step .t { font-weight: 600; margin: 0.25rem 0; }
        .step .d { color: #777; font-size: 0.9rem; }
        </style>
        <div class="hero">
          <h1>🎯 AI 求职助手</h1>
          <div class="sub">上传简历、建立你的技能库，粘贴 JD 即可一键得到能力 / 薪资 / 语言 / 到岗匹配与面试建议</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    s1, s2, s3 = st.columns(3)
    with s1:
        st.markdown(
            """<div class="step"><div class="n">1</div><div class="t">完善个人资料</div>
            <div class="d">上传简历 PDF 或粘贴文本，用联想式输入建立技能库，填写期望薪资与语言</div></div>""",
            unsafe_allow_html=True,
        )
    with s2:
        st.markdown(
            """<div class="step"><div class="n">2</div><div class="t">粘贴职位 JD</div>
            <div class="d">把招聘网页上的 JD 原文粘贴进来，自动识别必需 / 加分技能与语言要求</div></div>""",
            unsafe_allow_html=True,
        )
    with s3:
        st.markdown(
            """<div class="step"><div class="n">3</div><div class="t">一键分析</div>
            <div class="d">得到能力 / 薪资 / 语言 / 到岗匹配度，外加提升建议、职业前景与面试问题</div></div>""",
            unsafe_allow_html=True,
        )


def render() -> None:
    _render_hero()

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        b1, b2 = st.columns(2)
        if b1.button("完善个人资料", type="primary", use_container_width=True):
            if not auth.is_logged_in():
                _show_login_dialog()
            else:
                st.switch_page(st.Page(profile_page.render, url_path="profile"))
        if b2.button("开始职位分析", type="primary", use_container_width=True):
            if not auth.is_logged_in():
                _show_login_dialog()
            elif not storage.has_profile_data(auth.current_user_id()):
                _show_need_profile_dialog()
            else:
                st.switch_page(st.Page(job_analysis_page.render, url_path="job-analysis"))
