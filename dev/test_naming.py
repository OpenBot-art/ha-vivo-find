# -*- coding: utf-8 -*-
"""实体名称 / 实体 ID 的生成规则。

为什么要单独测这个：实体 ID（`device_tracker.iqoo_neo10pro`）是用户在地图
卡片、自动化、person 里手写引用的东西。它一旦取错来源，用户的配置就全部
指向一个「看起来对但实际不对」的实体 —— 而且症状往往是「地图上的点不是我
期望的那台设备」，非常难排查。所以这里把「名字从哪来」钉死。

核心断言：**名称只允许来自配置项，绝不允许来自运行期数据。**
"""
from __future__ import annotations

import pathlib
import re
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
    mark = "OK  " if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def slugify_entity_id(platform: str, name: str) -> str:
    """近似复刻 HA 的实体 ID slugify：小写、非字母数字转下划线。"""
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return f"{platform}.{slug}"


def new_entry(**data) -> L.FakeEntry:
    """默认 title='iQOOO'（_loader.FakeEntry 的默认值）。

    IMEI 是配置阶段就固化进 entry.data 的（见 config_flow._device_identity），
    所以这里默认带上，模拟一个正常配置好的条目。
    """
    return L.FakeEntry(data={"device_imei": "860000000000000", **data})


def build_tracker(entry, data=None):
    coordinator, _ = L.make_coordinator(coord_mod, entry)
    coordinator.data = data
    return dt_mod.VivoFindDeviceTracker(coordinator)


# ---------------------------------------------------------------- 1
section("1. 配置项里有别名 → 名称取别名（正常路径）")

entry = new_entry(device_alias="iQOOO", device_model="iQOO Neo10 Pro")
t = build_tracker(entry)
check("name == 别名", t.name == "iQOOO", f"name={t.name!r}")
check(
    "entity_id == device_tracker.iqooo",
    slugify_entity_id("device_tracker", t.name) == "device_tracker.iqooo",
    slugify_entity_id("device_tracker", t.name),
)

# ---------------------------------------------------------------- 2
section("2. 别名缺失但配置项里有型号 → 不该退化成型号")

# 这是用户报告的场景：实体实际是 device_tracker.iqoo_neo10pro ——
# 说明名称取到的是「型号」。型号是产品线名，两台同型号手机会撞名。
entry2 = new_entry(device_alias="", device_model="iQOO Neo10 Pro")
t2 = build_tracker(entry2)
check(
    "名称没有变成型号（避免同型号撞名）",
    t2.name != "iQOO Neo10 Pro",
    f"name={t2.name!r}",
)
check(
    "退化为 entry.title 而不是型号",
    t2.name == entry2.title,
    f"name={t2.name!r}, title={entry2.title!r}",
)

# ---------------------------------------------------------------- 3
section("3. 名称绝不依赖运行期数据（首轮/次轮必须一致）")

run_data = coord_mod.VivoFindData(
    device_alias="iQOOO",
    device_model="iQOO Neo10 Pro",
    imei="860000000000000",
)

entry3 = new_entry(device_alias="iQOOO")

# 首轮：还没有任何数据
t3_first = build_tracker(entry3, data=None)
# 次轮：数据到位
t3_second = build_tracker(entry3, data=run_data)

check("首轮/次轮 name 一致", t3_first.name == t3_second.name,
      f"{t3_first.name!r} vs {t3_second.name!r}")
check("首轮/次轮 unique_id 一致", t3_first.unique_id == t3_second.unique_id,
      f"{t3_first.unique_id!r} vs {t3_second.unique_id!r}")

# ---------------------------------------------------------------- 4
section("4. 配置项完全没有别名时，仍然稳定")

entry4 = new_entry()  # 无 device_alias
t4a = build_tracker(entry4, data=None)
t4b = build_tracker(entry4, data=run_data)
check("无别名时两轮 name 一致", t4a.name == t4b.name,
      f"{t4a.name!r} vs {t4b.name!r}")
check("无别名时落到 entry.title", t4a.name == entry4.title,
      f"name={t4a.name!r}, title={entry4.title!r}")

# ---------------------------------------------------------------- 5
section("5. unique_id 与名称、语言无关（必须锚定到 IMEI）")

