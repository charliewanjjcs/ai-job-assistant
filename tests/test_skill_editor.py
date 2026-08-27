"""app/components/skill_editor.py 的纯函数单元测试（不依赖 Streamlit 运行期）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.components.skill_editor import suggest_skills, skill_dedupe_key

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


# ── 技能去重键：连字符 / 复数 s 归一化，但不合并语义不同的技能 ──
def test_dedupe_key_hyphen_and_plural():
    # 连字符差异 → 同一键
    assert skill_dedupe_key("detail-oriented") == skill_dedupe_key("detail oriented")
    # 复数 s 差异 → 同一键
    assert skill_dedupe_key("attention to detail") == skill_dedupe_key("attention to details")
    # 语义不同 → 不同键
    assert skill_dedupe_key("detail-oriented") != skill_dedupe_key("attention to detail")
    # 大小写不敏感
    assert skill_dedupe_key("Excel") == skill_dedupe_key("excel")


def test_suggest_dedups_near_duplicate_candidates():
    vocab = ["detail-oriented", "detail oriented", "attention to detail", "attention to details"]
    res = suggest_skills("detail", vocab, [])
    # 近重复去重后只剩两个：detail-oriented 与 attention to detail（保留词库中先出现的写法）
    assert res == ["detail-oriented", "attention to detail"]


def test_suggest_excludes_existing_by_dedupe_key():
    vocab = ["detail-oriented", "detail oriented", "attention to detail"]
    # 已加 detail oriented，则 detail-oriented / detail oriented 都不再候选（连字符归一）
    res = suggest_skills("detail", vocab, ["detail oriented"])
    assert "detail-oriented" not in res
    assert "detail oriented" not in res
    assert "attention to detail" in res

