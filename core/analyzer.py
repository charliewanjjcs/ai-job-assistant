"""分析编排主入口：协调 salary / matcher / career / interview，产出 Report。

实现 `Analyzer` 接口。后续 Phase 的「肉」（PDF/URL/薪资API）都通过接口注入，不改这里。
"""
from __future__ import annotations

from datetime import datetime

from .career import CareerAnalyzer
from .interfaces import Analyzer
from .interview import InterviewAnalyzer
from .llm import DeepSeekClient
from .matcher import (
    AvailabilityMatcher,
    LanguageMatcher,
    PersonalityMatcher,
    SkillMatcher,
    build_improvements,
)
from .models import JdInfo, Report, UserProfile
from .salary import RuleBasedSalaryProvider, SalaryMatcher


class CoreAnalyzer(Analyzer):
    def __init__(self, llm: DeepSeekClient | None = None, salary_provider=None):
        self.llm = llm or DeepSeekClient()
        self.salary_provider = salary_provider or RuleBasedSalaryProvider()
        self.career = CareerAnalyzer(self.llm)
        self.interview = InterviewAnalyzer(self.llm)

    def analyze(self, profile: UserProfile, jd: JdInfo) -> Report:
        # 1) 薪资：市场区间（Provider） + 公司报价（Provider 解析） + 三方对比
        market = self.salary_provider.estimate_market_range(
            jd.title or profile.ideal_job or "", jd.city or profile.city
        )
        company_offer = self.salary_provider.get_company_offer(jd)
        salary_analysis = SalaryMatcher.analyze(profile.expected_salary, market, company_offer)

        # 2) 能力匹配 + 提升建议
        skill_match = SkillMatcher.match(profile, jd)
        personality_match = PersonalityMatcher.match(profile, jd)
        language_match = LanguageMatcher.match(profile, jd)
        availability_match = AvailabilityMatcher.match(profile, jd)
        improvements = build_improvements(
            skill_match, profile, jd, language_match, availability_match
        )

        # 3) 前景 / 日常工作（LLM）
        career = self.career.analyze(profile, jd)

        # 4) 面试高频问题（LLM）
        interview = self.interview.analyze(profile, jd)

        return Report(
            role=jd.title or profile.ideal_job,
            company=jd.company,
            salary_analysis=salary_analysis,
            skill_match=skill_match,
            language_match=language_match,
            availability_match=availability_match,
            personality_match=personality_match,
            improvement_suggestions=improvements,
            career_prospect=career,
            daily_work=career.daily,
            interview_qa=interview,
            generated_at=datetime.now().isoformat(timespec="seconds"),
        )
