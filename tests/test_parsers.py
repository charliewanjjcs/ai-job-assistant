"""文本解析器 TDD 用例：覆盖简历/JD 结构化抽取。

对应流程：先写极端/关键用例 -> 实现 core/parsers.py -> 跑绿。
"""
from core.parsers import (
    extract_skills,
    extract_expected_salary,
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
    assert r["target_role"] == "后端开发工程师"
    assert r["city"] == "深圳"
    assert r["expected_salary"] == 350000.0
    assert "Python" in r["skills"] and "Docker" in r["skills"]
    assert r["personality"] == "细心、抗压"


def test_parse_resume_empty():
    assert parse_resume_text("") == {
        "target_role": None, "skills": [], "city": None,
        "expected_salary": None, "personality": None,
    }


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
