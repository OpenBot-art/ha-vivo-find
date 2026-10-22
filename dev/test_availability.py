# -*- coding: utf-8 -*-
"""复现并验证「其他实体显示 13 分钟前」这一现象。

用户报告：采集间隔 10 分钟，位置 / 地址 / 定位时间都对，
但其他实体（电量、在线、网络…）显示 13 分钟前。

核心断言：
- device_tracker 与 sensor 的 available 语义**必须一致**，
  否则同一个协调器的一轮失败会让两组实体状态不一致。
- 单轮失败（限流 / 网络抖动）时，实体不应集体变 unavailable ——
  集成本来就做了「空值回退保留上次读数」，变 unavailable 等于
  把回退出来的数据白白藏起来。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _loader as L  # noqa: E402

L.install_ha_stubs()
coord_mod = L.load_module("coordinator")
dt_mod = L.load_module("device_tracker")
sensor_mod = L.load_module("sensor")

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    marker = "OK  " if ok else "FAIL"
    print(f"  [{marker}] {name}" + (f"   {detail}" if detail else ""))


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


class _FakeState:
    """模拟 HA 的 State 对象，只为让 last_updated 可断言。"""

    def __init__(self, last_updated):
        self.last_updated = last_updated


def make_pair(data, last_update_success: bool):
    """构造同一协调器下的 device_tracker + sensor。"""
    entry = L.FakeEntry(data={"device_imei": "860000000000000",
                              "device_alias": "iQOOO"})
    coordinator, _ = L.make_coordinator(coord_mod, entry)
    coordinator.data = data
    coordinator.last_update_success = last_update_success
    tracker = dt_mod.VivoFindDeviceTracker(coordinator)
    sensor = sensor_mod.VivoFindSensor(coordinator, sensor_mod.SENSORS[0])
    return coordinator, tracker, sensor


# ---------------------------------------------------------------- 1
section("1. 正常轮次：两组实体都可用（基线）")

data = coord_mod.VivoFindData(
    latitude=30.55, longitude=114.30,
    battery=88, online=True, fix_time=coord_mod.dt_util.utcnow(),
)
coord, tracker, battery = make_pair(data, last_update_success=True)

check("device_tracker.available", tracker.available is True)
check("sensor.available", battery.available is True)

# ---------------------------------------------------------------- 2
section("2. 单轮失败（限流/网络抖动）：两组实体状态必须一致")

# 关键场景：这一轮拉取失败，但协调器用缓存把数据撑住了
coord2, tracker2, battery2 = make_pair(data, last_update_success=False)

check("device_tracker.available（有坐标 → 保持可用）",
      tracker2.available is True, f"got {tracker2.available}")
check("sensor.available（应与 tracker 一致，保持可用）",
      battery2.available is True, f"got {battery2.available}")

check("  → 两者 available 一致",
      tracker2.available == battery2.available,
      f"tracker={tracker2.available}, sensor={battery2.available}")

# ---------------------------------------------------------------- 3
section("3. 失败时传感器仍应能读出缓存值（否则等于藏数据）")

check("sensor.native_value 仍能取到电量 88",
      battery2.native_value == 88, f"got {battery2.native_value!r}")
check("device_tracker.latitude 仍有值",
      tracker2.latitude == 30.55, f"got {tracker2.latitude!r}")

# ---------------------------------------------------------------- 4
section("4. 从未拿到坐标时，device_tracker 才应不可用")

empty = coord_mod.VivoFindData()  # 什么都没有
coord4, tracker4, sensor4 = make_pair(empty, last_update_success=True)
check("无坐标时 device_tracker.available 为 False",
      tracker4.available is False, f"got {tracker4.available}")

# ---------------------------------------------------------------- 5
section("5. 回归：两组实体的 available 语义必须由同一规则决定")

# 穷举 (有数据? 轮次成功?) 组合，断言两组永远一致
cases = [
    ("有数据 + 成功", data, True),
    ("有数据 + 失败", data, False),
    ("无数据 + 成功", empty, True),
    ("无数据 + 失败", empty, False),
]
for label, d, ok in cases:
    _, t, s = make_pair(d, last_update_success=ok)
    same = (t.available == s.available)
    check(f"{label:16} tracker={t.available!s:5} sensor={s.available!s:5}",
          same, "" if same else "← 不一致！")

# ----------------------------------------------------------------
print()
print("=" * 72)
if FAILED:
    print(f"失败 {len(FAILED)} 项 / 通过 {len(PASSED)} 项")
    for f in FAILED:
        print(f"   - {f}")
    raise SystemExit(1)
print(f"全部通过（{len(PASSED)} 项）")
