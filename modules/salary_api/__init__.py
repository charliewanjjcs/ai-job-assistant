"""Phase4 外部薪资数据源（DeepSeek 大模型估算）。"""

from .deepseek_salary import DeepSeekSalaryProvider
from .tighten import TightenedSalaryProvider, tighten_market_range, seniority_spread

__all__ = [
    "DeepSeekSalaryProvider",
    "TightenedSalaryProvider",
    "tighten_market_range",
    "seniority_spread",
]
