"""个人资料页（决策：左侧控制栏「个人资料」入口）。

进入时把已保存资料从 DB 载入 session_state（带守卫，避免覆盖未保存编辑），
技能用 Workday 式编辑器管理（存于个人技能库）；保存时把表单字段写回 DB。
"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st

import app.auth as auth
import app.storage as storage
from app.components.lang_manager import lang_manager
from app.components.skill_editor import skill_editor
from app.state import AVAIL_OPTIONS, CURRENCY_LABELS, EXP_LABELS, PERIOD_LABELS
from core.parsers import SKILL_VOCAB, SOFT_SKILL_VOCAB
from modules.resume_pdf.pdf_parser import PdfResumeParser

_VOCAB_SET = {s.lower() for s in SKILL_VOCAB + SOFT_SKILL_VOCAB}


def _load_profile_to_session(uid: int) -> None:
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


def _save_profile(uid: int) -> None:
    storage.save_profile(uid, {
        "resume": st.session_state.get("resume", ""),
        "ideal_job": st.session_state.get("ideal_job", ""),
        "personality": st.session_state.get("personality", ""),
        "city": st.session_state.get("city", ""),
        "exp_period_label": st.session_state.get("exp_period_label", "年薪"),
        "exp_currency_label": st.session_state.get("exp_currency_label", "¥ 人民币 (CNY)"),
        "exp_value": st.session_state.get("exp_value", 0.0),
        "lang_list": st.session_state.get("lang_list", []),
        "availability": st.session_state.get("availability", "未填写"),
    })
    # 技能由 skill_editor 实时持久化；这里再同步一次 session_state["skills"]
    st.session_state["skills"] = ", ".join(storage.list_skills(uid))


def render() -> None:
    if not auth.is_logged_in():
        st.info("请先在左侧登录 / 注册后再编辑个人资料。")
        return

    uid = auth.current_user_id()
    st.title("个人资料")
    st.caption("编辑并保存你的简历 / 资料，下次登录自动载入，无需重复填写。")

    # 加载守卫：仅当用户切换时从 DB 覆盖一次，避免覆盖当前未保存编辑
    if st.session_state.get("_profile_loaded_uid") != uid:
        _load_profile_to_session(uid)
        st.session_state["_profile_loaded_uid"] = uid

    # 上传 PDF 简历，自动抽取并填充字段（手动字段仍优先、可改）
    uploaded = st.file_uploader("上传简历 PDF（可选，自动填充下方字段）", type=["pdf"])
    if uploaded is not None:
        sig = f"{uploaded.name}:{uploaded.size}"
        if st.session_state.get("_pdf_last") != sig:  # 仅处理新上传，避免覆盖手动编辑
            st.session_state["_pdf_last"] = sig
            # 写到系统临时目录（唯一文件名），避免同名覆盖被占用锁定 / 项目目录权限问题
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
            try:
                with os.fdopen(tmp_fd, "wb") as f:
                    f.write(uploaded.getbuffer())
                parser = PdfResumeParser()
                text = parser.extract_text(tmp_path)
                if not text:
                    st.warning("该 PDF 无文字层（可能是扫描件），请改用下方文本粘贴。")
                else:
                    prof = parser.parse(tmp_path)
                    if prof.raw_resume:
                        st.session_state["resume"] = prof.raw_resume
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
                    # 解析出的技能直接写入个人技能库
                    for s in prof.skills:
                        storage.add_skill(uid, s, is_custom=(s.lower() not in _VOCAB_SET))
                    st.success("已从 PDF 提取并填充字段，可手动调整。")
            except Exception as e:
                st.error(f"PDF 解析失败：{e}")
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    st.text_area("简历文本（粘贴）", key="resume", height=140)
    st.text_area(
        "理想工作",
        key="ideal_job", height=70,
        placeholder="例：想要稳定、不追求高薪；或想赚得多愿意拼搏；或喜欢坐办公室/户外；"
                    "或需要常与人沟通；或一直对着电脑数据。",
    )

    st.markdown("**掌握的技能（个人技能库）**")
    st.caption("输入即联想（如 detail → detail-oriented），点击或回车加入；也可添加词库外自定义技能。")
    skill_editor(uid)

    st.text_input("性格描述", key="personality", placeholder="外向/内向、细心、抗压、沟通好等")
    st.text_input("期望工作城市", key="city")

    # 预期薪资：左=计薪方式，中=纯数字金额，右=币种
    st.markdown("**预期薪资**")
    ecol1, ecol2, ecol3 = st.columns(3)
    period_label = ecol1.selectbox("计薪方式", PERIOD_LABELS, key="exp_period_label")
    ecol2.number_input(EXP_LABELS[period_label], key="exp_value", min_value=0.0, step=1.0)
    ecol3.selectbox("币种", CURRENCY_LABELS, key="exp_currency_label")

    # 语言（语言 + 3 档熟练度）
    st.markdown("**语言能力（手动选择，用于匹配 JD 语言要求）**")
    lang_manager("lang_list", "")

    # 到岗时间（手动选择）
    st.markdown("**到岗时间（手动选择）**")
    st.selectbox(
        "到岗时间",
        ["未填写"] + AVAIL_OPTIONS,
        key="availability",
        label_visibility="collapsed",
    )

    c1, c2 = st.columns([1, 2])
    if c1.button("保存资料", type="primary", use_container_width=True):
        _save_profile(uid)
        st.success("资料已保存到本机。")
    if c2.button("重新载入已保存资料", use_container_width=True):
        st.session_state.pop("_profile_loaded_uid", None)
        _load_profile_to_session(uid)
        st.session_state["_profile_loaded_uid"] = uid
        st.rerun()
