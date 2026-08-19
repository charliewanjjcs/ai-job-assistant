"""分析结果页（决策：左侧控制栏「分析结果」入口，位于「职位分析」下方）。

左：历史列表（dataframe 单行选中即切换）；右：完整报告（复用 render_report）+ JD 原文回显。
支持单条删除、二次确认的一键清空。
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
from app.components.result_tabs import render_report


def render() -> None:
    if not auth.is_logged_in():
        st.info("请先在左侧登录 / 注册后查看分析结果。")
        return

    uid = auth.current_user_id()
    st.title("分析结果")
    st.caption("选择左侧记录查看完整分析；结果会持久化保存，可随时回看。")

    rows = storage.list_analysis_results(uid)
    if not rows:
        st.info("还没有分析结果。去「职位分析」页粘贴 JD 开始第一次分析吧。")
        return

    ids = [r["id"] for r in rows]  # 与 dataframe 行顺序一一对应（位置索引映射）

    # 「职位分析」跳转带来的“刚分析记录”默认选中（读后即清，避免覆盖用户后续手选）
    pending = st.session_state.pop("_pending_result_id", None)
    if pending in ids:
        st.session_state["history_df"] = {"selection": {"rows": [ids.index(pending)]}}

    col_left, col_right = st.columns([2, 3])

    with col_left:
        st.subheader("历史记录")
        table = [
            {
                "职位": r["role"] or "未命名岗位",
                "公司": r["company"] or "—",
                "分析时间": r["generated_at"] or r["created_at"] or "—",
                "技能匹配": (f"{r['skill_score']:.0f}分" if r["skill_score"] is not None else "—"),
                "薪资结论": r["salary_verdict"] or "—",
            }
            for r in rows
        ]
        event = st.dataframe(
            table,
            key="history_df",
            on_select="rerun",
            selection_mode="single-row-required",
            hide_index=True,
            use_container_width=True,
        )
        sel_rows = list(event.selection.rows) if event and event.selection.rows else []
        selected_id = ids[sel_rows[0]] if sel_rows else ids[0]

        st.caption(f"共 {len(rows)} 条记录")
        d1, d2 = st.columns(2)
        if d1.button("删除选中", use_container_width=True):
            storage.delete_analysis_result(uid, selected_id)
            st.session_state.pop("history_df", None)
            st.rerun()
        if d2.button("清空全部", use_container_width=True):
            st.session_state["_confirm_clear"] = True
        if st.session_state.get("_confirm_clear"):
            st.warning("将删除该用户全部分析结果，此操作不可撤销。")
            c1, c2 = st.columns(2)
            if c1.button("确认清空", type="primary", use_container_width=True):
                storage.clear_analysis_results(uid)
                st.session_state.pop("_confirm_clear", None)
                st.session_state.pop("history_df", None)
                st.rerun()
            if c2.button("取消", use_container_width=True):
                st.session_state.pop("_confirm_clear", None)
                st.rerun()

    with col_right:
        row = storage.get_analysis_result(uid, selected_id)
        if not row:
            st.info("未找到该记录，可能已被删除。")
        else:
            report = storage.deserialize_report(row["report_json"])
            st.markdown(f"#### {report.role or '未命名岗位'} @ {report.company or '—'}")
            st.caption(f"分析时间：{report.generated_at or row['created_at']}")
            render_report(report)
            st.divider()
            st.markdown("**当时粘贴的 JD 原文**")
            st.code(row["jd_text"] or "（无 JD 原文）", language=None)
