"""数据与状态层（供 main.py / pages 复用，并在 app.main 命名空间 re-export 以保测试）。

仅纯函数 + 选项常量 + DemoLLM；所有函数只读 st.session_state，便于单测
（tests/test_app_logic.py 通过 m.st.session_state = dict(...) monkeypatch）。
"""
from __future__ import annotations

import streamlit as st
import uuid

from core.parsers import parse_jd_text, parse_resume_text, split_skills
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

# ─────────────────────────────────────────────────────────────────────────────
# 选项常量（UI 与解析共用）
# ─────────────────────────────────────────────────────────────────────────────
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
