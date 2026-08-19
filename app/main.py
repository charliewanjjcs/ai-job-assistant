"""AI 求职助手 —— Streamlit 前端。

流程：用户填写画像（可上传 PDF / 粘贴文本自动抽取） + 填写/粘贴 JD -> CoreAnalyzer -> 结果展示。
演示模式可用（无需 API Key）；真实模式读取 config/.env 的 DeepSeek Key。
"""
import os
import sys
import uuid

# 确保项目根在 sys.path，便于 import core
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, "config", ".env"))

import streamlit as st

from core.analyzer import CoreAnalyzer
from core.llm import DeepSeekClient
from core.models import (
    Availability,
    Currency,
    JdInfo,
    LanguageLevel,
    LanguageProficiency,
    PayPeriod,
    SalaryAmount,
    UserProfile,
)
from core.parsers import parse_jd_text, parse_resume_text, split_skills
from modules.resume_pdf.pdf_parser import PdfResumeParser

# 选项常量
LANG_OPTIONS = ["英语", "粤语", "普通话", "日语", "法语", "韩语", "德语", "西班牙语", "其他"]
LEVEL_OPTIONS = ["基础", "熟练", "母语"]
AVAIL_OPTIONS = ["立刻", "一周内", "一个月", "两个月", "三个月", "更长"]
# 预期薪资：用「标签」做 selectbox 选项，再映射到内部枚举值（避免元组选项导致 KeyError）
PERIOD_LABELS = ["年薪", "月薪", "时薪"]
PERIOD_VALUES = {"年薪": "annual", "月薪": "monthly", "时薪": "hourly"}
CURRENCY_LABELS = ["¥ 人民币 (CNY)", "HK$ 港币 (HKD)"]
CURRENCY_VALUES = {"¥ 人民币 (CNY)": "CNY", "HK$ 港币 (HKD)": "HKD"}
EXP_LABELS = {"年薪": "预期年薪（元）", "月薪": "预期月薪（元）", "时薪": "预期时薪（元）"}


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


def _idx(options, value):
    try:
        return options.index(value)
    except ValueError:
        return 0


def _lang_manager(state_key: str, header: str = ""):
    """语言 + 熟练度 管理器。

    初始状态只显示「+ 添加语言」按钮；点击后新增一栏「语言 + 熟练度」选择框（可随手改、可删除）。
    每个条目带稳定 id，避免删除后索引错位。
    """
    if header:
        st.markdown(f"**{header}**")
    items = st.session_state.setdefault(state_key, [])
    # 兼容 JD 自动识别回填的无 id 旧条目：补齐稳定 id
    for it in items:
        if "id" not in it:
            it["id"] = str(uuid.uuid4())
    # 渲染已有条目（可编辑）
    for it in items:
        rid = it["id"]
        c1, c2, c3 = st.columns([2, 1, 0.8])
        lang = c1.selectbox(
            "语言", LANG_OPTIONS,
            index=_idx(LANG_OPTIONS, it.get("language", "")),
            key=f"{state_key}_lang_{rid}", label_visibility="collapsed",
        )
        lvl = c2.selectbox(
            "熟练度", LEVEL_OPTIONS,
            index=_idx(LEVEL_OPTIONS, it.get("level", "")),
            key=f"{state_key}_lvl_{rid}", label_visibility="collapsed",
        )
        it["language"] = lang
        it["level"] = lvl
        if c3.button("×", key=f"{state_key}_del_{rid}"):
            st.session_state[state_key] = [x for x in items if x["id"] != rid]
            st.rerun()
    # 添加按钮（初始即显示；空列表时也只显示它）
    if st.button("+ 添加语言", key=f"{state_key}_add_btn"):
        items.append({"id": str(uuid.uuid4()), "language": LANG_OPTIONS[0], "level": LEVEL_OPTIONS[1]})
        st.session_state[state_key] = items
        st.rerun()


def on_jd_text_change():
    """JD 原文变化时的回调：解析并回填必需/加分技能、语言要求、到岗偏好。

    用 on_change 回调写入 session_state，可避免「widget 已实例化后又直接赋值」导致的
    StreamlitAPIException（st.session_state.jd_req 不可在 widget 实例化后修改）。
    """
    jd_text = st.session_state.get("jd_text", "")
    if not jd_text:
        return
    pjd = parse_jd_text(jd_text)
    st.session_state["jd_lang_list"] = [
        {"id": str(uuid.uuid4()), "language": l.language, "level": l.level.value}
        for l in pjd["required_languages"]
    ]
    st.session_state["jd_prefers_immediate"] = pjd["prefers_immediate"]
    st.session_state["jd_req"] = ", ".join(pjd["required_skills"])
    st.session_state["jd_pref"] = ", ".join(pjd["preferred_skills"])


def build_profile():
    resume = st.session_state.get("resume", "")
    parsed = parse_resume_text(resume) if resume else {}
    skills_raw = st.session_state.get("skills", "")
    skills = split_skills(skills_raw) or (parsed.get("skills") or [])
    personality = st.session_state.get("personality", "") or parsed.get("personality")
    ideal_job = st.session_state.get("ideal_job", "") or None
    city = st.session_state.get("city", "") or parsed.get("city")

    # 预期薪资：手动优先；手动未填则用解析结果
    period_label = st.session_state.get("exp_period_label", "年薪")
    period = PERIOD_VALUES.get(period_label, "annual")
    currency_label = st.session_state.get("exp_currency_label", "¥ 人民币 (CNY)")
    currency = CURRENCY_VALUES.get(currency_label, "CNY")
    value = st.session_state.get("exp_value", 0.0)
    expected = None
    if value and value > 0:
        v = float(value)
        expected = SalaryAmount(value=v, currency=Currency(currency), period=PayPeriod(period))
    else:
        pexp = parsed.get("expected_salary")
        if pexp:
            expected = pexp

    langs = [
        LanguageProficiency(language=e["language"], level=LanguageLevel(e["level"]))
        for e in st.session_state.get("lang_list", [])
    ]
    av = st.session_state.get("availability")
    availability = Availability(av) if av and av != "未填写" else None

    return UserProfile(
        raw_resume=resume or None,
        ideal_job=ideal_job,
        skills=skills,
        personality=personality,
        expected_salary=expected,
        languages=langs,
        availability=availability,
        city=city,
    )


