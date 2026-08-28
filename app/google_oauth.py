"""谷歌真实 OAuth 登录（基于 streamlit-oauth 的 popup 流程）。

设计要点：
- 用 streamlit_oauth.OAuth2Component 渲染「使用 Google 登录」按钮；点击后在 popup 完成授权，
  组件把 token 回传主标签页（主标签页不刷新，session_state 不丢 → 不会卡顿、不丢登录态）。
- Google 返回的 id_token（JWT）里含 sub / email / name，据此落到已有的 users 表
  （storage.get_or_create_user），与邮箱/手机号账户共用同一套持久化层，资料天然跟随。
- 校验/落库只在「点登录按钮那一刻」发生一次，日常操作零额外网络开销 → 不会卡顿。

配置（Streamlit Cloud Secrets 或项目 config/.env，不进仓库）：
  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI
  GOOGLE_REDIRECT_URI 必须是 https://<你的域名>/component/streamlit_oauth.authorize_button
"""
from __future__ import annotations

import base64
import json
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", ".env"))

import streamlit as st

import app.storage as storage

GOOGLE_AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"


def _cfg(key: str) -> str | None:
    """优先读 Streamlit Secrets，回退到环境变量（本地 config/.env）。"""
    try:
        val = st.secrets.get(key)
        if val:
            return val
    except Exception:
        pass
    return os.getenv(key)


def is_configured() -> bool:
    """是否已配置谷歌 OAuth（缺任一项即视为未配置）。"""
    return bool(
        _cfg("GOOGLE_CLIENT_ID")
        and _cfg("GOOGLE_CLIENT_SECRET")
        and _cfg("GOOGLE_REDIRECT_URI")
    )


def decode_id_token(id_token: str) -> dict:
    """解码 Google id_token（JWT）的 payload；不校验签名（可选步骤）。

    返回 sub / email / name / picture 等声明。格式非法或缺少 payload 时抛 ValueError。
    """
    if not id_token or id_token.count(".") != 2:
        raise ValueError("id_token 格式非法")
    _, payload_b64, _ = id_token.split(".")
    # base64url 补 padding 后解码
    padding = "=" * (-len(payload_b64) % 4)
    raw = base64.urlsafe_b64decode((payload_b64 + padding).encode("ascii"))
    return json.loads(raw)


def upsert_google_user(payload: dict) -> int:
    """按 Google 身份落到 users 表，返回 user_id。

    - 若 id_token 中的邮箱已存在于 users 表（曾用邮箱注册），则合并到同一账户，
      避免 users.email 唯一索引冲突，也让邮箱登录与谷歌登录指向同一份资料。
    - 否则按 (provider="google", sub) 创建/复用账户。
    """
    sub = payload.get("sub")
    email = (payload.get("email") or "").strip().lower()
    name = payload.get("name") or payload.get("email") or "Google 用户"
    if not sub:
        raise ValueError("id_token 缺少 sub")

    if email:
        existing = storage.get_user_by_email(email)
        if existing:
            return int(existing["id"])

    uid = storage.get_or_create_user(
        "google", sub, email=email or None, display_name=name
    )
    return int(uid)


def render_login_button() -> None:
    """在登录表单里渲染「使用 Google 登录」按钮。

    授权成功后：解析 id_token → 落库 → 写入 session_state["user_id"/"user_display"] → rerun。
    未配置 Secrets 时给出提示而非报错（应用其余功能不受影响）。
    """
    if not is_configured():
        st.info(
            "Google 登录尚未配置（需在 Secrets 填入 GOOGLE_CLIENT_ID / "
            "GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI）。当前可用邮箱/手机号登录。"
        )
        return

    from streamlit_oauth import OAuth2Component

    oauth2 = OAuth2Component(
        _cfg("GOOGLE_CLIENT_ID"),
        _cfg("GOOGLE_CLIENT_SECRET"),
        GOOGLE_AUTHORIZE_ENDPOINT,
        GOOGLE_TOKEN_ENDPOINT,
        GOOGLE_TOKEN_ENDPOINT,  # 刷新端点（Google 复用 token 端点）
        GOOGLE_REVOKE_ENDPOINT,
    )
    result = oauth2.authorize_button(
        name="使用 Google 登录",
        icon="https://www.google.com/favicon.ico",
        redirect_uri=_cfg("GOOGLE_REDIRECT_URI"),
        scope="openid email profile",
        key="google_oauth",
        extras_params={"prompt": "select_account", "access_type": "offline"},
        use_container_width=True,
        pkce="S256",
    )
    if result and "token" in result:
        id_token = result["token"].get("id_token")
        if not id_token:
            st.error("Google 未返回 id_token，请重试。")
            return
        try:
            payload = decode_id_token(id_token)
            uid = upsert_google_user(payload)
        except Exception as e:
            st.error(f"Google 登录失败：{e}")
            return
        u = storage.get_user(uid)
        st.session_state["user_id"] = uid
        st.session_state["user_display"] = (
            (u and u.get("display_name")) or payload.get("email") or "Google 用户"
        )
        st.rerun()
