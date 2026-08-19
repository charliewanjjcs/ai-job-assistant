"""侧边栏登录态组件（决策 #2：登录按钮 → 弹层）。

每个页面顶部调用 render_auth_sidebar()：未登录显示「登录 / 注册」弹层入口，
登录后显示用户名 + 退出。弹层内含微信/QQ/谷歌（模拟）、手机号、邮箱（真实哈希）等方式。
"""
from __future__ import annotations

import streamlit as st

import app.auth as auth


def render_auth_sidebar() -> None:
    with st.sidebar:
        if auth.is_logged_in():
            st.success(f"👤 已登录：**{auth.current_display()}**")
            if st.button("退出登录", key="auth_logout", use_container_width=True):
                auth.logout()
                st.rerun()
        else:
            with st.popover("🔑 登录 / 注册", use_container_width=True):
                st.markdown("选择登录方式（本机模拟账户，数据存于本地）")

                c1, c2, c3 = st.columns(3)
                if c1.button("微信", key="lp_wechat", use_container_width=True):
                    auth.login_provider("wechat", "simulated", "微信用户")
                    st.rerun()
                if c2.button("QQ", key="lp_qq", use_container_width=True):
                    auth.login_provider("qq", "simulated", "QQ 用户")
                    st.rerun()
                if c3.button("谷歌", key="lp_google", use_container_width=True):
                    auth.login_provider("google", "simulated", "Google 用户")
                    st.rerun()

                st.divider()
                with st.form("phone_form", clear_on_submit=False):
                    st.markdown("**手机号登录**")
                    phone = st.text_input("手机号", key="lp_phone")
                    code = st.text_input("验证码", key="lp_code")
                    sc, lc = st.columns(2)
                    if sc.form_submit_button("发送验证码"):
                        if phone:
                            auth.send_phone_code(phone)
                        else:
                            st.warning("请先输入手机号")
                    if lc.form_submit_button("登录"):
                        if phone and code:
                            uid = auth.login_phone(phone, code)
                            if uid:
                                st.success("登录成功"); st.rerun()
                            else:
                                st.error("验证码错误")
                        else:
                            st.warning("请输入手机号和验证码")

                st.divider()
                with st.form("email_form", clear_on_submit=False):
                    st.markdown("**邮箱账户**")
                    email = st.text_input("邮箱", key="lp_email")
                    pwd = st.text_input("密码", type="password", key="lp_pwd")
                    rg, lg = st.columns(2)
                    if rg.form_submit_button("注册"):
                        if email and pwd:
                            try:
                                auth.register_email(email, pwd)
                                st.success("注册成功"); st.rerun()
                            except ValueError:
                                st.error("该邮箱已注册")
                        else:
                            st.warning("请输入邮箱和密码")
                    if lg.form_submit_button("登录"):
                        if email and pwd:
                            uid = auth.login_email(email, pwd)
                            if uid:
                                st.success("登录成功"); st.rerun()
                            else:
                                st.error("邮箱或密码错误")
                        else:
                            st.warning("请输入邮箱和密码")

        st.divider()
        st.checkbox("演示模式（无需 API Key）", value=True, key="demo")
