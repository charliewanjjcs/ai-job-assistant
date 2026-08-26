"""Phase4 外部薪资数据源（DeepSeek 大模型估算 + 真实薪资 grounding）。"""

from .deepseek_salary import DeepSeekSalaryProvider
from .tighten import TightenedSalaryProvider, tighten_market_range, seniority_spread
from .salary_grounding import get_salary_context, search_web_salary

__all__ = [
    "DeepSeekSalaryProvider",
    "TightenedSalaryProvider",
    "tighten_market_range",
    "seniority_spread",
    "get_salary_context",
    "search_web_salary",
]
