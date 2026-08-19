"""语言 + 熟练度 管理器组件（从 main.py 抽出，独立复用）。"""
from __future__ import annotations

import uuid

import streamlit as st

from app.state import LANG_OPTIONS, LEVEL_OPTIONS


def _idx(options, value):
    try:
        return options.index(value)
    except ValueError:
        return 0


def lang_manager(state_key: str, header: str = ""):
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
