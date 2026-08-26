"""市场区间收窄：基于职级与市场价，将过宽区间收窄到合理幅度。

设计：不改动 core 与 DeepSeekSalaryProvider 的原始估算（保留其单测），
通过 `TightenedSalaryProvider` 包装任意 SalaryProvider，
在其 `estimate_market_range` 返回后做收窄再交给上层。

收窄逻辑：
- 以区间中点（即市场价）为锚；
- 职级越高合理浮动越大（实习/初级最窄，资深/管理略宽，其余居中）；
- 年化结果取整到 1000，使按月展示时为规整数字。
"""
from __future__ import annotations

from typing import Optional, Tuple

from core.interfaces import SalaryProvider
from core.models import JdInfo, SalaryAmount

# 职级关键词（小写匹配，含中英）
_JUNIOR_KW = (
    "实习", "初级", "助理", "应届", "毕业生",
    "intern", "junior", "entry", "trainee", "assistant", "graduate",
)
_SENIOR_KW = (
    "资深", "高级", "专家", "主管", "经理", "总监", "负责人", "首席",
    "lead", "senior", "principal", "manager", "director", "head", "chief", "vp",
)


def seniority_spread(role: str) -> float:
    """根据岗位名推断合理浮动比例（半宽）。"""
    r = (role or "").lower()
    if any(k in r for k in _JUNIOR_KW):
        return 0.10
    if any(k in r for k in _SENIOR_KW):
        return 0.15
    return 0.12


def tighten_market_range(
    low: Optional[float], high: Optional[float], role: str
) -> Tuple[Optional[float], Optional[float]]:
    """将市场区间收窄：以区间中点（市场价）为锚，按职级浮动比例收窄。"""
    if low is None or high is None or low <= 0 or high <= low:
        return low, high
    mid = (low + high) / 2.0
    spread = seniority_spread(role)
    new_low = mid * (1 - spread)
    new_high = mid * (1 + spread)
    # 年化取整到 1000，使按月展示时为规整数字
    new_low = round(new_low / 1000) * 1000
    new_high = round(new_high / 1000) * 1000
    if new_high <= new_low:
        new_high = new_low + 1000
    return float(new_low), float(new_high)


class TightenedSalaryProvider(SalaryProvider):
    """包装任意 SalaryProvider，对其返回的市场区间做收窄处理。"""

    def __init__(self, base: SalaryProvider) -> None:
        self.base = base

    def estimate_market_range(
        self, role: str, city: Optional[str] = None
    ) -> Tuple[Optional[float], Optional[float]]:
        low, high = self.base.estimate_market_range(role, city)
        return tighten_market_range(low, high, role)

    def get_company_offer(self, jd: JdInfo) -> Optional[SalaryAmount]:
        return self.base.get_company_offer(jd)