entry5 = new_entry(device_alias="iQOOO")
t5 = build_tracker(entry5)
check("device_tracker.unique_id 锚定 IMEI",
      t5.unique_id == "vivo_find_860000000000000", t5.unique_id)

desc = sensor_mod.SENSORS[0]
coordinator5, _ = L.make_coordinator(coord_mod, entry5)
s5 = sensor_mod.VivoFindSensor(coordinator5, desc)
check("sensor.unique_id 锚定 IMEI + 传感器 key",
      s5.unique_id == f"vivo_find_860000000000000_{desc.key}", s5.unique_id)

# 改别名不该影响 unique_id
entry5b = new_entry(device_alias="我的手机")
t5b = build_tracker(entry5b)
check("改别名后 unique_id 不变（历史数据不丢）",
      t5b.unique_id == t5.unique_id, f"{t5b.unique_id!r} vs {t5.unique_id!r}")

# ---------------------------------------------------------------- 6
section("6. 传感器继承设备名（_attr_has_entity_name=True）")

entry6 = new_entry(device_alias="iQOOO")
coordinator6, _ = L.make_coordinator(coord_mod, entry6)
s6 = sensor_mod.VivoFindSensor(coordinator6, desc)
check("sensor.device_info['name'] 用别名",
      s6.device_info["name"] == "iQOOO", s6.device_info["name"])
check("sensor._attr_has_entity_name 为 True",
      sensor_mod.VivoFindSensor._attr_has_entity_name is True)
print(f"          → 完整实体 ID：sensor.iqooo_{desc.key}")

# ---------------------------------------------------------------- 7
section("7. device_info 的 identifiers 与名称一致（同一台设备归一个设备卡）")

check(
    "tracker 与 sensor 指向同一 identifiers",
    t5.device_info["identifiers"] == s5.device_info["identifiers"],
    f"{t5.device_info['identifiers']} vs {s5.device_info['identifiers']}",
)

# ---------------------------------------------------------------- 8
section("8. 用户实测场景：vivo 把机型名当别名返回")

# 真实情况：用户从没给设备改过名，vivo 就返回 alias='iQOO Neo10 Pro'，
# 于是 title / 名称 / entity_id 全变成 iqoo_neo10_pro。
# 这不是 bug（alias 确实是这个值），但**必须**可解释、可预期。
entry8 = new_entry(device_alias="iQOO Neo10 Pro", device_model="iQOO Neo10 Pro")
t8 = build_tracker(entry8)
check("alias 就是机型时，名称如实采用 alias",
      t8.name == "iQOO Neo10 Pro", f"name={t8.name!r}")
print(f"          → entity_id = {slugify_entity_id('device_tracker', t8.name)}")
print(f"          → 用户预期是 device_tracker.iqooo，差在「去 vivo 网站给设备改名」")

# 用户改名之后（这里是我们在配置阶段把 alias 换掉的效果）
entry8b = new_entry(device_alias="iQOOO", device_model="iQOO Neo10 Pro")
t8b = build_tracker(entry8b)
check("改名后 entity_id 变成 iqooo",
      slugify_entity_id("device_tracker", t8b.name) == "device_tracker.iqooo",
      slugify_entity_id("device_tracker", t8b.name))
check("改名后 unique_id 不变（IMEI 锚定，历史数据不丢）",
      t8b.unique_id == t8.unique_id, f"{t8b.unique_id!r} vs {t8.unique_id!r}")

# ---------------------------------------------------------------- 9
section("9. 两平台取名必须完全一致（否则设备卡片会分裂成两张）")

for alias, model in [("iQOOO", "iQOO Neo10 Pro"), ("iQOO Neo10 Pro", "iQOO Neo10 Pro")]:
    e = new_entry(device_alias=alias, device_model=model)
    tr = build_tracker(e)
    c, _ = L.make_coordinator(coord_mod, e)
    sn = sensor_mod.VivoFindSensor(c, desc)
    check(f"tracker/sensor 同名（alias={alias!r}）",
          tr.name == sn.device_info["name"],
          f"{tr.name!r} vs {sn.device_info['name']!r}")

# ----------------------------------------------------------------
print()
print("=" * 72)
if FAILED:
    print(f"失败 {len(FAILED)} 项 / 通过 {len(PASSED)} 项")
    for f in FAILED:
        print(f"   - {f}")
    raise SystemExit(1)
print(f"全部通过（{len(PASSED)} 项）")
