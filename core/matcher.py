"""技能/性格匹配 + 提升建议（规则版，可单测）。

Phase 1 用规则匹配；后续可把 PersonalityMatcher 升级为 LLM 驱动（接口不变）。
"""
from __future__ import annotations

from typing import List, Optional

from .models import (
    Availability,
    AvailabilityMatchResult,
    ImprovementSuggestion,
    JdInfo,
    LanguageLevel,
    LanguageMatchResult,
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
    skill_result: SkillMatchResult,
    profile: UserProfile,
    jd: JdInfo,
    language_result: "LanguageMatchResult | None" = None,
    availability_result: "AvailabilityMatchResult | None" = None,
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
    if language_result and language_result.missing:
        sugg.append(ImprovementSuggestion(
            area=f"补齐语言要求：{', '.join(language_result.missing)}",
            detail="JD 对以上语言有要求，建议补充对应语言能力证明（如证书/语言成绩）或说明实际运用经验。",
            priority="中",
        ))
    if availability_result and availability_result.fit == "不匹配":
        sugg.append(ImprovementSuggestion(
            area="到岗时间匹配",
            detail="JD 偏好尽快到岗，而你选择的到岗时间较晚，建议在沟通中明确可协调空间或强调其他优势。",
            priority="中",
        ))
    if not sugg:
        sugg.append(ImprovementSuggestion(
            area="保持优势",
            detail="当前技能与 JD 高度匹配，建议深化专长并准备可量化的项目故事。",
            priority="低",
        ))
    return sugg


class LanguageMatcher:
    _ORDER = {LanguageLevel.BASIC: 0, LanguageLevel.FLUENT: 1, LanguageLevel.NATIVE: 2}

    @classmethod
    def _level_ge(cls, have: LanguageLevel, need: LanguageLevel) -> bool:
        return cls._ORDER.get(have, 0) >= cls._ORDER.get(need, 0)

    @classmethod
    def match(cls, profile: UserProfile, jd: JdInfo) -> LanguageMatchResult:
        req = jd.required_languages or []
        if not req:
            return LanguageMatchResult(matched=[], missing=[], match_score=100.0,
                                       notes=["JD 未提出语言要求"])
        user_langs = {p.language.strip().lower(): p for p in (profile.languages or [])}
        matched: List[str] = []
        missing: List[str] = []
        for need in req:
            prof = user_langs.get(need.language.strip().lower())
            if prof and cls._level_ge(prof.level, need.level):
                matched.append(f"{need.language}({need.level.value})")
            else:
                missing.append(f"{need.language}(需{need.level.value})")
        score = round(len(matched) / len(req) * 100, 1)
        return LanguageMatchResult(
            matched=matched, missing=missing, match_score=score,
            notes=["语言匹配按「语言 + 熟练度」比对，熟练度需达到 JD 要求"] if missing else [],
        )


class AvailabilityMatcher:
    # JD 偏好尽快到岗时，用户到岗时间与匹配度的映射
    _FIT = {
        Availability.IMMEDIATE: ("完全匹配", "你选择「立刻」到岗，完全契合 JD 的尽快到岗偏好。"),
        Availability.WITHIN_WEEK: ("较匹配", "你选择「一周内」到岗，较契合 JD 的尽快到岗偏好。"),
        Availability.ONE_MONTH: ("基本匹配", "你选择「一个月」到岗，基本可接受，但略晚于 JD 偏好。"),
        Availability.TWO_MONTHS: ("略不匹配", "你选择「两个月」到岗，与 JD 尽快到岗偏好有差距。"),
        Availability.THREE_MONTHS: ("不匹配", "你选择「三个月」到岗，与 JD 尽快到岗偏好不匹配。"),
        Availability.LONGER: ("不匹配", "你选择「更长」到岗，与 JD 尽快到岗偏好不匹配。"),
    }

    @classmethod
    def match(cls, profile: UserProfile, jd: JdInfo) -> AvailabilityMatchResult:
        if not jd.prefers_immediate:
            return AvailabilityMatchResult(fit="无明确要求",
                                          note="JD 未明确要求到岗时间，此项不影响匹配。")
        av = profile.availability
        if av is None:
            return AvailabilityMatchResult(fit="未知",
                                          note="JD 偏好尽快到岗，但你未填写到岗时间，无法判定匹配。")
        fit, note = cls._FIT.get(av, ("未知", ""))
        return AvailabilityMatchResult(fit=fit, note=note)
