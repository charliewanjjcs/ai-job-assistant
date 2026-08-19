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
| 文本占位解析 | `core/parsers.py` | `parse_resume_text(...)`, `parse_jd_text(...)`, `extract_skills/extract_personality/parse_expected_salary/extract_jd_languages/extract_prefers_immediate`（技能=**双语词库**(硬技能 MS Office/Excel/PowerPoint/Power BI/MATLAB… + 软技能 data analysis/communication skills/analytical and problem-solving skills/attention to detail…，中英文各一套) + **边界匹配(中文亦视为边界) + 整词包含去重(MS Office 不重复 Office、Power BI 不重复 BI) + 同族去重**(`_dedupe_by_family`：detail-oriented 与 attention to detail、Excel 与 MS Office 等同义/上下位族只保留最先出现的一条，消除重复展示，命中哪个语言就原样输出哪个，不翻译不双语)，`SKILL_SYNONYMS`/`SKILL_SUPERSETS`/`_skill_family` 为单一来源（matcher 复用，不再重复定义）；性格=显式性格标签字面 或 从「个人总结/自我评价」段落抽取性格词(含外向/内向)；`split_skills()`=逗号/中文逗号/顿号/分号/斜杠/换行分隔，不做空格切分 | locked | core-refine-locked |

## modules/（可插拔的肉）
| 模块 | 路径 | 实现接口 | 状态 | 锁定 |
|------|------|----------|------|------|
| PDF 简历解析 | `modules/resume_pdf/pdf_parser.py` | `PdfResumeParser.parse(path:str) -> UserProfile`（pypdf 抽文本 + 复用 core.parsers.parse_resume_text，不修改 core） | locked | phase2 |
| URL 读取 JD | `modules/jd_url/` | `JdSource` | planned | — |
| 外部薪资 API | `modules/salary_api/` | `SalaryProvider` | planned | — |

## app/（Streamlit 前端）
| 模块 | 路径 | 状态 | 锁定 |
|------|------|------|------|
| 入口/表单/展示 | `app/main.py` | locked(演进)：薪资改时薪/月薪/年薪+币种选择（**年薪单位改为「元」**）；新增语言(语言+3档熟练度)、到岗时间(手动)；目标岗位→理想工作(手动，**标签去掉"（手动填写，不读简历）"**)；**JD 原文粘贴框位于「岗位标题」之上**，on_change 回调回填「必需/加分技能/语言/到岗」输入框；新增「语言匹配」「到岗匹配」标签页；预期薪资左(计薪方式)/中(纯数字)/右(币种)三栏；**计薪方式/币种/到岗 selectbox 不加 help（selectbox 本就只可选不可编辑）**；**到岗冗余"可到岗时间"标签删除**；**语言能力区初始仅显示「+ 添加语言」按钮**；**JD 语言要求大标题改为"语言要求"**；性格框提示移入 placeholder 并去掉"取简历原话"；语言区删冗余"已掌握语言"副标题；必需技能原名"必选技能"；**技能三处标签去掉"（逗号分隔）"，改用 split_skills**；**技能抽取按同义/上下位族去重(extract_skills 调用 _dedupe_by_family)**；**词库补充 communication/interpersonal skills/人际交往能力 等软技能（识别非连续的 "communication and interpersonal skills" 写法）**；修复 availability="未填写" 构造枚举崩溃 | skill-vocab-soft-locked |
