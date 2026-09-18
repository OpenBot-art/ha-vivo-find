# -*- coding: utf-8 -*-
"""地址 / 定位状态逻辑测试。

锁住的核心事实（2026-09-18 实测）：
  **地址（locationDesc）只随「定位指令成功」返回，devicestatus 的缓存位置不带它。**
所以「有没有地址」等价于「这一轮有没有成功发出定位指令」。这套测试就是
把这层等价关系钉死，防止以后再把「首轮盲目避让」这类改动带回来。
"""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))

import _loader as L  # noqa: E402

L.install_ha_stubs()
coord = L.load_module("coordinator")
const = L.load_module("const")
api = L.load_module("api")

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK]   {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  <-- {detail}")


LOCATED = {
    "longitude": 114.350814,
    "latitude": 30.559136,
    "locationDesc": "武重四街坊，湖北省武汉市武昌区水果湖街道东湖路104号",
    "radius": 40,
    "time": 1789720206000,
}


def store_key(eid):
    return f"{const.STORAGE_KEY}.{eid}"


def _stub_store():
    """取 _loader 装进 homeassistant.helpers.storage 的那个 Store 桩。"""
    import sys as _sys

    return _sys.modules["homeassistant.helpers.storage"].Store


def seed_cache(eid, **fields):
    """往 Store.memory 里预置一份「上次运行的数据」。"""
    data = coord.VivoFindData(**fields)
    _stub_store().memory[store_key(eid)] = coord.serialize_data(data)


def clear_cache(eid):
    _stub_store().memory.pop(store_key(eid), None)


def build(eid, *, options=None):
    entry = L.FakeEntry(entry_id=eid, title="iQOOO", options=options)
    c = coord.VivoFindCoordinator(hass=None, entry=entry)
    return c, entry


async def refresh(c):
    d = await c._async_update_data()
    c.data = d  # 模拟 DataUpdateCoordinator 把结果写回 self.data
    return d


# =====================================================================
async def t1_first_refresh_needs_address():
    print()
    print("[1] 首轮：devicestatus 无地址 → 必须下发定位指令把地址补上")
    eid = "t1"
    clear_cache(eid)
    c, _ = build(eid)
    c.client = L.FakeVivoClient(
        status=L.make_status(desc=None),  # 实测：devicestatus 不带 locationDesc
        locate=dict(LOCATED),
    )
    d = await refresh(c)
    check("首轮就发了定位指令", c.client.locate_calls == 1,
          f"locate_calls={c.client.locate_calls}")
    check("地址拿到了", bool(d.address), str(d.address)[:24])
    check("locate_status=ok", d.locate_status == const.LOCATE_OK, str(d.locate_status))
    check("address_time 有值", d.address_time is not None, str(d.address_time))


async def t2_first_refresh_skips_when_address_known():
    print()
    print("[2] 首轮：缓存里已有坐标+地址 → 仍要避让限流，不下发指令")
    eid = "t2"
    seed_cache(
        eid,
        latitude=30.5591,
        longitude=114.3507,
        raw_latitude=30.559136,
        raw_longitude=114.350814,
        address="武重四街坊（缓存）",
        address_time=None,
        battery=41,
    )
    c, _ = build(eid)
    c.client = L.FakeVivoClient(status=L.make_status(desc=None), locate=dict(LOCATED))
    await c.async_restore()
    check("缓存恢复到了地址", bool(c._restored and c._restored.address),
          str(c._restored.address if c._restored else None))
    d = await refresh(c)
    check("首轮没有下发指令（避让限流）", c.client.locate_calls == 0,
          f"locate_calls={c.client.locate_calls}")
    check("locate_status=skipped_first_refresh",
          d.locate_status == const.LOCATE_SKIP_FIRST, str(d.locate_status))
    check("地址沿用缓存没丢", d.address == "武重四街坊（缓存）", str(d.address))


async def t3_first_refresh_without_cached_address():
    print()
    print("[3] 首轮：缓存有坐标但没地址 → 不能避让，必须去拿地址")
    eid = "t3"
    seed_cache(
        eid,
        latitude=30.5591,
        longitude=114.3507,
        raw_latitude=30.559136,
        raw_longitude=114.350814,
        battery=41,
    )
    c, _ = build(eid)
    c.client = L.FakeVivoClient(status=L.make_status(desc=None), locate=dict(LOCATED))
    await c.async_restore()
    d = await refresh(c)
    check("下发了定位指令", c.client.locate_calls == 1,
          f"locate_calls={c.client.locate_calls}")
    check("地址补上了", bool(d.address), str(d.address)[:24])


async def t4_rate_limited():
    print()
    print("[4] 定位被限流 → status=throttled，位置/地址沿用缓存不丢")
    eid = "t4"
    clear_cache(eid)
    c, _ = build(eid)
    # 第1轮：一切正常，把地址和冷却基线攒下来
    c.client = L.FakeVivoClient(status=L.make_status(desc=None), locate=dict(LOCATED))
    d0 = await refresh(c)
    check("第1轮地址正常", bool(d0.address), str(d0.address)[:20])
    check("第1轮 locate_status=ok", d0.locate_status == const.LOCATE_OK,
          str(d0.locate_status))

    # 第2轮：接口开始限流。手动清掉冷却，模拟「下一轮冷却已过」
    c._locate_unlock_at = None
    c.client = L.FakeVivoClient(
        status=L.make_status(desc=None),
        locate_error=api.VivoFindRateLimitError("操作过于频繁"),
    )
    d = await refresh(c)
    check("locate_status=throttled", d.locate_status == const.LOCATE_THROTTLED,
          str(d.locate_status))
    check("位置没丢", d.has_coordinates, f"{d.latitude},{d.longitude}")
    check("地址没被清空", d.address == d0.address, str(d.address))
    check("locate_throttled 标记为真", d.locate_throttled is True,
          f"locate_throttled={d.locate_throttled}")

    # 第3轮：仍在冷却窗口内 → 不该再撞接口
    calls_before = c.client.locate_calls
    d = await refresh(c)
    check("冷却窗口内不再发指令", c.client.locate_calls == calls_before,
          f"{calls_before} → {c.client.locate_calls}")
    check("冷却跳过时 status=skipped_cooldown",
          d.locate_status == const.LOCATE_SKIP_COOLDOWN, str(d.locate_status))
    check("地址依然保留", d.address == d0.address, str(d.address))


async def t5_timeout():
    print()
    print("[5] 定位超时 → status=timeout（和一般失败区分开）")
    eid = "t5"
    clear_cache(eid)
    c, _ = build(eid)
    c.client = L.FakeVivoClient(
        status=L.make_status(desc=None),
        locate_error=api.VivoFindError("定位超时（轮询 15 次仍未返回结果）"),
    )
    d = await refresh(c)
    check("locate_status=timeout", d.locate_status == const.LOCATE_TIMEOUT,
          str(d.locate_status))
    check("位置仍可用（来自 devicestatus）", d.has_coordinates)


async def t6_other_failure():
    print()
    print("[6] 其他定位失败 → status=failed")
    eid = "t6"
    clear_cache(eid)
    c, _ = build(eid)
    c.client = L.FakeVivoClient(
        status=L.make_status(desc=None),
        locate_error=api.VivoFindError("设备定位失败（设备可能已关机或未开启查找功能）"),
    )
    d = await refresh(c)
    check("locate_status=failed", d.locate_status == const.LOCATE_FAILED,
          str(d.locate_status))


async def t7_disabled_and_offline():
    print()
    print("[7] 关闭定位开关 / 设备离线 → 各自的状态码")
    eid = "t7a"
    clear_cache(eid)
    c, _ = build(eid)
    c.locate_on_update = False
    c.client = L.FakeVivoClient(status=L.make_status(desc=None), locate=dict(LOCATED))
    d = await refresh(c)
    check("关闭开关 → skipped_disabled",
          d.locate_status == const.LOCATE_SKIP_DISABLED, str(d.locate_status))
    check("关闭开关后不下发指令", c.client.locate_calls == 0)

    eid = "t7b"
    clear_cache(eid)
    c, _ = build(eid)
    c.client = L.FakeVivoClient(status=L.make_status(online=0, desc=None),
                                locate=dict(LOCATED))
    d = await refresh(c)
    check("离线 → skipped_offline",
          d.locate_status == const.LOCATE_SKIP_OFFLINE, str(d.locate_status))
    check("离线时不下发指令", c.client.locate_calls == 0)


async def t8_address_time_separate_from_fix_time():
    print()
    print("[8] address_time 与 fix_time 必须各走各的（地址可能旧得多）")
    eid = "t8"
    clear_cache(eid)
    c, _ = build(eid)
    c.client = L.FakeVivoClient(
        status=L.make_status(desc=None, fix_ms=1789720206000),
        locate=dict(LOCATED),
    )
    d1 = await refresh(c)
    t1 = d1.address_time
    check("第1轮拿到 address_time", t1 is not None, str(t1))

    # 第2轮：devicestatus 给了**更新**的坐标和 fix_time，但没有地址
    c.client = L.FakeVivoClient(
        status=L.make_status(lng=114.352086, lat=30.561536, radius=6,
                             desc=None, fix_ms=1789730000000),
        locate_error=api.VivoFindRateLimitError("操作过于频繁"),
    )
    d2 = await refresh(c)
    check("fix_time 更新了（新坐标）",
          d2.fix_time is not None and d2.fix_time != d1.fix_time,
          f"{d1.fix_time} → {d2.fix_time}")
    check("address_time 保持旧值（地址没变）", d2.address_time == t1,
          str(d2.address_time))
    check("地址仍是第1轮那个", d2.address == d1.address)


async def t9_serialize_roundtrip():
    print()
    print("[9] 序列化往返：新字段 address_time / locate_status 不能丢")
    from datetime import datetime, timezone

    moment = datetime(2026, 9, 18, 8, 30, 6, tzinfo=timezone.utc)
    original = coord.VivoFindData(
        latitude=30.5591,
        longitude=114.3507,
        address="武重四街坊",
        address_time=moment,
        fix_time=moment,
        locate_status=const.LOCATE_OK,
        battery=82,
    )
    raw = coord.serialize_data(original)
    check("address_time 序列化成 ISO 字符串",
          isinstance(raw["address_time"], str), repr(raw["address_time"]))
    back = coord.deserialize_data(raw)
    check("address_time 还原成 datetime",
          isinstance(back.address_time, datetime), type(back.address_time).__name__)
    check("address_time 值一致", back.address_time == moment, str(back.address_time))
    check("locate_status 保留", back.locate_status == const.LOCATE_OK,
          str(back.locate_status))
    check("其余字段一致", back.address == original.address
          and back.battery == original.battery)


async def t10_locate_now_service_logic():
    print()
    print("[10] async_locate_now：冷却拦截 / force 放行 / 结果直接推给实体")
    eid = "t10"
    clear_cache(eid)
    c, _ = build(eid)
    c.client = L.FakeVivoClient(
        status=L.make_status(desc=None),
        locate={
            "longitude": 114.350814,
            "latitude": 30.559136,
            "locationDesc": "武重四街坊，湖北省武汉市武昌区水果湖街道东湖路104号",
            "radius": 40,
            "time": None,
        },
    )
    await refresh(c)  # 第1轮会定位并锁上冷却
    check("refresh 阶段已定位", c.client.locate_calls == 1)

    msg = await c.async_locate_now()
    check("冷却中被拦住", "冷却中" in msg, msg)
    check("冷却拦截时未发指令", c.client.locate_calls == 1)

    msg = await c.async_locate_now(force=True)
    check("force 放行并成功", msg.startswith("成功"), msg)
    check("force 真的发了指令", c.client.locate_calls == 2)
    check("结果被推给实体（async_set_updated_data）", len(c.pushed) >= 1,
          f"pushed={len(c.pushed)}")
    check("推送的数据带地址", bool(c.data.address), str(c.data.address)[:24])
    check("推送数据 locate_status=ok", c.data.locate_status == const.LOCATE_OK)

    # 限流时手动定位要给出明确提示，而不是抛异常
    c.client = L.FakeVivoClient(
        status=L.make_status(desc=None),
        locate_error=api.VivoFindRateLimitError("操作过于频繁"),
    )
    msg = await c.async_locate_now(force=True)
    check("限流时返回可读提示", msg.startswith("被限流"), msg)


async def t11_offline_keeps_previous():
    print()
    print("[11] 设备离线：位置/地址沿用缓存，实体不会变未知")
    eid = "t11"
    clear_cache(eid)
    c, _ = build(eid)
    c.client = L.FakeVivoClient(status=L.make_status(desc=None), locate=dict(LOCATED))
    d1 = await refresh(c)
    c.client = L.FakeVivoClient(
        status=L.make_status(online=0, lng=None, lat=None, radius=None, desc=None,
                             battery=None, net=None),
        locate=dict(LOCATED),
    )
    d2 = await refresh(c)
    check("离线后仍有坐标", d2.has_coordinates, f"{d2.latitude},{d2.longitude}")
    check("离线后仍有地址", d2.address == d1.address, str(d2.address))
    check("在线状态标记为离线", d2.online is False)


async def main():
    await t1_first_refresh_needs_address()
    await t2_first_refresh_skips_when_address_known()
    await t3_first_refresh_without_cached_address()
    await t4_rate_limited()
    await t5_timeout()
    await t6_other_failure()
    await t7_disabled_and_offline()
    await t8_address_time_separate_from_fix_time()
    await t9_serialize_roundtrip()
    await t10_locate_now_service_logic()
    await t11_offline_keeps_previous()

    print()
    print("=" * 66)
    print(f"通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 66)
    return 0 if FAIL == 0 else 1


sys.exit(asyncio.run(main()))
