"""登录态编排层（依赖 storage + streamlit.session_state）。

本地模拟账户：微信/QQ/谷歌/手机号走 get_or_create_user 落到本机 user 行（不接真实 OAuth）；
邮箱走真实密码哈希。登录态存于 session_state["user_id"] / ["user_display"]，
并通过 data/session.json 持久化（决策 #3：保持登录，重启自动恢复）。
"""
from __future__ import annotations

import json
import os
import random

import streamlit as st

import app.storage as storage

# 本机会话持久化文件
SESSION_FILE = os.path.join(storage.ROOT, "data", "session.json")
# 开发模式：发送验证码时在界面显示明文，便于联调
DEV_MODE = os.getenv("APP_DEV", "0") == "1"
# 固定测试/演示验证码（自动化与本地演示用）
TEST_CODE = "000000"

# 各模拟 provider 的稳定标识（保证重复登录落到同一账户、数据可延续）
_SIM_ID = "simulated"


# ─────────────────────────────────────────────────────────────────────────────
# 当前会话
# ─────────────────────────────────────────────────────────────────────────────
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
    # 标记本次会话已主动退出：即使 session.json 因文件锁删除失败，也不在本会话自动恢复
    st.session_state["_logged_out"] = True
    _clear_session_file()


# ─────────────────────────────────────────────────────────────────────────────
# 各 provider 登录（均落本机 user 行）
# ─────────────────────────────────────────────────────────────────────────────
def _set_session(uid: int, display: str) -> None:
    st.session_state["user_id"] = uid
    st.session_state["user_display"] = display
    persist_login(uid)


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
# 登录态持久化（决策 #3：保持登录）
# ─────────────────────────────────────────────────────────────────────────────
def persist_login(uid: int) -> None:
    """把当前 user_id 写入本机标记文件，供重启后自动恢复。"""
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump({"user_id": uid}, f)


def _clear_session_file() -> None:
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
    except OSError:
        # 删除失败（Windows 下文件可能被短暂锁定）：退化为清空内容，避免下次被自动恢复
        try:
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f)
        except OSError:
            pass


def try_restore_login() -> None:
    """在应用启动时调用：若当前会话未登录且本机有有效标记，则恢复登录态。

    注意：必须在脚本运行期（页面渲染/run_app）调用，不能在模块导入期调用。
    """
    if st.session_state.get("user_id"):
        return
    if st.session_state.get("_logged_out"):
        return  # 用户本次会话主动退出，不自动恢复
    if not os.path.exists(SESSION_FILE):
        return
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        uid = data.get("user_id")
        if uid is None:
            return
        u = storage.get_user(uid)
        if u:
            st.session_state["user_id"] = uid
            st.session_state["user_display"] = u.get("display_name") or ""
    except (OSError, json.JSONDecodeError):
        pass
