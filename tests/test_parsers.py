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
    split_skills,
)


def test_extract_skills_hits_vocab():
    assert "Python" in extract_skills("技能：Python、MySQL、Redis")
    assert "Kubernetes" in extract_skills("熟悉 Kubernetes 者优先")


def test_split_skills_multiple_delimiters():
    # 逗号 / 中文逗号 / 顿号 / 分号 / 斜杠 / 换行 都应作为分隔符
    assert split_skills("Python, MySQL、Redis；Excel/PPT\nDocker") == [
        "Python", "MySQL", "Redis", "Excel", "PPT", "Docker"
    ]
    # 多词技能（含空格）不应被空格拆散
    assert split_skills("data analysis, attention to detail") == [
        "data analysis", "attention to detail"
    ]
    # 空串 / 全空 -> 空列表；首尾空白忽略；重复去重
    assert split_skills("") == []
    assert split_skills("  Excel ,, Excel ， Word ") == ["Excel", "Word"]


def test_extract_skills_empty():
    assert extract_skills("") == []


def test_extract_skills_family_dedupe():
    # 同义/上下位表述只保留一条，避免重复展示
    # 1) detail-oriented 与 attention to detail 同族 -> 仅一条
    assert extract_skills("Detail-oriented with strong attention to detail.") == ["attention to detail"]
    # 2) 仅出现 detail-oriented 时，原样保留，不冒出 attention to detail
    assert extract_skills("I am detail-oriented and a team player.") == ["detail-oriented"]
    # 3) MS Office ⊇ Excel 同族 -> 仅保留 MS Office
    assert extract_skills("I have MS Office and Excel skills.") == ["MS Office"]
    # 4) 不同族（问题解决 / 细致）各自保留
    out = extract_skills("attention to detail and problem solving skills")
    assert "attention to detail" in out and "problem solving skills" in out
    assert len(out) == 2


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


def test_extract_skills_no_false_positive():
    # 边界匹配：'Go' 不应命中 'Google'，'Git' 不应命中 'GitHub'，'Office' 不应命中 'officer'
    t = "Google 是一家公司，团队使用 GitHub，招聘一名 officer"
    skills = extract_skills(t)
    assert "Go" not in skills
    assert "Git" not in skills
    assert "Office" not in skills


def test_extract_skills_genuine_go_git():
    # 真实出现时仍应命中（独立词；不再收录裸 Go，避免命中 go-to-market 等误判）
    t = "熟悉 Go 语言与 Git 版本控制"
    skills = extract_skills(t)
    assert "Go 语言" in skills
    assert "Git" in skills


def test_extract_skills_no_raw_section_grab():
    # 不应把「技能」标签后的整段文字当作技能
    t = "技能：负责需求评审，参与代码编写与测试，协助上线"
    assert extract_skills(t) == []


def test_extract_skills_office_tools():
    # 用户点名的办公/分析工具应被识别；MS Office/Excel/PowerPoint 同属一族，只保留代表性的一条
    t = "熟练使用 MS Office、Excel 与 data analysis，常用 PowerPoint 做汇报"
    skills = extract_skills(t)
    assert "MS Office" in skills            # 保留宽泛表述
    assert "data analysis" in skills        # 独立技能族，保留
    assert "Excel" not in skills            # 已被 MS Office 族去重折叠
    assert "PowerPoint" not in skills       # 同上
    assert len(skills) == 2


def test_extract_skills_communication_interpersonal():
    # 用户点名的软技能：communication / interpersonal skills 必须识别
    # 1) 非连续写法 "communication and interpersonal skills" 也要命中
    t1 = "Excellent communication and interpersonal skills; strong team player."
    s1 = extract_skills(t1)
    assert "communication" in s1
    assert "interpersonal skills" in s1
    # 2) 单独 "communication" 或 "interpersonal skills" 也要命中
    assert "communication" in extract_skills("Strong communication, problem solving.")
    assert "interpersonal skills" in extract_skills("Good interpersonal skills required.")
    # 3) 中文 "人际交往能力" 应识别
    t3 = "具备良好沟通能力，优秀的跨部门协作与人际交往能力。"
    s3 = extract_skills(t3)
    assert "沟通能力" in s3
    assert "人际交往能力" in s3


def test_extract_skills_cjk_adjacent():
    # 修复：英文技能紧贴中文（无空格）也应识别；且不能命中 Google/GitHub
    t = "精通Python，熟悉MySQL、Redis，有Docker、Kubernetes经验者优先使用Git"
    skills = extract_skills(t)
    assert "Python" in skills
    assert "MySQL" in skills
    assert "Redis" in skills
    assert "Docker" in skills
    assert "Kubernetes" in skills
    assert "Git" in skills
    # 不应把长词误判
    assert "Go" not in skills


def test_parse_jd_single_block():
    # 网页复制来的单段 JD（技能词紧贴中文）也应正确区分必需/加分
    t = "任职要求：精通Python，熟悉MySQL、Redis，有Docker、Kubernetes经验者优先"
    j = parse_jd_text(t)
    assert "Python" in j["required_skills"]
    assert "MySQL" in j["required_skills"]
    assert "Redis" in j["required_skills"]
    assert "Docker" in j["preferred_skills"]
    assert "Kubernetes" in j["preferred_skills"]


def test_extract_skills_bilingual_en():
    # 英文简历：命中英文词条，不输出中文翻译
    t = "Proficient in data analysis and communication skills, using Excel and MATLAB."
    skills = extract_skills(t)
    assert "data analysis" in skills
    assert "communication skills" in skills
    assert "Excel" in skills
    assert "MATLAB" in skills
    assert "数据分析" not in skills
    assert "沟通能力" not in skills


def test_extract_skills_bilingual_zh():
    # 中文简历：命中中文词条，不输出英文
    t = "熟练掌握数据分析与沟通能力，常用 Excel 与 MATLAB 做建模。"
    skills = extract_skills(t)
    assert "数据分析" in skills
    assert "沟通能力" in skills
    assert "Excel" in skills
    assert "MATLAB" in skills
    assert "data analysis" not in skills
    assert "communication skills" not in skills


def test_extract_skills_dedup_subsumed():
    # 命中 MS Office 时不应再重复 Office（整词包含去重）
    t = "熟练使用 MS Office 办公，常用 Power BI 做报表"
    skills = extract_skills(t)
    assert "MS Office" in skills
    assert "Office" not in skills
    assert "Power BI" in skills
    assert "BI" not in skills


def test_extract_personality_intro_extro():
    # 从个人总结抽取「外向 / 内向」等性格词（原文字面，不润色）
    t = "自我评价：性格偏外向，做事细心，有时也偏内向，但乐于团队协作"
    r = extract_personality(t)
    assert r is not None
    assert "外向" in r
    assert "内向" in r
    assert "细心" in r


def test_extract_personality_from_summary():
    # 从「个人总结 / 自我评价」段落抽取性格词（不依赖显式 性格 标签）
    t = "个人总结：本人性格积极乐观，做事细致，富有责任心，乐于团队协作。"
    r = extract_personality(t)
    assert r is not None
    assert "积极乐观" in r
    assert "细致" in r
    assert "团队协作" in r


def test_extract_personality_summary_dedup():
    # 同时命中「责任心」与「责任心强」时只保留更长表达
    t = "自我评价：责任心强，做事细心，执行力强"
    r = extract_personality(t)
    assert r is not None
    assert "责任心强" in r
    assert "责任心、" not in (r + "、")  # 不应出现单独的「责任心」
    assert "细心" in r
    assert "执行力强" in r




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
