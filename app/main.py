"""AI 求职助手 —— Streamlit 前端入口（导航外壳）。

- 左侧控制栏：登录/注册（弹层）+ 演示模式开关，置于导航链接之上（run_app 内 render_auth_sidebar）。
- 三个页面：「首页」「个人资料」「职位分析」（app/pages/*）。职位分析自动复用个人资料。
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
import app.storage as storage  # noqa: E402
from app.components.auth_sidebar import render_auth_sidebar  # noqa: E402
from app.pages import home as home_page  # noqa: E402
from app.pages import job_analysis as job_analysis_page  # noqa: E402
from app.pages import profile as profile_page  # noqa: E402


def run_app() -> None:
    storage.init_db()  # 首次运行即建表（幂等），否则登录会报 no such table
    st.set_page_config(page_title="AI 求职助手", layout="wide")
    auth.try_restore_login()  # 决策 #3：重启后自动恢复登录态

    # 侧边栏：登录区在上，导航链接在下（position="hidden" 下需手动渲染导航）
    with st.sidebar:
        render_auth_sidebar()
        st.divider()
        st.page_link(st.Page(home_page.render, url_path="home"), label="首页", icon="🏠")
        st.page_link(st.Page(profile_page.render, url_path="profile"), label="个人资料", icon="🧑")
        st.page_link(st.Page(job_analysis_page.render, url_path="job-analysis"), label="职位分析", icon="🔍")
        st.divider()
        st.checkbox("演示模式（无需 API Key）", value=True, key="demo")

    pg = st.navigation([
        st.Page(home_page.render, title="首页", icon="🏠", url_path="home", default=True),
        st.Page(profile_page.render, title="个人资料", icon="🧑", url_path="profile"),
        st.Page(job_analysis_page.render, title="职位分析", icon="🔍", url_path="job-analysis"),
    ], position="hidden")
    pg.run()


if __name__ == "__main__":
    run_app()
