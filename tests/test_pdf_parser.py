"""Phase2 PDF 简历解析器测试（TDD）。

设计要点：
- 用 fpdf2 生成 ASCII PDF 验证 pypdf 抽取链路（避免 CJK 抽取不确定性）。
- 用 monkeypatch 把 extract_text 替成已知中文简历文本，直接验证「抽取文本 -> 结构字段」
  的胶水逻辑（这是本项目新增代码的核心）。
- 覆盖极端用例：扫描件/空 PDF 降级、文件缺失、损坏 PDF。
"""
from __future__ import annotations

import pytest
from fpdf import FPDF

from modules.resume_pdf.pdf_parser import PdfResumeParser

# 已知中文简历文本（用于 monkeypatch，绕开 CJK PDF 抽取不确定性）
SAMPLE_RESUME = (
    "目标岗位：后端开发工程师\n"
    "掌握的技能：Python, MySQL, Redis, Docker\n"
    "期望城市：深圳\n"
    "预期年薪：35万\n"
    "性格：细心、抗压、喜欢钻研\n"
)


def _ascii_pdf(text: str, path: str) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in text.split("\n"):
        pdf.cell(0, 8, line)
        pdf.ln()
    pdf.output(path)


def _scan_pdf(path: str) -> None:
    """只画图形、无文字层，模拟扫描件。"""
    pdf = FPDF()
    pdf.add_page()
    pdf.rect(20, 20, 100, 100)
    pdf.output(path)


@pytest.fixture
def parser() -> PdfResumeParser:
    return PdfResumeParser()


# ===== 1. pypdf 抽取链路（ASCII） =====
def test_extract_text_ascii(parser, tmp_path):
    p = tmp_path / "ascii.pdf"
    _ascii_pdf("Skills: Python, MySQL, Redis, Docker", str(p))
    text = parser.extract_text(str(p))
    assert "Python" in text and "MySQL" in text and "Docker" in text


# ===== 2. 胶水逻辑：抽取文本 -> 结构字段（核心新增代码） =====
def test_parse_routes_through_parser(parser, monkeypatch):
    monkeypatch.setattr(parser, "extract_text", lambda raw: SAMPLE_RESUME)
    prof = parser.parse("dummy.pdf")
    assert prof.target_role == "后端开发工程师"
    assert set(["Python", "MySQL", "Redis", "Docker"]).issubset(set(prof.skills))
    assert prof.city == "深圳"
    assert prof.personality == "细心、抗压、喜欢钻研"
    assert prof.expected_salary is not None
    assert prof.expected_salary.value == 350000.0
    assert prof.raw_resume == SAMPLE_RESUME


# ===== 3. 扫描件 / 空 PDF 降级 =====
def test_scan_pdf_returns_none(parser, tmp_path):
    p = tmp_path / "scan.pdf"
    _scan_pdf(str(p))
    prof = parser.parse(str(p))
    assert prof.raw_resume is None


def test_empty_pdf_extract_returns_empty(parser, tmp_path):
    p = tmp_path / "empty.pdf"
    pdf = FPDF()
    pdf.add_page()
    pdf.output(str(p))
    assert parser.extract_text(str(p)) == ""


# ===== 4. 异常用例 =====
def test_missing_file_raises(parser):
    with pytest.raises(FileNotFoundError):
        parser.extract_text("/no/such/file.pdf")


def test_corrupt_pdf_raises(parser, tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_text("%PDF-1.4 this is not a real pdf garbage")
    with pytest.raises(ValueError):
        parser.extract_text(str(p))


def test_non_string_path_raises(parser):
    with pytest.raises(ValueError):
        parser.parse(123)  # type: ignore[arg-type]
