"""Phase3 URL 读取 JD 测试（TDD）。

设计要点（与 Phase2 PDF 解析器同构：实现接口 + 复用 core.parsers，不碰 core）：
- 用 monkeypatch 把 _fetch_html / _fetch_with_playwright 替成可控返回值，
  直接验证「抓取 -> 抽正文 -> parse_jd_text -> JdInfo」的胶水逻辑（本项目新增代码）。
- 覆盖混合策略：HTTP 优先、内容不足/失败回退 Playwright、两者皆败抛错。
- 覆盖非法 URL 校验、HTML 正文抽取剥离 script/style。
"""
from __future__ import annotations

import pytest

from modules.jd_url import url_source as _urlmod
from modules.jd_url.url_source import UrlJdSource, _html_to_text, _select_jd_region

# 已知 JD 文本（用于验证 parse_jd_text 的胶水映射）
SAMPLE_JD = """
公司：字节跳动
岗位：后端开发工程师
工作城市：北京
岗位职责：负责服务端架构设计
任职要求：
- 精通 Python、MySQL、Redis
- 熟悉 Docker、Kubernetes 者优先
- 英语可作为工作语言
到岗时间：尽快到岗
"""

SAMPLE_HTML = (
    "<html><head><script>var x=1;</script><style>.a{color:red}</style></head>"
    "<body><h1>招聘</h1><script>track();</script><p>" + SAMPLE_JD + "</p></body></html>"
)


@pytest.fixture
def source() -> UrlJdSource:
    return UrlJdSource()


def _patch_fetchers(monkeypatch, html: str | None, pw_text: str | None):
    """把 HTTP 返回 html（或 None 表示失败），Playwright 返回 pw_text（或 None）。"""
    monkeypatch.setattr(
        UrlJdSource, "_fetch_html", lambda self, url: html
    )
    monkeypatch.setattr(
        UrlJdSource, "_fetch_with_playwright", lambda self, url: pw_text
    )


# ===== 1. HTTP 优先路径：内容足够时不走 Playwright =====
def test_http_first_when_content_sufficient(source, monkeypatch):
    # 测试样本正文较短，用构造参数调低阈值以验证「HTTP 内容足够」分支；
    # 真实 JD 页正文通常远超默认 300 字阈值。
    calls = {"pw": 0}
    src = UrlJdSource(min_text=50)
    monkeypatch.setattr(UrlJdSource, "_fetch_html", lambda self, url: SAMPLE_HTML)
    monkeypatch.setattr(
        UrlJdSource, "_fetch_with_playwright",
        lambda self, url: calls.__setitem__("pw", calls["pw"] + 1) or None,
    )
    jd = src.fetch("https://example.com/job/1")
    assert calls["pw"] == 0  # 没触发回退
    assert jd.source_url == "https://example.com/job/1"
    assert "后端开发工程师" in jd.raw_text
    assert jd.title == "后端开发工程师"
    assert jd.company == "字节跳动"
    assert jd.city == "北京"
    assert jd.prefers_immediate is True
    assert set(["Python", "MySQL", "Redis"]).issubset(set(jd.required_skills))
    assert set(["Docker", "Kubernetes"]).issubset(set(jd.preferred_skills))
    assert jd.required_languages  # 英语被识别


# ===== 2. Playwright 回退：HTTP 内容不足 =====
def test_playwright_fallback_when_http_insufficient(source, monkeypatch):
    # HTTP 返回的 HTML 抽出来几乎无正文（script 壳）
    monkeypatch.setattr(
        UrlJdSource, "_fetch_html",
        lambda self, url: "<html><script>app.bootstrap()</script></html>",
    )
    monkeypatch.setattr(
        UrlJdSource, "_fetch_with_playwright", lambda self, url: SAMPLE_JD
    )
    jd = source.fetch("https://example.com/job/2")
    assert jd.raw_text.strip() == SAMPLE_JD.strip()
    assert jd.title == "后端开发工程师"


