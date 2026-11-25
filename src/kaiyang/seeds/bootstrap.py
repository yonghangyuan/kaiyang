"""种子数据引导：默认源注册 + 内置知识库种子（从 main.py 迁出）。"""
from __future__ import annotations

from ..db import async_session


async def seed_default_sources():
    """首次启动时注册默认 RSS 源。幂等——已存在则跳过。"""
    from sqlalchemy import select
    from ..models import Source, _new_id

    defaults = [
        # ═══ Tier 1 — 官方权威中文（2026-08-25 大清扫后新增，全国仅存的可 RSS 官方源） ═══
        {"name": "中国军网", "type": "rss", "url": "http://www.81.cn/rss.xml", "credibility_tier": 1},  # 军委政工部主办, 2096条活feed
        {"name": "中新网滚动", "type": "rss", "url": "https://www.chinanews.com.cn/rss/scroll-news.xml", "credibility_tier": 1},  # 国侨办背景通讯社, 30条滚动
        # ═══ Tier 1 — CGTN（2026-08-25: 6频道并为2个新鲜频道, 4个半死频道移除） ═══
        {"name": "CGTN World", "type": "rss", "url": "https://www.cgtn.com/subscribe/rss/section/world.xml", "credibility_tier": 1},
        {"name": "CGTN Politics", "type": "rss", "url": "https://www.cgtn.com/subscribe/rss/section/politics.xml", "credibility_tier": 1},
        {"name": "Ecns.cn", "type": "rss", "url": "http://www.ecns.cn/rss/rss.xml", "credibility_tier": 1},  # 中新社英文版, 最能打的源
        # ═══ Tier 2 — 中文科技/社区 ═══
        {"name": "爱范儿", "type": "rss", "url": "https://www.ifanr.com/feed", "credibility_tier": 2},
        {"name": "Solidot", "type": "rss", "url": "https://www.solidot.org/index.rss", "credibility_tier": 2},
        # ═══ Tier 1 — 实时API ═══
        {"name": "USGS Earthquakes", "type": "usgs", "url": "usgs", "credibility_tier": 1},
        {"name": "GDELT Global", "type": "gdelt", "url": "gdelt", "credibility_tier": 1},
        # ═══ Tier 2 — 国际（本机可达） ═══
        {"name": "France24", "type": "rss", "url": "https://www.france24.com/en/rss", "credibility_tier": 2},
        # ═══ Tier 2 — 欧洲风险监测（信源协议, 2026-08-13; 本机不可达待服务器复验） ═══
        {"name": "Politico Europe", "type": "rss", "url": "https://www.politico.eu/feed/", "credibility_tier": 2, "status": "paused"},
        {"name": "Euractiv", "type": "rss", "url": "https://www.euractiv.com/feed/", "credibility_tier": 2, "status": "paused"},
        {"name": "DW World", "type": "rss", "url": "https://rss.dw.com/rdf/rss-en-world", "credibility_tier": 2, "status": "paused"},
        # ═══ Tier 2 — AI 浪潮监测（信源协议, 2026-08-20, analysis/ai-wave-monitor.md） ═══
        {"name": "量子位", "type": "rss", "url": "https://www.qbitai.com/feed", "credibility_tier": 2, "status": "paused"},  # 2026-08-25: feed 需云环境, 本机验证失败
        {"name": "MIT TR AI", "type": "rss", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed", "credibility_tier": 2},
        {"name": "TechCrunch AI", "type": "rss", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "credibility_tier": 2},
        {"name": "VentureBeat AI", "type": "rss", "url": "https://venturebeat.com/category/ai/feed/", "credibility_tier": 2},
        {"name": "The Verge AI", "type": "rss", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "credibility_tier": 2},
        # ═══ 实时快讯（2026-10-29 实时门户）: live_text 源，走 60s 快通道 ═══
        # feed_tz_offset_hours=8: 快讯时间是 CST 墙上时间，入库由 time_norm 归一
        {"name": "金十快讯", "type": "live_text", "url": "jin10://flash",
         "credibility_tier": 2,
         "config": {"adapter": "jin10", "channel": -8200, "feed_tz_offset_hours": 8}},
        {"name": "东方财富快讯", "type": "live_text", "url": "eastmoney://kuaixun",
         "credibility_tier": 2,
         "config": {"adapter": "eastmoney", "list_id": 102, "feed_tz_offset_hours": 8}},
    ]

    # 2026-08-25 大清扫移除名单（不在 defaults 里 + 存在于库 → 删除或暂停）。
    # 删除: 0 数据纯僵尸（占位符/反爬挡死/存档僵尸）——无关联 intel，删了干净。
    # 暂停: 有历史数据但退出轮转的（半死频道/专题源降级）——数据保留可查。
    _retire_delete = [
        "CGTN",  # 占位符 url='c'
        "TASS",  # 占位符 url='t'
        "百度新闻", "百度新闻·欧洲风险", "百度新闻·AI算力政策", "百度新闻·AI税与自动化税", "百度新闻·AI治理与算法管理",  # 反爬挡死 0产出
        "知乎·UAP话题",  # 反爬 0产出
        "环球时报英文",  # 7天0产出
        "Euronews",  # 本机不可达, 非协议核心源
        "China Daily World", "China Daily China", "China Daily Opinion", "China Daily Business",  # 2017存档僵尸, 0新数据
        "Xinhua English",  # 2018存档僵尸
        "人民日报",  # feed停更14个月
    ]
    _retire_pause = [
        "知乎·韩真宇",  # 反爬基本挡死(7天1条), UAP专题降级为手动
        "CGTN China", "CGTN Business", "CGTN Tech", "CGTN Opinion",  # 半死频道(90%存档稿)退出轮转, 历史200条保留
    ]

    async with async_session() as db:
        for d in defaults:
            result = await db.execute(select(Source).where(Source.name == d["name"]))
            existing = result.scalar_one_or_none()
            if existing is None:
                db.add(Source(
                    id=_new_id("SRC"),
                    name=d["name"],
                    type=d["type"],
                    url=d["url"],
                    credibility_tier=d["credibility_tier"],
                    status=d.get("status", "active"),
                    # 种子源 tier 为人工策展结果，标记手动覆盖，
                    # 防止自动评估按域名规则改写（P0 修复）
                    config={**d.get("config", {}), "credibility_manual": True},
                ))
            else:
                # 迁移: 旧库中已存在的种子源补上手动覆盖标记
                existing_config = dict(existing.config or {})
                if not existing_config.get("credibility_manual"):
                    existing.config = {**existing_config, "credibility_manual": True}
        # 2026-10-29: 解析器只能拿到"墙上时间"的源 → 标注本地时区，
        # 入库时由 pipeline/time_norm 减去得到 UTC（aware feed 不需要）。
        _feed_tz = {
            "Ecns.cn": 8,
            "中国军网": 8,
            "人民网国际": 8,
            "央视新闻国际": 8,
        }
        # 2026-08-25 大清扫: 僵尸源删除 / 专题源暂停（幂等——不在名单里的不碰）
        result = await db.execute(select(Source))
        for s in result.scalars():
            if s.name in _retire_delete:
                await db.delete(s)
                continue
            if s.name in _retire_pause and s.status == "active":
                s.status = "paused"
            if s.name in _feed_tz:
                cfg = dict(s.config or {})
                if cfg.get("feed_tz_offset_hours") != _feed_tz[s.name]:
                    cfg["feed_tz_offset_hours"] = _feed_tz[s.name]
                    s.config = cfg
        await db.commit()


async def run_seeds() -> None:
    """启动时执行全部种子（幂等）。"""
    await seed_default_sources()
    from ..pipeline.seed_facilities import seed_facilities
    n = await seed_facilities()
    if n > 0: print(f"[开阳] 设施数据: {n} 个")
    from ..pipeline.seed_uap_disclosure import seed_uap_disclosure
    r = await seed_uap_disclosure()
    if sum(r.values()) > 0: print(f"[开阳] UAP 披露线知识库: {r}")
    from ..pipeline.seed_finance_distortion import seed_finance_distortion
    rf = await seed_finance_distortion()
    if sum(rf.values()) > 0: print(f"[开阳] 金融信息失真知识库: {rf}")
    from ..pipeline.seed_sanxingdui import seed_sanxingdui
    rs = await seed_sanxingdui()
    if sum(rs.values()) > 0: print(f"[开阳] 三星堆知识库: {rs}")
