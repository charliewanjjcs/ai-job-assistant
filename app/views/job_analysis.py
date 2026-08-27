"""职位分析页（决策：左侧控制栏「职位详情/JD」入口）。

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
from app.components.sidebar_offset import inject_content_offset
from app.state import (DemoLLM, build_jd, build_profile, cache_candidate_from_db,
                       coerce_int_salary, extract_jd_meta, on_jd_text_change)
from app.views import results as results_page
from core.analyzer import CoreAnalyzer
from core.llm import DeepSeekClient
from modules.jd_url import UrlJdSource
from modules.salary_api import DeepSeekSalaryProvider, TightenedSalaryProvider
from core.salary import RuleBasedSalaryProvider


# 「开始分析」的加载浮窗（纯前端 CSS 动画，不增加任何网络/计算开销）：
# 屏幕中央弹出半透明遮罩 + 卡片，卡片上是「卡通人物喝水」的 emoji 动效（😊 上下浮动、
# 🧋 左右摇晃、💧 水滴依次下落），配上提示文字。分析结束即跳转结果页，浮窗随页面切换消失。
_LOADING_OVERLAY_HTML = """
<style>
@keyframes wb-sip { 0%,100%{transform:rotate(-7deg)} 50%{transform:rotate(7deg)} }
@keyframes wb-bob { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-4px)} }
@keyframes wb-drop { 0%{transform:translateY(0);opacity:0} 25%{opacity:1} 100%{transform:translateY(26px);opacity:0} }
.wb-mask {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(30, 42, 30, 0.35);
  display: flex; align-items: center; justify-content: center; z-index: 9999;
}
.wb-card {
  background: #ffffff; border-radius: 18px; padding: 1.8rem 2.2rem;
  box-shadow: 0 16px 48px rgba(0,0,0,0.22); text-align: center; min-width: 280px;
}
.wb-scene { display: flex; align-items: center; justify-content: center; gap: 6px; font-size: 56px; line-height: 1; }
.wb-face { display: inline-block; animation: wb-bob 1.4s ease-in-out infinite; }
.wb-drink { display: inline-block; animation: wb-sip 1.1s ease-in-out infinite; }
.wb-drops { font-size: 20px; letter-spacing: 8px; height: 26px; margin-top: 2px; }
.wb-drops span { display: inline-block; animation: wb-drop 1.5s ease-in infinite; }
.wb-drops span:nth-child(2) { animation-delay: 0.4s; }
.wb-drops span:nth-child(3) { animation-delay: 0.8s; }
.wb-text { margin-top: 0.8rem; font-size: 16px; font-weight: 600; color: #333; }
</style>
<div class="wb-mask">
  <div class="wb-card">
    <div class="wb-scene"><span class="wb-face">😊</span><span class="wb-drink">🧋</span></div>
    <div class="wb-drops"><span>💧</span><span>💧</span><span>💧</span></div>
    <div class="wb-text">正在分析中，喝口水，马上就好……</div>
  </div>
</div>
"""


def _show_loading_overlay() -> None:
    """渲染加载浮窗。需在阻塞的 analyze() 之前调用，浮窗才会在分析期间显示。"""
    st.markdown(_LOADING_OVERLAY_HTML, unsafe_allow_html=True)


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
    # 预期薪资：仅当 session_state 中尚无有效值时才用 DB 覆盖。
    # 否则「在个人资料页填了但还没点保存」的月薪/港币会被 DB 的空值冲掉，
    # 导致分析结果显示「未填 / 年薪」。已保存过的值本就在 session_state，无需再读 DB。
    if not st.session_state.get("exp_value"):
        st.session_state["exp_period_label"] = p.get("exp_period_label") or "年薪"
        st.session_state["exp_currency_label"] = p.get("exp_currency_label") or "¥ 人民币 (CNY)"
        st.session_state["exp_value"] = coerce_int_salary(p.get("exp_value"))
    st.session_state["lang_list"] = p.get("lang_list") or []
    st.session_state["availability"] = p.get("availability") or "未填写"
    st.session_state["skills"] = ", ".join(storage.list_skills(uid))
    # 把已保存值并入非 widget 缓存：即便跨页导航裁剪了 widget 键，分析结果时仍可回退
    cache_candidate_from_db(p)


def _fetch_jd_from_url() -> None:
    """「从链接抓取」按钮回调：抓取 URL 的 JD 并回填文本框与字段。"""
    url = (st.session_state.get("jd_url") or "").strip()
    if not url:
        st.session_state["jd_fetch_error"] = "请先在上方填入 JD 链接。"
        return
    try:
        jd = UrlJdSource().fetch(url)
    except (ValueError, RuntimeError) as e:
        st.session_state["jd_fetch_error"] = str(e)
        return
    st.session_state["jd_fetch_error"] = ""
    st.session_state["jd_text"] = jd.raw_text
    on_jd_text_change()  # 先回填必需技能、语言、到岗偏好（含启发式软技能）
    # 元信息抽取：职位名称 / 公司 / 软技能特质（有 Key 走 LLM，否则本地启发式）
    meta = extract_jd_meta(jd.raw_text)
    st.session_state["jd_title"] = meta.get("title") or jd.title or ""
    st.session_state["jd_company"] = meta.get("company") or jd.company or ""
    st.session_state["jd_city"] = jd.city or ""
    if meta.get("soft_skills"):
        st.session_state["jd_pref"] = ", ".join(meta["soft_skills"])
    st.session_state["_jd_fetched"] = True


def render() -> None:
    if not auth.is_logged_in():
        st.info("请先在左侧登录 / 注册后再进行职位分析。")
        return

    uid = auth.current_user_id()
    # 去掉顶部大标题，改用二级标题「职位详情/JD」，提示句置于其下方
    st.header("职位详情/JD")
    st.caption("已自动载入你的个人资料（技能库/简历/语言等），直接粘贴 JD 即可出匹配结果。")

    # 标题字符级对齐：展开时「情」（第 4 字，index=3）中心在 50%；收起时「D」（JD 的 D）中心在 45%
    inject_content_offset(
        expanded={"index": 3, "pct": 0.5},
        collapsed={"index": 6, "pct": 0.45},
        name="job",
    )

    # 进入本页（含从别的页切换回来）时载入最新已保存候选人资料；绝不碰 jd_* 键
    if st.session_state.get("_active_page") != "job_analysis":
        _load_candidate_to_session(uid)
        st.session_state["_active_page"] = "job_analysis"

    # 整体占左半宽，避免侧栏收起后被拉长填满整页
    _wrap, _ = st.columns([1, 1])
    with _wrap:
        with st.container():
            # ── JD 链接抓取（Phase3：URL 读取 JD）──
            url_col, fetch_col = st.columns([4, 1], vertical_alignment="center")
            with url_col:
                st.text_input(
                    "JD 链接（可选，填了点「从链接抓取」自动读取）",
                    key="jd_url",
                    placeholder="https://jobs.example.com/xxx",
                )
            with fetch_col:
                st.button(
                    "从链接抓取", key="jd_fetch", on_click=_fetch_jd_from_url,
                    use_container_width=True,
                )
            if st.session_state.get("_jd_fetched"):
                st.success("已从链接抓取并回填 JD 原文与字段 ✅")
                st.session_state["_jd_fetched"] = False
            if st.session_state.get("jd_fetch_error"):
                st.error(st.session_state["jd_fetch_error"])

            col_text, col_btn = st.columns([4, 1], vertical_alignment="center")
            with col_text:
                st.text_area(
                    "JD 原文（粘贴）", key="jd_text", height=100, on_change=on_jd_text_change,
                    placeholder="把招聘网页上的 JD 文本粘贴到这里，粘贴后按 Ctrl+Enter 或点「确认」",
                )
            with col_btn:
                st.button("确认", key="jd_confirm", on_click=on_jd_text_change, use_container_width=True)
            st.markdown("**职位名称**")
            st.text_input("", key="jd_title", label_visibility="collapsed")
            st.markdown("**公司**")
            st.text_input("", key="jd_company", label_visibility="collapsed")
            st.markdown("**城市**")
            st.text_input("", key="jd_city", label_visibility="collapsed")
            st.markdown("**必需技能**")
            st.text_input("", key="jd_req", placeholder="Python, Go, MySQL", label_visibility="collapsed")
            st.markdown("**软技能/特质**")
            st.text_input("", key="jd_pref", placeholder="attention to detail, financial products knowledge", label_visibility="collapsed")

            st.markdown("**语言要求**")
            lang_manager("jd_lang_list", "")
            st.checkbox("JD 偏好「尽快到岗 / Immediate available」", key="jd_prefers_immediate")

    # 上一次「开始分析」失败的错误提示（失败后 rerun 展示；成功则不会存在）
    _err = st.session_state.pop("_analysis_error", None)
    if _err:
        st.error(f"分析失败：{_err}")

    if st.button("开始分析", type="primary"):
        # 跨页导航会裁剪个人资料页的 widget 键，这里再从 DB 把已保存值并入缓存（空值不覆盖），
        # 与 build_profile 的缓存回退配合，确保「填了月薪港币」在分析时不被清成未填/年薪
        cache_candidate_from_db(storage.load_profile(uid) or {})
        profile = build_profile()
        jd = build_jd()
        demo = bool(st.session_state.get("demo", True))
        try:
            llm = DemoLLM() if demo else DeepSeekClient()
            # 薪资数据源：无 Key（demo）用规则估算；有 Key 用 DeepSeek 大模型估算（失败自动回退规则）。
            # 外层统一用 TightenedSalaryProvider 收窄市场区间（按职级+市场价），避免区间过宽。
            base_salary = RuleBasedSalaryProvider() if demo else DeepSeekSalaryProvider(llm=llm)
            salary = TightenedSalaryProvider(base_salary)
            analyzer = CoreAnalyzer(llm=llm, salary_provider=salary)
            # 加载浮窗：必须在阻塞的 analyze() 之前渲染，分析期间才显示「喝水」动效；
            # 完成后 st.switch_page 跳结果页，浮窗随页面切换消失。
            _show_loading_overlay()
            report = analyzer.analyze(profile, jd)
        except RuntimeError as e:
            # 失败时把错误存 session_state 后 rerun，清掉浮窗并在下次渲染展示错误（避免浮窗残留）
            st.session_state["_analysis_error"] = str(e)
            st.rerun()
        # 持久化 + 跳转「分析结果」页并默认选中刚分析的记录；同时请求进入后自动收起左侧控制栏
        new_id = storage.save_analysis_result(uid, report, jd_text=jd.raw_text)
        st.session_state["_pending_result_id"] = new_id
        st.session_state["_collapse_sidebar"] = True
        st.switch_page(st.Page(results_page.render, url_path="results"))
