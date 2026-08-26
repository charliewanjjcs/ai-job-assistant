"""面试高频问题与回答方向（LLM 驱动）。"""
from __future__ import annotations

import re
from typing import Optional

from .llm import DeepSeekClient
from .models import InterviewQA, JdInfo, UserProfile

INTERVIEW_SYSTEM = (
    "你是技术招聘专家，基于 JD 与候选人画像，"
    "预测该岗位面试高频问题，并给出来源合理的回答方向。"
)

# 两道「高频必问」问题：始终出现，回答方向由 LLM 基于 JD/公司/候选人生成。
# frequency 标记为「高频」；DEFAULT 仅作 LLM 不可用时的兜底。
HF_QUESTION_UNDERSTAND = "对岗位的理解（你如何看这个岗位的核心职责与价值？）"
HF_QUESTION_COMPANY = "对公司的认识（为什么想来这家公司？）"
_HF_DEFAULTS = {
    HF_QUESTION_UNDERSTAND: "结合 JD 的职责描述，说明你对该岗位目标的理解，并关联自身相关经验。",
    HF_QUESTION_COMPANY: "说明你对该公司业务、产品或文化的了解，以及个人职业规划与公司的契合点。",
}


def _build_prompt(profile: UserProfile, jd: JdInfo) -> str:
    return f"""岗位：{jd.title or '未知'} @ {jd.company or '未知'}
JD 摘要：{jd.raw_text[:1500]}
候选人技能：{', '.join(profile.skills) or '未知'}

请列出 6 个该岗位面试高频问题。每个问题严格按如下格式：
Q: <问题>
A: <回答方向，2-3 句>
F: <高频/中频/低频>
"""


def _build_hf_prompt(profile: UserProfile, jd: JdInfo) -> str:
    return f"""岗位：{jd.title or '未知'} @ {jd.company or '未知'}
JD 摘要：{jd.raw_text[:1500]}
候选人技能：{', '.join(profile.skills) or '未知'}

请针对以下两道面试必问问题，结合上述 JD 与候选人背景，给出个性化的「回答方向」（每题 2-3 句）：

问题一：{HF_QUESTION_UNDERSTAND}
问题二：{HF_QUESTION_COMPANY}

严格按如下格式返回（不要输出多余文字）：
A1: <问题一的回答方向>
A2: <问题二的回答方向>
"""


def _parse(text: str) -> list[InterviewQA]:
    qas: list[InterviewQA] = []
    blocks = re.findall(r"Q:\s*(.*?)\nA:\s*(.*?)\nF:\s*(\S+)", text, re.S)
    for q, a, f in blocks:
        qas.append(InterviewQA(question=q.strip(), direction=a.strip(), frequency=f.strip()))
    return qas


def _parse_hf(text: str) -> tuple[Optional[str], Optional[str]]:
    """从 LLM 输出解析两道高频问题方向；缺失返回 (None, None) 以走兜底。"""
    a1 = a2 = None
    m = re.search(r"A1:\s*(.*?)\s*A2:\s*(.*)", text, re.S)
    if m:
        a1, a2 = m.group(1).strip(), m.group(2).strip()
    else:
        m1 = re.search(r"A1:\s*(.*)", text, re.S)
        if m1:
            a1 = m1.group(1).strip()
    return a1, a2


class InterviewAnalyzer:
    def __init__(self, llm: DeepSeekClient):
        self.llm = llm

    def analyze(self, profile: UserProfile, jd: JdInfo) -> list[InterviewQA]:
        text = self.llm.complete(_build_prompt(profile, jd), system=INTERVIEW_SYSTEM, temperature=0.6)
        qas = _parse(text)
        qas.extend(self._high_frequency(profile, jd))
        return qas

    def _high_frequency(self, profile: UserProfile, jd: JdInfo) -> list[InterviewQA]:
        """两道高频必问：始终出现，回答方向优先由 LLM 生成，失败回退默认。"""
        try:
            out = self.llm.complete(
                _build_hf_prompt(profile, jd),
                system="你是资深面试官，基于岗位与候选人给出务实、个性化的回答方向。",
                temperature=0.5,
            )
            a1, a2 = _parse_hf(out)
        except Exception:
            a1 = a2 = None
        return [
            InterviewQA(
                question=HF_QUESTION_UNDERSTAND,
                direction=a1 or _HF_DEFAULTS[HF_QUESTION_UNDERSTAND],
                frequency="高频",
            ),
            InterviewQA(
                question=HF_QUESTION_COMPANY,
                direction=a2 or _HF_DEFAULTS[HF_QUESTION_COMPANY],
                frequency="高频",
            ),
        ]
