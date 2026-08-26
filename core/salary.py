"""薪资匹配：市场区间估计（规则）+ 公司报价解析 + 三方对比分析。

- `SalaryMatcher.analyze` 是纯函数，不依赖 LLM，可直接单测（极端用例见 tests/test_salary.py）。
- `RuleBasedSalaryProvider` 实现 `SalaryProvider` 接口，MVP 用规则估算；Phase4 由真实 API 同接口替换。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .interfaces import SalaryProvider
from .models import (
    Currency,
    JdInfo,
    PayPeriod,
    SalaryAnalysis,
    SalaryAmount,
    to_annual_cny,
)


class SalaryMatcher:
    """三方对比：预期薪资 vs 市场区间 vs 公司报价。"""

    @staticmethod
    def analyze(
        expected: Optional[SalaryAmount],
        market: Tuple[Optional[float], Optional[float]],
        company_offer: Optional[SalaryAmount],
    ) -> SalaryAnalysis:
        exp = to_annual_cny(expected)
        comp = to_annual_cny(company_offer)
        low, high = market
        notes: List[str] = []
        currency_warning: Optional[str] = None

        # 展示周期：跟随用户预期薪资周期（月薪 -> 月薪；否则年薪）。
        # 仅影响对外展示口径，内部各值仍统一为年化 CNY。
        if expected is not None and expected.period in (
            PayPeriod.MONTHLY, PayPeriod.MONTHLY_13, PayPeriod.MONTHLY_14
        ):
            display_period = PayPeriod.MONTHLY
        else:
            display_period = PayPeriod.ANNUAL

        # 展示币种：跟随用户预期薪资币种（港币/美元 -> 对应币种；否则人民币）。
        if expected is not None and expected.currency in (Currency.HKD, Currency.USD):
            display_currency = expected.currency
        else:
            display_currency = Currency.CNY

        if (
            (expected and expected.currency == Currency.USD)
            or (company_offer and company_offer.currency == Currency.USD)
        ):
            currency_warning = "你填写的薪资为美元，已按汇率折算后与市场/报价对比，结果按你的预期币种（美元）呈现。"

        verdict = "数据不足"
        gap_vs_expected: Optional[float] = None
        gap_vs_market: Optional[float] = None

        if exp is not None and comp is not None:
            gap = round(comp - exp, 2)
            gap_vs_expected = gap
            if comp < exp * 0.95:
                verdict = "偏低"
            elif comp > exp * 1.05:
                verdict = "偏高"
            else:
                verdict = "匹配"
        elif exp is not None and comp is None:
            verdict = "公司报价缺失"
            notes.append("JD 未提供明确薪资，仅与你预期/市场区间对比。")
            if low is not None and high is not None:
                if exp < low:
                    notes.append("你的预期低于市场区间下限，可能偏保守。")
                elif exp > high:
                    notes.append("你的预期高于市场区间上限，兑现难度较大。")
        elif exp is None and comp is not None:
            verdict = "预期缺失"
            notes.append("你未填写预期薪资，仅对比公司报价与市场区间。")
        else:
            notes.append("预期薪资与公司报价均缺失，无法判断匹配度。")

        if comp is not None and low is not None and high is not None:
            mid = (low + high) / 2
            gap_vs_market = round(comp - mid, 2)

        return SalaryAnalysis(
            market_low=low,
            market_high=high,
            company_offer=comp,
            expected=exp,
            verdict=verdict,
            gap_vs_expected=gap_vs_expected,
            gap_vs_market=gap_vs_market,
            currency_warning=currency_warning,
            notes=notes,
            display_period=display_period,
            display_currency=display_currency,
        )


class RuleBasedSalaryProvider(SalaryProvider):
    """MVP 规则估算器：按岗位关键词 + 城市系数粗略估计市场区间，从 JD 文本正则解析报价。

    注意：这是占位估算，准确性有限；Phase4 会被真实薪资 API 实现替换。
    """

    # 岗位基准（年化 CNY 元）—— 仅 MVP 占位
    ROLE_BASE = {
        "算法": 450000, "后端": 350000, "前端": 320000, "全栈": 360000,
        "数据": 380000, "测试": 280000, "运维": 300000, "开发": 330000,
        "产品": 330000, "运营": 250000, "设计": 260000, "分析": 340000,
    }
    TIER1 = ("北京", "上海", "深圳", "广州", "杭州")
    TIER2 = ("成都", "武汉", "西安", "南京", "苏州", "重庆", "天津")

    def estimate_market_range(
        self, role: str, city: Optional[str] = None
    ) -> Tuple[Optional[float], Optional[float]]:
        base = None
        if role:
            for k, v in self.ROLE_BASE.items():
                if k in role:
                    base = v
                    break
        if base is None:
            base = 300000
        factor = 1.0
        if city:
            if any(c in city for c in self.TIER1):
                factor = 1.2
            elif any(c in city for c in self.TIER2):
                factor = 0.9
        low = int(base * factor * 0.8)
        high = int(base * factor * 1.3)
        return low, high

    def get_company_offer(self, jd: JdInfo) -> Optional[SalaryAmount]:
        text = jd.raw_text or ""
        # 月薪区间：20-35K / 15k-25k / 2w-3w
        m = re.search(r"(\d+(?:\.\d+)?)\s*[-~到]\s*(\d+(?:\.\d+)?)\s*[Kk千]", text)
        if m:
            lo = float(m.group(1)) * 1000
            hi = float(m.group(2)) * 1000
            val = (lo + hi) / 2
            period = PayPeriod.MONTHLY_13 if "13薪" in text else PayPeriod.MONTHLY
            return SalaryAmount(value=val, currency=Currency.CNY, period=period, raw=m.group(0))
        # 时薪/日薪不处理；年薪区间：20万-35万
        m2 = re.search(r"(\d+(?:\.\d+)?)\s*[-~到]\s*(\d+(?:\.\d+)?)\s*万", text)
        if m2:
            lo = float(m2.group(1)) * 10000
            hi = float(m2.group(2)) * 10000
            val = (lo + hi) / 2
            return SalaryAmount(value=val, currency=Currency.CNY, period=PayPeriod.ANNUAL, raw=m2.group(0))
        return None
