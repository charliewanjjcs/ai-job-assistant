"""从自由文本（简历 / JD）中启发式抽取结构化字段。

MVP 占位解析器：只用「正则 + 技能词表」做轻量抽取，目的是让「粘贴文本即可分析」
的体验成立——否则结构化分析（薪资对比 / 技能匹配）因缺少字段而全空。

Phase 2（PDF 解析）与 Phase 3（URL 解析）会用更强的解析器以同接口替换本模块，
本文件是「肉」的一部分，不属于 Phase 1 锁定的核心算法（salary/matcher/llm/career/interview）。

设计约束：
- 纯函数、无 streamlit 依赖，便于单测。
- 只做「抽取」，不做任何判断；所有匹配/建议仍由 core 里的稳定模块负责。
"""
from __future__ import annotations

import re
from typing import List, Optional

# 技能词表（覆盖常见技术栈；命中即视为用户/JD 具备该技能）
SKILL_VOCAB: List[str] = [
    "Python", "Go", "Golang", "Java", "C++", "C#", "JavaScript", "TypeScript", "Rust",
    "PHP", "Ruby", "Swift", "Kotlin", "Scala",
    "MySQL", "PostgreSQL", "Redis", "MongoDB", "Elasticsearch", "Kafka", "RabbitMQ",
    "Docker", "Kubernetes", "K8s", "Linux", "Nginx", "Git", "Shell",
    "Django", "Flask", "FastAPI", "Spring", "Spring Boot", "React", "Vue", "Node.js", "Node",
    "TensorFlow", "PyTorch", "HTML", "CSS", "SQL", "Oracle", "Hadoop", "Spark", "Flink",
    "Hive", "Tableau", "Excel", "PowerBI", "gRPC", "RPC", "MQ",
]

# 城市词表（用于抽取工作城市）
CITIES: List[str] = [
    "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "西安", "南京", "苏州",
    "重庆", "天津", "长沙", "厦门", "宁波", "青岛", "东莞", "佛山", "郑州", "济南",
]


def extract_skills(text: str) -> List[str]:
    """从文本中按词表抽取技能（去重、保序）。"""
    if not text:
        return []
    low = text.lower()
    found: List[str] = []
    for s in SKILL_VOCAB:
        if s.lower() in low and s not in found:
            found.append(s)
    return found


def extract_city(text: str) -> Optional[str]:
    if not text:
        return None
    for c in CITIES:
        if c in text:
            return c
    return None


def extract_expected_salary(text: str) -> Optional[float]:
    """抽取「预期年薪 X 万」-> 年化元。"""
    if not text:
        return None
    m = re.search(r"预期[年薪]*?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*万", text)
    if m:
        return float(m.group(1)) * 10000.0
    return None


def extract_role(text: str, label: str) -> Optional[str]:
    """抽取「<label>：内容」一行中的内容。"""
    if not text:
        return None
    m = re.search(rf"{label}\s*[:：]\s*(.+)", text)
    if m:
        return m.group(1).strip().rstrip("。；;，,")
    return None


def parse_resume_text(text: str) -> dict:
    """从简历自由文本抽取画像结构化字段。"""
    return {
        "target_role": extract_role(text, "目标岗位") or extract_role(text, "岗位"),
        "skills": extract_skills(text),
        "city": extract_city(text),
        "expected_salary": extract_expected_salary(text),
        "personality": extract_role(text, "性格"),
    }


def parse_jd_text(text: str) -> dict:
    """从 JD 自由文本抽取岗位结构化字段（区分必选/加分技能）。

    加分判定按「子句」粒度：仅当包含该技能的那一句（按逗号/分号/句号切分，
    **顿号「、」视为同一技能列表、不当分隔符**）出现「优先/加分」才视为加分项。

    这样既能把「熟悉 Docker、Kubernetes 者优先」整体判为加分（者优先跨顿号生效），
    又不会把「熟悉 MySQL、Redis，有高并发经验者优先」里的 MySQL/Redis 误判为加分
    （该句的优先指的是「高并发经验」，在逗号之后的另一子句）。
    """
    if not text:
        return {
            "title": None, "company": None, "city": None,
            "required_skills": [], "preferred_skills": [],
        }
    skills = extract_skills(text)
    required: List[str] = []
    preferred: List[str] = []
    for line in text.splitlines():
        for s in skills:
            if s.lower() not in line.lower():
                continue
            clauses = re.split(r"[，,；;。\n]", line)
            clause = next((c for c in clauses if s.lower() in c.lower()), line)
            if re.search(r"优先|加分|prefer|优先者", clause, re.I):
                if s not in preferred:
                    preferred.append(s)
            else:
                if s not in required:
                    required.append(s)
    return {
        "title": extract_role(text, "岗位") or extract_role(text, "职位"),
        "company": extract_role(text, "公司"),
        "city": extract_city(text),
        "required_skills": required,
        "preferred_skills": preferred,
    }
