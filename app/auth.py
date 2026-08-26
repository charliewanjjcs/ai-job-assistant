"""登录态编排层（依赖 storage + streamlit.session_state）。

本地模拟账户：微信/QQ/谷歌/手机号走 get_or_create_user 落到本机 user 行（不接真实 OAuth）；
邮箱走真实密码哈希。登录态存于 session_state["user_id"] / ["user_display"]。

部署适配（多用户）：**不再写全局 data/session.json**。原「单文件记录最后登录用户」的机制
在多用户并发下会把 A 用户刷新后错误恢复成 B 用户（串号）。登录态仅存 session_state
（每个浏览器会话独立，Streamlit 按浏览器 session 持久化，刷新页面不丢；
服务重启/应用休眠后需重新登录，这是多用户安全的必要取舍）。
"""
from __future__ import annotations

import os
import random
import uuid

import streamlit as st

import app.storage as storage

# 开发模式：发送验证码时在界面显示明文，便于联调
DEV_MODE = os.getenv("APP_DEV", "0") == "1"
# 固定测试/演示验证码（自动化与本地演示用）
TEST_CODE = "000000"

# 各模拟 provider 的稳定标识（保证重复登录落到同一账户、数据可延续）
_SIM_ID = "simulated"


# ─────────────────────────────────────────────────────────────────────────────
# 当前会话
# ─────────────────────────────────────────────────────────────────────────────
def session_device_id() -> str:
    """为本浏览器会话生成稳定的唯一标识（模拟登录用，确保多用户隔离）。

    Streamlit 的 st.session_state 按浏览器会话隔离；首次调用时生成随机 id 并缓存进
    session_state，同一会话内复用（重登录回到同一账户，资料可延续），不同浏览器/设备
    因 session_state 不同会得到不同的 id（互不串号，修复「共享简历」问题）。

    注意：模拟社交登录无真实 OAuth，故该身份与浏览器绑定——清除浏览器存储或换新设备
    会进入全新账户（数据不跨设备）。需要跨设备持久账户请用手机号/邮箱登录（已按真实
    手机号/邮箱隔离）。
    """
    if "_device_id" not in st.session_state:
        st.session_state["_device_id"] = f"dev-{uuid.uuid4().hex}"
    return st.session_state["_device_id"]


def current_user_id() -> int | None:
    return st.session_state.get("user_id")


def current_display() -> str | None:
    return st.session_state.get("user_display")


def is_logged_in() -> bool:
    return bool(st.session_state.get("user_id"))


def require_login() -> int:
    """守卫：未登录则提示并 st.stop()，返回已登录 user_id。"""
    uid = current_user_id()
    if not uid:
        st.warning("请先登录后再使用本功能。")
        st.stop()
    return uid


def logout() -> None:
    st.session_state.pop("user_id", None)
    st.session_state.pop("user_display", None)


# ─────────────────────────────────────────────────────────────────────────────
# 各 provider 登录（均落本机 user 行）
# ─────────────────────────────────────────────────────────────────────────────
def _set_session(uid: int, display: str) -> None:
    st.session_state["user_id"] = uid
    st.session_state["user_display"] = display


def login_provider(provider: str, provider_user_id: str | None = None,
                   display_name: str | None = None) -> int:
    """微信/QQ/谷歌等模拟登录（不接真实 OAuth）。"""
    pid = provider_user_id or _SIM_ID
    uid = storage.get_or_create_user(provider, pid, display_name=display_name)
    u = storage.get_user(uid)
    name = (u and u.get("display_name")) or display_name or f"{provider}用户"
    _set_session(uid, name)
    return uid


def login_email(email: str, password: str) -> int | None:
    """邮箱登录（真实密码哈希）。成功返回 user_id，失败返回 None。"""
    uid = storage.authenticate_email(email, password)
    if uid is None:
        return None
    u = storage.get_user(uid)
    _set_session(uid, (u and u.get("display_name")) or email)
    return uid


def register_email(email: str, password: str, display_name: str | None = None) -> int:
    """邮箱注册（真实密码哈希）。邮箱已存在则抛 ValueError。"""
    uid = storage.create_email_user(email, password, display_name)
    _set_session(uid, display_name or email)
    return uid


def send_phone_code(phone: str) -> str:
    """生成并保存 6 位验证码；DEV_MODE 时在界面提示明文，始终接受 TEST_CODE。"""
    code = "".join(str(random.randint(0, 9)) for _ in range(6))
    storage.save_verification_code(phone, code, ttl_seconds=300)
    if DEV_MODE:
        st.info(f"开发模式验证码（演示/测试用）：**{code}**")
    return code


def login_phone(phone: str, code: str) -> int | None:
    """手机号+验证码登录（模拟）。TEST_CODE 始终通过，便于自动化。"""
    if code != TEST_CODE and not storage.verify_code(phone, code):
        return None
    uid = storage.get_or_create_user(
        "phone", phone, phone=phone, display_name=f"手机用户{phone[-4:]}"
    )
    u = storage.get_user(uid)
    _set_session(uid, (u and u.get("display_name")) or f"手机用户{phone[-4:]}")
    return uid


# ─────────────────────────────────────────────────────────────────────────────
# 登录态持久化（部署适配：多用户安全）
# 不再使用全局 data/session.json（单文件记录「最后登录用户」会导致多用户串号）。
# 登录态仅存 session_state，Streamlit 按浏览器 session 持久化（刷新不丢、多用户隔离）。
# 保留以下空实现，避免 main.py / 历史调用处 import 报错。
# ─────────────────────────────────────────────────────────────────────────────
def persist_login(uid: int) -> None:
    """（已废弃）不再写全局 session.json。登录态由 _set_session 写入 session_state。"""
    return


def try_restore_login() -> None:
    """（已废弃）不再从全局 session.json 恢复，避免多用户串号。"""
    return
