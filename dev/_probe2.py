# -*- coding: utf-8 -*-
"""实测：devicestatus 的 location vs operate/polling 的 location 字段差异。"""
import asyncio, json, os, sys, time

ROOT = r"C:\Users\Administrator\WorkBuddy\2026-09-18-14-20-17\ha-vivo-find"
sys.path.insert(0, os.path.join(ROOT, "dev"))
import _loader as L

async def main():
    import aiohttp
    api = L.prepare_api()
    async with aiohttp.ClientSession() as sess:
        cli = api.VivoFindClient(sess, L.get_cookie())
        dev = await cli.async_resolve_device("")
        print("=" * 76)
        print("[1] devicestatus 返回的 location")
        raw = await cli.async_get_status(dev)
        vo = raw.get("deviceVO") or {}
        loc1 = vo.get("location") or {}
        print(json.dumps(loc1, ensure_ascii=False, indent=2))
        print("  locationDesc 存在?", "locationDesc" in loc1)

        print()
        print("=" * 76)
        print("[2] 下发定位指令（operate + polling）")
        t0 = time.time()
        try:
            loc2 = await cli.async_locate(dev)
            dt = time.time() - t0
            print(f"  耗时 {dt:.1f} 秒")
            print(json.dumps(loc2, ensure_ascii=False, indent=2))
            print("  locationDesc 存在?", "locationDesc" in loc2)
            if "locationDesc" in loc2:
                print("  地址:", loc2["locationDesc"])
        except Exception as e:
            dt = time.time() - t0
            print(f"  耗时 {dt:.1f} 秒  →  异常: {type(e).__name__}: {e}")

asyncio.run(main())
