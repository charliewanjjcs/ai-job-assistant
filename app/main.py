"""AI 求职助手 —— Streamlit 前端入口（导航外壳）。

- 左侧控制栏：登录/注册（弹层）+ 演示模式开关（由每个页面的 render_auth_sidebar 渲染）。
- 两个页面：「个人资料」「职位分析」（app/pages/*）。职位分析自动复用个人资料。
- 数据层在 app/state.py；持久化在 app/storage.py；登录态在 app/auth.py。

为保证 tests/test_app_logic.py（monkeypatch m.st.session_state）不破，本模块顶层保留
`import streamlit as st`，并把 build_profile/build_jd/on_jd_text_change 从 app.state re-export
到本命名空间。导航初始化仅放在 run_app()（__main__ 守卫），避免导入期触发 Streamlit 运行期调用。
"""
import os
import sys

# 确保项目根在 sys.path，便于 import core
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, "config", ".env"))

import streamlit as st

# 对外 re-export（保测试；test_app_logic 通过 m.st.session_state 注入）
from app.state import (  # noqa: E402
    AVAIL_OPTIONS,
    CURRENCY_LABELS,
    CURRENCY_VALUES,
    EXP_LABELS,
    LANG_OPTIONS,
    LEVEL_OPTIONS,
    PERIOD_LABELS,
    PERIOD_VALUES,
    DemoLLM,
    build_jd,
    build_profile,
    on_jd_text_change,
)
import app.auth as auth  # noqa: E402
from app.pages import job_analysis as job_analysis_page  # noqa: E402
from app.pages import profile as profile_page  # noqa: E402


def run_app() -> None:
    st.set_page_config(page_title="AI 求职助手", layout="wide")
    auth.try_restore_login()  # 决策 #3：重启后自动恢复登录态
    pg = st.navigation([
        st.Page(profile_page.render, title="个人资料", icon="🧑", default=True),
        st.Page(job_analysis_page.render, title="职位分析", icon="🔍"),
    ])
    pg.run()


if __name__ == "__main__":
    run_app()
