"""坐标系转换 —— 解决国内地图偏移（WGS84 / GCJ-02 / BD-09）。

为什么这个模块必须存在
----------------------
vivo 云服务返回的经纬度是 **BD-09（百度坐标）**，而 Home Assistant 内部
统一使用 **WGS84**：device_tracker 规范、zone / person 的到家判定，以及
默认的 OpenStreetMap 底图，全部基于 WGS84。

如果直接把 BD-09 当 WGS84 交给 HA，地图上的点会**偏移约 1.2 公里**
（武汉地区实测位移 lng +0.011962 / lat +0.003878 ≈ 1225 米），
看起来就是"位置跟我实际在的地方不是一回事"。

判定依据（2026-09-18 实测，四重证据交叉验证）
---------------------------------------------
vivo 返回 `114.350962, 30.558978`，自报地址
「武重四街坊，湖北省武汉市武昌区水果湖街道东湖路104号」。

**证据 1 — 门牌号。** 高德对「东湖路104号」的门址级解析是
`114.343824, 30.552492`。该点距各候选：

    假设接口是     高德应显示点          距「东湖路104号」门址
    bd09          114.344537,30.552745        74 m   ← 吻合
    gcj02         114.350962,30.558978       994 m
    wgs84         114.356473,30.556639      1296 m

门牌号是最精确的地址要素，994 米/1296 米的偏差不可能。

**证据 2 — 小区门牌归属。** vivo 报的门牌是「东湖路104号」。而高德 POI 显示：
「中北路四街坊」的门牌是**东湖路97号**、「仙茶(东湖路店)」是**东湖路91号** ——
都落在武重四街坊一带，且距 bd09 候选 135 m / 154 m。
相反，「复地·东湖国际四期」的门牌是**兴武路1号 / 中北路118号**，根本不在东湖路上，
距 bd09 候选约 1000 米。也就是说只有 BD-09 假设才和 vivo 自报的地址对得上。

**证据 3 — 高德官方转换接口。** 把 vivo 原值交给高德 coordinate_convert
（coordsys=baidu）得到 `114.344537, 30.552745`，与本地 bd09_to_gcj02 只差
**0.11 米**；而按 coordsys=gps 转换得到的点距「东湖路104号」有 1296 米。

**证据 4 — POI 群簇。** 「武重四街坊」「武重宿舍」「中北路四街坊」
「汉街总部国际C座」等 5 个独立 POI 全部落在 bd09 候选 84~166 米范围内，
而距接口原值均在 800~950 米。

四重证据一致指向：**vivo 返回 BD-09**。合理推测是 vivo 端使用百度地图 SDK
做定位与逆地理编码，因此坐标与地址描述都是百度体系。

> 排查记录：最初用「复地·东湖国际四期」单个 POI 做锚点时曾误判为 GCJ-02
> （该 POI 距原值仅 121 米）。后来发现那是巧合 —— BD-09 的偏移量恰好把
> 「武重四街坊」搬到了「复地·东湖国际」附近，两个 POI 相距本来就有约 1 公里。
> 判坐标系必须用门牌级证据 + 多个独立锚点，单个 POI 会骗人。

单位与约定
----------
* 全部函数使用 `(longitude, latitude)` 顺序、十进制度。
* HA 侧最后统一输出 WGS84（除非用户显式选择输出 GCJ-02 给高德底图卡片）。
* 中国境外不做偏移（GCJ-02 / BD-09 只在大陆范围内有意义）。
"""
from __future__ import annotations

import math

# ---- 坐标系标识 ----
CRS_WGS84 = "wgs84"
CRS_GCJ02 = "gcj02"
CRS_BD09 = "bd09"

CRS_LABELS: dict[str, str] = {
    CRS_WGS84: "WGS84（GPS 原始坐标，国际标准 / OSM / HA 默认）",
    CRS_GCJ02: "GCJ-02（火星坐标，高德 / 腾讯 / 国内多数厂商）",
    CRS_BD09: "BD-09（百度坐标）",
}

