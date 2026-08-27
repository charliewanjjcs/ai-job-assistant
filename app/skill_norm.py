"""技能「去重键」规范化（用于「添加技能」的候选去重与已添加去重）。

与 core 的匹配判定相互独立：core 用 SKILL_SYNONYMS 把「同义/上下位」技能判为匹配
（如 detail-oriented ≈ attention to detail），本模块只做「字面近重复」的归一化，
规则更保守：

- 小写、去除空格/连字符等非「字母数字/汉字」字符（同 core.parsers.normalize_skill）；
- 去掉末尾「复数 s」（details→detail、skills→skill），使：
    * 'detail-oriented' 与 'detail oriented' 视为同一技能（连字符差异）；
    * 'attention to detail' 与 'attention to details' 视为同一技能（复数 s 差异）；
- **不**合并语义不同的技能（'detail-oriented' 与 'attention to detail' 仍是两个）。

用途：添加技能候选去重 / 已添加去重，避免「多一个 s 或 - 的相似重复」；
不影响 core 的匹配判定（匹配另有 SKILL_SYNONYMS 负责同义/上下位）。
"""
from __future__ import annotations

import re


def skill_dedupe_key(skill: str) -> str:
    """返回技能的去重键；仅用于「判断是否字面近重复」，不用于语义匹配。"""
    base = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (skill or "").strip().lower())
    # 去末尾复数 s：仅当去掉后仍是「合理长度 + 倒数第二位是字母」时，
    # 避免误伤 aws/css/js 这类短缩写（长度 ≤3 不触发）；kubernetes 等虽会被
    # 误削末尾 s，但其去重键不会与任何其它词条碰撞，故无害。
    if base.endswith("s") and len(base) > 3 and base[-2].isalpha():
        base = base[:-1]
    return base
