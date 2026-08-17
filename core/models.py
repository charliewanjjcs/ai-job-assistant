"""数据模型：用户输入画像、JD、分析报告。

金额约定：所有对外展示前的内部计算统一归一化为「年化 CNY 元」，
由 `to_annual_cny()` 负责换算（月薪×12、美元×汇率等）。
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Currency(str, Enum):
    CNY = "CNY"
    USD = "USD"
    UNKNOWN = "UNKNOWN"


class PayPeriod(str, Enum):
    ANNUAL = "annual"
    MONTHLY = "monthly"
    MONTHLY_13 = "monthly_13"
    MONTHLY_14 = "monthly_14"
    UNKNOWN = "unknown"


class SalaryAmount(BaseModel):
    value: float
    currency: Currency = Currency.CNY
    period: PayPeriod = PayPeriod.ANNUAL
    raw: Optional[str] = None


class UserProfile(BaseModel):
    name: Optional[str] = None
    target_role: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    personality: Optional[str] = None          # 自由描述 / 性格关键词
    expected_salary: Optional[SalaryAmount] = None
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
    personality_match: PersonalityMatchResult = Field(default_factory=PersonalityMatchResult)
    improvement_suggestions: List[ImprovementSuggestion] = Field(default_factory=list)
    career_prospect: CareerProspect = Field(default_factory=CareerProspect)
    daily_work: str = ""
    interview_qa: List[InterviewQA] = Field(default_factory=list)
    generated_at: Optional[str] = None


# ===== 金额归一化工具 =====
USD_TO_CNY = 7.2


def to_annual_cny(amount: Optional[SalaryAmount], usd_rate: float = USD_TO_CNY) -> Optional[float]:
    """将任意 SalaryAmount 归一化为「年化 CNY 元」。无法计算返回 None。"""
    if amount is None:
        return None
    val = amount.value
    if amount.currency == Currency.USD:
        val = val * usd_rate
    if amount.period == PayPeriod.MONTHLY:
        val = val * 12
    elif amount.period == PayPeriod.MONTHLY_13:
        val = val * 13
    elif amount.period == PayPeriod.MONTHLY_14:
        val = val * 14
    # ANNUAL / UNKNOWN -> 视为已年化
    return float(round(val, 2))
