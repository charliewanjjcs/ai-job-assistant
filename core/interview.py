"""面试高频问题与回答方向（LLM 驱动）。"""
from __future__ import annotations

import re

from .llm import DeepSeekClient
from .models import InterviewQA, JdInfo, UserProfile

INTERVIEW_SYSTEM = (
    "你是技术招聘专家，基于 JD 与候选人画像，"
    "预测该岗位面试高频问题，并给出来源合理的回答方向。"
)


def _build_prompt(profile: UserProfile, jd: JdInfo) -> str:
    return f"""岗位：{jd.title or '未知'} @ {jd.company or '未知'}
JD 摘要：{jd.raw_text[:1500]}
候选人技能：{', '.join(profile.skills) or '未知'}
候选人与岗位差距：{', '.join(profile.skills) and '待具体分析'}

请列出 6 个该岗位面试高频问题。每个问题严格按如下格式：
Q: <问题>
A: <回答方向，2-3 句>
F: <高频/中频/低频>
"""


def _parse(text: str) -> list[InterviewQA]:
    qas: list[InterviewQA] = []
    blocks = re.findall(r"Q:\s*(.*?)\nA:\s*(.*?)\nF:\s*(\S+)", text, re.S)
    for q, a, f in blocks:
        qas.append(InterviewQA(question=q.strip(), direction=a.strip(), frequency=f.strip()))
    return qas


class InterviewAnalyzer:
    def __init__(self, llm: DeepSeekClient):
        self.llm = llm

    def analyze(self, profile: UserProfile, jd: JdInfo) -> list[InterviewQA]:
        text = self.llm.complete(_build_prompt(profile, jd), system=INTERVIEW_SYSTEM, temperature=0.6)
        return _parse(text)
