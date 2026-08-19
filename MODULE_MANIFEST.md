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

## app/（Streamlit 前端：多页面 + 本地账户 + SQLite 持久化）
| 模块 | 路径 | 公开接口 | 状态 | 锁定 |
|------|------|----------|------|------|
| 导航外壳 | `app/main.py` | 顶层 `import streamlit as st`；re-export `build_profile`/`build_jd`/`on_jd_text_change`（保 59 测试契约）；`__main__` 内 `st.navigation([st.Page(profile), st.Page(job_analysis)])` | active | — |
| 数据层纯函数 | `app/state.py` | `build_profile() -> UserProfile`、`build_jd() -> JdInfo`、`on_jd_text_change()`、`DemoLLM` + 选项常量 | active | — |
| 存储层 | `app/storage.py` | SQLite（`users`/`profiles`/`skill_library`/`verification_codes`）：`init_db`/`set_db_path`/`get_db_path`/`get_user`/`get_user_by_provider`/`get_user_by_email`/`get_or_create_user`/`create_email_user`/`authenticate_email`/`load_profile`/`save_profile`/`list_skills`/`add_skill`/`remove_skill`/`is_custom_skill`/`save_verification_code`/`verify_code` | active | — |
| 登录态 | `app/auth.py` | `current_user_id`/`current_display`/`is_logged_in`/`require_login`/`logout`/`login_provider`/`login_email`/`register_email`/`send_phone_code`/`login_phone`/`persist_login`/`try_restore_login`（本地模拟账户：微信/QQ/谷歌/手机号/邮箱；邮箱密码哈希；验证码存 DB+TTL；`data/session.json` 保持登录） | active | — |
| 技能编辑器 | `app/components/skill_editor.py` | `suggest_skills(query, vocab, existing, limit)` + `skill_editor(user_id)`（Workday 式联想→点选→标签可删→回车自定义，复用 `core.parsers` 词库） | active | — |
| 语言管理 | `app/components/lang_manager.py` | `lang_manager(state_key, header)`（初始仅「+ 添加语言」） | active | — |
| 结果标签页 | `app/components/result_tabs.py` | `render_salary`/`render_skill`/`render_language`/`render_availability`/`render_improve`/`render_career`/`render_daily`/`render_interview`/`render_report` | active | — |
| 登录侧边栏 | `app/components/auth_sidebar.py` | `render_auth_sidebar()`（未登录「登录」按钮→弹层各 provider；登录后用户名+退出） | active | — |
| 个人资料页 | `app/pages/profile.py` | `render()`（DB→session_state、技能编辑器、语言、薪资、性格、保存） | active | — |
| 职位分析页 | `app/pages/job_analysis.py` | `render()`（require_login + 自动载候选人资料 + JD 粘贴 on_change 回填 + 分析） | active | — |

> **UI 产品决策（沿用 skill-vocab-soft-locked 及之前锁定）**：薪资左计薪方式/中纯数字/右币种三栏（年薪单位「元」）；JD 原文粘贴框位于岗位标题之上，on_change 回填必需/加分技能、语言、到岗；计薪方式/币种/到岗 selectbox 仅可选不可编辑；语言区初始仅「+ 添加语言」按钮；JD 语言要求标题「语言要求」；性格提示在 placeholder；技能按同义/上下位族去重（`split_skills`，不加逗号分隔标签）；词库含 communication/interpersonal/人际交往 等软技能。