# ===== 3. Playwright 回退：HTTP 直接失败（返回 None） =====
def test_playwright_fallback_when_http_fails(source, monkeypatch):
    monkeypatch.setattr(UrlJdSource, "_fetch_html", lambda self, url: None)
    monkeypatch.setattr(
        UrlJdSource, "_fetch_with_playwright", lambda self, url: SAMPLE_JD
    )
    jd = source.fetch("https://example.com/job/3")
    assert jd.source_url == "https://example.com/job/3"
    assert "后端开发工程师" in jd.raw_text


# ===== 4. 两者皆败：抛明确异常 =====
def test_fetch_raises_when_both_fail(source, monkeypatch):
    monkeypatch.setattr(UrlJdSource, "_fetch_html", lambda self, url: None)
    monkeypatch.setattr(
        UrlJdSource, "_fetch_with_playwright", lambda self, url: None
    )
    with pytest.raises(RuntimeError):
        source.fetch("https://example.com/job/4")


# ===== 5. 非法 URL 校验 =====
@pytest.mark.parametrize("bad", ["", "   ", "ftp://x.com", "not-a-url", "file:///etc/passwd"])
def test_invalid_url_raises(source, bad):
    with pytest.raises(ValueError):
        source.fetch(bad)


# ===== 6. HTML 正文抽取剥离 script/style =====
def test_html_to_text_strips_scripts():
    html = (
        "<html><head><script>var secret=1;</script><style>.x{color:red}</style></head>"
        "<body><p>岗位：测试工程师</p><script>evil();</script></body></html>"
    )
    text = _html_to_text(html)
    assert "岗位：测试工程师" in text
    assert "secret=1" not in text
    assert "evil();" not in text
    assert "color:red" not in text


# ===== 7. JD 正文抽取：剥离整站导航/页脚，只保留 JD 主体 =====
def test_extract_jd_text_ignores_nav_and_footer():
    """模拟 jobsdb 类页面：左侧/顶部导航与底部版权应被剔除，JD 正文（职责/要求）保留。"""
    html = """
    <html><body>
      <nav class="site-header"><a>Skip to content</a><a>Jobsdb</a><a>Open app</a>
        <a>Sign in</a><a>Job search</a><a>People search</a><a>Career advice</a>
        <a>Companies</a><a>Employer site</a></nav>
      <header class="topbar"><span>Hong Kong</span><span>English</span><span>中文</span></header>
      <main>
        <h1>Senior Backend Engineer</h1>
        <p>Company: Acme Technology Limited</p>
        <h2>Job Purpose</h2>
        <p>Lead the design of our core payment platform.</p>
        <h2>Responsibilities</h2>
        <ul><li>Build scalable microservices</li><li>Mentor junior engineers</li></ul>
        <h2>Requirements</h2>
        <ul><li>5+ years Python</li><li>Experience with Kubernetes</li></ul>
      </main>
      <footer class="site-footer"><a>Help centre</a><a>Contact us</a>
        <span>Copyright © 1998-2026, Jobsdb</span></footer>
    </body></html>
    """
    out = _select_jd_region(_html_to_text(html))
    # JD 正文保留
    assert "Senior Backend Engineer" in out
    assert "Job Purpose" in out
    assert "Responsibilities" in out
    assert "Requirements" in out
    assert "Kubernetes" in out
    # 整站框架噪声被剔除
    assert "Skip to content" not in out
    assert "Jobsdb" not in out
    assert "Sign in" not in out
    assert "Job search" not in out
    assert "Career advice" not in out
    assert "Employer site" not in out
    assert "Help centre" not in out
    assert "Copyright" not in out


# ===== 8. JD 正文抽取：繁体中文 + 多样化标题仍可命中 =====
def test_extract_jd_text_traditional_chinese():
    html = """
    <html><body>
      <div class="breadcrumb">首页 / 徵才</div>
      <article>
        <h1>資深前端工程師</h1>
        <h2>職位描述</h2>
        <p>負責公司核心產品的前端開發。</p>
        <h2>任职要求</h2>
        <p>熟悉 React；具備三年以上經驗。</p>
        <h2>福利</h2>
        <p>周休二日、三節獎金。</p>
      </article>
      <aside class="sidebar"><a>相關職缺</a><a>訂閱通知</a></aside>
    </body></html>
    """
    out = _select_jd_region(_html_to_text(html))
    assert "資深前端工程師" in out
    assert "職位描述" in out
    assert "任职要求" in out
    assert "React" in out
    # 侧栏噪声剔除
    assert "相關職缺" not in out
    assert "訂閱通知" not in out


