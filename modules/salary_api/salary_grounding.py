"""薪资 grounding：把「真实市场薪资基准」注入 LLM 提示词，取代纯拍脑袋。

两条数据来源（可并存、互为兜底）：
1. 联网搜索（默认启用，无需 Key）：用 DuckDuckGo HTML 检索 "{role} {city} 薪资"，
   取前几条结果摘要作为上下文。免费、无需密钥，但可能被限流/被反爬拦截，故仅作增强。
   可用环境变量 SALARY_WEB_SEARCH=0 关闭（关闭后只走参考表）。
2. 结构化参考表 REFERENCE_TABLE（岗位族 × 城市档位 → 年化中位区间）：
   作为可靠锚点，确保即使联网失败也能给出贴近真实的区间，而非 LLM 凭空猜。

get_salary_context(role, city) 返回拼进提示词的上下文字符串。
"""
from __future__ import annotations

import os
import re
from typing import Optional, Tuple

try:
    import requests
except Exception:  # pragma: no cover - 导入失败由运行期报错暴露
    requests = None  # type: ignore

# 城市分档
_TIER1 = ("北京", "上海", "深圳", "广州", "杭州", "香港", "香港特別行政區", "HK", "Hong Kong")
_TIER2 = (
    "成都", "武汉", "西安", "南京", "苏州", "重庆", "天津", "长沙", "青岛", "宁波",
    "东莞", "无锡", "厦门", "合肥", "郑州", "沈阳",
)

# 岗位族关键词 -> (tier1_low, tier1_high, tier2_low, tier2_high, other_low, other_high) 年化 CNY
REFERENCE_TABLE = {
    "人力资源": (150000, 260000, 110000, 190000, 90000, 160000),
    "行政": (80000, 150000, 60000, 120000, 50000, 100000),
    "财务": (120000, 220000, 90000, 160000, 75000, 140000),
    "会计": (120000, 220000, 90000, 160000, 75000, 140000),
    "软件": (300000, 540000, 220000, 400000, 180000, 340000),
    "开发": (300000, 540000, 220000, 400000, 180000, 340000),
    "工程师": (300000, 540000, 220000, 400000, 180000, 340000),
    "产品": (300000, 520000, 220000, 380000, 180000, 320000),
    "运营": (180000, 320000, 130000, 240000, 110000, 200000),
    "设计": (180000, 320000, 130000, 240000, 110000, 200000),
    "数据": (260000, 460000, 190000, 340000, 160000, 300000),
    "分析": (260000, 460000, 190000, 340000, 160000, 300000),
    "销售": (150000, 360000, 120000, 280000, 100000, 240000),
    "市场": (200000, 380000, 150000, 280000, 120000, 240000),
    "营销": (200000, 380000, 150000, 280000, 120000, 240000),
    "客服": (80000, 150000, 60000, 120000, 50000, 100000),
    "法务": (240000, 480000, 180000, 340000, 150000, 300000),
    "供应链": (180000, 340000, 130000, 260000, 110000, 220000),
    "采购": (180000, 340000, 130000, 260000, 110000, 220000),
    "物流": (150000, 300000, 110000, 220000, 90000, 180000),
}
_DEFAULT_RANGE: Tuple[int, int, int, int, int, int] = (200000, 400000, 150000, 300000, 120000, 260000)

# 岗位族关键词（中英双语，按优先级从上到下匹配；越具体越靠前）
_FAMILY_KEYWORDS = {
    "人力资源": ["人力资源", "hr", "human resources", "recruit", "招聘", "人事", "人力"],
    "行政": ["行政", "administration", "assistant", "助理", "文员", "clerk", "secretary"],
    "财务": ["财务", "finance", "financial"],
    "会计": ["会计", "account", "accounting"],
    "软件": ["软件", "software"],
    "开发": ["开发", "developer", "develop"],
    "工程师": ["工程师", "engineer"],
    "产品": ["产品", "product"],
    "运营": ["运营", "operation", "ops"],
    "设计": ["设计", "design", "ui", "ux"],
    "数据": ["数据", "data"],
    "分析": ["分析", "analyst", "analysis"],
    "销售": ["销售", "sales", "sale"],
    "市场": ["市场", "marketing", "market"],
    "营销": ["营销", "marketing"],
    "客服": ["客服", "customer service", "support"],
    "法务": ["法务", "legal", "lawyer"],
    "供应链": ["供应链", "supply chain", "物流", "logistics"],
    "采购": ["采购", "purchase", "procurement"],
    "物流": ["物流", "logistics"],
}


def _web_search_enabled() -> bool:
    return os.getenv("SALARY_WEB_SEARCH", "1") != "0"


def _city_tier(city: Optional[str]) -> str:
    if not city:
        return "other"
    c = city.strip()
    if any(t in c for t in _TIER1):
        return "tier1"
    if any(t in c for t in _TIER2):
        return "tier2"
    return "other"


def _family_of(role: str) -> str:
    r = (role or "").lower()
    for fam, keys in _FAMILY_KEYWORDS.items():
        if any(k in r for k in keys):
            return fam
    return "通用"


def _reference_range(role: str, city: Optional[str]) -> Tuple[str, int, int]:
    fam = _family_of(role)
    table = REFERENCE_TABLE.get(fam, _DEFAULT_RANGE)
    tier = _city_tier(city)
    if tier == "tier1":
        lo, hi = table[0], table[1]
    elif tier == "tier2":
        lo, hi = table[2], table[3]
    else:
        lo, hi = table[4], table[5]
    return fam, lo, hi


def search_web_salary(role: str, city: Optional[str], timeout: float = 5.0) -> Optional[str]:
    """DuckDuckGo HTML 检索薪资摘要（best-effort，失败返回 None）。"""
    if requests is None or not _web_search_enabled():
        return None
    q = f"{role} {city or ''} 薪资 市场区间 月薪".strip()
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": q},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', resp.text, re.S)
        texts = []
        for s in snippets[:3]:
            clean = re.sub(r"<[^>]+>", "", s).strip()
            if clean:
                texts.append(clean)
        return "\n".join(texts) if texts else None
    except Exception:
        return None


def get_salary_context(role: str, city: Optional[str]) -> str:
    """返回拼进 LLM 提示词的薪资上下文（联网检索 + 参考表锚点）。"""
    fam, lo, hi = _reference_range(role, city)
    monthly_lo, monthly_hi = lo // 12, hi // 12
    tier = _city_tier(city)
    lines = [
        f"参考薪资基准（基于真实市场调研的区间锚点，岗位族={fam}，城市档位={tier}）：",
        f"年化约 {lo:,}–{hi:,} 元（折合月薪约 {monthly_lo:,}–{monthly_hi:,} 元）。",
    ]
    web = search_web_salary(role, city)
    if web:
        lines.append("联网检索到的近期薪资信息（供参考，可能含地区/经验差异）：")
        lines.append(web)
    lines.append("请在该基准附近估计，不要大幅偏离；高职级/多年经验可上调，初级/应届可下调。")
    return "\n".join(lines)
