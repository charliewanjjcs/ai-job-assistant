"""薪资匹配 TDD：先写极端用例（红），再写实现（绿）。

覆盖：薪资过低 / 薪资过高 / 数据缺失 / 币种不同 / 部分缺失。
金额统一用 core.models.SalaryAmount；内部归一化为年化 CNY。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from core.models import SalaryAmount, Currency, PayPeriod
from core.salary import SalaryMatcher


def _cny(v, period=PayPeriod.ANNUAL):
    return SalaryAmount(value=v, currency=Currency.CNY, period=period)


def test_offer_too_low():
    """公司报价远低于预期 -> 偏低，缺口为负。"""
    exp = _cny(400000)
    comp = _cny(200000)
    r = SalaryMatcher.analyze(exp, (300000, 500000), comp)
    assert r.verdict == "偏低"
    assert r.gap_vs_expected is not None and r.gap_vs_expected < 0


def test_offer_too_high():
    """公司报价远高于预期 -> 偏高，缺口为正。"""
    exp = _cny(200000)
    comp = _cny(400000)
    r = SalaryMatcher.analyze(exp, (300000, 500000), comp)
    assert r.verdict == "偏高"
    assert r.gap_vs_expected is not None and r.gap_vs_expected > 0


def test_both_missing():
    """预期与公司报价均缺失 -> 数据不足。"""
    r = SalaryMatcher.analyze(None, (300000, 500000), None)
    assert r.verdict == "数据不足"


def test_currency_difference():
    """公司用美元、预期用人民币 -> 应折算并提示币种，再判匹配。"""
    exp = _cny(400000)
    comp = SalaryAmount(value=50000, currency=Currency.USD, period=PayPeriod.ANNUAL)  # ~360k CNY
    r = SalaryMatcher.analyze(exp, (300000, 500000), comp)
    assert r.currency_warning is not None
    assert r.company_offer is not None
    # 50k USD*7.2=360k < 预期 400k -> 偏低
    assert r.verdict == "偏低"


def test_partial_missing_company():
    """有预期、公司报价缺失 -> 仅与预期/市场对比，不误判。"""
    exp = _cny(400000)
    r = SalaryMatcher.analyze(exp, (300000, 500000), None)
    assert r.verdict == "公司报价缺失"
    assert r.company_offer is None
    assert r.expected is not None


def test_monthly_offer_normalized():
    """月薪 20-30K -> 年化后与预期对比正确。"""
    exp = _cny(360000)              # 年化 36w
    comp = _cny(25000, PayPeriod.MONTHLY)  # 25k*12=300k
    r = SalaryMatcher.analyze(exp, (300000, 500000), comp)
    assert r.company_offer == 300000.0
    assert r.verdict == "偏低"      # 30w < 36w
