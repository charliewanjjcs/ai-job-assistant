"""从自由文本（简历 / JD）中启发式抽取结构化字段。

MVP 占位解析器：只用「正则 + 词表」做轻量抽取，目的是让「粘贴/上传即可分析」的体验成立。

Phase 2（PDF 解析）与 Phase 3（URL 解析）会用更强的解析器以同接口替换本模块，
本文件是「肉」的一部分，不属于 Phase 1 锁定的核心算法（salary/matcher/llm/career/interview）。

设计约束：
- 纯函数、无 streamlit 依赖，便于单测。
- 只做「抽取」，不做任何判断；所有匹配/建议仍由 core 里的稳定模块负责。
- 技能抽取：以「词表」为唯一边界，逐词做带边界的匹配（英文用单词边界、含特殊字符用前后非字母数字边界），
  只认 MS Office / Excel / data analysis 这类明确技能词，**绝不**把「技能」标签后的整段文字当作技能。
- 性格抽取：优先取简历「性格/个性/特质」标签后的原文字面；若没有，则从「个人总结/自我评价」等段落中
  抽取性格描述词（积极乐观、细致等），不润色、不编造。
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


def _token_present(text: str, token: str) -> bool:
    """判断 token 是否作为「独立词」出现在 text 中（大小写不敏感）。

    - 纯英文字母/数字词：用 \\b 单词边界，避免 'Go' 命中 'Google'、'Git' 命中 'GitHub'。
    - 含特殊字符（. + # 等）或中文词：用「前后非字母数字」边界，避免嵌在更长单词里被误判。
    """
    esc = re.escape(token)
    if re.fullmatch(r"[A-Za-z0-9]+", token):
        pat = r"\b" + esc + r"\b"
    else:
        pat = r"(?<![A-Za-z0-9])" + esc + r"(?![A-Za-z0-9])"
    return re.search(pat, text, re.I) is not None


# 技术/工具硬技能词库（命中即视为具备该技能；全部以词表为边界，不乱抓）
# 同一概念提供「中文 / 英文」两种表述，输出时原样保留简历中出现的语言——
# 中文简历命中中文词、英文简历命中英文词，不翻译、不双语；因此用户「掌握的技能」栏位语言自然一致。
SKILL_VOCAB: List[str] = [
    # 编程语言
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Golang", "Go 语言", "Go语言",
    "PHP", "Ruby", "Swift", "Kotlin", "Scala", "Rust", "R 语言", "R language",
    "MATLAB", "Matlab", "SQL", "HTML", "CSS", "Shell", "Bash",
    # 数据库 / 中间件
    "MySQL", "PostgreSQL", "Redis", "MongoDB", "Oracle", "SQL Server",
    "Elasticsearch", "Kafka", "RabbitMQ",
    # 运维 / 云
    "Docker", "Kubernetes", "K8s", "Linux", "Nginx", "Git",
    "阿里云", "AWS", "腾讯云", "Azure", "云计算", "cloud computing",
    # 工程框架
    "Django", "Flask", "FastAPI", "Spring", "Spring Boot", "React", "Vue",
    "Node.js", "Angular", "TensorFlow", "PyTorch",
    # 大数据 / AI
    "Hadoop", "Spark", "Flink", "Hive", "ETL", "数仓", "数据仓库", "数据挖掘",
    "数据可视化", "数据建模",
    "机器学习", "machine learning", "深度学习", "deep learning", "NLP",
    "计算机视觉", "大模型", "LLM", "Prompt",
    # 办公 / 分析软件（用户点名：MS Office、Excel、PowerPoint、Power BI 等）
    "MS Office", "Office", "Excel", "PowerPoint", "PPT", "Word",
    "Outlook", "Visio", "WPS", "Access", "Tableau", "Power BI", "PowerBI", "BI",
    "SAP", "Salesforce", "ERP", "CRM",
    # 设计 / 产品 / 运营工具
    "Figma", "Axure", "Sketch", "Photoshop", "Illustrator", "Xmind",
    "原型设计", "产品设计", "UI设计", "UI 设计",
    "SEO", "SEM", "Google Analytics", "A/B测试", "埋点",
    # 项目管理 / 协作
    "Jira", "Confluence", "Scrum", "Kanban", "敏捷",
]

# 软技能词库（从经历/描述中抓取，均为明确指向「能力」的短语；中英文双语）
SOFT_SKILL_VOCAB: List[str] = [
    "数据分析", "data analysis", "data analytics",
    "数据可视化", "data visualization",
    "数据挖掘", "data mining",
    "市场调研", "market research",
    "用户调研", "user research",
    "竞品分析", "competitive analysis",
    "需求分析", "requirement analysis",
    "制定SOP", "流程优化", "流程梳理",
    "沟通协调", "团队协作", "跨部门协作",
    "项目管理", "project management", "项目统筹",
    "商务谈判", "商务沟通", "客户维护", "客户关系管理", "危机处理",
    "培训带教", "员工培训", "报告撰写", "方案策划", "活动策划",
    "预算管控", "成本控制", "风险管理",
    "问题解决", "problem solving",
    "时间管理", "time management", "团队管理", "人员管理",
    "英文沟通", "英语沟通", "演讲汇报", "公开演讲", "presentation skills",
    "产品规划", "产品设计", "用户增长", "user growth",
    "运营策划", "内容运营", "社群运营",
    "业务分析", "business analysis", "财务分析", "financial analysis",
    "供应链管理", "供应商管理", "质量管控", "自动化测试", "性能优化",
    "沟通能力", "communication skills",
    "团队合作", "teamwork",
    "领导力", "leadership",
]


def _dedupe_subsumed(found: List[str]) -> List[str]:
    """去掉被其它已命中词条「整词包含」的短词条，避免重复。

    命中「MS Office」后不再重复「Office」；命中「Power BI」后不再重复「BI」。
    但「MySQL」与「SQL」互不包含（SQL 不是 MySQL 的独立整词），两者都保留。
    """
    kept: List[str] = []
    for t in sorted(found, key=len, reverse=True):
        if any(_token_present(other, t) and other != t for other in kept):
            continue
        kept.append(t)
    order = {t: i for i, t in enumerate(found)}
    return sorted(kept, key=lambda x: order[x])


def extract_skills(text: str) -> List[str]:
    """从文本抽取技能（去重、保序、语言原样保留）。

    仅以「词库」为边界做逐词匹配，**不会**把「技能」标签后的整段文字当作技能。
    英文短词（Git 等）使用单词边界匹配，避免命中 GitHub 等长词造成误抓。
    同概念的中英文词条都收录，命中哪个就输出哪个（不翻译、不双语）——
    因此中文简历自然填中文、英文简历填英文，JD 文本中的技能同理。
    """
    if not text:
        return []
    found: List[str] = []
    for s in SKILL_VOCAB + SOFT_SKILL_VOCAB:
        if s not in found and _token_present(text, s):
            found.append(s)
    return _dedupe_subsumed(found)


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

# 性格描述词表（从「个人总结 / 自我评价」等段落抽取，均为字面形容词/短语）
PERSONALITY_VOCAB: List[str] = [
    "积极乐观", "乐观", "开朗", "外向", "内向", "热情", "亲和",
    "细心", "细致", "细致入微", "严谨", "认真", "务实", "踏实",
    "负责", "责任心强", "有责任心", "责任心", "靠谱",
    "抗压", "抗压能力强", "抗压强",
    "主动", "积极主动", "进取", "上进", "自律", "独立",
    "沉稳", "冷静", "耐心", "勤奋",
    "高效", "执行力强", "结果导向", "目标导向", "客户导向",
    "逻辑思维", "逻辑清晰",
    "学习能力强", "快速学习", "好奇心强",
    "团队合作", "团队协作", "善于沟通", "沟通能力强", "表达能力强", "同理心",
    "创新思维", "创新意识", "灵活",
]

# 个人总结 / 自我评价 等段落标题
PERSONALITY_SECTION_LABELS = (
    "个人总结", "自我评价", "个人评价", "个人简介", "个人概述",
    "个人基本情况", "个人资料", "About Me", "About", "Summary", "PROFILE", "Profile",
)


def _extract_section(text: str, labels) -> str:
    """抽取以 labels 中任一标题开头的「段落」文本（标题行 + 后续直到空行或新标题前）。"""
    lines = text.splitlines()
    chunks: List[str] = []
    in_sec = False
    for line in lines:
        s = line.strip()
        if not s:
            if in_sec:
                break
            continue
        if not in_sec:
            hit = None
            for lbl in labels:
                if re.match(rf"^{re.escape(lbl)}[\s:：]", s, re.I):
                    hit = lbl
                    break
            if hit is not None:
                in_sec = True
                chunks.append(re.sub(rf"^{re.escape(hit)}[\s:：]*", "", s, flags=re.I))
                continue
        else:
            if re.match(r"^[^，,、\s]{0,16}[:：]", s):  # 遇到新段落标题则结束
                break
            chunks.append(s)
    return "\n".join(chunks).strip()


def extract_city(text: str) -> Optional[str]:
    if not text:
        return None
    for c in CITIES:
        if c in text:
            return c
    return None


def extract_personality(text: str) -> Optional[str]:
    """抽取性格描述（原文字面，不润色、不编造）。

    1) 优先取「性格/个性/个人特质/特质」标签后的原文字面；
    2) 否则从「个人总结 / 自我评价」等段落抽取性格描述词，用「、」拼接（去掉被更长表达包含的短词）。
    """
    if not text:
        return None
    for label in ("性格", "个性", "个人特质", "特质"):
        m = re.search(rf"{label}\s*[:：]\s*(.+)", text)
        if m:
            val = re.split(r"[。；\n]", m.group(1).strip())[0].strip().rstrip("，、 ")
            if val:
                return val
    region = _extract_section(text, PERSONALITY_SECTION_LABELS)
    if region:
        found = [p for p in PERSONALITY_VOCAB if _token_present(region, p)]
        # 去掉被更长表达包含的短词（如保留了「责任心强」就不再保留「责任心」），并保持顺序去重
        kept = [p for p in found if not any(p != q and p in q for q in found)]
        if kept:
            return "、".join(dict.fromkeys(kept))
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
