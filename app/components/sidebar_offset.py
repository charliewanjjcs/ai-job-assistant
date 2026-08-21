"""为「个人资料」「职位详情/JD」两页做**标题字符级精准对齐**。

做法：注入一段 CSS（`:has()` 按侧栏 `aria-expanded` 切换 `transform: translateX(var(--dx-*))`，
随页导航自动清除）+ 一段 JS（`components.html`，在 iframe 内用 `window.parent.document` 操作父页面）。

JS 用 `document.createRange()` 精确测量标题里某字符相对 `.block-container` 左缘的偏移（**与侧栏
状态、平移无关**），再按「块固定宽 W、在可用区内居中」的几何关系，一次性算出展开/收起两个平移量：

    delta = (pct - 0.5) * vw + (W - S) / 2 - charX

- `pct`：目标字符中心要放到的**视口百分比**（0=最左、0.5=正中心、1=最右）。
- `W`：内容板固定宽度（75vw）；`S`：侧栏宽度（收起=0、展开=实测）；`charX`：字符相对块左缘偏移。

侧栏切换时 `:has()` 纯 CSS 在同一次样式重算里切换两个偏移，**无 JS 轮询、无重排竞态、无跳变**。

⚠️ 每个页面用**独立的 CSS 变量名**（`--dx-{name}-expanded/collapsed`）：因为变量写在 `<html>` 上、
会跨 SPA 导航残留，若共享变量名，从 A 页切到 B 页时 B 页会短暂套用 A 页的旧偏移。
"""
import json

import streamlit as st
import streamlit.components.v1 as components

_CSS_TMPL = """
<style>
.stApp:has([data-testid="stSidebar"][aria-expanded="true"]) .block-container {
  transform: translateX(var(--dx-%NAME%-expanded, 0px));
}
.stApp:has([data-testid="stSidebar"][aria-expanded="false"]) .block-container {
  transform: translateX(var(--dx-%NAME%-collapsed, 0px));
}
</style>
"""

_JS_TMPL = """
<script>
(function () {
  var CONFIG = %CONFIG%;
  var NAME = "%NAME%";
  var doc, win;
  try { doc = window.parent.document; win = window.parent; } catch (e) { return; }

  function getTitle() { return doc.querySelector('.block-container h2, .block-container h1'); }
  function getBlock() { return doc.querySelector('.block-container'); }
  function sidebarEl() { return doc.querySelector('[data-testid="stSidebar"]'); }
  // Streamlit 把 h2 的标题文字包在第一个 <span> 里，取其中的文本节点
  function titleTextNode(el) {
    if (!el) return null;
    var span = el.querySelector('span');
    var n = (span && span.firstChild) ? span.firstChild : el.firstChild;
    return (n && n.nodeType === 3) ? n : null;
  }
  // 标题第 i 个字符（UTF-16 索引）左边界在视口中的 x 坐标
  function boundary(el, i) {
    var n = titleTextNode(el);
    if (!n) return el.getBoundingClientRect().left;
    var r = doc.createRange();
    r.setStart(n, 0);
    r.setEnd(n, Math.max(0, Math.min(i, n.length)));
    return r.getBoundingClientRect().right;
  }
  // 字符中心相对 .block-container 左缘的偏移（与侧栏状态、translateX 无关）
  function charCenterInBlock(el, i) {
    var cx = (boundary(el, i) + boundary(el, i + 1)) / 2;
    return cx - getBlock().getBoundingClientRect().left;
  }

  var SBW = 300;  // 缓存的「展开态」侧栏宽度（px），首次展开时实测更新

  function compute() {
    var t = getTitle(), bc = getBlock();
    if (!t || !bc) return false;
    var root = doc.documentElement;
    var vw = win.innerWidth || 1280;
    var sb = sidebarEl();
    var S = (sb && sb.getAttribute('aria-expanded') === 'true') ? sb.getBoundingClientRect().width : 0;
    if (S > 0) SBW = S;
    var W = bc.getBoundingClientRect().width;  // 固定块宽（75vw）

    // 把第 index 个字符的中心放到视口 pct 位置；Sx=该状态的侧栏宽
    function deltaFor(cfg, Sx) {
      var charX = charCenterInBlock(t, cfg.index);
      return (cfg.pct - 0.5) * vw + (W - Sx) / 2 - charX;
    }

    root.style.setProperty('--dx-' + NAME + '-expanded', deltaFor(CONFIG.expanded, SBW) + 'px');
    root.style.setProperty('--dx-' + NAME + '-collapsed', deltaFor(CONFIG.collapsed, 0) + 'px');
    return true;
  }

  // 初次轮询直到标题/块渲染就绪（父页面渲染可能晚于本 iframe）
  var tries = 0;
  var init = setInterval(function () { if (compute() || ++tries > 200) clearInterval(init); }, 100);
  // 块尺寸变化（侧栏切换/侧栏拖拽/视口缩放）→ 重算。ResizeObserver 在重排完成后触发，无竞态。
  var bc0 = getBlock();
  if (bc0 && win.ResizeObserver) {
    new win.ResizeObserver(function () { compute(); }).observe(bc0);
  }
  win.addEventListener('resize', function () { setTimeout(compute, 120); });
})();
</script>
"""


def inject_content_offset(expanded, collapsed, name):
    """注入标题字符级对齐。

    expanded / collapsed：`{'index': int, 'pct': float}` —— 把标题第 `index` 个字符的中心
    放到视口 `pct`（0~1）处。`name`：本页唯一标识（用于隔离 CSS 变量名，防跨页残留）。
    """
    config = json.dumps({"expanded": expanded, "collapsed": collapsed}, ensure_ascii=False)
    css = _CSS_TMPL.replace("%NAME%", name)
    js = _JS_TMPL.replace("%CONFIG%", config).replace("%NAME%", name)
    st.markdown(css, unsafe_allow_html=True)
    components.html(js, height=0)
