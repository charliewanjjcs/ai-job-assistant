"""app/components/skill_editor.py 的纯函数单元测试（不依赖 Streamlit 运行期）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.components.skill_editor import suggest_skills

VOCAB = [
    "Python", "Excel", "data analysis", "detail-oriented", "attention to detail",
    "communication skills", "Go 语言", "数据分析", "机器学习", "Docker", "Kubernetes",
]


def test_empty_query_returns_empty():
    assert suggest_skills("", VOCAB, []) == []
    assert suggest_skills("   ", VOCAB, []) == []


def test_prefix_before_substring():
    # "data" 前缀命中 data analysis；"analysis" 是子串命中
    res = suggest_skills("data", VOCAB, [])
    assert "data analysis" in res
    # 前缀优先：data analysis 应排在含 "data" 子串但非前缀的项之前
    assert res[0] == "data analysis"


def test_case_insensitive():
    res = suggest_skills("EXCEL", VOCAB, [])
    assert "Excel" in res


def test_substring_match():
    res = suggest_skills("oriented", VOCAB, [])
    assert "detail-oriented" in res


def test_excludes_existing():
    res = suggest_skills("d", VOCAB, ["data analysis", "detail-oriented"])
    assert "data analysis" not in res
    assert "detail-oriented" not in res


def test_limit_truncation():
    big = [f"skill{i}" for i in range(50)]
    res = suggest_skills("skill", big, [], limit=5)
    assert len(res) == 5


def test_existing_special_chars():
    res = suggest_skills("go", VOCAB, ["Go 语言"])
    assert "Go 语言" not in res
