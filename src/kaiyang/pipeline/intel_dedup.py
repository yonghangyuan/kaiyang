"""开阳 (Kaiyang) — intel 层跨源/跨版本规范化去重门。

2026-09-02 重复展示案例的三类根因（都不在原精确-id 去重的覆盖面）:
  1. GDACS 同事件小时级更新: url 同, pub 每次不同 → hash 不同 → 10条同题
  2. NOAA CAP 版本号: 同一警报 url 尾巴 .001→.005 五个版本 → 5条同题
  3. 中新跨频道分发: 同一新闻在滚动+社会两频道, source_id 不同 → hash 必不同

方案: 入库前(_store_items 内, url_trust 之后)按 指纹 = norm_url + norm_title
查重, 命中则并入已有条目(corroboration+1, 保留最早一条), 不新建。

norm_url:  剥查询串/fragment; 剥已知版本尾巴(CAP .NNN.1.cap); 小写域名
norm_title: 去空白/标点, 全角→半角, 小写——"同一条新闻跨源改写"由
            事件聚合层的语义去重兜底, 这里只杀"完全同题"。
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

# CAP 警报版本尾巴: urn:...ef.003.1.cap → urn:...ef
_CAP_VER = re.compile(r"(\.\d{3}\.\d(?:\.cap)?)$", re.IGNORECASE)
# GDACS report.aspx?eventtype=WF&eventid=10313 → 事件id保留即可(查询串里只留 eventid)
_WS = re.compile(r"\s+")
# 标点集: 中英文常用标点(弯引号由 NFKC 处理不到, 但改写场景极少, 忽略)
_PUNCT_CHARS = "，。！？；：、（）【】《》〈〉「」『』[]()<>\"'.,!?;:~·—-_|/\\ \t"
_PUNCT = re.compile("[" + re.escape(_PUNCT_CHARS) + "]+")


def _strip_punct(s: str) -> str:
    return _PUNCT.sub("", s)


def normalize_url(url: str) -> str:
    """URL → 规范指纹形态。"""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = (parts.netloc or "").lower()
    path = parts.path or ""
    # CAP 版本尾巴剥掉
    path = _CAP_VER.sub("", path)
    query = parts.query or ""
    if "eventid=" in query:
        # GDACS 系: 只留事件 id（eventtype+eventid 定位事件本体）
        m = re.search(r"eventid=(\w+)", query)
        et = re.search(r"eventtype=(\w+)", query)
        query = f"eventtype={et.group(1)}&eventid={m.group(1)}" if (m and et) else ""
    else:
        query = ""   # 其余查询参数(u
    return urlunsplit(("", host, path, query, ""))


def normalize_title(title: str) -> str:
    """标题 → 规范指纹形态。"""
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", title)      # 全角→半角
    t = t.lower()
    t = _strip_punct(t)
    t = _WS.sub("", t)
    return t.strip()


def intel_fingerprint(url: str, title: str) -> str:
    """条目指纹: norm_url#norm_title。"""
    return f"{normalize_url(url)}#{normalize_title(title)}"


async def check_duplicate(session, fingerprint: str) -> str | None:
    """查指纹是否已入库。返回已有条目 id（=重复）或 None。

    用 SQLite JSON1 的 json_extract 精确取 raw_data.fp——比 LIKE 匹配
    JSON 文本可靠(序列化空格不定), 且同样走全表扫不建索引。
    """
    from sqlalchemy import select, text
    from ..models import IntelItem
    row = (await session.execute(
        select(IntelItem.id)
        .where(text("json_extract(raw_data, '$.fp') = :fp"))
        .order_by(IntelItem.fetched_at.asc())
        .limit(1),
        {"fp": fingerprint},
    )).scalar_one_or_none()
    return row
