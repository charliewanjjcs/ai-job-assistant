"""从自由文本（简历 / JD）中启发式抽取结构化字段。

MVP 占位解析器：只用「正则 + 词表」做轻量抽取，目的是让「粘贴/上传即可分析」的体验成立。

Phase 2（PDF 解析）与 Phase 3（URL 解析）会用更强的解析器以同接口替换本模块，
本文件是「肉」的一部分，不属于 Phase 1 锁定的核心算法（salary/matcher/llm/career/interview）。

设计约束：
- 纯函数、无 streamlit 依赖，便于单测。
- 只做「抽取」，不做任何判断；所有匹配/建议仍由 core 里的稳定模块负责。
- 技能抽取三路合并且全部以「词表/字段」为边界，避免乱抓：
  1) 技术词表（SKILL_VOCAB）在全文命中
  2) 软技能词表（SOFT_SKILL_VOCAB）在全文命中（从经历里抓软技能）
  3) 显式「技能」字段里的条目（即使不在词表也保留，保证不漏）
- 性格抽取：严格取简历原文字面，绝不润色/编造。
"""
from __future__ import annotations

import re
from typing import List, Optional

from .models import (
    Currency,
    LanguageLevel,
    LanguageProficiency,
    PayPeriod,
    SalaryAmount,
)

# 技术词表（覆盖常见技术栈；命中即视为具备该技能）
SKILL_VOCAB: List[str] = [
    "Python", "Go", "Golang", "Java", "C++", "C#", "JavaScript", "TypeScript", "Rust",
    "PHP", "Ruby", "Swift", "Kotlin", "Scala",
    "MySQL", "PostgreSQL", "Redis", "MongoDB", "Elasticsearch", "Kafka", "RabbitMQ",
    "Docker", "Kubernetes", "K8s", "Linux", "Nginx", "Git", "Shell",
    "Django", "Flask", "FastAPI", "Spring", "Spring Boot", "React", "Vue", "Node.js", "Node",
    "TensorFlow", "PyTorch", "HTML", "CSS", "SQL", "Oracle", "Hadoop", "Spark", "Flink",
    "Hive", "Tableau", "Excel", "PowerBI", "gRPC", "RPC", "MQ", "Power BI",
]

# 软技能词表（从经历描述中抓取，均为明确指向「能力」的短语，避免误抓）
SOFT_SKILL_VOCAB: List[str] = [
    "数据分析", "数据可视化", "数据挖掘", "市场调研", "用户调研", "竞品分析", "需求分析",
    "制定SOP", "流程优化", "流程梳理", "沟通协调", "团队协作", "跨部门协作", "项目管理",
    "项目统筹", "商务谈判", "商务沟通", "客户维护", "客户关系管理", "危机处理", "培训带教",
    "员工培训", "报告撰写", "方案策划", "活动策划", "预算管控", "成本控制", "风险管理",
    "问题解决", "时间管理", "团队管理", "人员管理", "英文沟通", "英语沟通", "演讲汇报",
    "公开演讲", "产品规划", "产品设计", "用户增长", "运营策划", "内容运营", "社群运营",
    "业务分析", "财务分析", "供应链管理", "供应商管理", "质量管控", "自动化测试", "性能优化",
]

# 技能字段常见标签
SKILL_SECTION_LABELS = ("技能", "专业技能", "掌握技能", "掌握的技能", "技术栈", "技能特长", "特长", "skill", "skills")

# 技能条目前导修饰词（提取时剥离，得到干净技能名）
_SKILL_QUALIFIERS = ("熟练掌握", "熟悉", "精通", "了解", "懂", "会", "良好的", "较强", "扎实的", "具备", "掌握")

# 城市词表（用于抽取工作城市）
CITIES: List[str] = [
    "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "西安", "南京", "苏州",
    "重庆", "天津", "长沙", "厦门", "宁波", "青岛", "东莞", "佛山", "郑州", "济南",
]

# JD 语言能力识别
LANGUAGE_NAMES = {
    "英语": "英语", "英文": "英语", "english": "英语", "eng": "英语",
    "粤语": "粤语", "广东话": "粤语", "cantonese": "粤语",
    "普通话": "普通话", "中文": "普通话", "国语": "普通话", "mandarin": "普通话", "chinese": "普通话",
    "日语": "日语", "japanese": "日语",
    "法语": "法语", "french": "法语",
    "韩语": "韩语", "korean": "韩语",
    "德语": "德语", "german": "德语",
}
LANGUAGE_LEVEL_MAP = {
    "母语": LanguageLevel.NATIVE, "native": LanguageLevel.NATIVE,
    "流利": LanguageLevel.FLUENT, "熟练": LanguageLevel.FLUENT, "fluent": LanguageLevel.FLUENT,
    "六级": LanguageLevel.FLUENT, "cet6": LanguageLevel.FLUENT, "专八": LanguageLevel.FLUENT,
    "基础": LanguageLevel.BASIC, "入门": LanguageLevel.BASIC, "basic": LanguageLevel.BASIC,
}


def extract_skills(text: str) -> List[str]:
    """从文本抽取技能（去重、保序）。

    三路合并：技术词表命中 + 软技能词表命中 + 显式「技能」字段条目。
    全部以词表/字段为边界，不会凭空抓取无关词。
    """
    if not text:
        return []
    low = text.lower()
    found: List[str] = []
    for s in SKILL_VOCAB:
        if s.lower() in low and s not in found:
            found.append(s)
    for s in SOFT_SKILL_VOCAB:
        if s in text and s not in found:
            found.append(s)
    for item in _skill_section_items(text):
        it = _clean_skill_token(item)
        if it and it not in found:
            found.append(it)
    return found


