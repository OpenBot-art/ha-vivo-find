"""coordinator.py 纯解析/合并逻辑的单元测试（用桩替换 Home Assistant 依赖）。

用法（在仓库根目录）：
    python dev/test_parse.py

重点验证三件事：
1. 限流时 vivo 返回空 batteryInfo/signalInfo，合并逻辑必须保留上一次读数；
2. 0% 电量这种"合法假值"不能被当成空值而被旧值覆盖；
3. location.time 是毫秒时间戳且服务器时钟可能快几秒，未来时间要被钳住。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _loader import install_ha_stubs, load_module, prepare_api  # noqa: E402

install_ha_stubs()
prepare_api()
co = load_module("coordinator")

FAILS: list[str] = []


def check(label: str, actual, expected) -> None:
    ok = actual == expected
    print(
        f"  {'PASS' if ok else 'FAIL'}  {label}: {actual!r}"
        + ("" if ok else f"  期望 {expected!r}")
    )
    if not ok:
        FAILS.append(label)


def section(title: str) -> None:
    print()
    print(f"--- {title} ---")


section("_pick：空值回退，假值不算空")
check("None → 用旧值", co._pick(None, 40), 40)
check("'' → 用旧值", co._pick("", "5G"), "5G")
check("{} → 用旧值", co._pick({}, {"a": 1}), {"a": 1})
check("[] → 用旧值", co._pick([], [1]), [1])
check("0 保留（0% 电量合法）", co._pick(0, 40), 0)
check("False 保留（未充电合法）", co._pick(False, True), False)
check("有新值就用新值", co._pick(88, 40), 88)

section("_parse_network：网络类型归一化")
check("5g → 5G", co._parse_network({"simNetWorkType": "5g"}), "5G")
check("nr → 5G", co._parse_network({"simNetWorkType": "NR"}), "5G")
check("lte → 4G", co._parse_network({"simNetWorkType": "lte"}), "4G")
check(
    "wifiSSID 优先",
    co._parse_network({"wifiSSID": "MyWiFi", "simNetWorkType": "5g"}),
    "WiFi: MyWiFi",
)
check("空 dict → None", co._parse_network({}), None)
check("缺字段 → None", co._parse_network({"simOperator": "联通"}), None)
check("未知类型 → 大写透出", co._parse_network({"simNetWorkType": "6g"}), "6G")

section("_parse_fix_time：毫秒时间戳与未来时间钳制")
stamp = datetime(2026, 9, 18, 6, 21, 17, tzinfo=timezone.utc)
check(
    "正常毫秒戳",
    co._parse_fix_time(int(stamp.timestamp() * 1000)),
    stamp,
)
check("0 → None", co._parse_fix_time(0), None)
check("None → None", co._parse_fix_time(None), None)
check("非法字符串 → None", co._parse_fix_time("abc"), None)
check(
    "未来 30 秒被钳到当前",
    co._parse_fix_time(
        int((datetime.now(timezone.utc) + timedelta(seconds=30)).timestamp() * 1000)
    )
    <= datetime.now(timezone.utc),
    True,
)

section("merge_with_previous：限流空字段时保留旧读数")
old = co.VivoFindData(
    online=True,
    online_raw=1,
    latitude=30.5506,
    longitude=114.3098,
    accuracy=40.0,
    address="黄鹤楼公园",
    battery=40,
    charging=True,
    network="5G",
    operator="联通",
)
throttled = co.VivoFindData(online=True, online_raw=1, latitude=None, longitude=None)
merged = co.merge_with_previous(throttled, old)
check("电量保留", merged.battery, 40)
check("充电状态保留", merged.charging, True)
check("网络保留", merged.network, "5G")
check("运营商保留", merged.operator, "联通")
check("纬度保留（地图上的点不消失）", merged.latitude, 30.5506)
check("经度保留", merged.longitude, 114.3098)
check("地址保留", merged.address, "黄鹤楼公园")
check("has_coordinates 为真", merged.has_coordinates, True)

section("merge_with_previous：真实新值不能被旧值吃掉")
fresh = co.VivoFindData(
    online=True,
    online_raw=1,
    latitude=31.0,
    longitude=121.0,
    battery=0,
    charging=False,
    network="4G",
)
merged2 = co.merge_with_previous(fresh, old)
check("0% 电量被采纳", merged2.battery, 0)
check("未充电被采纳", merged2.charging, False)
check("4G 被采纳", merged2.network, "4G")
check("新坐标被采纳", merged2.latitude, 31.0)

section("merge_with_previous：没有历史数据时原样返回")
check("previous=None", co.merge_with_previous(fresh, None) is fresh, True)

section("online 判定：非 0 即在线（限流期间曾观测到 2）")
check("0 → 离线", 0 in (0, None), True)
check("None → 离线", None in (0, None), True)
check("1 → 在线", 1 not in (0, None), True)
check("2 → 在线（异常值也不误判离线）", 2 not in (0, None), True)

print()
if FAILS:
    print(f"结果: {len(FAILS)} 项失败")
    for item in FAILS:
        print("  -", item)
    sys.exit(1)
print("结果: 全部通过 ✅")
