"""一次性信源扩军（2026-09-02，用户拍板"国内外大新闻网站都搞进去"）。

六轮网络探测的结论入库。规则:
  - 只收实测 HTTP 200 + feed 结构合法 + 最新条目 ≤7 天的源
  - tier 初判: 官方通讯社/国家级媒体=1, 国际权威媒体=2, 行业媒体=3
  - 每源 config 记 probe 结论 + admitted_via=source_expansion 溯源
  - 幂等: 按 URL 去重, 已存在的不动

本机网络边界(2026-09-02 实测, 全部 ConnectTimeout 的不收):
  BBC/Guardian/NYT/Reuters/AP/AlJazeera/DW/NHK/CNN/SCMP/RTHK/台媒/
  Google News 全系/RSSHub 官方/Euronews/TRT/Sputnik/TOI/Hindu——
  这些的内容通过 web_search 引擎链(cn.bing 转述)兜底覆盖。
"""

from __future__ import annotations

from sqlalchemy import select

from ..db import async_session
from ..models import Source, _new_id

# (name, url, tier, 说明)
NEW_SOURCES = [
    # ── France24 分频道 (域可达, 25条/频道) ──
    ("France24 中东", "https://www.france24.com/en/middle-east/rss", 2, "法广国际|中东线,法语视角补充美伊/以巴"),
    ("France24 亚太", "https://www.france24.com/en/asia-pacific/rss", 2, "亚太线,台海/朝鲜半岛报道"),
    ("France24 美洲", "https://www.france24.com/en/americas/rss", 2, "美洲线,美国国内事件外视角"),
    ("France24 法国", "https://www.france24.com/en/france/rss", 2, "法国国内,欧洲风险监测线"),
    # ── 美洲 ──
    ("NPR World", "https://feeds.npr.org/1004/rss.xml", 2, "美国公共广播国际线,无付费墙"),
    ("NPR National", "https://feeds.npr.org/1001/rss.xml", 2, "美国国内线——美国自然灾害主信源"),
    # ── 俄罗斯视角 ──
    ("塔斯社", "https://tass.com/rss/v2.xml", 2, "俄官方通讯社EN,58条/日,俄乌+全球俄方视角"),
    # ── 中东 ──
    ("耶路撒冷邮报", "https://www.jpost.com/rss/rssfeedsfrontpage.aspx", 3, "以色列主流媒体,以伊/以巴前线视角"),
    # ── 韩国 ──
    ("韩联社EN", "https://en.yna.co.kr/RSS/news.xml", 2, "韩官方通讯社,朝鲜半岛+东亚"),
    # ── 国内补充 ──
    ("环球时报EN", "https://www.globaltimes.cn/rss/outbrain.xml", 2, "环时英文版50条/日,中国官方视角外宣线"),
    ("IT之家", "https://www.ithome.com/rss/", 3, "国内科技,消费电子+供应链"),
    # ── 灾害/地质 ──
    ("GDACS 全球灾害", "https://www.gdacs.org/xml/rss.xml", 1, "欧盟全球灾害预警协调系统,地震/台风/洪水官方预警"),
    ("NOAA 美国气象预警", "https://api.weather.gov/alerts/active.atom", 1, "美国国家气象局活跃预警——美国飓风/山火/洪水实时官方源"),
    # ── 军事 ──
    ("Defense News", "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml", 3, "美国军事专业媒体,装备/军购/编制"),
]

# 恢复激活(曾因停机被误暂停, 复验活着)
REACTIVATE = {
    "中国军网": None,   # root rss 停在 8-19, 确认死, 不恢复——留 paused 等它复活
    "中新网滚动": None,  # active 且活
}


async def run() -> dict:
    stats = {"added": 0, "existing": 0, "reactivated": 0}
    async with async_session() as db:
        for name, url, tier, note in NEW_SOURCES:
            dup = (await db.execute(select(Source).where(Source.url == url))).scalar_one_or_none()
            if dup:
                stats["existing"] += 1
                continue
            db.add(Source(
                id=_new_id("SRC"), name=name, url=url, type="rss",
                credibility_tier=tier, status="active",
                config={"admitted_via": "source_expansion_2026_09_02",
                        "probe_note": note},
            ))
            stats["added"] += 1
        await db.commit()
    return stats


if __name__ == "__main__":
    import asyncio
    print(asyncio.run(run()))