def build_jd():
    raw = st.session_state.get("jd_text", "")
    parsed = parse_jd_text(raw) if raw else {}
    title = st.session_state.get("jd_title", "") or parsed.get("title")
    company = st.session_state.get("jd_company", "") or parsed.get("company")
    city = st.session_state.get("jd_city", "") or parsed.get("city")
    req_raw = st.session_state.get("jd_req", "")
    req = split_skills(req_raw) or (parsed.get("required_skills") or [])
    pref_raw = st.session_state.get("jd_pref", "")
    pref = split_skills(pref_raw) or (parsed.get("preferred_skills") or [])
    jd_langs = [
        LanguageProficiency(language=e["language"], level=LanguageLevel(e["level"]))
        for e in st.session_state.get("jd_lang_list", [])
    ]
    prefers = bool(st.session_state.get("jd_prefers_immediate", parsed.get("prefers_immediate", False)))
    return JdInfo(
        title=title, company=company, city=city,
        required_skills=req, preferred_skills=pref,
        required_languages=jd_langs,
        prefers_immediate=prefers,
        raw_text=raw or "",
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


def main():
    st.set_page_config(page_title="AI 求职助手", layout="wide")
    st.title("AI 求职助手")
    st.caption("单机版分析器：支持上传 PDF 简历 / 粘贴文本，查看薪资/能力/语言/到岗/前景/面试分析")

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
                        if prof.personality:
                            st.session_state["personality"] = prof.personality
                        if prof.city:
                            st.session_state["city"] = prof.city
                        if prof.expected_salary:
                            es = prof.expected_salary
                            st.session_state["exp_period_label"] = {
                                "annual": "年薪", "monthly": "月薪", "hourly": "时薪"
                            }.get(es.period.value, "年薪")
                            st.session_state["exp_value"] = es.value
                            st.session_state["exp_currency_label"] = {
                                "CNY": "¥ 人民币 (CNY)", "HKD": "HK$ 港币 (HKD)"
                            }.get(es.currency.value, "¥ 人民币 (CNY)")
                        st.success("已从 PDF 提取并填充字段，可手动调整。")
                except Exception as e:
                    st.error(f"PDF 解析失败：{e}")

        st.text_area("简历文本（粘贴）", key="resume", height=140)
        st.text_area(
            "理想工作（手动填写，不读简历）",
            key="ideal_job", height=70,
            placeholder="例：想要稳定、不追求高薪；或想赚得多愿意拼搏；或喜欢坐办公室/户外；"
                        "或需要常与人沟通；或一直对着电脑数据。",
        )
        st.text_input("掌握的技能", key="skills", placeholder="Python, MySQL, Redis")
        st.text_input("性格描述", key="personality", placeholder="外向/内向、细心、抗压、沟通好等")
        st.text_input("期望工作城市", key="city")

        # 预期薪资：左=计薪方式，中=纯数字金额，右=币种（手动填充；PDF 解析可自动带出）
        st.markdown("**预期薪资**")
        ecol1, ecol2, ecol3 = st.columns(3)
        period_label = ecol1.selectbox("计薪方式", PERIOD_LABELS, key="exp_period_label")
        ecol2.number_input(EXP_LABELS[period_label], key="exp_value", min_value=0.0, step=1.0)
        ecol3.selectbox("币种", CURRENCY_LABELS, key="exp_currency_label")

        # 语言（手动选择：语言 + 熟练度 3 档）
        st.markdown("**语言能力（手动选择，用于匹配 JD 语言要求）**")
        _lang_manager("lang_list", "")

        # 到岗时间（手动选择）
        st.markdown("**到岗时间（手动选择）**")
        st.selectbox(
            "到岗时间",
            ["未填写"] + AVAIL_OPTIONS,
            key="availability",
            label_visibility="collapsed",
        )

    with c2:
        st.header("职位描述 JD")
        st.text_input("岗位标题", key="jd_title")
        st.text_input("公司", key="jd_company")
        st.text_input("城市", key="jd_city")
        st.text_input("必需技能", key="jd_req", placeholder="Python, Go, MySQL")
        st.text_input("加分技能", key="jd_pref", placeholder="Docker, K8s")
        st.text_area(
            "JD 原文（粘贴）", key="jd_text", height=160, on_change=on_jd_text_change,
            placeholder="把招聘网页上的 JD 文本粘贴到这里（第三步将支持直接填 URL）",
        )

        # JD 语言要求（自动识别 + 手动增删）：JD 原文变化时由 on_jd_text_change 回调回填技能/语言/到岗
        st.markdown("**JD 语言要求（自动识别 + 可增删）**")
        _lang_manager("jd_lang_list", "")
        st.checkbox("JD 偏好「尽快到岗 / Immediate available」", key="jd_prefers_immediate")

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


if __name__ == "__main__":
    main()
