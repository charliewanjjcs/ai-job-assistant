# 模块清单（MODULE_MANIFEST）

> **上下文管理核心**：每次新对话只加载「本清单 + 当前目标模块源码 + 该模块测试」，
> 不要把历史代码/修改记录灌进上下文。一个对话聚焦一个 Phase。
> 标记为 `locked: true` 的模块，**后续只调用其接口、不得修改其代码**；
> 改 locked 模块需用户显式授权。

## 状态说明
- `planned`：已规划，未实现
- `active` ：正在实现中
- `locked` ：已完成并锁定（git tag `phaseN-locked`）

---

## core/（核心算法，骨）
| 模块 | 路径 | 公开接口 | 状态 | 锁定 |
|------|------|----------|------|------|
| 数据模型 | `core/models.py` | `UserProfile(idel_job/languages/availability + 原字段), JdInfo(required_languages/prefers_immediate), Report(language_match/availability_match), SalaryAmount, LanguageProficiency, LanguageMatchResult, AvailabilityMatchResult, Availability/LanguageLevel/Currency/HKD+HOURLY` + `to_annual_cny()` | locked(演进) | core-refine-locked |
| 抽象接口 | `core/interfaces.py` | `SalaryProvider, ResumeParser, JdSource, Analyzer`（均为 ABC） | locked | phase1 |
| 薪资匹配 | `core/salary.py` | `SalaryMatcher.analyze(...)`, `RuleBasedSalaryProvider` | locked | phase1 |
| 能力匹配 | `core/matcher.py` | `SkillMatcher.match(...)`, `PersonalityMatcher.match(...)`, `LanguageMatcher.match(...)`, `AvailabilityMatcher.match(...)`, `build_improvements(...)` | locked(演进) | core-refine-locked |
| LLM 封装 | `core/llm.py` | `DeepSeekClient.complete(prompt)` | locked | phase1 |
| 前景/工作 | `core/career.py` | `CareerAnalyzer.analyze(profile, jd)` | locked | phase1 |
| 面试问答 | `core/interview.py` | `InterviewAnalyzer.analyze(profile, jd)` | locked | phase1 |
| 编排入口 | `core/analyzer.py` | `CoreAnalyzer.analyze(profile, jd) -> Report` | locked | phase1 |
| 文本占位解析 | `core/parsers.py` | `parse_resume_text(...)`, `parse_jd_text(...)`, `extract_skills/extract_personality/parse_expected_salary/extract_jd_languages/extract_prefers_immediate`（技能=词表+软技能词表+技能字段字面；性格取原文字面；薪资识别时薪/月薪/年薪+币种；JD 抽语言/到岗偏好） | locked | core-refine-locked |

## modules/（可插拔的肉）
| 模块 | 路径 | 实现接口 | 状态 | 锁定 |
|------|------|----------|------|------|
| PDF 简历解析 | `modules/resume_pdf/pdf_parser.py` | `PdfResumeParser.parse(path:str) -> UserProfile`（pypdf 抽文本 + 复用 core.parsers.parse_resume_text，不修改 core） | locked | phase2 |
| URL 读取 JD | `modules/jd_url/` | `JdSource` | planned | — |
| 外部薪资 API | `modules/salary_api/` | `SalaryProvider` | planned | — |

## app/（Streamlit 前端）
| 模块 | 路径 | 状态 | 锁定 |
|------|------|------|------|
| 入口/表单/展示 | `app/main.py` | locked(演进)：薪资改时薪/月薪/年薪+币种选择；新增语言(语言+3档熟练度)、到岗时间(手动)；目标岗位→理想工作(手动)；JD 自动识别语言/到岗偏好；新增「语言匹配」「到岗匹配」标签页 | core-refine-locked |
