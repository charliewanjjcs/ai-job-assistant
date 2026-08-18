"""文本解析器 TDD 用例：覆盖简历/JD 结构化抽取。

对应流程：先写极端/关键用例 -> 实现 core/parsers.py -> 跑绿。
"""
from core.parsers import (
    extract_personality,
    extract_skills,
    extract_expected_salary,
    parse_expected_salary,
    parse_jd_text,
    parse_resume_text,
)


def test_extract_skills_hits_vocab():
    assert "Python" in extract_skills("技能：Python、MySQL、Redis")
    assert "Kubernetes" in extract_skills("熟悉 Kubernetes 者优先")


def test_extract_skills_empty():
    assert extract_skills("") == []


def test_extract_expected_salary_wan():
    assert extract_expected_salary("预期年薪：35 万") == 350000.0
    assert extract_expected_salary("无薪资信息") is None


def test_parse_resume_pulls_fields():
    t = """目标岗位：后端开发工程师
城市：深圳
预期年薪：35 万
技能：Python、MySQL、Redis、Docker
性格：细心、抗压"""
    r = parse_resume_text(t)
    # 理想工作（原目标岗位）改为用户手动填写，解析器不再抽取
    assert "target_role" not in r
    assert r["city"] == "深圳"
    assert r["expected_salary"] is not None
    assert r["expected_salary"].value == 350000.0
    assert r["expected_salary"].period.value == "annual"
    assert "Python" in r["skills"] and "Docker" in r["skills"]
    assert r["personality"] == "细心、抗压"


def test_parse_resume_empty():
    assert parse_resume_text("") == {
        "skills": [], "city": None,
        "expected_salary": None, "personality": None,
    }


def test_extract_soft_skills_from_experience():
    # 从经历描述中抓取软技能（受词表约束，不乱抓）
    t = "通过数据分析提升了转化率，并制定SOP规范流程；日常负责沟通协调与团队管理，做过市场调研。"
    skills = extract_skills(t)
    assert "数据分析" in skills
    assert "制定SOP" in skills
    assert "沟通协调" in skills
    assert "市场调研" in skills
    # 不应把整句误当技能
    assert "转化率" not in skills


def test_extract_personality_literal():
    # 严格取原文字面，不润色
    assert extract_personality("性格：严谨，细致，乐观") == "严谨，细致，乐观"
    assert extract_personality("无相关字段 abc") is None


def test_parse_expected_salary_variants():
    a = parse_expected_salary("预期年薪：35万")
    assert a.value == 350000.0 and a.period.value == "annual" and a.currency.value == "CNY"
    b = parse_expected_salary("期望月薪：25k")
    assert b.value == 25000.0 and b.period.value == "monthly"
    c = parse_expected_salary("时薪：200")
    assert c.value == 200.0 and c.period.value == "hourly"
    d = parse_expected_salary("期望薪资：30万港币")
    assert d.currency.value == "HKD"
    assert parse_expected_salary("无薪资信息") is None


def test_parse_jd_languages():
    j = parse_jd_text("英语可作为工作语言，要求流利；粤语优先")
    langs = {l.language for l in j["required_languages"]}
    assert "英语" in langs
    assert "粤语" in langs


def test_parse_jd_prefers_immediate():
    j = parse_jd_text("Immediate available is preferred")
    assert j["prefers_immediate"] is True
    j2 = parse_jd_text("正常到岗即可，无特殊要求")
    assert j2["prefers_immediate"] is False


def test_parse_jd_required_vs_preferred():
    t = """岗位：高级后端开发工程师
公司：某互联网科技有限公司
精通 Python
熟悉 MySQL、Redis
熟悉 Docker、Kubernetes 者优先"""
    j = parse_jd_text(t)
    assert j["title"] == "高级后端开发工程师"
    assert j["company"] == "某互联网科技有限公司"
    assert "Python" in j["required_skills"]
    assert "MySQL" in j["required_skills"]
    assert "Docker" in j["preferred_skills"]
    assert "Kubernetes" in j["preferred_skills"]


def test_parse_jd_salary_line_not_required_pref():
    # 公司报价行含「K」但应进报价解析（salary 模块处理），不应误判为技能优先
    t = "薪资：25-40K·13薪\n精通 Python"
    j = parse_jd_text(t)
    assert "Python" in j["required_skills"]


def test_parse_jd_priority_no_leak_to_unrelated_skills():
    # 「熟悉 MySQL、Redis，有高并发经验者优先」：优先指的是「高并发经验」，
    # 在逗号之后的另一子句，不应把 MySQL/Redis 误判为加分项
    t = "熟悉 MySQL、Redis，有高并发经验者优先"
    j = parse_jd_text(t)
    assert "MySQL" in j["required_skills"]
    assert "Redis" in j["required_skills"]
    assert "MySQL" not in j["preferred_skills"]
    assert "Redis" not in j["preferred_skills"]
