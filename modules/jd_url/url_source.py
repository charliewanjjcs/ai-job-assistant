"""URL 读取 JD（Phase3「肉」）。

实现 core.interfaces.JdSource：
- fetch(url): url -> JdInfo
- 内部混合策略：HTTP 优先（requests 抓取 + 纯 stdlib 抽取正文），
  当正文不足或抓取失败时才回退 Playwright 无头浏览器渲染后再抽正文
- 复用 core.parsers.parse_jd_text 把网页正文转成结构化字段，再组装成 JdInfo
- 不修改 core，仅调用其公开接口（严守「沙盒」原则）

降级与异常处理：
- 非法 URL（非 http/https 或空）-> ValueError，由调用方（前端）提示
- HTTP 与 Playwright 均失败 -> RuntimeError，由调用方捕获并提示用户检查链接
- 仅 import 失败的库做软降级（requests / playwright 缺失时跳过对应路径）
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import urlparse

from core.interfaces import JdSource
from core.models import JdInfo
from core.parsers import parse_jd_text

try:
    import requests
except Exception:  # pragma: no cover - 导入失败由运行期报错暴露
    requests = None  # type: ignore

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - 导入失败由运行期报错暴露
    sync_playwright = None  # type: ignore

# 抽出的正文低于该字符数视为「内容不足」，触发 Playwright 回退
_HTML_MIN_TEXT = 300

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# 更完整的请求头，降低被站点按「空 UA / 非浏览器」直接拒掉的概率
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
# 反爬 / JS 挑战页特征：命中即视为抓取失败，直接走回退/报错
_BLOCKED_MARKERS = (
    "enable javascript", "enable your javascript", "verify you are human",
    "checking your browser", "just a moment", "confirm you are human",
    "security check", "ddos protection", "cf-chl", "are you a robot",
    "人机验证", "请开启 javascript", "请启用 javascript", "浏览器检查",
)
_GOOGLEBOT_UA = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)


def _is_blocked_page(html: str) -> bool:
    """页面是否为反爬挑战页 / JS 空壳（无可用正文）。"""
    if not html:
        return True
    low = html.lower()
    if any(m in low for m in _BLOCKED_MARKERS):
        return True
    # 抽出的可见正文极少（基本是空壳/挑战页）也视为失败
    return len(_html_to_text(html)) < 50


class _TextExtractor(HTMLParser):
    """从 HTML 抽取可见正文文本。

    - 跳过 script/style/head/noscript/svg/iframe，以及整块导航与页脚（nav/header/footer/aside）
    - 跳过 class/id 命中噪声关键词（nav/header/footer/menu/sidebar/cookie/banner…）的元素
      这样能滤掉「Skip to content / Sign in / Job search / Career advice / Copyright」等整站框架文本
    """

    _SKIP_TAGS = {"script", "style", "head", "noscript", "svg", "iframe",
                  "nav", "header", "footer", "aside"}
    _BREAK_TAGS = {"br", "p", "div", "li", "tr", "section", "article", "main",
                   "td", "h1", "h2", "h3", "h4", "h5", "h6"}
    # class/id 含以下片段的元素整体丢弃（大小写不敏感）
    _DROP_CLASS_HINTS = (
        "nav", "header", "footer", "menu", "sidebar", "cookie", "banner",
        "breadcrumb", "toolbar", "share", "advert", "popup", "modal",
        "skip", "utility", "site-", "topbar", "subnav",
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._skip = 0
        self._stack: List[tuple[str, str]] = []  # [(tag, class_lower), ...]
        self._in_drop = 0

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "") or ""
        classes_low = classes.lower()
        self._stack.append((tag, classes_low))
        if tag in self._SKIP_TAGS:
            self._skip += 1
        if self._skip == 0 and any(h in classes_low for h in self._DROP_CLASS_HINTS):
            self._in_drop += 1
        if tag in self._BREAK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if self._stack:
            t, c = self._stack[-1]
            if t == tag:
                if self._in_drop > 0 and any(h in c for h in self._DROP_CLASS_HINTS):
                    self._in_drop -= 1
                self._stack.pop()
        if tag in self._SKIP_TAGS and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip == 0 and self._in_drop == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return re.sub(r"\n{2,}", "\n", "".join(self._parts)).strip()


def _html_to_text(html: str) -> str:
    """把 HTML 字符串转成可见正文文本（已剥离导航/页脚等框架噪声）。"""
    if not html:
        return ""
    # 非 HTML（已是纯文本）直接返回
    if "<" not in html:
        return html.strip()
    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text()


# 用于定位 JD 正文区域的多语言关键词（简体/繁体中文 + 英文，覆盖多样化表达）
_JD_KEYWORDS = (
    # English
    "responsibilit", "requirement", "qualification", "experience", "skill",
    "job purpose", "about the role", "about this role", "the role", "role purpose",
    "what you'll do", "what you will do", "what we offer", "what you need",
    "what we're looking for", "what we are looking for", "duties",
    "key accountabilities", "accountabilities", "essential", "preferred",
    "nice to have", "job description", "position description", "about us",
    # 简体中文
    "职责", "要求", "资格", "经验", "技能", "职位描述", "岗位", "任职",
    "工作职责", "职位", "招聘", "到岗", "薪资", "福利", "语言", "工作地点",
    # 繁体中文
    "職責", "要求", "資格", "經驗", "技能", "職位描述", "崗位", "任職",
    "工作職責", "職位", "招募", "應徵", "到崗", "薪資", "福利", "語言", "工作地點",
)


def _score_block(block: str) -> int:
    low = block.lower()
    return sum(1 for kw in _JD_KEYWORDS if kw.lower() in low)


def _select_jd_region(text: str) -> str:
    """从抽取出的正文里挑出 JD 主体区域。

    策略：
    - 短文本（<1500 字）且命中任一 JD 关键词 -> 直接整体返回（已是单页 JD）
    - 否则按换行切块，用滑动窗口选出「关键词得分最高、其次最长」的连续区块，
      再向前多纳入 2 块以保留职位标题/公司名等表头；完全无命中则回退到最长块。
    """
    if not text:
        return ""
    text = text.strip()
    if len(text) < 1500 and _score_block(text) >= 1:
        return text
    blocks = [b.strip() for b in re.split(r"\n", text) if b.strip()]
    if not blocks:
        return text
    scores = [_score_block(b) for b in blocks]
    best_score, best_start, best_end, best_len = 0, 0, 0, 0
    n = len(blocks)
    for i in range(n):
        s = 0
        for j in range(i, min(n, i + 80)):
            s += scores[j]
            if s > 0:
                length = sum(len(blocks[k]) for k in range(i, j + 1))
                if s > best_score or (s == best_score and length > best_len):
                    best_score, best_start, best_end, best_len = s, i, j, length
    if best_score == 0:
        return max(blocks, key=len)
    start = max(0, best_start - 2)  # 向前纳入表头（职位标题/公司）
    return "\n".join(blocks[start:best_end + 1]).strip()


class UrlJdSource(JdSource):
    """从 JD 链接抓取并解析为 JdInfo（HTTP 优先 + Playwright 回退）。"""

    def __init__(self, min_text: int = _HTML_MIN_TEXT, timeout: float = 20.0) -> None:
        self.min_text = min_text
        self.timeout = timeout

    # ── 公开接口 ──────────────────────────────────────────────
    def fetch(self, url: str) -> JdInfo:
        """url -> JdInfo。混合策略：HTTP 优先，不足则 Playwright 回退。"""
        self._validate_url(url)
        url = url.strip()

        text: Optional[str] = None
        html = self._fetch_html(url)
        if html:
            candidate = _select_jd_region(_html_to_text(html))
            # 命中 JD 关键词即视为有效，避免短 JD 被误判「内容不足」去拉浏览器
            if len(candidate) >= self.min_text or _score_block(candidate) >= 1:
                text = candidate
        if not text:
            fallback = self._fetch_with_playwright(url)
            if fallback:
                # _fetch_with_playwright 已返回抽取后的 JD 正文
                candidate = fallback
                if len(candidate) >= self.min_text or _score_block(candidate) >= 1:
                    text = candidate

        if not text:
            raise RuntimeError(
                f"无法从链接读取 JD 内容（该站点可能启用了反爬或需要 JavaScript 渲染）。"
                f"请检查链接，或直接粘贴 JD 文本：{url}"
            )

        parsed = parse_jd_text(text)
        return JdInfo(
            title=parsed.get("title"),
            company=parsed.get("company"),
            city=parsed.get("city"),
            required_skills=parsed.get("required_skills") or [],
            preferred_skills=parsed.get("preferred_skills") or [],
            required_languages=parsed.get("required_languages") or [],
            prefers_immediate=parsed.get("prefers_immediate", False),
            raw_text=text,
            source_url=url,
        )

    # ── 内部：校验 ─────────────────────────────────────────────
    def _validate_url(self, url: str) -> None:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("JD 链接必须为非空字符串")
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("仅支持 http/https 链接")

    # ── 内部：HTTP 优先 ─────────────────────────────────────────
    def _fetch_html(self, url: str) -> Optional[str]:
        """HTTP GET 抓取 HTML；失败 / 4xx-5xx / 反爬挑战页 均返回 None。

        先普通浏览器 UA；若被测为反爬页/空壳，再用 Googlebot UA 重试一次
        （部分站点对爬虫 UA 返回不同内容）。两路都拿不到可用正文则返回 None。
        """
        if requests is None:
            return None
        for ua in (_USER_AGENT, _GOOGLEBOT_UA):
            try:
                resp = requests.get(
                    url, headers={**_HEADERS, "User-Agent": ua}, timeout=self.timeout
                )
            except Exception:
                continue
            if resp.status_code >= 400:
                continue
            html = resp.text or ""
            if _is_blocked_page(html):
                continue
            return html
        return None

    # ── 内部：Playwright 回退 ────────────────────────────────────
    def _fetch_with_playwright(self, url: str) -> Optional[str]:
        """无头 Chromium 渲染后取可见正文；失败返回 None。

        注：部分环境（如带进程清理钩子的沙箱）会在浏览器/驱动退出阶段强杀子进程，
        导致 close() 抛错。这里「先抽取文本、再用吞错方式收尾」，且 return 放在 finally
        之外，确保即便退出阶段抛错也已拿到正文、不会被覆盖成 None。
        """
        if sync_playwright is None:
            return None
        extracted: Optional[str] = None
        p = None
        browser = None
        try:
            p = sync_playwright().start()
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
            page = browser.new_page()
            page.goto(url, timeout=self.timeout * 1000, wait_until="networkidle")
            # 取完整 HTML，抽取为 JD 正文（剥离导航/页脚）后返回
            html = page.content()
            extracted = _select_jd_region(_html_to_text(html)) or ""
        except Exception:
            return None
        finally:
            # 防御性收尾：退出阶段可能被强杀，吞掉所有错误，绝不连累已抽到的正文
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass
            try:
                if p is not None:
                    p.stop()
            except Exception:
                pass
        return extracted or ""