def _skill_section_items(text: str) -> List[str]:
    """抽取「技能」字段区域内的条目（按分隔符切分）。"""
    lines = text.splitlines()
    chunks: List[str] = []
    in_sec = False
    for line in lines:
        s = line.strip()
        if not s:
            if in_sec:
                break
            continue
        m = re.match(r"^(技能|专业技能|掌握技能|技术栈|技能特长|特长|skill|skills)[\s:：]*(.*)$", s, re.I)
        if m:
            in_sec = True
            content = m.group(2).strip()
            if content:
                chunks.append(content)
            continue
        if in_sec:
            if re.match(r"^[^，,、\s]{0,14}[:：]", s):  # 遇到新段落标题则结束
                break
            chunks.append(s)
    out: List[str] = []
    for piece in re.split(r"[，,、；;。/\n|｜]+", " ".join(chunks)):
        piece = piece.strip().rstrip("。；;，,、 ")
        if piece:
            out.append(piece)
    return out


def _clean_skill_token(token: str) -> str:
    t = token.strip()
    for q in _SKILL_QUALIFIERS:
        if t.startswith(q):
            t = t[len(q):].strip()
    return t


def extract_city(text: str) -> Optional[str]:
    if not text:
        return None
    for c in CITIES:
        if c in text:
            return c
    return None


def extract_personality(text: str) -> Optional[str]:
    """严格取简历「性格/个性/特质」标签后的原文字面，不润色、不编造。"""
    if not text:
        return None
    for label in ("性格", "个性", "个人特质", "特质"):
        m = re.search(rf"{label}\s*[:：]\s*(.+)", text)
        if m:
            val = re.split(r"[。；\n]", m.group(1).strip())[0].strip().rstrip("，、 ")
            return val or None
    return None


def extract_expected_salary(text: str) -> Optional[float]:
    """（兼容旧接口）抽取「预期年薪 X 万」-> 年化元；找不到返回 None。"""
    if not text:
        return None
    m = re.search(r"预期[年薪]*?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*万", text)
    if m:
        return float(m.group(1)) * 10000.0
    return None


def parse_expected_salary(text: str) -> Optional[SalaryAmount]:
    """抽取预期薪资为 SalaryAmount（含周期与币种）。找不到返回 None。

    识别：时薪 / 月薪 / 年薪；人民币 / 港币。数值支持「35万」「25k」「200/小时」等。
    """
    if not text:
        return None
    segs = re.findall(r"[^。\n]*[薪资薪][^。\n]*", text)
    if not segs:
        return None
    seg = segs[0]
    currency = Currency.HKD if re.search(r"港币|港幣|HKD|HK\$|港", seg) else Currency.CNY
    if re.search(r"时薪|小时|\d+\s*元/时|\d+\s*/时|/小时", seg):
        period = PayPeriod.HOURLY
    elif re.search(r"月薪|/月|\dk\b|\dK\b|k/月|月", seg, re.I):
        period = PayPeriod.MONTHLY
    else:
        period = PayPeriod.ANNUAL
    nums = re.findall(r"(\d+(?:\.\d+)?)", seg)
    if not nums:
        return None
    val = float(nums[-1])
    if "万" in seg:
        val = val * 10000
    elif re.search(r"\dk\b|\dK\b", seg, re.I) or "k" in seg.lower():
        val = val * 1000
    return SalaryAmount(value=val, currency=currency, period=period, raw=seg.strip())


def extract_role(text: str, label: str) -> Optional[str]:
    """抽取「<label>：内容」一行中的内容。"""
    if not text:
        return None
    m = re.search(rf"{label}\s*[:：]\s*(.+)", text)
    if m:
        return m.group(1).strip().rstrip("。；;，,")
    return None


def parse_resume_text(text: str) -> dict:
    """从简历自由文本抽取画像结构化字段。

    注：「理想工作」属用户主观偏好，不读简历，由用户在前端手动填写，故此处不抽取。
    """
    return {
        "skills": extract_skills(text),
        "city": extract_city(text),
        "expected_salary": parse_expected_salary(text),
        "personality": extract_personality(text),
    }


def extract_jd_languages(text: str) -> List[LanguageProficiency]:
    """从 JD 文本抽取语言要求（语言 + 熟练度）。"""
    if not text:
        return []
    low = text.lower()
    found: dict[str, LanguageProficiency] = {}
    for key, canon in LANGUAGE_NAMES.items():
        idx = low.find(key.lower())
        if idx < 0:
            continue
        window = text[max(0, idx - 20): idx + 40]
        level = LanguageLevel.FLUENT  # 未写明熟练度时默认「熟练」
        for kw, lv in LANGUAGE_LEVEL_MAP.items():
            if kw.lower() in window.lower():
                level = lv
                break
        if canon not in found or level == LanguageLevel.NATIVE:
            found[canon] = LanguageProficiency(language=canon, level=level)
    return list(found.values())


def extract_prefers_immediate(text: str) -> bool:
    """JD 是否偏好「尽快到岗 / Immediate available」。"""
    if not text:
        return False
    return bool(re.search(
        r"immediate\s*available|尽快到岗|立即到岗|随时到岗|可尽快入职|到岗时间不限|asap|immediately|到岗越快越好",
        text, re.I,
    ))


def parse_jd_text(text: str) -> dict:
    """从 JD 自由文本抽取岗位结构化字段（区分必选/加分技能 + 语言要求 + 到岗偏好）。

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
            "required_languages": [], "prefers_immediate": False,
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
        "required_languages": extract_jd_languages(text),
        "prefers_immediate": extract_prefers_immediate(text),
    }
