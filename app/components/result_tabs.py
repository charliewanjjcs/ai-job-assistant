"""分析结果渲染组件（从 main.py 抽出 8 个 render_* + 统一的 render_report）。"""
from __future__ import annotations

import streamlit as st


def render_salary(r):
    s = r.salary_analysis
    st.subheader("薪资匹配结论")
    col1, col2, col3 = st.columns(3)
    col1.metric("你的预期(年化)", f"{s.expected:,.0f}" if s.expected is not None else "未填")
    col2.metric("公司报价(年化)", f"{s.company_offer:,.0f}" if s.company_offer is not None else "未提供")
    col3.metric("市场区间", f"{s.market_low:,.0f}~{s.market_high:,.0f}" if s.market_low else "—")
    st.write(f"**判定：{s.verdict}**")
    if s.currency_warning:
        st.warning(s.currency_warning)
    if s.gap_vs_expected is not None:
        st.write(f"公司报价相对预期差距：{s.gap_vs_expected:,.0f} 元/年")
    for n in s.notes:
        st.write(f"- {n}")


def render_skill(r):
    sm = r.skill_match
    st.subheader(f"能力匹配度：{sm.match_score}/100")
    st.write(f"**已匹配：** {', '.join(sm.matched) or '无'}")
    st.write(f"**缺失-必需：** {', '.join(sm.missing_required) or '无'}")
    st.write(f"**缺失-加分：** {', '.join(sm.missing_preferred) or '无'}")


def render_language(r):
    lm = r.language_match
    if lm is None:
        st.write("—")
        return
    st.subheader(f"语言匹配度：{lm.match_score}/100")
    st.write(f"**已匹配：** {', '.join(lm.matched) or '无'}")
    st.write(f"**缺失：** {', '.join(lm.missing) or '无'}")
    for n in lm.notes:
        st.write(f"- {n}")


def render_availability(r):
    am = r.availability_match
    if am is None:
        st.write("—")
        return
    st.subheader("到岗匹配")
    st.write(f"**判定：{am.fit}**")
    if am.note:
        st.write(am.note)


def render_improve(r):
    st.subheader("提升建议")
    for s in r.improvement_suggestions:
        st.markdown(f"- **[{s.priority}] {s.area}**：{s.detail}")


def render_career(r):
    c = r.career_prospect
    st.subheader("岗位前景")
    st.markdown(f"**晋升机会：** {c.promotion or '—'}")
    st.markdown(f"**加薪机会：** {c.raise_outlook or '—'}")
    st.markdown(f"**跳槽机会：** {c.jump_outlook or '—'}")


def render_daily(r):
    st.subheader("日常工作")
    st.write(r.daily_work or "—")


def render_interview(r):
    st.subheader("面试高频问题与回答方向")
    if not r.interview_qa:
        st.write("未能生成，请检查 JD 文本或 API Key。")
        return
    for i, qa in enumerate(r.interview_qa, 1):
        with st.expander(f"Q{i}. {qa.question}  ({qa.frequency})"):
            st.write(f"**回答方向：** {qa.direction}")


def render_report(report, demo: bool = False):
    """用 8 个标签页渲染完整分析报告。"""
    tabs = st.tabs([
        "薪资匹配", "能力匹配", "语言匹配", "到岗匹配",
        "提升建议", "岗位前景", "日常工作", "面试问题",
    ])
    with tabs[0]:
        render_salary(report)
    with tabs[1]:
        render_skill(report)
    with tabs[2]:
        render_language(report)
    with tabs[3]:
        render_availability(report)
    with tabs[4]:
        render_improve(report)
    with tabs[5]:
        render_career(report)
    with tabs[6]:
        render_daily(report)
    with tabs[7]:
        render_interview(report)