# ===== 9. Playwright 退出阶段被强杀仍返回已抽到的正文 =====
class _FakePage:
    def __init__(self, text):
        self._t = text

    def goto(self, *a, **k):
        pass

    def evaluate(self, *a, **k):
        return self._t

    def content(self, *a, **k):
        # 模拟 page.content()：返回含正文的 HTML，供 _html_to_text 抽取
        return f"<html><body><p>{self._t}</p></body></html>"


class _FakeBrowser:
    def __init__(self, text):
        self._t = text

    def new_page(self):
        return _FakePage(self._t)

    def close(self):
        # 模拟沙箱钩子在退出阶段强杀子进程
        raise RuntimeError("simulated teardown kill")


class _FakeChromium:
    def __init__(self, text):
        self._t = text

    def launch(self, *a, **k):
        return _FakeBrowser(self._t)


class _FakePW:
    def __init__(self, text):
        self._t = text
        self.chromium = _FakeChromium(text)  # 真实 API：p.chromium 是对象，非方法

    def start(self):
        return self

    def stop(self):
        raise RuntimeError("simulated driver stop kill")


def test_fetch_with_playwright_swallows_teardown_error(source, monkeypatch):
    monkeypatch.setattr(_urlmod, "sync_playwright", lambda: _FakePW("职位：测试工程师"))
    out = source._fetch_with_playwright("https://example.com/job")
    assert out == "职位：测试工程师"


# ===== 10. HTTP 抓取：反爬/挑战页识别为失败（返回 None） =====
class _FakeResp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status


class _FakeRequests:
    def __init__(self, resp):
        self._resp = resp
        self.last_headers = None

    def get(self, url, headers=None, timeout=None):
        self.last_headers = headers
        return self._resp


def test_fetch_html_returns_none_on_blocked_page(source, monkeypatch):
    blocked = "<html><body>enable JavaScript to continue. verify you are human</body></html>"
    monkeypatch.setattr(_urlmod, "requests", _FakeRequests(_FakeResp(blocked)))
    assert source._fetch_html("https://hk.jobsdb.com/job/1") is None


def test_fetch_html_returns_html_on_normal_page(source, monkeypatch):
    monkeypatch.setattr(_urlmod, "requests", _FakeRequests(_FakeResp(SAMPLE_HTML)))
    assert source._fetch_html("https://example.com/job") == SAMPLE_HTML


def test_fetch_html_googlebot_retry_on_blocked(source, monkeypatch):
    """第一个 UA 命中反爬页时，应换 Googlebot UA 重试并成功。"""
    normal = (
        "<html><body><h1>岗位：后端工程师</h1>"
        "<p>负责服务端架构设计与开发，参与核心系统性能优化；精通 Python、MySQL、Redis；"
        "熟悉 Docker、Kubernetes；具备 5 年以上后端开发经验，有高并发系统经验者优先。</p>"
        "</body></html>"
    )

    class _UARequests:
        def __init__(self):
            self.calls = 0

        def get(self, url, headers=None, timeout=None):
            self.calls += 1
            if self.calls == 1:
                return _FakeResp("<html>enable javascript</html>")  # 第一次被反爬
            return _FakeResp(normal)

    fake = _UARequests()
    monkeypatch.setattr(_urlmod, "requests", fake)
    out = source._fetch_html("https://example.com/job")
    assert out == normal
    assert fake.calls == 2  # 普通 UA 失败 + Googlebot 重试


def test_fetch_raises_when_http_blocked_and_pw_fails(source, monkeypatch):
    blocked = "<html>verify you are human</html>"
    monkeypatch.setattr(_urlmod, "requests", _FakeRequests(_FakeResp(blocked)))
    monkeypatch.setattr(UrlJdSource, "_fetch_with_playwright", lambda self, url: None)
    with pytest.raises(RuntimeError):
        source.fetch("https://hk.jobsdb.com/job/1")