# 克拉索夫斯基椭球参数（GCJ-02 加密算法固定使用）
_A = 6378245.0
_EE = 0.00669342162296594323
# 百度坐标转换用的圆周率常量
_X_PI = math.pi * 3000.0 / 180.0

# 中国大陆粗略范围（用于判断是否需要偏移）
_CHINA_LNG = (73.66, 135.05)
_CHINA_LAT = (3.86, 53.55)


def out_of_china(lng: float, lat: float) -> bool:
    """是否在中国大陆范围之外 —— 境外不做偏移。"""
    return not (_CHINA_LNG[0] < lng < _CHINA_LNG[1] and _CHINA_LAT[0] < lat < _CHINA_LAT[1])


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """WGS84 → GCJ-02（正向加密算法）。"""
    if out_of_china(lng, lat):
        return lng, lat
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = 1 - _EE * math.sin(rad_lat) ** 2
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    dlng = (dlng * 180.0) / (_A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return lng + dlng, lat + dlat


def gcj02_to_wgs84(lng: float, lat: float, iterations: int = 3) -> tuple[float, float]:
    """GCJ-02 → WGS84（迭代逼近）。

    没有解析反函数，常见做法是 `2*x - forward(x)`，误差约 1~2 米。
    这里用迭代法把误差压到厘米级，迭代 3 次即收敛。
    """
    if out_of_china(lng, lat):
        return lng, lat
    wlng, wlat = lng, lat
    for _ in range(iterations):
        glng, glat = wgs84_to_gcj02(wlng, wlat)
        wlng += lng - glng
        wlat += lat - glat
    return wlng, wlat


def gcj02_to_bd09(lng: float, lat: float) -> tuple[float, float]:
    """GCJ-02 → BD-09。"""
    if out_of_china(lng, lat):
        return lng, lat
    z = math.sqrt(lng * lng + lat * lat) + 0.00002 * math.sin(lat * _X_PI)
    theta = math.atan2(lat, lng) + 0.000003 * math.cos(lng * _X_PI)
    return z * math.cos(theta) + 0.0065, z * math.sin(theta) + 0.006


def bd09_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """BD-09 → GCJ-02。"""
    if out_of_china(lng, lat):
        return lng, lat
    x = lng - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * _X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * _X_PI)
    return z * math.cos(theta), z * math.sin(theta)


def wgs84_to_bd09(lng: float, lat: float) -> tuple[float, float]:
    return gcj02_to_bd09(*wgs84_to_gcj02(lng, lat))


def bd09_to_wgs84(lng: float, lat: float) -> tuple[float, float]:
    return gcj02_to_wgs84(*bd09_to_gcj02(lng, lat))


_TO_WGS84 = {
    CRS_WGS84: lambda lng, lat: (lng, lat),
    CRS_GCJ02: gcj02_to_wgs84,
    CRS_BD09: bd09_to_wgs84,
}

_FROM_WGS84 = {
    CRS_WGS84: lambda lng, lat: (lng, lat),
    CRS_GCJ02: wgs84_to_gcj02,
    CRS_BD09: wgs84_to_bd09,
}


def to_wgs84(lng: float, lat: float, source: str) -> tuple[float, float]:
    """把 `source` 坐标系的点转成 WGS84。未知坐标系按原样返回。"""
    fn = _TO_WGS84.get(source)
    return fn(lng, lat) if fn else (lng, lat)


def from_wgs84(lng: float, lat: float, target: str) -> tuple[float, float]:
    """把 WGS84 的点转成 `target` 坐标系。未知坐标系按原样返回。"""
    fn = _FROM_WGS84.get(target)
    return fn(lng, lat) if fn else (lng, lat)


def convert(lng: float, lat: float, source: str, target: str) -> tuple[float, float]:
    """任意坐标系之间互转（经由 WGS84 中转）。

    偏移量很小（几百米），中转带来的额外误差可忽略。
    """
    if source == target:
        return lng, lat
    return from_wgs84(*to_wgs84(lng, lat, source), target)


# 允许出现在配置里的坐标系取值
VALID_CRS = (CRS_WGS84, CRS_GCJ02, CRS_BD09)
