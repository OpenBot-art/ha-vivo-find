# -*- coding: utf-8 -*-
"""用真实 vivo 接口验证「HA 重启后首轮数据不全」的修复。

走一遍完整时序：
  1. 打印接口当前真实状态（很可能正处限流，电量/网络为空 —— 这正是问题现场）
  2. 塞一份「上次成功」的完整缓存，模拟关机前最后一次刷新落了盘
  3. 新建 coordinator（= 重启）→ async_restore() 恢复缓存
  4. 用真实接口刷一轮 → 看电量/位置是否被缓存补齐
  5. 对照：新 coordinator 不带缓存，同样刷一轮 → 看缺什么

用法：venv/Scripts/python.exe dev/check_restart.py
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _loader as L  # noqa: E402

L.install_ha_stubs()
coord = L.load_module("coordinator")
const = L.load_module("const")
api = L.prepare_api()

ENTRY_ID = "check_restart"


class ThrottledStatusClient(api.VivoFindClient):
    """把 devicestatus 的电量/网络抹掉，精确复现 vivo 限流时的响应。

    实测（2026-09-18）：限流时 vivo 返回**空的 batteryInfo / signalInfo，
    但 code 正常、不报错** —— 这是最难查的一种响应：看起来一切正常，
    实际什么都没读到。位置字段仍然有值（那是上一次定位的缓存）。
    """

    async def async_get_status(self, device):
        data = await super().async_get_status(device)
        data["batteryInfo"] = {}
        data["signalInfo"] = {}
        return data


def rule(title: str) -> None:
    print()
    print("=" * 76)
    print(title)
    print("=" * 76)


def describe(data) -> str:
    return coord._describe(data)


async def main() -> None:
    import aiohttp

    # 先自检：api 与 coordinator 必须引用同一批异常类，否则 except 接不住，
    # 会让人误以为集成代码有问题（这个坑踩过一次，见 _loader.load_module 注释）
    same_classes = (
        coord.VivoFindRateLimitError is api.VivoFindRateLimitError
        and coord.VivoFindAuthError is api.VivoFindAuthError
        and coord.VivoFindConnectionError is api.VivoFindConnectionError
    )
    print(f"桩自检 — 异常类一致: {'是' if same_classes else '否 ← 测试脚本有问题'}")
    if not same_classes:
        raise SystemExit("测试桩加载异常，先修 dev/_loader.py")

    cookie = L.get_cookie()
    entry = L.FakeEntry(entry_id=ENTRY_ID, title="iQOOO")
    entry.data.update(
        {
            const.CONF_DEVICE_IMEI: "860000000000000",
            const.CONF_DEVICE_EMMCID: "EMMC-TEST",
            const.CONF_DEVICE_ALIAS: "iQOOO",
            const.CONF_DEVICE_MODEL: "iQOO Neo10 Pro",
        }
    )

    async with aiohttp.ClientSession() as session:
        # ---------- 1. 当前真实状态 ----------
        rule("[1] 接口当前真实状态")
        probe = coord.VivoFindCoordinator(hass=None, entry=entry)
        probe.client = api.VivoFindClient(session, cookie)
        device = await probe.client.async_resolve_device("")
        status = await probe.client.async_get_status(device)
        vo = status.get("deviceVO") or {}
        loc = vo.get("location") or {}
        bat = status.get("batteryInfo") or {}
        sig = status.get("signalInfo") or {}
        print(f"  设备          : {device.get('alias')} / {device.get('model')}")
        print(f"  online        : {vo.get('online')}")
        print(f"  location      : {loc.get('longitude')}, {loc.get('latitude')}"
              f"  radius={loc.get('radius')}")
        print(f"  locationDesc  : {loc.get('locationDesc')}")
        print(f"  batteryInfo   : {bat or '（空）'}")
        print(f"  signalInfo    : {sig or '（空）'}")
        throttled = not bat and not sig
        print()
        if throttled:
            print("  >>> 接口此刻正处于限流状态（电量/网络为空）—— 这就是问题现场。")
        else:
            print("  >>> 接口此刻正常。为稳定复现问题，下面会把 batteryInfo /")
            print("      signalInfo 抹成空 —— 与实测到的限流响应逐字段一致。")

        # ---------- 2. 模拟「上次成功」的缓存 ----------
        rule("[2] 塞一份上次成功的数据（模拟关机前最后一次刷新落盘）")
        # 用实测值构造：vivo 返回 BD-09，缓存里存的是换算后的 WGS84 + 原始值
        cached = coord.VivoFindData(
            online=True,
            online_raw=1,
            latitude=30.547232,
            longitude=114.297915,
            raw_latitude=30.550455,
            raw_longitude=114.309931,
            source_crs="bd09",
            target_crs="wgs84",
            accuracy=40.0,
            address="黄鹤楼公园，湖北省武汉市武昌区蛇山西山坡特1号",
            fix_time=coord.datetime(2026, 9, 18, 6, 46, tzinfo=coord.timezone.utc),
            located_live=True,
            battery=41,
            charging=False,
            network="5G",
            signal="4",
            operator="中国联通",
            device_alias="iQOOO",
            device_model="iQOO Neo10 Pro",
            imei="860000000000000",
            emmc_id="EMMC-TEST",
        )
        store_probe = coord.VivoFindCoordinator(hass=None, entry=entry)
        await store_probe._async_persist(cached)
        print(f"  已写入缓存: {describe(cached)}")

        # ---------- 3+4. 重启后首轮（带缓存）----------
        rule("[3] 重启后首轮刷新（带缓存 + 接口限流）")
        c1 = coord.VivoFindCoordinator(hass=None, entry=entry)
        await c1.async_restore()
        print(f"  恢复结果      : {describe(c1._restored)}")
        print(f"  恢复的 located_live: {c1._restored.located_live}（应为 False，已归零）")
        c1.client = ThrottledStatusClient(session, cookie)
        d1 = await c1._async_update_data()
        print()
        print(f"  首轮刷新结果  : {describe(d1)}")
        print(f"    latitude/longitude : {d1.latitude}, {d1.longitude}")
        print(f"    raw_coordinates    : {d1.raw_longitude}, {d1.raw_latitude}")
        print(f"    address            : {d1.address}")
        print(f"    fix_time           : {d1.fix_time}")
        print(f"    located_live       : {d1.located_live}（首轮未下发定位指令）")
        print(f"    locate_throttled   : {d1.locate_throttled}")

        # ---------- 5. 对照：无缓存 ----------
        rule("[4] 对照 —— 完全相同的限流响应，但没有缓存")
        entry_nc = L.FakeEntry(entry_id="check_restart_nocache", title="iQOOO")
        c2 = coord.VivoFindCoordinator(hass=None, entry=entry_nc)
        c2.client = ThrottledStatusClient(session, cookie)
        c2._first_refresh_pending = False  # 跳过首轮重试，别多等
        d2 = await c2._async_update_data()
        print(f"  无缓存首轮结果: {describe(d2)}")
        print(f"    address 有值？ {bool(d2.address)}")
        print(f"    fix_time 有值？ {d2.fix_time is not None}")

        # ---------- 结论 ----------
        rule("[5] 结论")
        rows = [
            ("位置（坐标）", d1.has_coordinates, d2.has_coordinates),
            ("原始坐标", d1.raw_longitude is not None, d2.raw_longitude is not None),
            ("电量", d1.battery is not None, d2.battery is not None),
            ("网络", d1.network is not None, d2.network is not None),
            ("地址", bool(d1.address), bool(d2.address)),
            ("定位时间", d1.fix_time is not None, d2.fix_time is not None),
        ]
        print(f"  {'字段':<16}{'重启后首轮(有缓存)':<22}{'对照(无缓存)':<14}")
        for name, with_cache, without_cache in rows:
            left = "有" if with_cache else "无"
            right = "有" if without_cache else "无"
            print(f"  {name:<16}{left:<22}{right:<14}")

        with_cache_ok = all(a for _, a, _ in rows)
        contrast_ok = (not d2.battery) and (not d2.network)
        print()
        if with_cache_ok:
            print("  ✅ 有缓存时，即使 devicestatus 被限流抹掉了电量/网络，")
            print("     重启后首轮依然把各项补全了 —— 不用再手动重载一次。")
        else:
            print("  ❌ 有缓存时仍有字段缺失：")
            for name, with_cache, _ in rows:
                if not with_cache:
                    print(f"       - {name}")

        if contrast_ok:
            print()
            print("  ✅ 对照组（同样响应、无缓存）电量与网络确实为空 ——")
            print("     证明上面补全的功劳来自缓存，不是接口这次恰好给全了。")
        else:
            print()
            print("  ⚠️ 对照组数据也齐了，说明这次没真正复现出限流缺口，")
            print("     结论仅供位置/地址参考。")


asyncio.run(main())
