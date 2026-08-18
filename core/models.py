"""数据模型：用户输入画像、JD、分析报告。

金额约定：所有对外展示前的内部计算统一归一化为「年化 CNY 元」，
由 `to_annual_cny()` 负责换算（月薪×12、美元×汇率、港币×汇率、时薪×年工时等）。
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Currency(str, Enum):
    CNY = "CNY"
    HKD = "HKD"
    USD = "USD"
    UNKNOWN = "UNKNOWN"


class PayPeriod(str, Enum):
    ANNUAL = "annual"
    MONTHLY = "monthly"
    MONTHLY_13 = "monthly_13"
    MONTHLY_14 = "monthly_14"
    HOURLY = "hourly"
    UNKNOWN = "unknown"


class LanguageLevel(str, Enum):
    BASIC = "基础"
    FLUENT = "熟练"
    NATIVE = "母语"


class Availability(str, Enum):
    IMMEDIATE = "立刻"
    WITHIN_WEEK = "一周内"
    ONE_MONTH = "一个月"
    TWO_MONTHS = "两个月"
    THREE_MONTHS = "三个月"
    LONGER = "更长"


class SalaryAmount(BaseModel):
    value: float
    currency: Currency = Currency.CNY
    period: PayPeriod = PayPeriod.ANNUAL
    raw: Optional[str] = None


class LanguageProficiency(BaseModel):
    language: str
    level: LanguageLevel = LanguageLevel.BASIC


class UserProfile(BaseModel):
    name: Optional[str] = None
    ideal_job: Optional[str] = None          # 理想工作（用户手动填写，不读简历）
    skills: List[str] = Field(default_factory=list)
    personality: Optional[str] = None          # 严格取自简历原文字面，不润色
    expected_salary: Optional[SalaryAmount] = None
    languages: List[LanguageProficiency] = Field(default_factory=list)  # 手动选择
    availability: Optional[Availability] = None                            # 到岗时间，手动选择
    experience_years: Optional[int] = None
    education: Optional[str] = None
    city: Optional[str] = None
    raw_resume: Optional[str] = None


class JdInfo(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    responsibilities: List[str] = Field(default_factory=list)
    salary_offer: Optional[SalaryAmount] = None
    city: Optional[str] = None
    raw_text: str = ""
    source_url: Optional[str] = None
    required_languages: List[LanguageProficiency] = Field(default_factory=list)
    prefers_immediate: bool = False           # JD 偏好「尽快到岗 / Immediate available」


# ===== 报告子模型 =====
class SalaryAnalysis(BaseModel):
    market_low: Optional[float] = None       # 年化 CNY
    market_high: Optional[float] = None
    company_offer: Optional[float] = None    # 年化 CNY
    expected: Optional[float] = None         # 年化 CNY
    verdict: str = "数据不足"                # 偏低 / 匹配 / 偏高 / 数据不足
    gap_vs_expected: Optional[float] = None
    gap_vs_market: Optional[float] = None
    currency_warning: Optional[str] = None
    notes: List[str] = Field(default_factory=list)


class SkillMatchItem(BaseModel):
    skill: str
    status: str          # matched / missing_required / missing_preferred
    note: Optional[str] = None


class SkillMatchResult(BaseModel):
    matched: List[str] = Field(default_factory=list)
    missing_required: List[str] = Field(default_factory=list)
    missing_preferred: List[str] = Field(default_factory=list)
    match_score: float = 0.0                 # 0-100
    items: List[SkillMatchItem] = Field(default_factory=list)


class LanguageMatchResult(BaseModel):
    matched: List[str] = Field(default_factory=list)
    missing: List[str] = Field(default_factory=list)
    match_score: float = 0.0                 # 0-100
    notes: List[str] = Field(default_factory=list)


class AvailabilityMatchResult(BaseModel):
    fit: str = "未知"          # 完全匹配 / 较匹配 / 基本匹配 / 不匹配 / 无明确要求
    note: Optional[str] = None


class PersonalityDimension(BaseModel):
    name: str
    fit: str                                # 高 / 中 / 低
    note: Optional[str] = None


class PersonalityMatchResult(BaseModel):
    summary: str = ""
    dimensions: List[PersonalityDimension] = Field(default_factory=list)
    score: float = 0.0


class CareerProspect(BaseModel):
    promotion: str = ""                      # 晋升机会
    raise_outlook: str = ""                  # 加薪机会
    jump_outlook: str = ""                   # 跳槽机会
    daily: str = ""                          # 日常工作
    overall: str = ""                        # 原始完整文本


class InterviewQA(BaseModel):
    question: str
    direction: str = ""                      # 回答方向
    frequency: str = ""                      # 高频 / 中频 / 低频


class ImprovementSuggestion(BaseModel):
    area: str
    detail: str
    priority: str = "中"                     # 高 / 中 / 低


class Report(BaseModel):
    role: Optional[str] = None
    company: Optional[str] = None
    salary_analysis: SalaryAnalysis = Field(default_factory=SalaryAnalysis)
    skill_match: SkillMatchResult = Field(default_factory=SkillMatchResult)
    language_match: Optional[LanguageMatchResult] = None
    availability_match: Optional[AvailabilityMatchResult] = None
    personality_match: PersonalityMatchResult = Field(default_factory=PersonalityMatchResult)
    improvement_suggestions: List[ImprovementSuggestion] = Field(default_factory=list)
    career_prospect: CareerProspect = Field(default_factory=CareerProspect)
    daily_work: str = ""
    interview_qa: List[InterviewQA] = Field(default_factory=list)
    generated_at: Optional[str] = None


# ===== 金额归一化工具 =====
USD_TO_CNY = 7.2
HKD_TO_CNY = 0.92
HOURLY_TO_ANNUAL_FACTOR = 2080  # 假设每周 40h × 全年 52 周；仅 MVP 估算用


def to_annual_cny(amount: Optional[SalaryAmount], usd_rate: float = USD_TO_CNY,
                  hkd_rate: float = HKD_TO_CNY) -> Optional[float]:
    """将任意 SalaryAmount 归一化为「年化 CNY 元」。无法计算返回 None。"""
    if amount is None:
        return None
    val = amount.value
    if amount.currency == Currency.USD:
        val = val * usd_rate
    elif amount.currency == Currency.HKD:
        val = val * hkd_rate
    # 其余币种（CNY/UNKNOWN）按面值计
    if amount.period == PayPeriod.MONTHLY:
        val = val * 12
    elif amount.period == PayPeriod.MONTHLY_13:
        val = val * 13
    elif amount.period == PayPeriod.MONTHLY_14:
        val = val * 14
    elif amount.period == PayPeriod.HOURLY:
        val = val * HOURLY_TO_ANNUAL_FACTOR
    # ANNUAL / UNKNOWN -> 视为已年化
    return float(round(val, 2))
