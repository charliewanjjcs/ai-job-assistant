"""AI 求职助手 —— Streamlit 前端（Phase 1：单机版分析器）。

流程：用户粘贴简历/画像 + 粘贴 JD -> CoreAnalyzer -> 六维度结果展示。
演示模式可用（无需 API Key）；真实模式读取 config/.env 的 DeepSeek Key。
"""
import os
import sys

# 确保项目根在 sys.path，便于 import core
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, "config", ".env"))

import streamlit as st

from core.analyzer import CoreAnalyzer
from core.llm import DeepSeekClient
from core.models import Currency, JdInfo, PayPeriod, SalaryAmount, UserProfile
from core.parsers import parse_jd_text, parse_resume_text
from modules.resume_pdf.pdf_parser import PdfResumeParser


class DemoLLM:
    """演示用假 LLM：返回结构化文本，便于无 Key 预览界面。"""

    def complete(self, prompt, system="", temperature=0.7, max_tokens=1500):
        if system and "职业规划" in system:
            return (
                "## 晋升机会\n该岗位通常 1-2 年可晋升至高级或组长，取决于业务产出与带人能力。\n"
                "## 加薪机会\n年度调薪幅度多在 5%-15%，晋升时幅度更大。\n"
                "## 跳槽机会\n市场需求稳定，积累 2-3 年经验后跳槽选择较多。\n"
                "## 日常工作\n需求评审、方案设计、编码实现、联调测试与线上问题排查。"
            )
        return (
            "Q: 请介绍你做过的重点项目。\nA: 用 STAR 结构讲清背景、你的角色、动作与量化结果。\nF: 高频\n"
            "Q: 你遇到最难的技术问题是什么？\nA: 说明问题、排查思路与最终解法，突出方法论。\nF: 高频\n"
            "Q: 为什么想加入我们？\nA: 结合公司业务与个人职业规划，避免空泛。\nF: 中频\n"
            "Q: 你的优缺点是什么？\nA: 优点贴合岗位，缺点谈改进动作而非硬伤。\nF: 中频\n"
            "Q: 期望薪资是多少？\nA: 基于市场与自身能力给出区间，并说明依据。\nF: 高频\n"
            "Q: 未来三到五年规划？\nA: 技术与业务双线成长，逐步承担更大责任。\nF: 低频"
        )


def build_profile():
    resume = st.session_state.get("resume", "")
    # 手动字段优先；未填时从粘贴的简历文本启发式抽取（MVP 占位解析）
    parsed = parse_resume_text(resume) if resume else {}
    skills_raw = st.session_state.get("skills", "")
    skills = [s.strip() for s in skills_raw.split(",") if s.strip()] or (parsed.get("skills") or [])
    personality = st.session_state.get("personality", "") or parsed.get("personality")
    target_role = st.session_state.get("target_role", "") or parsed.get("target_role")
    city = st.session_state.get("city", "") or parsed.get("city")
    exp_wan = st.session_state.get("exp_wan", 0.0)
    is_usd = st.session_state.get("exp_usd", False)
    expected = None
    if exp_wan and exp_wan > 0:
        expected = SalaryAmount(
            value=float(exp_wan) * 10000.0,
            currency=Currency.USD if is_usd else Currency.CNY,
            period=PayPeriod.ANNUAL,
        )
    else:
        pexp = parsed.get("expected_salary")
        if pexp:
            expected = SalaryAmount(value=pexp, currency=Currency.CNY, period=PayPeriod.ANNUAL)
    return UserProfile(
        raw_resume=resume or None,
        skills=skills,
        personality=personality,
        target_role=target_role,
        city=city,
        expected_salary=expected,
    )


def build_jd():
    raw = st.session_state.get("jd_text", "")
    # 手动字段优先；未填时从粘贴的 JD 文本启发式抽取（MVP 占位解析）
    parsed = parse_jd_text(raw) if raw else {}
    title = st.session_state.get("jd_title", "") or parsed.get("title")
    company = st.session_state.get("jd_company", "") or parsed.get("company")
    city = st.session_state.get("jd_city", "") or parsed.get("city")
    req_raw = st.session_state.get("jd_req", "")
    req = [s.strip() for s in req_raw.split(",") if s.strip()] or (parsed.get("required_skills") or [])
    pref_raw = st.session_state.get("jd_pref", "")
    pref = [s.strip() for s in pref_raw.split(",") if s.strip()] or (parsed.get("preferred_skills") or [])
    return JdInfo(
        title=title, company=company, city=city,
        required_skills=req, preferred_skills=pref, raw_text=raw or "",
    )


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
    st.write(f"**缺失-必选：** {', '.join(sm.missing_required) or '无'}")
    st.write(f"**缺失-加分：** {', '.join(sm.missing_preferred) or '无'}")


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


