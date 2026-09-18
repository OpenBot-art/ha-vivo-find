# -*- coding: utf-8 -*-
"""坐标系转换的单元测试 + 外部参照校验。

分两层：
  第一层 纯本地数学自洽性（不联网）：往返一致性、偏移量级、境外不偏移。
  第二层 外部参照（联网）：用高德官方 coordinate_convert 接口（gps → 高德/GCJ-02）
        作为 oracle，校验本地实现的绝对正确性。
"""
from __future__ import annotations

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "custom_components", "vivo_find"))

import _loader  # noqa: E402

cr = _loader.load_module("crs")

PASS = 0
FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK]   {label}" + (f"   {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {label}   {detail}")


def dist_m(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(b), math.radians(d)
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(c - a) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


# ============================================================
print("=" * 70)
print("[1] 本地数学自洽性")
print("=" * 70)

# --- 往返一致性 ---
spots = [
    ("武汉", 114.309761, 30.550594),
    ("北京", 116.391248, 39.906844),
    ("上海", 121.473701, 31.230416),
    ("广州", 113.264385, 23.129112),
    ("乌鲁木齐", 87.616848, 43.825592),
    ("拉萨", 91.140856, 29.645554),
]
for name, lng, lat in spots:
    g_lng, g_lat = cr.wgs84_to_gcj02(lng, lat)
    b_lng, b_lat = cr.gcj02_to_wgs84(g_lng, g_lat)
    err = dist_m(lng, lat, b_lng, b_lat)
    off = dist_m(lng, lat, g_lng, g_lat)
    check(
        f"{name} 往返一致",
        err < 0.05,
        f"往返误差 {err * 100:.2f} cm | 偏移量 {off:.0f} m",
    )
    check(
        f"{name} 偏移量在合理区间(100~900m)",
        100 < off < 900,
        f"{off:.0f} m",
    )

# --- 偏移方向：把接口给的 GCJ 转回 WGS 时，武汉地区应是"经度变小、纬度变大" ---
w = (114.309761, 30.550594)
g = cr.wgs84_to_gcj02(*w)
back = cr.gcj02_to_wgs84(*g)
check(
    "武汉 GCJ→WGS 后经度变小、纬度变大",
    back[0] < g[0] and back[1] > g[1],
    f"GCJ {g[0]:.6f},{g[1]:.6f} → WGS {back[0]:.6f},{back[1]:.6f}",
)

# --- 境外不偏移 ---
for name, lng, lat in [
    ("东京", 139.691711, 35.689487),
    ("纽约", -74.005973, 40.712775),
    ("伦敦", -0.127758, 51.507351),
]:
    g2 = cr.wgs84_to_gcj02(lng, lat)
    check(f"{name} 境外不做偏移", g2 == (lng, lat), f"{g2}")

# --- BD-09 往返 ---
for name, lng, lat in spots[:3]:
    g_lng, g_lat = cr.wgs84_to_gcj02(lng, lat)
    b_lng, b_lat = cr.gcj02_to_bd09(g_lng, g_lat)
    r_lng, r_lat = cr.bd09_to_gcj02(b_lng, b_lat)
    err = dist_m(g_lng, g_lat, r_lng, r_lat)
    check(f"{name} BD-09 往返一致", err < 0.5, f"误差 {err:.3f} m")

# --- convert() ---
c1 = cr.convert(114.309761, 30.550594, "gcj02", "wgs84")
c2 = cr.gcj02_to_wgs84(114.309761, 30.550594)
check("convert() 与直接调用一致", c1 == c2, f"{c1}")
check("convert() 同坐标系恒等", cr.convert(1.0, 2.0, "wgs84", "wgs84") == (1.0, 2.0))
check("convert() 未知坐标系原样返回", cr.convert(1.0, 2.0, "zzz", "wgs84") == (1.0, 2.0))

# --- 真实锚点判定：用实测的 GCJ-02 地标，看哪个坐标系假设最吻合 ---
# 这三个数值来自 2026-09-18 高德实测（门址级 / POI 级，精度足够做判定）。
VIVO_LNG, VIVO_LAT = 114.309931, 30.550455
ANCHORS_GCJ = {
    "蛇山西山坡特1号门址": (114.302467, 30.544649),
    "黄鹤楼红墙POI": (114.302691, 30.547544),
    "胜像宝塔POI": (114.300938, 30.545056),
}
print()
print("--- 用实测 GCJ-02 锚点反推：接口到底是哪个坐标系 ---")
cand_points = {
    "bd09": cr.bd09_to_gcj02(VIVO_LNG, VIVO_LAT),
    "gcj02": (VIVO_LNG, VIVO_LAT),
    "wgs84": cr.wgs84_to_gcj02(VIVO_LNG, VIVO_LAT),
}
for anchor, (alng, alat) in ANCHORS_GCJ.items():
    ds = {k: dist_m(alng, alat, *v) for k, v in cand_points.items()}
    best = min(ds, key=ds.get)
    detail = "  ".join(f"{k}={v:.0f}m" for k, v in ds.items())
    check(f"锚点「{anchor}」→ 最吻合 {best}", best == "bd09", detail)

# ============================================================
print()
print("=" * 70)
print("[2] 集成层：convert_coordinates()")
print("=" * 70)

import _loader as L  # noqa: E402

L.install_ha_stubs()
coord = L.load_module("coordinator")

out = coord.convert_coordinates(VIVO_LNG, VIVO_LAT, "bd09", "wgs84")
off = dist_m(VIVO_LNG, VIVO_LAT, out[0], out[1])
check(
    "BD-09 → WGS84 生效（这是默认路径）",
    out[0] is not None and 1000 < off < 1400,
    f"{out[0]:.6f},{out[1]:.6f}  偏移 {off:.0f} m",
)
check(
    "输出经度与纬度均变小（武汉地区实测方向）",
    out[0] < VIVO_LNG and out[1] < VIVO_LAT,
    f"Δlng={out[0]-VIVO_LNG:+.6f} Δlat={out[1]-VIVO_LAT:+.6f}",
)
# 转换后（WGS84）再转回 GCJ-02，应落在蛇山西山坡特1号附近 —— 闭环验证
back_gcj = cr.wgs84_to_gcj02(out[0], out[1])
d104 = dist_m(*ANCHORS_GCJ["蛇山西山坡特1号门址"], *back_gcj)
check(
    "闭环：BD-09→WGS84→GCJ 后落在「蛇山西山坡特1号」150m 内",
    d104 < 150,
    f"{d104:.0f} m  ({back_gcj[0]:.6f},{back_gcj[1]:.6f})",
)

ident = coord.convert_coordinates(114.309761, 30.550594, "wgs84", "wgs84")
check("同坐标系时不产生偏移", ident == (114.309761, 30.550594), f"{ident}")

check("经度缺失 → (None, None)", coord.convert_coordinates(None, 30.5, "gcj02", "wgs84") == (None, None))
check("纬度缺失 → (None, None)", coord.convert_coordinates(114.3, None, "gcj02", "wgs84") == (None, None))
check("全缺失 → (None, None)", coord.convert_coordinates(None, None, "gcj02", "wgs84") == (None, None))

# --- 反向：输出 GCJ-02（给高德底图卡片用）---
out2 = coord.convert_coordinates(114.309761, 30.550594, "gcj02", "gcj02")
check("target=gcj02 时原样透传（卡片自己处理）", out2 == (114.309761, 30.550594), f"{out2}")

# ============================================================
print()
print("=" * 70)
print("[3] 外部参照：高德官方 coordinate_convert(gps→GCJ-02) 对比")
print("=" * 70)

try:
    sys.path.insert(0, r"C:\Users\Administrator\.workbuddy\skills\gaode-map-pro__skillhub")
    import main as gd

    conv = getattr(gd, "tool_coordinate_convert", None)
    if conv is None:
        print("  (该 skill 未暴露 coordinate_convert，跳过外部参照)")
    else:
        import re

        cases = [
            ("武汉", 114.309931, 30.550455),
            ("北京", 116.391248, 39.906844),
            ("上海", 121.473701, 31.230416),
        ]
        for coordsys, myfn, label in [
            ("gps", cr.wgs84_to_gcj02, "WGS84→GCJ-02"),
            ("baidu", cr.bd09_to_gcj02, "BD-09→GCJ-02"),
        ]:
            print(f"\n  ── coordsys={coordsys}  对照本地 {label} ──")
            for name, lng, lat in cases:
                res = conv({"coords": f"{lng},{lat}", "coordsys": coordsys})
                data = (res or {}).get("data") or {}
                locs = data.get("locations") or data.get("location")
                if not locs:
                    print(f"  [SKIP] {name}: 接口未返回结果  {str(res)[:110]}")
                    continue
                if "*" in str(locs):
                    # 高德会随机给返回值打掩码（防爬），形如 114.3153****1632，
                    # 直接解析会得到被截断的假坐标，必须跳过而不是当成偏差。
                    print(f"  [SKIP] {name}: 接口返回带掩码，无法比对  {str(locs)[:70]}")
                    continue
                nums = [float(x) for x in re.findall(r"-?\d+\.\d+", str(locs))]
                if len(nums) < 2 or not (-180 <= nums[0] <= 180 and -90 <= nums[1] <= 90):
                    print(f"  [SKIP] {name}: 无法解析  {str(locs)[:70]}")
                    continue
                glng, glat = nums[0], nums[1]
                my_lng, my_lat = myfn(lng, lat)
                err = dist_m(glng, glat, my_lng, my_lat)
                check(
                    f"{name} {label} 与高德官方一致(<5m)",
                    err < 5.0,
                    f"高德 {glng:.6f},{glat:.6f} | 本地 {my_lng:.6f},{my_lat:.6f} | 差 {err:.2f} m",
                )

        # 专门验证：把 vivo 实测坐标当 BD-09 交给高德，应落在「蛇山西山坡特1号」附近
        res = conv({"coords": "114.309931,30.550455", "coordsys": "baidu"})
        locs = ((res or {}).get("data") or {}).get("locations")
        nums = [float(x) for x in re.findall(r"-?\d+\.\d+", str(locs))]
        if "*" in str(locs):
            print("  [SKIP] vivo BD-09 门址校验：接口返回带掩码，无法比对")
        elif len(nums) >= 2:
            d = dist_m(nums[0], nums[1], 114.302467, 30.544649)
            check(
                "vivo 坐标按 BD-09 转换后落在「蛇山西山坡特1号」100m 内",
                d < 100,
                f"高德给 {nums[0]:.6f},{nums[1]:.6f}  距门址 {d:.0f} m",
            )
except Exception as exc:  # noqa: BLE001
    print(f"  (外部参照跳过：{exc})")

# ============================================================
print()
print("=" * 70)
print(f"结果：{PASS} 通过 / {FAIL} 失败")
print("=" * 70)
sys.exit(1 if FAIL else 0)
