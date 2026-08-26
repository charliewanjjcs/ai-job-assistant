"""Phase4 外部薪资 API（DeepSeek 大模型估算）—— TDD 测试。

验证 DeepSeekSalaryProvider：
- estimate_market_range：有 Key 且 LLM 返回有效 JSON → 用 LLM 区间；
  无 Key / LLM 抛异常 / 返回非法 JSON → 回退父类 RuleBasedSalaryProvider 规则估算。
- get_company_offer：继承父类正则解析（从 JD 文本抽「25k-40k / 20万-35万」报价）。

全部用 mock LLM，不依赖真实 API Key。
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.models import JdInfo
from core.salary import RuleBasedSalaryProvider
from modules.salary_api import DeepSeekSalaryProvider, TightenedSalaryProvider
from modules.salary_api.tighten import tighten_market_range, seniority_spread


class _FakeLLM:
    """可配置返回值的假 LLM。"""

    def __init__(self, result=None, available=True, raise_err=None):
        self._result = result
        self._available = available
        self._raise = raise_err
        self.calls = 0

    def available(self) -> bool:
        return self._available

    def complete(self, prompt, system="", temperature=0.7, max_tokens=1500):
        self.calls += 1
        if self._raise:
            raise self._raise
        return self._result


def _make_jd(text: str) -> JdInfo:
    return JdInfo(title="后端开发工程师", company="测试", city="深圳",
                  required_skills=[], preferred_skills=[],
                  required_languages=[], prefers_immediate=False, raw_text=text)


# ── 1. LLM 成功：返回有效 JSON 区间 ──────────────────────────────────────────
def test_llm_estimate_success():
    llm = _FakeLLM(result='{"low": 300000, "high": 500000}')
    provider = DeepSeekSalaryProvider(llm=llm)
    low, high = provider.estimate_market_range("后端开发工程师", "深圳")
    assert low == 300000 and high == 500000
    assert llm.calls == 1, "应调用一次 LLM"


# ── 2. 无 Key：直接回退规则，不调 LLM ───────────────────────────────────────
def test_llm_fallback_when_no_key():
    llm = _FakeLLM(result='{"low": 1, "high": 2}', available=False)
    provider = DeepSeekSalaryProvider(llm=llm)
    low, high = provider.estimate_market_range("后端开发工程师", "深圳")
    assert llm.calls == 0, "无 Key 不应调用 LLM"
    # 规则估算（后端 350000 * 深圳1.2 * [0.8, 1.3]）
    assert low == int(350000 * 1.2 * 0.8)
    assert high == int(350000 * 1.2 * 1.3)


# ── 3. LLM 抛异常：回退规则 ────────────────────────────────────────────────
def test_llm_fallback_on_exception():
    llm = _FakeLLM(raise_err=RuntimeError("boom"))
    provider = DeepSeekSalaryProvider(llm=llm)
    low, high = provider.estimate_market_range("后端开发工程师", "深圳")
    assert low == int(350000 * 1.2 * 0.8)
    assert high == int(350000 * 1.2 * 1.3)


# ── 4. LLM 返回非法 JSON / 区间非法：回退规则 ───────────────────────────────
@pytest.mark.parametrize("bad", [
    "不是 JSON",
    '{"low": 500000, "high": 300000}',   # low > high
    '{"low": "abc", "high": "def"}',      # 非数字
    '{"low": -1, "high": 0}',             # 非法负值
])
def test_llm_fallback_on_bad_payload(bad):
    llm = _FakeLLM(result=bad)
    provider = DeepSeekSalaryProvider(llm=llm)
    low, high = provider.estimate_market_range("后端开发工程师", "深圳")
    assert low == int(350000 * 1.2 * 0.8)
    assert high == int(350000 * 1.2 * 1.3)


# ── 5. get_company_offer：先覆盖常见写法，再回退父类正则 ──────────────────
def test_get_company_offer_inherited():
    # core 锁定正则只认「25-40k」（k 仅在第 2 个数后），父类能命中
    provider = DeepSeekSalaryProvider(llm=_FakeLLM())
    jd = _make_jd("职位：后端开发工程师\n薪资范围：25-40k")
    offer = provider.get_company_offer(jd)
    assert offer is not None
    assert offer.value == (25000 + 40000) / 2  # 月薪中位数
    assert offer.period.value == "monthly"


@pytest.mark.parametrize("text,expected,period", [
    ("25k-40k", (25000 + 40000) / 2, "monthly"),       # k 在两个数后（core 漏掉）
    ("25K-40K", (25000 + 40000) / 2, "monthly"),
    ("2w-3w", (20000 + 30000) / 2, "annual"),          # w 在两个数后
    ("2万-3万", (20000 + 30000) / 2, "annual"),        # 万 在两个数后
])
def test_get_company_offer_extended_formats(text, expected, period):
    provider = DeepSeekSalaryProvider(llm=_FakeLLM())
    jd = _make_jd(f"薪资范围：{text}")
    offer = provider.get_company_offer(jd)
    assert offer is not None, f"未识别 {text}"
    assert abs(offer.value - expected) < 0.01
    assert offer.period.value == period


# ── 6. 无角色时直接走规则（LLM 无法估算空岗位）─────────────────────────────
def test_empty_role_uses_rule():
    llm = _FakeLLM(result='{"low": 1, "high": 2}')
    provider = DeepSeekSalaryProvider(llm=llm)
    low, high = provider.estimate_market_range("", "深圳")
    assert llm.calls == 0
    assert low == int(300000 * 1.2 * 0.8)  # 默认 base 300000
    assert high == int(300000 * 1.2 * 1.3)


# ── 7. TightenedSalaryProvider：收窄市场区间（不破坏原 provider 原始估算）──
def test_tighten_narrows_wide_range():
    # LLM 返回过宽区间 30w-50w，应被收窄到以中点(40w)为锚的窄区间
    llm = _FakeLLM(result='{"low": 300000, "high": 500000}')
    base = DeepSeekSalaryProvider(llm=llm)
    provider = TightenedSalaryProvider(base)
    low, high = provider.estimate_market_range("后端开发工程师", "深圳")
    mid = 400000
    # 中级浮动 0.12 -> [352000, 448000]
    assert low == 352000 and high == 448000
    # 区间明显窄于原始 30w-50w
    assert (high - low) < (500000 - 300000)


def test_tighten_preserves_llm_call_and_role_aware():
    # 高级岗位浮动更大（0.15），初级更小（0.10）
    llm = _FakeLLM(result='{"low": 300000, "high": 500000}')
    senior = TightenedSalaryProvider(DeepSeekSalaryProvider(llm=llm))
    s_low, s_high = senior.estimate_market_range("高级后端工程师", "深圳")
    s_mid = (s_low + s_high) / 2

    llm2 = _FakeLLM(result='{"low": 300000, "high": 500000}')
    junior = TightenedSalaryProvider(DeepSeekSalaryProvider(llm=llm2))
    j_low, j_high = junior.estimate_market_range("初级后端工程师", "深圳")
    j_mid = (j_low + j_high) / 2

    # 同中点下，高级区间宽度应大于初级
    assert (s_high - s_low) > (j_high - j_low)
    # 中点均保持 ~40w（只收窄宽度，不平移量级）
    assert abs(s_mid - 400000) < 1
    assert abs(j_mid - 400000) < 1


def test_tighten_wraps_rule_based_fallback():
    # 无 Key 时回退规则估算，再被收窄
    llm = _FakeLLM(result='{"low": 1, "high": 2}', available=False)
    provider = TightenedSalaryProvider(DeepSeekSalaryProvider(llm=llm))
    low, high = provider.estimate_market_range("后端开发工程师", "深圳")
    # 规则区间 后端350000*深圳1.2*[0.8,1.3] = [336000, 546000]，中点441000
    # 中级 0.12 -> [388000, 494000]
    assert low == 388000 and high == 494000


def test_tighten_demo_rule_path():
    # demo 模式（基类用 RuleBasedSalaryProvider）也应被收窄
    provider = TightenedSalaryProvider(RuleBasedSalaryProvider())
    low, high = provider.estimate_market_range("后端开发工程师", "深圳")
    # 规则 [336000, 546000] -> 收窄 [388000, 494000]
    assert low == 388000 and high == 494000


def test_tighten_invalid_range_passthrough():
    # 非法区间直接原样透传，不抛错
    assert tighten_market_range(None, 100.0, "x") == (None, 100.0)
    assert tighten_market_range(0, 0, "x") == (0, 0)


def test_seniority_spread_bounds():
    assert seniority_spread("实习生前端的") == 0.10
    assert seniority_spread("资深后端专家") == 0.15
    assert seniority_spread("后端开发") == 0.12


class _PromptCapturingLLM:
    """记录 prompt 的假 LLM，用于断言薪资估算把 JD 上下文（职级/经验/行业）传给模型。"""

    def __init__(self, result):
        self._result = result
        self.prompts = []

    def available(self):
        return True

    def complete(self, prompt, system="", temperature=0.7, max_tokens=1500):
        self.prompts.append(prompt)
        return self._result


def test_llm_estimate_uses_jd_context():
    # 高职位级（VP）岗位的薪资估算必须把完整 JD（职级/经验/行业）传给 LLM，
    # 避免只凭岗位名「Vice President」低估为月薪 2-3 万。
    llm = _PromptCapturingLLM('{"low": 800000, "high": 1200000}')
    provider = DeepSeekSalaryProvider(llm=llm)
    jd_text = "Vice President, Private Banking. 8-10 years of experience in wealth management."
    low, high = provider.estimate_market_range("Vice President", "香港", jd_text)
    assert (low, high) == (800000.0, 1200000.0)
    # prompt 应包含完整 JD 上下文（职级 + 经验年限 + 行业）
    assert llm.prompts, "LLM 应被调用"
    prompt = llm.prompts[0]
    assert "Vice President" in prompt
    assert "8-10 years" in prompt
    assert "Private Banking" in prompt


def test_tighten_passes_jd_text_through():
    # TightenedSalaryProvider 应把 jd_text 透传给底层 provider
    llm = _PromptCapturingLLM('{"low": 800000, "high": 1200000}')
    provider = TightenedSalaryProvider(DeepSeekSalaryProvider(llm=llm))
    jd_text = "Director, 10+ years experience."
    low, high = provider.estimate_market_range("Director", "上海", jd_text)
    assert llm.prompts and "10+ years" in llm.prompts[0]
    # 收窄后中点保持 100w，宽度按职级 0.15 浮动
    assert abs((low + high) / 2 - 1000000) < 2000


# ── 8. 薪资 grounding：参考表命中（含英文岗位名）────────────────────────────
def test_salary_context_reference_table_hr():
    # 英文岗位名 "Assistant Human Resources Officer" 应匹配「人力资源」族（而非通用）
    from modules.salary_api.salary_grounding import get_salary_context
    ctx = get_salary_context("Assistant Human Resources Officer", "上海")
    assert "人力资源" in ctx, "英文 HR 岗位应命中人力资源族"
    assert "150,000" in ctx, "一线城市 HR 年化下限应约 15 万"
    assert "月薪约" in ctx


def test_salary_context_falls_back_to_default_for_unknown():
    from modules.salary_api.salary_grounding import get_salary_context
    ctx = get_salary_context("完全不存在的岗位XYZ", "上海")
    assert "通用" in ctx


def test_salary_context_includes_web_search_when_available(monkeypatch):
    # 联网检索返回的摘要应被拼进上下文
    from modules.salary_api import salary_grounding
    monkeypatch.setattr(
        salary_grounding, "search_web_salary",
        lambda role, city, timeout=5.0: "某招聘平台显示该岗位月薪约 18000 元",
    )
    ctx = salary_grounding.get_salary_context("Assistant Human Resources Officer", "上海")
    assert "18000" in ctx


def test_deepseek_prompt_includes_grounding(monkeypatch):
    # 薪资提示词应注入真实薪资基准锚点（取代纯拍脑袋）
    from modules.salary_api import salary_grounding
    monkeypatch.setattr(salary_grounding, "search_web_salary", lambda *a, **k: None)  # 离线，仅用参考表
    llm = _PromptCapturingLLM('{"low": 180000, "high": 260000}')
    provider = DeepSeekSalaryProvider(llm=llm)
    low, high = provider.estimate_market_range("Assistant Human Resources Officer", "上海")
    assert (low, high) == (180000.0, 260000.0)
    assert llm.prompts, "LLM 应被调用"
    prompt = llm.prompts[0]
    assert "参考薪资基准" in prompt, "提示词应含 grounding 锚点"
    assert "人力资源" in prompt, "锚点应标识岗位族"