def main():
    st.set_page_config(page_title="AI 求职助手", layout="wide")
    st.title("AI 求职助手")
    st.caption("单机版分析器：支持上传 PDF 简历 / 粘贴文本，查看薪资/能力/前景/面试分析")

    with st.sidebar:
        st.header("模式")
        demo = st.checkbox("演示模式（无需 API Key）", value=True)
        st.markdown("---")
        with st.expander("关于本项目"):
            st.write(
                "模块独立、分步锁定：core/ 为核心算法，modules/ 按步骤填肉"
                "（PDF→URL→薪资API）。所有测试数据放在 sandbox/，不碰 core。"
            )

    c1, c2 = st.columns(2)

    with c1:
        st.header("候选人画像")
        # Phase2：上传 PDF 简历，自动抽取并填充下方字段（手动字段仍优先、可改）
        uploaded = st.file_uploader("上传简历 PDF（可选，自动填充下方字段）", type=["pdf"])
        if uploaded is not None:
            sig = f"{uploaded.name}:{uploaded.size}"
            if st.session_state.get("_pdf_last") != sig:  # 仅处理新上传，避免覆盖手动编辑
                st.session_state["_pdf_last"] = sig
                up_dir = os.path.join(ROOT, "sandbox", "uploads")
                os.makedirs(up_dir, exist_ok=True)
                up_path = os.path.join(up_dir, uploaded.name)
                with open(up_path, "wb") as f:
                    f.write(uploaded.getbuffer())
                try:
                    parser = PdfResumeParser()
                    text = parser.extract_text(up_path)
                    if not text:
                        st.warning("该 PDF 无文字层（可能是扫描件），请改用下方文本粘贴。")
                    else:
                        prof = parser.parse(up_path)
                        if prof.raw_resume:
                            st.session_state["resume"] = prof.raw_resume
                        if prof.skills:
                            st.session_state["skills"] = ", ".join(prof.skills)
                        if prof.target_role:
                            st.session_state["target_role"] = prof.target_role
                        if prof.personality:
                            st.session_state["personality"] = prof.personality
                        if prof.city:
                            st.session_state["city"] = prof.city
                        if prof.expected_salary:
                            st.session_state["exp_wan"] = round(prof.expected_salary.value / 10000.0, 1)
                        st.success("已从 PDF 提取并填充字段，可手动调整。")
                except Exception as e:
                    st.error(f"PDF 解析失败：{e}")
        st.text_area("简历文本（粘贴）", key="resume", height=160)
        st.text_input("目标岗位", key="target_role")
        st.text_input("掌握的技能（逗号分隔）", key="skills", placeholder="Python, MySQL, Redis")
        st.text_input("性格描述", key="personality", placeholder="细心、抗压、沟通好")
        st.text_input("期望工作城市", key="city")
        col_a, col_b = st.columns([2, 1])
        col_a.number_input("预期年薪（万元）", key="exp_wan", min_value=0.0, step=1.0)
        col_b.checkbox("以美元计", key="exp_usd")

    with c2:
        st.header("职位描述 JD")
        st.text_input("岗位标题", key="jd_title")
        st.text_input("公司", key="jd_company")
        st.text_input("城市", key="jd_city")
        st.text_input("必选技能（逗号分隔）", key="jd_req", placeholder="Python, Go, MySQL")
        st.text_input("加分技能（逗号分隔）", key="jd_pref", placeholder="Docker, K8s")
        st.text_area("JD 原文（粘贴）", key="jd_text", height=200,
                     placeholder="把招聘网页上的 JD 文本粘贴到这里（第三步将支持直接填 URL）")

    if st.button("开始分析", type="primary"):
        profile = build_profile()
        jd = build_jd()
        try:
            llm = DemoLLM() if demo else DeepSeekClient()
            analyzer = CoreAnalyzer(llm=llm)
            with st.spinner("分析中..."):
                report = analyzer.analyze(profile, jd)
        except RuntimeError as e:
            st.error(f"分析失败：{e}")
            return

        tabs = st.tabs(["薪资匹配", "能力匹配", "提升建议", "岗位前景", "日常工作", "面试问题"])
        with tabs[0]:
            render_salary(report)
        with tabs[1]:
            render_skill(report)
        with tabs[2]:
            render_improve(report)
        with tabs[3]:
            render_career(report)
        with tabs[4]:
            render_daily(report)
        with tabs[5]:
            render_interview(report)


if __name__ == "__main__":
    main()
