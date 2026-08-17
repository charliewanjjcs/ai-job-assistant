"""技能/性格匹配 + 提升建议（规则版，可单测）。

Phase 1 用规则匹配；后续可把 PersonalityMatcher 升级为 LLM 驱动（接口不变）。
"""
from __future__ import annotations

from typing import List, Optional

from .models import (
    ImprovementSuggestion,
    JdInfo,
    PersonalityDimension,
    PersonalityMatchResult,
    SkillMatchItem,
    SkillMatchResult,
    UserProfile,
)


class SkillMatcher:
    @staticmethod
    def match(profile: UserProfile, jd: JdInfo) -> SkillMatchResult:
        user_skills = [s.strip().lower() for s in (profile.skills or [])]

        def hits(skill: str) -> bool:
            s = skill.strip().lower()
            return any(s in u or u in s for u in user_skills)

        matched: List[str] = []
        missing_required: List[str] = []
        missing_preferred: List[str] = []
        items: List[SkillMatchItem] = []

        for s in jd.required_skills:
            if hits(s):
                matched.append(s)
                items.append(SkillMatchItem(skill=s, status="matched"))
            else:
                missing_required.append(s)
                items.append(SkillMatchItem(skill=s, status="missing_required", note="JD 要求但简历未体现"))

        for s in jd.preferred_skills:
            if hits(s):
                matched.append(s)
                items.append(SkillMatchItem(skill=s, status="matched"))
            else:
                missing_preferred.append(s)
                items.append(SkillMatchItem(skill=s, status="missing_preferred", note="加分项，非必须"))

        # 评分：required 占 70%，preferred 占 30%
        req_score = (len(jd.required_skills) - len(missing_required)) / len(jd.required_skills) * 70 if jd.required_skills else 70
        pref_score = (len(jd.preferred_skills) - len(missing_preferred)) / len(jd.preferred_skills) * 30 if jd.preferred_skills else 30
        score = round(req_score + pref_score, 1)

        return SkillMatchResult(
            matched=matched,
            missing_required=missing_required,
            missing_preferred=missing_preferred,
            match_score=score,
            items=items,
        )


class PersonalityMatcher:
    @staticmethod
    def match(profile: UserProfile, jd: JdInfo) -> PersonalityMatchResult:
        # MVP：通用维度初步匹配；详细匹配建议后续用 LLM 增强（接口不变）。
        dims = [
            PersonalityDimension(name="沟通协作", fit="中", note="建议结合简历项目经历判断"),
            PersonalityDimension(name="抗压能力", fit="中", note="可由面试表现验证"),
            PersonalityDimension(name="学习意愿", fit="中", note="可由技能广度推断"),
        ]
        return PersonalityMatchResult(
            summary="基于通用维度初步匹配，详细匹配建议结合 LLM 与面试表现综合判断。",
            dimensions=dims,
            score=60.0,
        )


def build_improvements(
    skill_result: SkillMatchResult, profile: UserProfile, jd: JdInfo
) -> List[ImprovementSuggestion]:
    sugg: List[ImprovementSuggestion] = []
    for s in skill_result.missing_required:
        sugg.append(ImprovementSuggestion(
            area=f"补齐硬技能：{s}",
            detail=f"JD 明确要求 {s}，建议系统学习并在项目中实践以补齐短板。",
            priority="高",
        ))
    for s in skill_result.missing_preferred:
        sugg.append(ImprovementSuggestion(
            area=f"强化加分项：{s}",
            detail=f"{s} 为加分项，掌握后可提升竞争力。",
            priority="中",
        ))
    if not sugg:
        sugg.append(ImprovementSuggestion(
            area="保持优势",
            detail="当前技能与 JD 高度匹配，建议深化专长并准备可量化的项目故事。",
            priority="低",
        ))
    return sugg
