# -*- coding: utf-8 -*-
"""验证「重启/重载后首轮数据不全」的修复。

要证明的四件事：
1. 持久化往返：VivoFindData 能存能读，坏数据不炸；
2. 有缓存时，首轮即使被限流（返回空字段）也能把电量/位置补齐；
3. 首轮若 devicestatus 已给坐标，就不再下发定位指令（避让限流窗口）；
4. 首轮请求失败但有缓存时，不抛异常 —— 用缓存把实体撑起来。
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _loader as L  # noqa: E402

L.install_ha_stubs()
coord = L.load_module("coordinator")

# 把重试间隔改成 0，别让测试真的等
coord.RETRY_DELAY = 0

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    mark = "OK  " if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


# 实测坐标：vivo 返回 BD-09，转 WGS84 后应当是 114.339043, 30.555106
VIVO_LNG, VIVO_LAT = 114.350962, 30.558978
WGS_LNG, WGS_LAT = 114.339043, 30.555106


def new_entry(entry_id: str) -> L.FakeEntry:
    return L.FakeEntry(entry_id=entry_id)


def _store_stub():
    """取 _loader 装进 homeassistant.helpers.storage 的 Store 桩。"""
    return sys.modules["homeassistant.helpers.storage"].Store


def seed_cache(entry_id: str, **fields) -> None:
    """预置一份「上次运行的数据」。"""
    data = coord.VivoFindData(**fields)
    _store_stub().memory[f"{coord.STORAGE_KEY}.{entry_id}"] = coord.serialize_data(data)


# 定位指令成功时返回的 location（**带地址**；devicestatus 那份不带）
LOCATE_OK = {
    "longitude": VIVO_LNG,
    "latitude": VIVO_LAT,
    "radius": 30,
    "locationDesc": "武重四街坊，湖北省武汉市武昌区水果湖街道东湖路104号",
}


async def refresh(entry, client):
    """跑一轮刷新，返回 (结果, coordinator)。"""
    c = coord.VivoFindCoordinator(hass=None, entry=entry)
    c.client = client
    return await c._async_update_data(), c


# ============================================================
section("[1] 序列化往返与容错")

full = coord.VivoFindData(
    online=True,
    online_raw=1,
    latitude=WGS_LAT,
    longitude=WGS_LNG,
    raw_latitude=VIVO_LAT,
    raw_longitude=VIVO_LNG,
    source_crs="bd09",
    target_crs="wgs84",
    accuracy=40.0,
    address="武重四街坊，湖北省武汉市武昌区水果湖街道东湖路104号",
    fix_time=coord.datetime(2026, 9, 18, 7, 30, tzinfo=coord.timezone.utc),
    located_live=True,
    locate_throttled=False,
    battery=41,
    charging=False,
    network="5G",
    signal="4",
    operator="中国联通",
    device_alias="iQOOO",
    device_model="iQOO Neo10 Pro",
    imei="868856076839295",
    emmc_id="EMMC-TEST",
)

raw = coord.serialize_data(full)
check("serialize 把 datetime 转成字符串", isinstance(raw["fix_time"], str), raw["fix_time"])
check("serialize 保留全部字段", set(raw) == {f.name for f in coord.dataclasses.fields(full)})

back = coord.deserialize_data(raw)
check("往返后 fix_time 能还原", back.fix_time == full.fix_time)
check("往返后坐标一致", (back.latitude, back.longitude) == (full.latitude, full.longitude))
check("往返后电量一致", back.battery == 41)
check("往返后 has_coordinates 为真", back.has_coordinates)

check("坏输入（None）不抛异常", coord.deserialize_data(None).battery is None)
check("坏输入（字符串）不抛异常", coord.deserialize_data("nonsense").battery is None)
check("字段未知时被忽略", coord.deserialize_data({"battery": 7, "unknown": 1}).battery == 7)
check("时间戳格式坏时退回 None", coord.deserialize_data({"fix_time": "not-a-date"}).fix_time is None)

weird = coord.deserialize_data({"latitude": None, "longitude": None, "battery": 0})
check("None 字段不覆盖默认值", weird.latitude is None and weird.battery == 0, "battery=0 是合法值")

# ============================================================
section("[2] 首轮刷新 + 缓存兜底（模拟重载后立刻撞限流）")

entry2 = new_entry("entry_restore")

# 第一轮：一切正常，顺便把缓存写下来（模拟关机前最后一次成功）
# locate 必须给一份带 locationDesc 的响应 —— 地址只从这里来
data_ok, _ = asyncio.run(
    refresh(
        entry2,
        L.FakeVivoClient(
            status=L.make_status(fix_ms=1789704155000),
            locate=dict(LOCATE_OK),
        ),
    )
)
check("首次正常刷新拿到坐标", data_ok.has_coordinates, f"{data_ok.longitude},{data_ok.latitude}")
check("首次正常刷新拿到电量", data_ok.battery == 41)
check("首次正常刷新拿到地址（来自定位指令）", bool(data_ok.address),
      str(data_ok.address)[:24])
check("坐标已从 BD-09 换算到 WGS84",
      abs(data_ok.longitude - WGS_LNG) < 0.0005 and abs(data_ok.latitude - WGS_LAT) < 0.0005,
      f"{data_ok.longitude:.6f},{data_ok.latitude:.6f}")
check("原始坐标原样保留", abs(data_ok.raw_longitude - VIVO_LNG) < 1e-9)

# 第二轮：模拟 HA 重启 —— 新 coordinator，先恢复缓存
c2 = coord.VivoFindCoordinator(hass=None, entry=entry2)
asyncio.run(c2.async_restore())
check("重启后能从缓存恢复", c2._restored is not None, coord._describe(c2._restored))
check("恢复的坐标与上次一致",
      c2._restored is not None
      and abs(c2._restored.longitude - WGS_LNG) < 0.0005)
check("恢复的 located_live 已归零（不是本次实时定位）",
      c2._restored is not None and c2._restored.located_live is False)

# 关键场景：这轮 devicestatus 被限流，batteryInfo/signalInfo 全空、location 也没了
throttled = L.make_status(lng=None, lat=None, radius=None, desc=None,
                          battery=None, charging=None, net=None, operator=None)
c2.client = L.FakeVivoClient(status=throttled)
data2 = asyncio.run(c2._async_update_data())
check("限流轮靠缓存保住了坐标", data2.has_coordinates,
      f"{data2.longitude},{data2.latitude}")
check("限流轮靠缓存保住了电量", data2.battery == 41, f"battery={data2.battery}")
check("限流轮靠缓存保住了网络", data2.network == "5G", f"network={data2.network}")
check("限流轮靠缓存保住了地址", bool(data2.address))
# 这一轮 devicestatus 连坐标都没给，所以按设计会尝试下发定位指令补救
# （补救失败也无所谓 —— 数据已经由缓存兜住了）
check("限流轮因无坐标而尝试下发定位指令",
      c2.client.locate_calls == 1, f"locate_calls={c2.client.locate_calls}")

# 没缓存的对照：同样空响应，就应该什么都拿不到（证明上面是缓存在起作用）
c_nc = coord.VivoFindCoordinator(hass=None, entry=new_entry("entry_nocache"))
c_nc.client = L.FakeVivoClient(status=throttled)
c_nc._first_refresh_pending = False  # 只验证回退逻辑，跳过首轮重试
data2b = asyncio.run(c_nc._async_update_data())
check("（对照）无缓存时空响应确实拿不到数据",
      not data2b.has_coordinates and data2b.battery is None,
      coord._describe(data2b))

# ============================================================
section("[3] 首轮避让定位指令（避免重启即撞限流）")

# 避让的前提是「缓存里已经有地址」—— 地址只随定位指令返回，
# 若缓存里没有地址还硬避让，首轮地址就会当场变空（这正是修掉的那个 bug）。
seed_cache(
    "entry_skip",
    latitude=WGS_LAT,
    longitude=WGS_LNG,
    raw_latitude=VIVO_LAT,
    raw_longitude=VIVO_LNG,
    address="武重四街坊（缓存）",
    battery=41,
)


async def case_skip_locate():
    entry = new_entry("entry_skip")
    c = coord.VivoFindCoordinator(hass=None, entry=entry)
    await c.async_restore()
    c.client = L.FakeVivoClient(
        status=L.make_status(lng=VIVO_LNG, lat=VIVO_LAT),
        locate=dict(LOCATE_OK),
    )
    data = await c._async_update_data()
    c.data = data
    return data, c.client


data3, client3 = asyncio.run(case_skip_locate())
check("首轮已有地址 → 不发定位指令（避让限流）", client3.locate_calls == 0,
      f"locate_calls={client3.locate_calls}")
check("首轮照样拿到坐标", data3.has_coordinates)
check("首轮 located_live 为 False（不是实时定位来的）", data3.located_live is False)
check("首轮地址沿用缓存没丢", data3.address == "武重四街坊（缓存）", str(data3.address))
check("首轮状态码为 skipped_first_refresh",
      data3.locate_status == coord.LOCATE_SKIP_FIRST, str(data3.locate_status))


async def case_no_address_must_locate():
    """对照：缓存里**没有地址**时绝不能避让，否则地址永远补不回来。"""
    seed_cache(
        "entry_skip_noaddr",
        latitude=WGS_LAT,
        longitude=WGS_LNG,
        raw_latitude=VIVO_LAT,
        raw_longitude=VIVO_LNG,
        battery=41,
    )
    entry = new_entry("entry_skip_noaddr")
    c = coord.VivoFindCoordinator(hass=None, entry=entry)
    await c.async_restore()
    c.client = L.FakeVivoClient(
        status=L.make_status(lng=VIVO_LNG, lat=VIVO_LAT),
        locate=dict(LOCATE_OK),
    )
    data = await c._async_update_data()
    return data, c.client


data3b, client3b = asyncio.run(case_no_address_must_locate())
check("首轮缓存无地址 → 必须下发定位指令", client3b.locate_calls == 1,
      f"locate_calls={client3b.locate_calls}")
check("地址补上了", bool(data3b.address), str(data3b.address)[:24])


async def case_no_coord_locate():
    entry = new_entry("entry_locate")
    client = L.FakeVivoClient(
        status=L.make_status(lng=None, lat=None, radius=None, desc=None),
        locate={"longitude": VIVO_LNG, "latitude": VIVO_LAT,
                "radius": 35, "locationDesc": "定位结果地址"},
    )
    data, _ = await refresh(entry, client)
    return data, client


data4, client4 = asyncio.run(case_no_coord_locate())
check("首轮 devicestatus 无坐标 → 下发定位指令补救", client4.locate_calls == 1,
      f"locate_calls={client4.locate_calls}")
check("定位指令的坐标进入了结果", data4.has_coordinates, coord._describe(data4))
check("located_live 标记为 True", data4.located_live is True)


async def case_second_round():
    """第二轮起恢复正常定位节奏。

    注意：真实运行时轮询间隔 600s > 定位冷却 300s，所以下一轮冷却必然已过；
    测试里时间不流逝，手动清掉冷却来等价模拟那 600 秒。
    """
    entry = new_entry("entry_second")
    client = L.FakeVivoClient(
        status=L.make_status(lng=VIVO_LNG, lat=VIVO_LAT),
        locate=dict(LOCATE_OK),
    )
    c = coord.VivoFindCoordinator(hass=None, entry=entry)
    c.client = client
    first = await c._async_update_data()
    c.data = first
    calls_after_first = client.locate_calls
    c._locate_unlock_at = None  # 等价于「600 秒过去了」
    second = await c._async_update_data()
    c.data = second
    return calls_after_first, client.locate_calls, first, second


first_calls, second_calls, d_first, d_second = asyncio.run(case_second_round())
check("首轮无缓存无地址 → 立刻下发定位指令", first_calls == 1,
      f"首轮 locate_calls={first_calls}")
check("首轮就拿到了地址", bool(d_first.address), str(d_first.address)[:24])
check("第二轮冷却已过 → 再下发一次", second_calls == 2,
      f"累计 locate_calls={second_calls}")
check("第二轮 locate_status=ok", d_second.locate_status == coord.LOCATE_OK,
      str(d_second.locate_status))

# ============================================================
section("[4] 首轮请求失败但缓存可用 → 不抛异常")

entry5 = new_entry("entry_fallback_error")
asyncio.run(refresh(entry5, L.FakeVivoClient(status=L.make_status(fix_ms=1789704155000))))

c5 = coord.VivoFindCoordinator(hass=None, entry=entry5)
asyncio.run(c5.async_restore())
c5.client = L.FakeVivoClient(status_error=coord.VivoFindConnectionError("网络不通"))


async def case_fallback():
    try:
        return await c5._async_update_data(), None
    except Exception as err:  # noqa: BLE001
        return None, err


data5, err5 = asyncio.run(case_fallback())
check("首轮失败但有缓存时不抛异常", err5 is None, f"err={err5}")
check("返回的是缓存数据", data5 is not None and data5.has_coordinates,
      coord._describe(data5) if data5 else "无")
check("返回的缓存里电量还在", data5 is not None and data5.battery == 41)

# 对照：没有缓存时，首轮失败必须抛出去（让 HA 重试 setup）
c6 = coord.VivoFindCoordinator(hass=None, entry=new_entry("entry_no_cache_error"))
c6.client = L.FakeVivoClient(status_error=coord.VivoFindConnectionError("网络不通"))


async def case_no_fallback():
    try:
        await c6._async_update_data()
        return "no-raise"
    except Exception as err:  # noqa: BLE001
        return type(err).__name__


outcome = asyncio.run(case_no_fallback())
check("无缓存时首轮失败会抛 UpdateFailed", outcome == "UpdateFailed", f"得到 {outcome}")

# ============================================================
section("[5] cookie 失效仍然必须抛认证异常（不能被缓存吞掉）")

c7 = coord.VivoFindCoordinator(hass=None, entry=entry5)
asyncio.run(c7.async_restore())
c7.client = L.FakeVivoClient(status_error=coord.VivoFindAuthError("cookie 过期"))


async def case_auth():
    try:
        await c7._async_update_data()
        return "no-raise"
    except Exception as err:  # noqa: BLE001
        return type(err).__name__


outcome_auth = asyncio.run(case_auth())
check("cookie 失效抛 ConfigEntryAuthFailed（不被缓存兜住）",
      outcome_auth == "ConfigEntryAuthFailed", f"得到 {outcome_auth}")

# ============================================================
section("[6] 定位被限流时不影响其余字段")

entry8 = new_entry("entry_rate_limit")
client8 = L.FakeVivoClient(
    status=L.make_status(),
    locate_error=coord.VivoFindRateLimitError("操作过于频繁"),
)


async def case_rate_limit():
    c = coord.VivoFindCoordinator(hass=None, entry=entry8)
    c.client = client8
    # 首轮避让，所以先把定位开关打开、标识首轮结束，逼它真的去下发
    c._first_refresh_pending = False
    return await c._async_update_data(), c


data8, c8 = asyncio.run(case_rate_limit())
check("定位被限流时仍保留 devicestatus 的坐标", data8.has_coordinates)
check("locate_throttled 被置位", data8.locate_throttled is True)
check("locate_status=throttled", data8.locate_status == coord.LOCATE_THROTTLED,
      str(data8.locate_status))
check("限流后设置了冷却", c8._locate_unlock_at is not None,
      f"unlock_at={c8._locate_unlock_at}")

# ============================================================
print()
print("=" * 72)
print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
if FAILED:
    print("失败项：")
    for name in FAILED:
        print("  -", name)
print("=" * 72)
sys.exit(1 if FAILED else 0)
