"""核心抽象接口。

所有「肉」（modules/）与运行时组件都通过这些接口与 core 解耦：
- SalaryProvider：薪资数据来源（MVP 规则估算，Phase4 真实 API）
- ResumeParser ：简历解析（Phase2 PDF）
- JdSource      ：JD 来源（Phase3 URL）
- Analyzer      ：分析编排主入口
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Tuple

from .models import JdInfo, Report, SalaryAmount, UserProfile


class SalaryProvider(ABC):
    """薪资数据来源。MVP 用规则估算；Phase4 用真实 API 实现同一接口热插拔。"""

    @abstractmethod
    def estimate_market_range(
        self, role: str, city: Optional[str] = None, jd_text: Optional[str] = None
    ) -> Tuple[Optional[float], Optional[float]]:
        """返回 (年化CNY下限, 年化CNY上限)；无法估计返回 (None, None)。

        `jd_text`：JD 原始文本（含职级、经验年限、行业、职责），供 LLM 估算
        高职位级岗位（如 VP）时参考，避免只凭岗位名低估薪资。
        """

    @abstractmethod
    def get_company_offer(self, jd: JdInfo) -> Optional[SalaryAmount]:
        """从 JD 解析公司报价；无则返回 None。"""


class ResumeParser(ABC):
    """简历解析：原始文本/PDF -> UserProfile。Phase2 实现 PDF 版。"""

    @abstractmethod
    def parse(self, raw: str) -> UserProfile:
        ...


class JdSource(ABC):
    """JD 来源：URL -> JdInfo。Phase3 用 Playwright 实现。"""

    @abstractmethod
    def fetch(self, url: str) -> JdInfo:
        ...


class Analyzer(ABC):
    """分析编排主入口。"""

    @abstractmethod
    def analyze(self, profile: UserProfile, jd: JdInfo) -> Report:
        ...
