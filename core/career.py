"""岗位前景 / 日常工作（LLM 驱动）。"""
from __future__ import annotations

import re

from .llm import DeepSeekClient
from .models import CareerProspect, JdInfo, UserProfile

CAREER_SYSTEM = (
    "你是一名资深职业规划师，基于岗位 JD 与候选人画像，"
    "给出客观、具体、可操作的职业发展分析，避免空话。"
)


def _build_prompt(profile: UserProfile, jd: JdInfo) -> str:
    return f"""岗位：{jd.title or '未知'} @ {jd.company or '未知'}
工作城市：{jd.city or profile.city or '未知'}
JD 摘要：{jd.raw_text[:1500]}
候选人技能：{', '.join(profile.skills) or '未知'}

请分别用 2-4 句话回答以下四部分（严格用标题分隔，不要遗漏）：
## 晋升机会
## 加薪机会
## 跳槽机会
## 日常工作
"""


def _parse(text: str) -> CareerProspect:
    def sec(name: str) -> str:
        m = re.search(rf"##\s*{name}\s*(.*?)(?=##|$)", text, re.S)
        return m.group(1).strip() if m else ""
    return CareerProspect(
        promotion=sec("晋升机会"),
        raise_outlook=sec("加薪机会"),
        jump_outlook=sec("跳槽机会"),
        daily=sec("日常工作"),
        overall=text.strip(),
    )


class CareerAnalyzer:
    def __init__(self, llm: DeepSeekClient):
        self.llm = llm

    def analyze(self, profile: UserProfile, jd: JdInfo) -> CareerProspect:
        text = self.llm.complete(_build_prompt(profile, jd), system=CAREER_SYSTEM, temperature=0.6)
        return _parse(text)
