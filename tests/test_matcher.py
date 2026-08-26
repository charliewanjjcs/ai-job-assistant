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
    # 无 LLM 时回退占位逻辑（score=60，3 个维度）
    r = PersonalityMatcher().match(_profile(["x"]), _jd(["x"]))
    assert r.score == 60.0
    assert len(r.dimensions) == 3


def test_personality_match_llm():
    """有 LLM 时走 LLM 路径，返回结构化 PersonalityMatchResult。"""
    class _FakeLLM:
        def available(self):
            return True

        def complete(self, prompt, system="", temperature=0.7, max_tokens=1500):
            return (
                '{"score": 82, "summary": "外向且求稳，与该岗位高度契合", '
                '"dimensions": [{"name": "沟通协作", "fit": "高", '
                '"note": "外向型适合频繁沟通"}, {"name": "稳定性", "fit": "高", '
                '"note": "求稳与该岗位稳定性质匹配"}]}'
            )

    r = PersonalityMatcher(llm=_FakeLLM()).match(
        UserProfile(personality="外向、善于沟通", ideal_job="稳定朝九晚五"),
        JdInfo(title="HR Officer", raw_text="需频繁与候选人沟通，团队稳定"),
    )
    assert r.score == 82
    assert "外向" in r.summary
    names = [d.name for d in r.dimensions]
    assert "沟通协作" in names
    assert "稳定性" in names
    assert r.dimensions[0].fit == "高"


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


def test_ms_office_covers_excel():
    # JD 要求 Excel，用户写 MS Office（上下位）应判匹配，而非缺失
    p = _profile(["MS Office", "Python"])
    jd = _jd(["Excel"], [])
    r = SkillMatcher.match(p, jd)
    assert r.missing_required == []
    assert r.match_score == 100.0


def test_excel_does_not_falsely_cover_msoffice_as_missing():
    # 反向：JD 要求 MS Office，用户仅 Excel —— 仍按同族判匹配（宽松，可接受）
    p = _profile(["Excel"])
    jd = _jd(["MS Office"], [])
    r = SkillMatcher.match(p, jd)
    assert r.missing_required == []


def test_analytical_synonym_match():
    # JD 要求 analytical and problem-solving skills，用户写 problem solving 应匹配
    p = _profile(["problem solving", "Python"])
    jd = _jd(["analytical and problem-solving skills"], [])
    r = SkillMatcher.match(p, jd)
    assert r.missing_required == []


def test_attention_to_detail_synonym():
    # JD 要求 attention to detail，用户写 detail-oriented 应匹配
    p = _profile(["detail-oriented", "Excel"])
    jd = _jd(["attention to detail"], [])
    r = SkillMatcher.match(p, jd)
    assert r.missing_required == []


def test_plain_skill_still_extracted_and_matched():
    # 软技能 analytical and problem-solving skills 应能被 extract_skills 识别
    from core.parsers import extract_skills
    found = extract_skills("具备 analytical and problem-solving skills 与 attention to detail")
    assert "analytical and problem-solving skills" in found
    assert "attention to detail" in found


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


def test_improvement_preferred_label_is_soft_skill():
    """缺失的加分项应归类为「软技能/特质」提升建议，而非「加分项」。"""
    p = _profile(["python"])
    jd = _jd(["Python"], ["沟通能力"])
    r = SkillMatcher.match(p, jd)
    sugg = build_improvements(r, p, jd)
    soft = [s for s in sugg if s.area.startswith("强化软技能/特质")]
    assert soft, "应生成软技能/特质提升建议"
    assert "沟通能力" in soft[0].area
    assert not any(s.area.startswith("强化加分项") for s in sugg)


