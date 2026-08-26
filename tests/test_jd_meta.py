"""Phase3 增强：JD 元信息抽取（职位名称 / 公司 / 软技能特质）的测试。

覆盖：
- extract_soft_skills_heuristic：词表 + 句式派生（如 'knowledge of X' -> 'X knowledge'）
- extract_job_title / extract_company_name：多标签识别
- extract_jd_meta：有 LLM Key 走 LLM 解析；无 Key 回退本地启发式
"""
from __future__ import annotations

import app.state as stmod
from core.parsers import (
    extract_company_name,
    extract_job_title,
    extract_soft_skills_heuristic,
)


# ===== 1. 软技能启发式抽取（含自由表述）=====
def test_soft_skills_knowledge_of_pattern():
    # knowledge of X 是「领域知识」硬技能，进必需技能；软技能栏只保留 attention to detail 等特质
    from core.parsers import extract_knowledge_skills, parse_jd_text
    jd = (
        "Basic knowledge of financial products and G/L account reconciliation. "
        "We need someone with attention to detail and strong communication skills."
    )
    # knowledge of X 进硬技能（必需技能）
    hard = extract_knowledge_skills(jd)
    assert "financial products knowledge" in hard
    assert "G/L account reconciliation knowledge" in hard
    assert "financial products knowledge" in parse_jd_text(jd)["required_skills"]
    # 软技能栏仍保留 attention to detail / communication（同族去重后为 communication），不含知识类
    soft = extract_soft_skills_heuristic(jd)
    assert "attention to detail" in soft
    assert "communication" in soft
    assert "financial products knowledge" not in soft
    assert "G/L account reconciliation knowledge" not in soft


def test_soft_skills_lexicon_match():
    jd = "要求具备团队合作、领导力与批判性思维；problem solving 能力突出。"
    out = extract_soft_skills_heuristic(jd)
    assert "团队合作" in out
    assert "领导力" in out
    assert "批判性思维" in out


# ===== 2. 职位名称 / 公司识别（多标签）=====
def test_extract_job_title_variants():
    assert extract_job_title("职位名称：后端开发工程师") == "后端开发工程师"
    assert extract_job_title("Job Title: Data Analyst") == "Data Analyst"
    assert extract_job_title("招聘岗位：产品经理") == "产品经理"


def test_extract_company_name_variants():
    assert extract_company_name("公司：某某科技有限公司") == "某某科技有限公司"
    assert extract_company_name("Company: Acme Ltd") == "Acme Ltd"


# ===== 3. extract_jd_meta：LLM 成功路径（mock）=====
class _FakeLLM:
    def available(self):
        return True

    def complete(self, prompt, system="", temperature=0.2, max_tokens=800):
        return (
            '{"title": "数据分析师", "company": "测试科技有限公司", '
            '"soft_skills": ["attention to detail", "financial products knowledge"]}'
        )


def test_extract_jd_meta_llm(monkeypatch):
    monkeypatch.setattr(stmod, "DeepSeekClient", lambda: _FakeLLM())
    out = stmod.extract_jd_meta(
        "职位名称：数据分析师\n公司：测试科技有限公司\n"
        "Basic knowledge of financial products."
    )
    assert out["title"] == "数据分析师"
    assert out["company"] == "测试科技有限公司"
    assert "financial products knowledge" in out["soft_skills"]


# ===== 4. extract_jd_meta：无 Key 回退本地启发式 =====
class _NoKeyLLM:
    def available(self):
        return False


def test_extract_jd_meta_fallback(monkeypatch):
    monkeypatch.setattr(stmod, "DeepSeekClient", lambda: _NoKeyLLM())
    out = stmod.extract_jd_meta(
        "职位名称：后端开发工程师\n公司：某某公司\nRequire attention to detail."
    )
    assert out["title"] == "后端开发工程师"
    assert out["company"] == "某某公司"
    assert "attention to detail" in out["soft_skills"]
