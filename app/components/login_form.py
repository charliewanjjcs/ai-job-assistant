"""登录表单组件（微信/QQ/谷歌/手机号/邮箱），供侧边栏 popover 与首页 dialog 复用。

prefix 用于区分不同挂载点的 widget key，避免同一会话内 key 冲突。
"""
from __future__ import annotations

import streamlit as st

import app.auth as auth


def render_login_form(prefix: str = "lf") -> None:
    """渲染登录方式表单。登录成功后内部调用 st.rerun() 关闭弹层并刷新。"""
    st.markdown(
        "选择登录方式（本机模拟账户）。"
        "微信/QQ/谷歌为模拟登录，**资料按当前浏览器隔离**（换设备/清缓存会进入新账户）；"
        "需要跨设备持久账户请用**手机号或邮箱**登录。"
    )

    c1, c2, c3 = st.columns(3)
    if c1.button("微信", key=f"{prefix}_wechat", use_container_width=True):
        # 用每浏览器会话的唯一 id 作身份，避免所有人共用 "simulated" 账户导致资料串号
        auth.login_provider("wechat", auth.session_device_id(), "微信用户")
        st.rerun()
    if c2.button("QQ", key=f"{prefix}_qq", use_container_width=True):
        auth.login_provider("qq", auth.session_device_id(), "QQ 用户")
        st.rerun()
    if c3.button("谷歌", key=f"{prefix}_google", use_container_width=True):
        auth.login_provider("google", auth.session_device_id(), "Google 用户")
        st.rerun()

    st.divider()
    with st.form(f"{prefix}_phone_form", clear_on_submit=False):
        st.markdown("**手机号登录**")
        phone = st.text_input("手机号", key=f"{prefix}_phone")
        code = st.text_input("验证码", key=f"{prefix}_code")
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
                    st.success("登录成功")
                    st.rerun()
                else:
                    st.error("验证码错误")
            else:
                st.warning("请输入手机号和验证码")

    st.divider()
    with st.form(f"{prefix}_email_form", clear_on_submit=False):
        st.markdown("**邮箱账户**")
        email = st.text_input("邮箱", key=f"{prefix}_email")
        pwd = st.text_input("密码", type="password", key=f"{prefix}_pwd")
        rg, lg = st.columns(2)
        if rg.form_submit_button("注册"):
            if email and pwd:
                try:
                    auth.register_email(email, pwd)
                    st.success("注册成功")
                    st.rerun()
                except ValueError:
                    st.error("该邮箱已注册")
            else:
                st.warning("请输入邮箱和密码")
        if lg.form_submit_button("登录"):
            if email and pwd:
                uid = auth.login_email(email, pwd)
                if uid:
                    st.success("登录成功")
                    st.rerun()
                else:
                    st.error("邮箱或密码错误")
            else:
                st.warning("请输入邮箱和密码")
