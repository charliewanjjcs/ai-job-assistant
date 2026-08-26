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
import streamlit.components.v1 as components

import app.auth as auth
import app.storage as storage
from app.components.result_tabs import render_report

# 进入分析结果页时（由「开始分析」跳转带来标志）自动收起左侧控制栏，
# 用 JS 点击 Streamlit 侧栏的折叠按钮。多选择器 + 重试，兼容不同版本 DOM。
# 注意：1.61 里折叠按钮 testid 在外层包裹 div 上，真正的 <button> 在其内层，故第一个选择器用后代 button。
# 关键修复：该按钮是「展开/收起」切换键——侧栏已收起时它实为「展开」按钮，盲点会反把侧栏展开。
# 故先读侧栏 aria-expanded：仅当为 "true"（展开态）才点击折叠；已收起（"false"）则什么都不做，
# 保证无论点「开始分析」前侧栏是展开还是收起，跳转后都收起、绝不会误展开。
_COLLAPSE_SIDEBAR_JS = """
<script>
(function () {
  function collapse() {
    var d = window.parent.document;
    var side = d.querySelector('[data-testid="stSidebar"]');
    if (!side) return false;  // 侧栏元素尚未就绪，继续重试
    // 已收起（aria-expanded === "false"）：无需任何操作，直接结束轮询
    if (side.getAttribute('aria-expanded') === 'false') return true;
    // 仅展开态点击折叠按钮（命中即停轮询，避免重复点击导致二次切换）
    var sel = [
      '[data-testid="stSidebarCollapseButton"] button',
      '[data-testid="stSidebarCollapseButton"]',
      'button[aria-label*="Collapse"]'
    ];
    for (var i = 0; i < sel.length; i++) {
      var el = d.querySelector(sel[i]);
      if (el) { el.click(); return true; }
    }
    return false;
  }
  var t = 0;
  var id = setInterval(function () {
    if (collapse() || t++ > 30) { clearInterval(id); }
  }, 50);
})();
</script>
"""

# 历史记录表格各列固定宽度（单位：像素，由 column_config.TextColumn(width=...) 应用）。
# 注意：Streamlit 的 column_config width 是「像素」语义（"small"=75px, "medium"=200px, "large"=400px），
# 不是百分比——若总和 < 容器宽度，剩余空间会平均分给各列，导致整数差异被抹平。
# 故本表使用绝对像素值并让总和接近容器宽度，让职位/公司明显宽于技能匹配/分析时间。
HISTORY_COLUMN_WIDTHS = {
    "职位": 150,
    "公司": 150,
    "技能匹配": 75,
    "薪资结论": 95,
    "分析时间": 75,
}


# 分析结果页布局：历史记录（左）与分隔线向左移动，左右各留约 1/20（5%）空白，
# 使历史表格无需左右滚动看全，右侧详情占满剩余宽度。覆盖 main.py 的全局居中（max-width:75%）。
_RESULTS_CSS = """
<style>
.block-container {
  max-width: 90% !important;
  margin-left: 5% !important;
  margin-right: 5% !important;
}
</style>
"""


def render() -> None:
    if not auth.is_logged_in():
        st.info("请先在左侧登录 / 注册后查看分析结果。")
        return

    uid = auth.current_user_id()
    st.title("分析结果")
    st.caption("选择左侧记录查看完整分析；结果会持久化保存，可随时回看。")
    st.markdown(_RESULTS_CSS, unsafe_allow_html=True)

    # 「开始分析」跳转带标志而来：进入即自动收起左侧控制栏
    if st.session_state.get("_collapse_sidebar"):
        st.session_state["_collapse_sidebar"] = False
        components.html(_COLLAPSE_SIDEBAR_JS, height=0)

    rows = storage.list_analysis_results(uid)
    if not rows:
        st.info("还没有分析结果。去「职位详情/JD」页粘贴 JD 开始第一次分析吧。")
        return

    ids = [r["id"] for r in rows]  # 与表格行顺序一一对应（位置索引映射）

    # 「职位详情/JD」页跳转带来的“刚分析记录”默认选中（读后即清，避免覆盖用户后续手选）
    pending = st.session_state.pop("_pending_result_id", None)
    if pending in ids:
        st.session_state["history_df"] = {"selection": {"rows": [ids.index(pending)]}}

    # 历史记录（左）:详情（右）= 5:5，使左侧历史表格无需左右滚动看全，右侧详情向右扩展
    col_left, col_div, col_right = st.columns([5, 0.1, 5])

    # 中缝分隔线，使左右两栏分隔明显
    with col_div:
        st.markdown(
            '<div style="height: 600px; border-left: 1px solid #b9c4ab; margin: 0 auto;"></div>',
            unsafe_allow_html=True,
        )

    with col_left:
        st.subheader("历史记录")
        table = [
            {
                "职位": r["role"] or "未命名岗位",
                "公司": r["company"] or "—",
                "技能匹配": (f"{r['skill_score']:.0f}分" if r["skill_score"] is not None else "—"),
                "薪资结论": r["salary_verdict"] or "—",
                "分析时间": r["generated_at"] or r["created_at"] or "—",
            }
            for r in rows
        ]
        # 固定各列宽度占比 + 单元格文字水平居中；点击某一行即切换详情（原生单行选择）。
        column_config = {
            name: st.column_config.TextColumn(name, width=w, alignment="center")
            for name, w in HISTORY_COLUMN_WIDTHS.items()
        }
        event = st.dataframe(
            table,
            key="history_df",
            on_select="rerun",
            selection_mode="single-row-required",
            hide_index=True,
            use_container_width=True,
            column_config=column_config,
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
            # 大标题：岗位名称（上一行）→ 公司名称（下一行），中间换行而非「@」
            st.markdown(f"#### {report.role or '未命名岗位'}")
            st.markdown(f"##### {report.company or '—'}")
            st.caption(f"分析时间：{report.generated_at or row['created_at']}")
            render_report(report)
            st.divider()
