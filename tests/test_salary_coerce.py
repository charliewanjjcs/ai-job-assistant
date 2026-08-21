"""薪资值规范化的单元测试（支撑「消除 float 传入 format=%d 告警」修复）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.state import coerce_int_salary


def test_coerce_none():
    assert coerce_int_salary(None) is None


def test_coerce_int_passthrough():
    assert coerce_int_salary(300000) == 300000
    assert isinstance(coerce_int_salary(300000), int)


def test_coerce_float_to_int():
    # 用户填入后 Streamlit 存为 float（如 300000.0），必须规范成 int 以消告警
    assert coerce_int_salary(300000.0) == 300000
    assert isinstance(coerce_int_salary(300000.0), int)


def test_coerce_non_integer_float_returns_none():
    assert coerce_int_salary(300000.5) is None


def test_coerce_nan_inf_none():
    assert coerce_int_salary(float("nan")) is None
    assert coerce_int_salary(float("inf")) is None
