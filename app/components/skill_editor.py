"""Workday 式技能编辑器组件。

- 自动补全建议来自 core.parsers 的双语技能词库（只读 import，不改 core）。
- 输入即联想（前缀命中优先于子串，大小写不敏感），点击建议即加入个人技能库；
  也可回车/按钮添加词库外自定义技能。
- 当前技能以标签（chip）展示，流式换行、只占左侧 3/4 宽度，可逐个删除。
- 始终同步 session_state["skills"]（CSV 串），供 build_profile / 职位分析复用。
"""
from __future__ import annotations

import streamlit as st

import app.storage as storage
from core.parsers import SKILL_VOCAB, SOFT_SKILL_VOCAB

# 合并词库并去重（大小写不敏感），保持出现顺序
_SEEN = set()
VOCAB: list[str] = []
for _s in SKILL_VOCAB + SOFT_SKILL_VOCAB:
    _k = _s.lower()
    if _k not in _SEEN:
        _SEEN.add(_k)
        VOCAB.append(_s)


def suggest_skills(query: str, vocab: list[str], existing: list[str],
                   limit: int = 12) -> list[str]:
    """根据输入联想技能。

    - 前缀命中（startswith）排在子串命中之前；
    - 大小写不敏感；
    - 排除已添加项；
    - 结果去重、保序、截断到 limit。
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    excl = {e.lower() for e in existing}
    prefix: list[str] = []
    sub: list[str] = []
    for s in vocab:
        ns = s.lower()
        if ns in excl:
            continue
        if ns.startswith(q):
            prefix.append(s)
        elif q in ns:
            sub.append(s)
    return (prefix + sub)[:limit]


def _refresh_skills(user_id: int) -> list[str]:
    skills = storage.list_skills(user_id)
    st.session_state["skills"] = ", ".join(skills)
    return skills


def _add_skill(user_id: int, skill: str) -> None:
    """on_click 回调：添加技能并清空输入框（在 rerun 前执行，安全）。"""
    skill = skill.strip()
    if not skill:
        return
    is_custom = skill not in VOCAB
    storage.add_skill(user_id, skill, is_custom=is_custom)
    _refresh_skills(user_id)
    st.session_state["skill_query"] = ""


def _remove_skill(user_id: int, skill: str) -> None:
    """on_click 回调：删除技能。"""
    storage.remove_skill(user_id, skill)
    _refresh_skills(user_id)


def skill_editor(user_id: int) -> None:
    """渲染技能编辑器（标签展示 + 输入联想 + 增删），直接读写技能库。"""
    # 渲染优先用 session_state["skills"] 缓存（个人资料页进入时已用 list_skills 载入），
    # 避免在每次页面重渲染（文本框输入/回车都会触发 rerun）时重复跨 Neon 读库——
    # 未上线连接池时，每次读库都新建一条到新加坡的 TLS 连接，导致逐栏编辑卡 ~3 秒。
    # 仅增删技能（_add_skill/_remove_skill 内部）才回源 DB 刷新缓存。
    if "skills" in st.session_state:
        existing = [
            s.strip() for s in st.session_state["skills"].split(",") if s.strip()
        ]
    else:
        existing = _refresh_skills(user_id)

    if existing:
        # 流式 chip 布局：只占可用区 3/4，右侧 1/4 留空，放不下自动换行
        # （侧栏展开/收起由 columns 自适应：占「当前主区」的 3/4）
        left, _right = st.columns([3, 1])
        with left:
            with st.container(horizontal=True, gap="xsmall"):
                for i, s in enumerate(existing):
                    st.button(
                        f"✕ {s}", key=f"skill_rm_{i}_{s}",
                        on_click=_remove_skill, args=(user_id, s),
                    )
    else:
        st.caption("还没有技能，下面输入并添加吧。")

    # 添加技能输入框与上下其他输入框（理想工作/性格描述/期望城市等）同宽：左半宽 [1,1]，
    # 不使用整列铺满，左对齐、右侧留空，视觉上与相邻的文本输入框长度一致。
    _add_wrap, _ = st.columns([1, 1])
    with _add_wrap:
        st.text_input(
            "添加技能",
            key="skill_query",
            placeholder="输入技能名，回车或点下方添加",
        )
    q = (st.session_state.get("skill_query") or "").strip()
    sugs = suggest_skills(q, VOCAB, existing, limit=12)
    if sugs:
        st.caption("候选（点击添加）：")
        left, _right = st.columns([3, 1])
        with left:
            with st.container(horizontal=True, gap="xsmall"):
                for i, s in enumerate(sugs):
                    st.button(
                        s, key=f"skill_add_{i}_{s}",
                        on_click=_add_skill, args=(user_id, s),
                    )
    # 自定义：输入了不在词库且非空的内容时，提供「添加自定义」入口
    if q and q not in existing:
        in_vocab = q in VOCAB
        label = f"添加为自定义技能：{q}" if not in_vocab else f"添加到技能库：{q}"
        st.button(label, key="skill_add_custom", on_click=_add_skill, args=(user_id, q))
