"""Workday 式技能编辑器组件。

- 自动补全建议来自 core.parsers 的双语技能词库（只读 import，不改 core）。
- 输入即联想（前缀命中优先于子串，大小写不敏感），点击建议即加入个人技能库；
  也可回车/按钮添加词库外自定义技能。
- 当前技能以标签（chip）展示，可逐个删除。
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


def skill_editor(user_id: int) -> None:
    """渲染技能编辑器（标签展示 + 输入联想 + 增删），直接读写技能库。"""
    existing = _refresh_skills(user_id)

    st.markdown("**已掌握技能（个人技能库）**")
    if existing:
        # 每行最多 4 个 chip（标签 + 删除按钮）
        rows = (len(existing) + 3) // 4
        idx = 0
        for _ in range(rows):
            cols = st.columns(4)
            for c in cols:
                if idx < len(existing):
                    s = existing[idx]
                    if c.button(f"✕ {s}", key=f"skill_rm_{idx}_{s}", help="点击删除"):
                        storage.remove_skill(user_id, s)
                        _refresh_skills(user_id)
                        st.rerun()
                    idx += 1
    else:
        st.caption("还没有技能，下面输入并添加吧。")

    st.text_input(
        "添加技能",
        key="skill_query",
        placeholder="如输入 detail 可联想 detail-oriented；也可直接输入自定义技能后添加",
    )
    q = (st.session_state.get("skill_query") or "").strip()
    sugs = suggest_skills(q, VOCAB, existing, limit=12)
    if sugs:
        st.caption("候选（点击添加）：")
        sug_cols = st.columns(min(len(sugs), 3))
        for i, s in enumerate(sugs):
            with sug_cols[i % 3]:
                if st.button(s, key=f"skill_add_{i}_{s}"):
                    _add_skill(user_id, s)
    # 自定义：输入了不在词库且非空的内容时，提供「添加自定义」入口
    if q and q not in existing:
        in_vocab = q in VOCAB
        label = f"添加为自定义技能：{q}" if not in_vocab else f"添加到技能库：{q}"
        if st.button(label, key="skill_add_custom"):
            _add_skill(user_id, q)


def _add_skill(user_id: int, skill: str) -> None:
    skill = skill.strip()
    if not skill:
        return
    is_custom = skill not in VOCAB
    storage.add_skill(user_id, skill, is_custom=is_custom)
    _refresh_skills(user_id)
    st.session_state["skill_query"] = ""
    st.rerun()
