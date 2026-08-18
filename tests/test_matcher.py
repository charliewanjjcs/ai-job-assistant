"""能力匹配 TDD：技能命中/缺失/评分 + 提升建议生成。

覆盖：完全匹配、部分匹配评分、无要求即满分、建议生成、性格维度。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import (
    Availability,
    JdInfo,
    LanguageLevel,
    LanguageProficiency,
    UserProfile,
)
from core.matcher import (
    AvailabilityMatcher,
    LanguageMatcher,
    PersonalityMatcher,
    SkillMatcher,
    build_improvements,
)


def _profile(skills):
    return UserProfile(skills=skills, personality="细心、抗压")


def _jd(req, pref=None):
    return JdInfo(title="后端", required_skills=req, preferred_skills=pref or [])


def test_full_match():
    p = _profile(["python", "mysql", "redis", "docker"])
    jd = _jd(["Python", "MySQL"], ["Docker"])
    r = SkillMatcher.match(p, jd)
    assert r.match_score == 100.0
    assert r.missing_required == []
    assert r.missing_preferred == []


def test_partial_match_score():
    p = _profile(["python"])
    jd = _jd(["Python", "Go", "MySQL"], ["Docker", "K8s"])
    r = SkillMatcher.match(p, jd)
    # required 命中 1/3 -> 23.3 分；preferred 0/2 -> 0
    assert r.match_score < 30
    assert "Go" in r.missing_required
    assert "MySQL" in r.missing_required


def test_no_required_jd():
    p = _profile(["python"])
    jd = _jd([], [])
    r = SkillMatcher.match(p, jd)
    assert r.match_score == 100.0


def test_improvements_generated():
    p = _profile(["python"])
    jd = _jd(["Python", "Go"], [])
    r = SkillMatcher.match(p, jd)
    sugg = build_improvements(r, p, jd)
    assert any("Go" in s.area for s in sugg)
    assert any(s.priority == "高" for s in sugg)


def test_personality_match():
    r = PersonalityMatcher.match(_profile(["x"]), _jd(["x"]))
    assert r.score >= 0
    assert len(r.dimensions) > 0


def test_language_match():
    p = UserProfile(
        languages=[LanguageProficiency(language="英语", level=LanguageLevel.FLUENT)],
    )
    # JD 要求英语流利 -> 匹配
    jd = JdInfo(required_languages=[LanguageProficiency(language="英语", level=LanguageLevel.FLUENT)])
    r = LanguageMatcher.match(p, jd)
    assert r.match_score == 100.0
    assert r.missing == []
    # JD 要求英语母语，用户仅流利 -> 缺失
    jd2 = JdInfo(required_languages=[LanguageProficiency(language="英语", level=LanguageLevel.NATIVE)])
    r2 = LanguageMatcher.match(p, jd2)
    assert r2.missing != []
    assert r2.match_score < 100.0


def test_language_match_no_requirement():
    p = UserProfile(languages=[LanguageProficiency(language="英语", level=LanguageLevel.BASIC)])
    jd = JdInfo()
    r = LanguageMatcher.match(p, jd)
    assert r.match_score == 100.0


def test_availability_match():
    # JD 偏好尽快到岗，用户「立刻」-> 完全匹配
    jd = JdInfo(prefers_immediate=True)
    r = AvailabilityMatcher.match(
        UserProfile(availability=Availability.IMMEDIATE), jd)
    assert r.fit == "完全匹配"
    # 用户「三个月」-> 不匹配
    r2 = AvailabilityMatcher.match(
        UserProfile(availability=Availability.THREE_MONTHS), jd)
    assert r2.fit == "不匹配"
    # JD 无要求 -> 无明确要求
    r3 = AvailabilityMatcher.match(
        UserProfile(availability=Availability.IMMEDIATE), JdInfo(prefers_immediate=False))
    assert r3.fit == "无明确要求"

