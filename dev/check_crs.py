# -*- coding: utf-8 -*-
"""诊断工具：判定 vivo 接口返回的坐标属于哪个坐标系。

什么时候用它
------------
换了城市、换了设备，或者地图上的点又偏了，跑这个脚本比靠猜快。
它做的事：
  1. 拉一次 vivo 当前数据，拿到 (坐标, 自报地址)；
  2. 把坐标按三种假设（WGS84 / GCJ-02 / BD-09）分别换算成"高德应该显示的 GCJ-02 点"；
  3. 用 vivo 自报地址去高德搜 POI，比较各 POI 到上述候选点的距离；
  4. 哪一种假设下 POI 系统性更近，接口就是哪种坐标系。

结论会直接告诉你 source_crs 该填什么。

用法：
    python dev/check_crs.py
"""
from __future__ import annotations

import asyncio
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))

import _loader  # noqa: E402

sys.path.insert(0, r"C:\Users\Administrator\.workbuddy\skills\gaode-map-pro__skillhub")

cr = _loader.load_module("crs")


def _dist_m(lng1, lat1, lng2, lat2):
    import math

    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


async def fetch_vivo():
    import aiohttp

    api = _loader.prepare_api()
    async with aiohttp.ClientSession() as sess:
        cli = api.VivoFindClient(sess, _loader.get_cookie())
        dev = await cli.async_resolve_device("")
        raw = await cli.async_get_status(dev)
    vo = raw.get("deviceVO") or {}
    return dev, (vo.get("location") or {})


def keywords_from(desc: str) -> list[str]:
    """从 locationDesc 里挑出可以拿去搜 POI 的词。

    典型格式：「武重四街坊，湖北省武汉市武昌区水果湖街道东湖路104号」
    取逗号前的地名 + 末尾的门牌地址。
    """
    out: list[str] = []
    if not desc:
        return out
    parts = [p.strip() for p in re.split(r"[，,]", desc) if p.strip()]
    if parts:
        out.append(parts[0])
    # 最后一段通常是"东湖路104号"这种门牌
    tail = re.search(r"([\u4e00-\u9fa5]{2,}(?:路|街|道|巷)\d+号?)", desc)
    if tail:
        out.append(tail.group(1))
    return list(dict.fromkeys(out))


async def main() -> int:
    print("=" * 74)
    print("vivo 坐标系诊断")
    print("=" * 74)

    dev, loc = await fetch_vivo()
    if not loc.get("longitude"):
        print("接口没有返回坐标，无法诊断。设备可能离线。")
        return 1

    lng, lat = float(loc["longitude"]), float(loc["latitude"])
    desc = loc.get("locationDesc") or ""

    print(f"  设备      : {dev.get('alias')} ({dev.get('model')})")
    print(f"  接口坐标  : {lng}, {lat}    半径 {loc.get('radius')} m")
    print(f"  自报地址  : {desc}")

    # 关键：key 是"假设接口返回的坐标系"，value 是"该假设下高德（GCJ-02 底图）应当显示的点"。
    #   - 若接口给 GCJ-02 → 真实位置的高德表示就是原值本身
    #   - 若接口给 WGS84  → 真实位置的高德表示是 wgs2gcj(原值)
    #   - 若接口给 BD-09  → 真实位置的高德表示是 bd09_to_gcj02(原值)
    # 于是"POI 离哪个候选最近，接口就是哪个坐标系"。
    cands = {
        cr.CRS_GCJ02: (lng, lat),
        cr.CRS_WGS84: cr.wgs84_to_gcj02(lng, lat),
        cr.CRS_BD09: cr.bd09_to_gcj02(lng, lat),
    }
    print("\n【若接口是 X 坐标系，高德（GCJ-02 底图）应当显示在这里】")
    for name, (a, b) in cands.items():
        print(f"  接口是 {name:6s} → 高德显示 {a:.6f}, {b:.6f}"
              f"   （距接口原值 {_dist_m(lng, lat, a, b):.0f} m）")

    try:
        import main as gd
    except Exception as exc:  # noqa: BLE001
        print(f"\n(无法加载高德技能，跳过 POI 对照：{exc})")
        return 0

    kws = keywords_from(desc)
    if not kws:
        print("\n自报地址为空，没法做 POI 对照。")
        return 0

    # 城市从自报地址里提取，换城市也能直接用。
    # 先剥掉省份（"湖北省武汉市…" → "武汉市…"），再非贪婪取到第一个"市"。
    tail = desc.split("省")[-1] if "省" in desc else desc
    city_match = re.search(r"([\u4e00-\u9fa5]{2,6}?市)", tail)
    city = city_match.group(1) if city_match else ""

    print(f"\n【用自报地址搜 POI，看哪个假设下更近】"
          f"  (搜索词: {' / '.join(kws)} | 城市: {city or '未指定'})")
    tally = {k: 0 for k in cands}
    checked = 0

    for kw in kws:
        res = gd.tool_poi_search({"keywords": kw, "city": city} if city else {"keywords": kw})
        pois = ((res or {}).get("data") or {}).get("pois") or []
        rows = []
        for p in pois[:5]:
            try:
                plng, plat = [float(x) for x in str(p["location"]).split(",")]
            except Exception:  # noqa: BLE001
                continue
            d = {k: _dist_m(plng, plat, *v) for k, v in cands.items()}
            rows.append((p.get("name"), plng, plat, d))
        if not rows:
            print(f"  「{kw}」无 POI 结果")
            continue

        print(f"\n  ■ 「{kw}」")
        for name, plng, plat, d in rows:
            best = min(d, key=d.get)
            print(
                f"     {str(name)[:24]:26s} 距 "
                f"WGS84={d[cr.CRS_WGS84]:5.0f}m  "
                f"GCJ02={d[cr.CRS_GCJ02]:5.0f}m  "
                f"BD09={d[cr.CRS_BD09]:5.0f}m   ← 最近: {best}"
            )
            tally[best] += 1
            checked += 1

    print("\n" + "=" * 74)
    if not checked:
        print("没有可用的 POI 参照点，无法给出结论。")
        return 0

    winner = max(tally, key=tally.get)
    total = sum(tally.values())
    print(f"统计：{total} 个候选点，最接近的假设分别为 {tally}")
    print(f"\n>>> 结论：vivo 接口返回的是 【{winner}】")
    print(f">>> 建议配置：source_crs = {winner}，target_crs = wgs84（HA 默认地图）")
    if winner == cr.CRS_GCJ02:
        gap = _dist_m(lng, lat, *cr.gcj02_to_wgs84(lng, lat))
        print(f">>> 若不转换（把 GCJ-02 直接当 WGS84 交给 HA），"
              f"地图上的点会偏约 {gap:.0f} 米。")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
