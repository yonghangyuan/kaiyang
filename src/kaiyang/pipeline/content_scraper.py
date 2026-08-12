"""开阳 (Kaiyang) — 内容刮削。

对 RSS 条目抓取完整文章正文，提取纯文本。
"""

from __future__ import annotations
import re, httpx


async def scrape_article(url: str) -> str | None:
    """抓取文章完整正文。返回纯文本，失败返回 None。"""
    try:
        async with httpx.AsyncClient(timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None

            html = resp.text

            # 尝试多种提取策略
            content = _extract_by_meta(html) or _extract_by_tags(html) or _extract_by_fallback(html)
            return content[:5000] if content else None
    except Exception:
        return None


def _extract_by_meta(html: str) -> str | None:
    """通过常见 HTML 结构提取正文。"""
    # 人民日报: <div class="article">
    patterns = [
        r'<div[^>]*class="[^"]*article[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*id="article[^"]*"[^>]*>(.*?)</div>',
        r'<article[^>]*>(.*?)</article>',
        r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*id="content[^"]*"[^>]*>(.*?)</div>',
    ]
    for p in patterns:
        m = re.search(p, html, re.DOTALL | re.IGNORECASE)
        if m:
            text = re.sub(r'<[^>]+>', ' ', m.group(1))
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 100:
                return text
    return None


def _extract_by_tags(html: str) -> str | None:
    """提取 <p> 标签聚集的区域。"""
    paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL)
    if len(paragraphs) < 3:
        return None
    texts = [re.sub(r'<[^>]+>', ' ', p).strip() for p in paragraphs]
    texts = [t for t in texts if len(t) > 20]
    return ' '.join(texts[:30]) if texts else None


def _extract_by_fallback(html: str) -> str:
    """全量去除标签后的文本。"""
    # 移除 script/style
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    # 取中间部分（通常正文在中间）
    if len(text) > 500:
        start = len(text) // 6
        text = text[start:start + 3000]
    return text
