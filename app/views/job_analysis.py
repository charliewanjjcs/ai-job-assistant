"""职位分析页（决策：左侧控制栏「职位分析」入口）。

进入时自动载入「个人资料」页已保存的候选人数据（只写候选人键，绝不碰 jd_* 键）；
用户只需粘贴 JD，即可出能力/薪资/语言/到岗等匹配结果。
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
from app.components.lang_manager import lang_manager
from app.state import DemoLLM, build_jd, build_profile, on_jd_text_change
from app.views import results as results_page
from core.analyzer import CoreAnalyzer
from core.llm import DeepSeekClient


def _load_candidate_to_session(uid: int) -> None:
    """把已保存的候选人资料载入 session_state，供 build_profile 使用。

    仅写候选人键（resume/skills/personality/ideal_job/city/exp_*/lang_list/availability），
    **绝不**写入 jd_* 键，避免覆盖用户已填的 JD。
    """
    p = storage.load_profile(uid) or {}
    st.session_state["resume"] = p.get("resume") or ""
    st.session_state["ideal_job"] = p.get("ideal_job") or ""
    st.session_state["personality"] = p.get("personality") or ""
    st.session_state["city"] = p.get("city") or ""
    st.session_state["exp_period_label"] = p.get("exp_period_label") or "年薪"
    st.session_state["exp_currency_label"] = p.get("exp_currency_label") or "¥ 人民币 (CNY)"
    st.session_state["exp_value"] = p.get("exp_value") or 0.0
    st.session_state["lang_list"] = p.get("lang_list") or []
    st.session_state["availability"] = p.get("availability") or "未填写"
    st.session_state["skills"] = ", ".join(storage.list_skills(uid))


def render() -> None:
    if not auth.is_logged_in():
        st.info("请先在左侧登录 / 注册后再进行职位分析。")
        return

    uid = auth.current_user_id()
    st.title("职位分析")
    st.caption("已自动载入你的个人资料（技能库/简历/语言等），直接粘贴 JD 即可出匹配结果。")

    # 自动载入候选人资料（守卫，仅切换用户时覆盖一次；绝不碰 jd_* 键）
    if st.session_state.get("_jd_loaded_uid") != uid:
        _load_candidate_to_session(uid)
        st.session_state["_jd_loaded_uid"] = uid

    with st.container():
        st.header("职位描述 JD")
        col_text, col_btn = st.columns([4, 1], vertical_alignment="bottom")
        with col_text:
            st.text_area(
                "JD 原文（粘贴）", key="jd_text", height=100, on_change=on_jd_text_change,
                placeholder="把招聘网页上的 JD 文本粘贴到这里，粘贴后按 Ctrl+Enter 或点「确认」",
            )
        with col_btn:
            st.button("确认", key="jd_confirm", on_click=on_jd_text_change, use_container_width=True)
        st.text_input("岗位标题", key="jd_title")
        st.text_input("公司", key="jd_company")
        st.text_input("城市", key="jd_city")
        st.text_input("必需技能", key="jd_req", placeholder="Python, Go, MySQL")
        st.text_input("加分技能", key="jd_pref", placeholder="Docker, K8s")

        st.markdown("**语言要求**")
        lang_manager("jd_lang_list", "")
        st.checkbox("JD 偏好「尽快到岗 / Immediate available」", key="jd_prefers_immediate")

    if st.button("开始分析", type="primary"):
        profile = build_profile()
        jd = build_jd()
        demo = bool(st.session_state.get("demo", True))
        try:
            llm = DemoLLM() if demo else DeepSeekClient()
            analyzer = CoreAnalyzer(llm=llm)
            with st.spinner("分析中..."):
                report = analyzer.analyze(profile, jd)
        except RuntimeError as e:
            st.error(f"分析失败：{e}")
            return
        # 持久化 + 跳转「分析结果」页并默认选中刚分析的记录
        new_id = storage.save_analysis_result(uid, report, jd_text=jd.raw_text)
        st.session_state["_pending_result_id"] = new_id
        st.switch_page(st.Page(results_page.render, url_path="results"))
