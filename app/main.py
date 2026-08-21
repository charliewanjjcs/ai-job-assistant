"""AI 求职助手 —— Streamlit 前端入口（导航外壳）。

- 左侧控制栏：登录/注册（弹层）+ 演示模式开关，置于导航链接之上（run_app 内 render_auth_sidebar）。
- 三个页面：「首页」「个人资料」「职位分析」（app/views/*）。职位分析自动复用个人资料。
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
from app.views import home as home_page  # noqa: E402
from app.views import job_analysis as job_analysis_page  # noqa: E402
from app.views import profile as profile_page  # noqa: E402
from app.views import results as results_page  # noqa: E402


def _inject_global_style() -> None:
    """注入全局样式：护眼浅绿背景 + 主内容始终居中 + 输入框统一边框。

    主内容用 .block-container 设 max-width:1000px 并 margin:auto，
    无论左侧控制栏展开或收起，内容都在可用区域内居中（侧栏展开时主区变窄，
    1000px 仍小于通常主区宽度，故仍保持左右对称居中）。
    """
    st.markdown(
        """
        <style>
        html, body, .stApp { background-color: #eef2e9; }
        [data-testid="stAppViewContainer"] { background-color: #eef2e9; }
        [data-testid="stSidebar"] { background-color: #e6ecdd; }
        [data-testid="stHeader"] { background-color: #eef2e9; }
        /* 主内容始终居中（无论侧栏展开/收起）；并上移大标题。
           用 75vw（相对视口，固定）+ !important：展开/收起侧栏时方框**长度不变**、
           只整体平移位置（用 % 会随侧栏可用区变化导致方框被拉长/压缩）。
           !important 覆盖 Streamlit wide 布局自带样式，避免内容贴主区左边（“偏左”）。 */
        .block-container {
            max-width: 75vw !important;
            margin-left: auto !important;
            margin-right: auto !important;
            padding-left: 1rem;
            padding-right: 1rem;
            padding-top: 2rem;
        }
        /* 所有输入框统一加边框 + 白底，提升与护眼绿背景的对比度 */
        .stTextInput input,
        .stTextArea textarea,
        .stNumberInput input {
            border: 1px solid #9aa98a !important;
            border-radius: 6px !important;
            background-color: #ffffff !important;
        }
        .stSelectbox > div {
            border: 1px solid #9aa98a !important;
            border-radius: 6px !important;
        }
        [data-testid="stFileUploader"] > div {
            border: 1px solid #9aa98a !important;
            border-radius: 6px !important;
            padding: 0.5rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def run_app() -> None:
    storage.init_db()  # 首次运行即建表（幂等），否则登录会报 no such table
    st.set_page_config(page_title="AI 求职助手", layout="wide")
    _inject_global_style()
    auth.try_restore_login()  # 决策 #3：重启后自动恢复登录态

    # 侧边栏：登录区在上，导航链接在下（position="hidden" 下需手动渲染导航）
    with st.sidebar:
        render_auth_sidebar()
        st.divider()
        st.page_link(st.Page(home_page.render, url_path="home"), label="首页", icon="🏠")
        st.page_link(st.Page(profile_page.render, url_path="profile"), label="个人资料", icon="🧑")
        st.page_link(st.Page(job_analysis_page.render, url_path="job-analysis"), label="职位详情/JD", icon="🔍")
        st.page_link(st.Page(results_page.render, url_path="results"), label="分析结果", icon="📄")
        st.divider()
        st.checkbox("演示模式（无需 API Key）", value=True, key="demo")

    pg = st.navigation([
        st.Page(home_page.render, title="首页", icon="🏠", url_path="home", default=True),
        st.Page(profile_page.render, title="个人资料", icon="🧑", url_path="profile"),
        st.Page(job_analysis_page.render, title="职位详情/JD", icon="🔍", url_path="job-analysis"),
        st.Page(results_page.render, title="分析结果", icon="📄", url_path="results"),
    ], position="hidden")
    pg.run()


if __name__ == "__main__":
    run_app()
