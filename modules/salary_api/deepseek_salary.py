"""Phase4：外部薪资数据源 —— DeepSeek 大模型估算实现。

`DeepSeekSalaryProvider` 实现 `SalaryProvider` 接口（继承 `RuleBasedSalaryProvider`）：
- `estimate_market_range`：优先用 DeepSeek LLM 按「岗位 + 城市」估计年化市场薪资区间；
  无 Key / 调用失败 / 返回非法 JSON 时，自动回退到父类的规则估算（兜底，不抛错）。
- `get_company_offer`：直接继承父类的正则解析（从 JD 文本抽取「25k-40k / 20万-35万」报价），
  该解析已足够可靠，无需 LLM。

只调 core 接口、不改 core。Key 经 core.llm.DeepSeekClient 从环境变量/`.env` 读取，不写死。
"""
from __future__ import annotations

import json
import re
from typing import Optional, Tuple

from core.llm import DeepSeekClient
from core.models import Currency, JdInfo, PayPeriod, SalaryAmount
from core.salary import RuleBasedSalaryProvider
from .salary_grounding import get_salary_context


class DeepSeekSalaryProvider(RuleBasedSalaryProvider):
    """用 DeepSeek LLM 估算薪资市场区间，失败回退规则估算。"""

    def __init__(self, llm: Optional[DeepSeekClient] = None) -> None:
        self.llm = llm or DeepSeekClient()

    # ── 内部：是否具备 LLM 估算能力 ────────────────────────────────────────
    def _llm_available(self) -> bool:
        # 兼容测试注入的假 LLM（可能没有 available 方法）
        return bool(getattr(self.llm, "available", lambda: True)())

    # ── 内部：调用 LLM 返回 (low, high) ────────────────────────────────────
    def _estimate_via_llm(
        self, role: str, city: Optional[str], jd_text: Optional[str] = None
    ) -> Tuple[float, float]:
        system = (
            "你是资深薪酬数据专家。根据岗位、城市与 JD 完整信息，估计该岗位在中国的"
            "年化薪资市场区间（人民币元/年，指含奖金的总包年薪）。只返回 JSON，不要任何解释或多余文字。"
        )
        context = ""
        if jd_text:
            context = f"\nJD 摘要（含职级、经验年限、行业、职责）：\n{jd_text[:1500]}"
        # 真实薪资基准（联网检索 + 参考表），作为校准锚点注入提示词
        grounding = get_salary_context(role, city)
        prompt = (
            f"岗位：{role}\n城市：{city or '未指定'}{context}\n\n"
            f"{grounding}\n\n"
            "请综合「职级（如 Vice President / 总监 / 经理 / 初级）、经验年限、行业（如私人银行 / 投行 / 科技）"
            "」判断薪资水平：高职级、多年经验、金融等高薪行业的岗位，年化薪资要显著高于初级岗位，"
            "不要只按岗位名低估（例如 Vice President 级别通常远超月薪 2-3 万）。\n"
            '请只返回 JSON：{"low": 年化下限(元), "high": 年化上限(元)}'
        )
        raw = self.llm.complete(prompt, system=system, temperature=0.2, max_tokens=200)
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise ValueError("LLM 未返回 JSON")
        data = json.loads(m.group(0))
        low = float(data.get("low"))
        high = float(data.get("high"))
        if not (low > 0 and high > low):
            raise ValueError("LLM 返回区间非法")
        return low, high

    # ── 实现 SalaryProvider.estimate_market_range ─────────────────────────
    def estimate_market_range(
        self, role: str, city: Optional[str] = None, jd_text: Optional[str] = None
    ) -> Tuple[Optional[float], Optional[float]]:
        if not role or not self._llm_available():
            return super().estimate_market_range(role, city, jd_text)
        try:
            return self._estimate_via_llm(role, city, jd_text)
        except Exception:
            # 任何 LLM 异常（无网/超时/返回乱码/解析失败）都不影响主流程，回退规则估算
            return super().estimate_market_range(role, city, jd_text)

    # ── 增强 get_company_offer：补齐 core 锁定正则漏掉的常见写法 ─────────
    # core 的规则只匹配「25-40k」（k 仅在第 2 个数后）、「20万-35万」，漏掉：
    #   「25k-40k」（k 在两个数后）、「2w-3w」「2万-3万」（w/万 在两个数后）。
    # 这里先按更全的正则匹配，命中不到再回退父类（不改 core）。
    def get_company_offer(self, jd: JdInfo) -> Optional[SalaryAmount]:
        text = jd.raw_text or ""
        # 月薪：25k-40k / 25K-40K / 25千-40千
        m = re.search(
            r"(\d+(?:\.\d+)?)\s*[Kk千]\s*[-~到]\s*(\d+(?:\.\d+)?)\s*[Kk千]", text
        )
        if m:
            lo = float(m.group(1)) * 1000
            hi = float(m.group(2)) * 1000
            val = (lo + hi) / 2
            period = PayPeriod.MONTHLY_13 if "13薪" in text else PayPeriod.MONTHLY
            return SalaryAmount(value=val, currency=Currency.CNY, period=period, raw=m.group(0))
        # 年薪：2w-3w / 2万-3万
        m = re.search(
            r"(\d+(?:\.\d+)?)\s*[Ww万]\s*[-~到]\s*(\d+(?:\.\d+)?)\s*[Ww万]", text
        )
        if m:
            lo = float(m.group(1)) * 10000
            hi = float(m.group(2)) * 10000
            val = (lo + hi) / 2
            return SalaryAmount(value=val, currency=Currency.CNY, period=PayPeriod.ANNUAL, raw=m.group(0))
        return super().get_company_offer(jd)
