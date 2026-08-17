"""PDF 简历解析器（Phase2「肉」）。

实现 core.interfaces.ResumeParser：
- parse(raw): raw 为 PDF 文件路径字符串 -> 返回 UserProfile
- 内部用 pypdf 抽全文，再复用 core.parsers.parse_resume_text 抽结构化字段
- 不修改 core，仅调用其公开接口（严守「沙盒」原则）

降级策略：
- 图片/扫描件（无文字层）-> extract_text 返回 ""，parse 返回 raw_resume=None 的 UserProfile
- 损坏/加密/不存在 -> 抛出明确异常，由调用方（前端）捕获并提示
"""
from __future__ import annotations

import os
from typing import Optional

from core.interfaces import ResumeParser
from core.models import Currency, PayPeriod, SalaryAmount, UserProfile
from core.parsers import parse_resume_text

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - 导入失败由运行期报错暴露
    PdfReader = None  # type: ignore


class PdfResumeParser(ResumeParser):
    """从 PDF 简历文件解析出 UserProfile。"""

    def extract_text(self, path: str) -> str:
        """抽取 PDF 全部文字；扫描件返回空字符串。异常向上抛。"""
        if PdfReader is None:
            raise RuntimeError("未安装 pypdf，无法解析 PDF。请执行 pip install pypdf")
        if not isinstance(path, str) or not path:
            raise ValueError("PdfResumeParser.parse 需要 PDF 文件路径字符串")
        if not os.path.exists(path):
            raise FileNotFoundError(f"PDF 文件不存在：{path}")
        try:
            reader = PdfReader(path)
        except Exception as e:  # 加密 / 损坏 / 非 PDF
            raise ValueError(f"PDF 解析失败（可能损坏、加密或非 PDF 文件）：{e}") from e
        chunks: list[str] = []
        for page in reader.pages:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                chunks.append("")
        return "\n".join(chunks).strip()

    def parse(self, raw: str) -> UserProfile:
        """raw = PDF 文件路径。返回 UserProfile（raw_resume 存抽取出的文本）。"""
        text = self.extract_text(raw)
        if not text:
            # 扫描件 / 无文字层：降级，不抛异常，由前端提示改用文本粘贴
            return UserProfile(raw_resume=None)
        parsed = parse_resume_text(text)
        expected = None
        if parsed.get("expected_salary"):
            expected = SalaryAmount(
                value=float(parsed["expected_salary"]),
                currency=Currency.CNY,
                period=PayPeriod.ANNUAL,
            )
        return UserProfile(
            raw_resume=text,
            skills=parsed.get("skills") or [],
            personality=parsed.get("personality"),
            target_role=parsed.get("target_role"),
            city=parsed.get("city"),
            expected_salary=expected,
        )
