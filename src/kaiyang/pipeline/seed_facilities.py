"""开阳 (Kaiyang) — 设施种子数据。

公开 OSINT 数据源:
  - 军事基地: Wikipedia, GlobalSecurity.org, SIPRI
  - 核设施: IAEA PRIS, Wikipedia
  - 港口/机场: OpenStreetMap, Wikipedia
"""

from __future__ import annotations
from ..db import async_session
from ..models import Facility

# 亚太地区关键设施 (公开可查)
SEED_DATA = [
    # === 军事基地 ===
    {"name":"横须贺海军基地","type":"military_base","country":"JP","lat":35.29,"lng":139.67,"desc":"美第七舰队母港","operator":"US Navy / JMSDF","threat":3},
    {"name":"关塔那摩湾海军基地","type":"military_base","country":"CU","lat":19.90,"lng":-75.15,"desc":"美海军基地","operator":"US Navy","threat":2},
    {"name":"迪戈加西亚基地","type":"military_base","country":"IO","lat":-7.31,"lng":72.42,"desc":"英美联合基地,印度洋战略枢纽","operator":"US/UK","threat":2},
    {"name":"冲绳嘉手纳空军基地","type":"military_base","country":"JP","lat":26.35,"lng":127.77,"desc":"美空军最大海外基地","operator":"USAF","threat":3},
    {"name":"关岛安德森空军基地","type":"military_base","country":"GU","lat":13.58,"lng":144.93,"desc":"美太平洋空军枢纽","operator":"USAF","threat":2},
    {"name":"巴林第五舰队基地","type":"military_base","country":"BH","lat":26.21,"lng":50.61,"desc":"美第五舰队司令部","operator":"US Navy","threat":4},
    {"name":"卡塔尔乌代德空军基地","type":"military_base","country":"QA","lat":25.12,"lng":51.32,"desc":"美中央司令部前沿基地","operator":"USAF","threat":3},
    {"name":"韩国乌山空军基地","type":"military_base","country":"KR","lat":37.09,"lng":127.03,"desc":"驻韩美空军基地","operator":"USAF","threat":4},
    {"name":"菲律宾苏比克湾","type":"military_base","country":"PH","lat":14.80,"lng":120.28,"desc":"美菲军事合作基地","operator":"PH Navy","threat":2},
    {"name":"新加坡樟宜海军基地","type":"military_base","country":"SG","lat":1.32,"lng":104.03,"desc":"东南亚重要海军设施","operator":"RSN","threat":2},
    {"name":"达尔文海军基地","type":"military_base","country":"AU","lat":-12.45,"lng":130.84,"desc":"澳北部海军枢纽,美海军陆战队轮驻","operator":"RAN / USMC","threat":2},
    {"name":"符拉迪沃斯托克海军基地","type":"military_base","country":"RU","lat":43.11,"lng":131.92,"desc":"俄太平洋舰队母港","operator":"Russian Navy","threat":3},
    {"name":"塞瓦斯托波尔海军基地","type":"military_base","country":"UA","lat":44.61,"lng":33.53,"desc":"俄黑海舰队基地","operator":"Russian Navy","threat":5},
    {"name":"塔尔图斯海军基地","type":"military_base","country":"SY","lat":34.91,"lng":35.87,"desc":"俄地中海唯一海军基地","operator":"Russian Navy","threat":4},
    {"name":"吉布提军事基地","type":"military_base","country":"DJ","lat":11.58,"lng":43.15,"desc":"多国军事基地(中/美/法/日)","operator":"Multi-national","threat":3},
    # === 核设施 ===
    {"name":"福岛第一核电站","type":"nuclear","country":"JP","lat":37.42,"lng":141.03,"desc":"2011年事故,退役中","operator":"TEPCO","threat":5},
    {"name":"扎波罗热核电站","type":"nuclear","country":"UA","lat":47.51,"lng":34.59,"desc":"欧洲最大核电站,冲突区","operator":"Energoatom","threat":5},
    {"name":"秦山核电站","type":"nuclear","country":"CN","lat":30.44,"lng":120.95,"desc":"中国首座自主设计核电站","operator":"CNNC","threat":1},
    {"name":"大亚湾核电站","type":"nuclear","country":"CN","lat":22.60,"lng":114.54,"desc":"中广核大型核电站","operator":"CGN","threat":1},
    {"name":"宁边核设施","type":"nuclear","country":"KP","lat":39.80,"lng":125.75,"desc":"朝鲜主要核设施","operator":"DPRK","threat":5},
    {"name":"布什尔核电站","type":"nuclear","country":"IR","lat":28.83,"lng":50.89,"desc":"伊朗首座核电站","operator":"NPPD","threat":4},
    {"name":"纳坦兹铀浓缩厂","type":"nuclear","country":"IR","lat":33.72,"lng":51.73,"desc":"伊朗主要铀浓缩设施","operator":"AEOI","threat":4},
    # === 战略港口 ===
    {"name":"上海港","type":"port","country":"CN","lat":31.35,"lng":121.60,"desc":"全球最大集装箱港口","operator":"SIPG","threat":1},
    {"name":"新加坡港","type":"port","country":"SG","lat":1.26,"lng":103.85,"desc":"全球第二大集装箱港口,马六甲海峡枢纽","operator":"PSA","threat":2},
    {"name":"釜山港","type":"port","country":"KR","lat":35.10,"lng":129.04,"desc":"韩国最大港口","operator":"BPA","threat":2},
    {"name":"高雄港","type":"port","country":"TW","lat":22.61,"lng":120.28,"desc":"台湾最大国际商港","operator":"TIPC","threat":2},
    {"name":"霍尔木兹海峡","type":"chokepoint","country":"IR","lat":26.57,"lng":56.25,"desc":"全球1/3石油运输通道","operator":"-","threat":5},
    {"name":"马六甲海峡","type":"chokepoint","country":"SG","lat":1.43,"lng":103.85,"desc":"全球最繁忙航运通道","operator":"-","threat":3},
    {"name":"苏伊士运河","type":"chokepoint","country":"EG","lat":30.58,"lng":32.27,"desc":"亚欧航运生命线","operator":"SCA","threat":3},
    {"name":"巴拿马运河","type":"chokepoint","country":"PA","lat":9.08,"lng":-79.68,"desc":"太平洋-大西洋通道","operator":"ACP","threat":2},
    # === 空间设施 ===
    {"name":"肯尼迪航天中心","type":"spaceport","country":"US","lat":28.57,"lng":-80.65,"desc":"NASA主要发射场","operator":"NASA","threat":1},
    {"name":"范登堡太空军基地","type":"spaceport","country":"US","lat":34.75,"lng":-120.52,"desc":"美军事/商业发射场","operator":"USSF","threat":2},
    {"name":"文昌航天发射场","type":"spaceport","country":"CN","lat":19.62,"lng":110.95,"desc":"中国最新航天发射场","operator":"CNSA","threat":1},
    {"name":"拜科努尔航天发射场","type":"spaceport","country":"KZ","lat":45.97,"lng":63.30,"desc":"俄罗斯主要发射场","operator":"Roscosmos","threat":2},
]


async def seed_facilities() -> int:
    """种子设施数据（幂等——跳过已存在的）。返回新增数量。"""
    from sqlalchemy import select
    added = 0
    async with async_session() as db:
        for d in SEED_DATA:
            result = await db.execute(select(Facility).where(Facility.name == d["name"]))
            if result.scalar_one_or_none() is None:
                from ..models import _new_id
                db.add(Facility(
                    id=_new_id("FC"), name=d["name"], facility_type=d["type"],
                    country_code=d["country"], lat=d["lat"], lng=d["lng"],
                    description=d["desc"], operator=d.get("operator",""),
                    threat_level=d.get("threat",1), source="public OSINT",
                ))
                added += 1
        if added > 0:
            await db.commit()
    return added
