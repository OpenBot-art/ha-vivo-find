# -*- coding: utf-8 -*-
"""诊断：地址为什么是空的 / 有多旧。

回答三个问题：
  1. 接口这一次到底给没给地址？（devicestatus 与 operate 分开看）
  2. 手里这个地址是哪一次定位的产物？
  3. 集成这一轮会打出什么 locate_status？

用法：python dev/check_address.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
import _loader as L  # noqa: E402

L.install_ha_stubs()
api = L.load_module("api")
coord = L.load_module("coordinator")
const = L.load_module("const")

TZ = timezone(timedelta(hours=8))


def when(ms):
    if not ms:
        return "（无）"
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%Y-%m-%d %H:%M:%S")


def rule(title):
    print()
    print("=" * 76)
    print(title)
    print("=" * 76)


LOCATE_HINT = {
    const.LOCATE_OK: "本轮定位成功（地址应当是新的）",
    const.LOCATE_THROTTLED: "本轮被限流 → 地址/位置只能是上一次的，等冷却后自动恢复",
    const.LOCATE_TIMEOUT: "本轮定位超时（设备可能没联网/关机）→ 沿用上一次",
    const.LOCATE_FAILED: "本轮定位失败 → 沿用上一次",
    const.LOCATE_SKIP_FIRST: "首轮避让（已有地址，主动跳过以避开限流窗口）",
    const.LOCATE_SKIP_COOLDOWN: "处于定位冷却窗口内 → 本轮没发指令",
    const.LOCATE_SKIP_OFFLINE: "设备离线 → 拿不到新位置/地址",
    const.LOCATE_SKIP_DISABLED: "「每次刷新下发定位指令」被关掉了 → 地址不会更新",
}


async def main() -> int:
    import aiohttp

    async with aiohttp.ClientSession() as sess:
        client = api.VivoFindClient(sess, L.get_cookie())
        device = await client.async_resolve_device("")

        rule("[1] devicestatus 里的 location（这是「缓存位置」）")
        raw = await client.async_get_status(device)
        vo = raw.get("deviceVO") or {}
        loc = vo.get("location") or {}
        print(json.dumps(loc, ensure_ascii=False, indent=2))
        desc_in_status = bool(loc.get("locationDesc"))
        print()
        print(f"  带地址吗？      {'有 ✅' if desc_in_status else '没有 ❌'}")
        print(f"  locationType    {loc.get('locationType')}   "
              f"execMsg={loc.get('execMsg')}")
        print(f"  定位时间        {when(loc.get('time'))}")
        print(f"  精度半径        {loc.get('radius')} 米")

        rule("[2] operate + polling（这是地址的唯一来源）")
        locate_ok = False
        try:
            fresh = await client.async_locate(device)
            locate_ok = bool(fresh.get("longitude"))
            print(json.dumps(fresh, ensure_ascii=False, indent=2))
            print()
            print(f"  带地址吗？  {'有 ✅' if fresh.get('locationDesc') else '没有 ❌'}")
        except api.VivoFindRateLimitError as err:
            print(f"  被限流：{err}")
            print("  → 这是可恢复的，等几分钟；地址只能沿用上一次的。")
        except api.VivoFindError as err:
            print(f"  失败：{err}")

        rule("[3] 结论")
        if desc_in_status or locate_ok:
            print("  接口当前**有能力**返回地址。")
        else:
            print("  接口当前拿不到地址（都在限流/失败）。")
        print()
        print("  关键规律：")
        print("    * 地址（locationDesc）只随「定位指令成功」返回；")
        print("    * 若手机自己上报过位置，会把那份带地址的记录**覆盖掉**")
        print("      （表现为 locationType=4、半径很小、没有 locationDesc）——")
        print("      这不是超时，是 vivo 侧两种定位来源轮流覆盖。")
        print("    * 集成会把上一次的有效地址留着，不会因为新数据没地址就清空。")
        print()
        print("  想立刻补一次地址：调用服务 vivo_find.locate_now")
        print("  （HA 里：开发者工具 → 服务 → VIVO 查找设备: 立刻定位）")

        rule("[4] HA 里该看哪几个属性")
        for key, text in LOCATE_HINT.items():
            print(f"  locate_status={key:22s} {text}")
        print()
        print("  address_age_s —— 地址距今多少秒（不是 fix_time；两者可能差很远）")
    return 0


sys.exit(asyncio.run(main()))
