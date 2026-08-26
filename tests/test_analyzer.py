"""编排器 TDD：用 FakeLLM 注入，验证 CoreAnalyzer 端到端产出 Report，无需真实 Key。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.analyzer import CoreAnalyzer
from core.models import UserProfile, JdInfo, SalaryAmount, Currency, PayPeriod


class FakeLLM:
    def complete(self, prompt, system="", temperature=0.7, max_tokens=1500):
        if system and "职业规划" in system:
            return ("## 晋升机会\n有机会。\n## 加薪机会\n一般。\n"
                    "## 跳槽机会\n较多。\n## 日常工作\n写代码、做需求。")
        # 面试
        return ("Q: 你做过什么项目？\nA: 描述一个完整项目经历。\nF: 高频\n"
                "Q: 为什么想离开上家？\nA: 谈职业发展。\nF: 中频")


def test_analyzer_runs_without_real_key():
    p = UserProfile(
        skills=["python"],
        expected_salary=SalaryAmount(value=300000, currency=Currency.CNY, period=PayPeriod.ANNUAL),
    )
    jd = JdInfo(title="后端", company="X", required_skills=["Python"], raw_text="薪资 20-30K")
    r = CoreAnalyzer(llm=FakeLLM()).analyze(p, jd)
    assert r.role == "后端"
    assert r.company == "X"
    assert r.salary_analysis.verdict in ("匹配", "偏低", "偏高", "公司报价缺失")
    assert r.skill_match.match_score >= 0
    assert len(r.interview_qa) >= 1
    assert r.interview_qa[0].question
    assert r.career_prospect.promotion  # 前景已解析


def test_high_frequency_interview_questions_present_and_labeled():
    """两道高频必问（对岗位理解/对公司认识）应始终出现并标记为「高频」；职业规划题已移除。"""
    p = UserProfile(
        skills=["python"],
        expected_salary=SalaryAmount(value=300000, currency=Currency.CNY, period=PayPeriod.ANNUAL),
    )
    jd = JdInfo(title="后端", company="X", required_skills=["Python"], raw_text="薪资 20-30K")
    r = CoreAnalyzer(llm=FakeLLM()).analyze(p, jd)
    questions = [q.question for q in r.interview_qa]
    assert any("对岗位的理解" in q for q in questions)
    assert any("为什么想来这家公司" in q for q in questions)
    # 这两题必须标记为「高频」，不再叫「固定」
    hf = [q for q in r.interview_qa if "对岗位的理解" in q.question or "为什么想来这家公司" in q.question]
    assert len(hf) == 2
    for q in hf:
        assert q.frequency == "高频"
        assert q.direction  # 即使 LLM 未生成，也应回退到默认回答方向
    # 职业规划题已被移除
    assert not any("职业规划" in q for q in questions)
