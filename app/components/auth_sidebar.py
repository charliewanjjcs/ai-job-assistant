"""侧边栏登录态组件（决策 #2：登录按钮 → 弹层）。

在 run_app 的 `with st.sidebar` 上下文内、导航链接之前调用，使登录区显示在
「首页 / 个人资料 / 职位分析」链接上方。未登录显示「登录 / 注册」弹层入口，
登录后显示用户名 + 退出。
"""
from __future__ import annotations

import streamlit as st

import app.auth as auth
from app.components.login_form import render_login_form


def render_auth_sidebar() -> None:
    """渲染登录/退出区（需在 st.sidebar 上下文内调用）。"""
    if auth.is_logged_in():
        # 用代码跨度包裹显示名：避免 markdown 把邮箱自动转成 mailto: 超链接（点击会跳去发邮件）
        st.success(f"👤 已登录：**`{auth.current_display()}`**")
        if st.button("退出登录", key="sb_logout", use_container_width=True):
            auth.logout()
            st.rerun()
    else:
        with st.popover("🔑 登录 / 注册", use_container_width=True):
            render_login_form(prefix="sb")
