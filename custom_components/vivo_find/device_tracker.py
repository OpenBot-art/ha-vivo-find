"""VIVO 查找设备 - device_tracker 实体（HA 地图上的那个点）。

HA 的地图卡片只渲染 device_tracker（source_type=gps）和 person 实体，
所以这是让设备位置出现在地图上的关键实体。
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEVICE_EMMCID,
    CONF_DEVICE_IMEI,
    DOMAIN,
    MANUFACTURER,
    resolve_device_name,
)
from .coordinator import VivoFindCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VivoFindCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VivoFindDeviceTracker(coordinator)])


class VivoFindDeviceTracker(CoordinatorEntity[VivoFindCoordinator], TrackerEntity):
    """把 VIVO 云服务返回的坐标暴露成 GPS 设备追踪器。"""

    _attr_has_entity_name = False
    _attr_source_type = SourceType.GPS
    _attr_icon = "mdi:cellphone-marker"

    def __init__(self, coordinator: VivoFindCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.entry
        data = coordinator.data
        # 名称与 unique_id 一律优先取配置项里的静态值，绝不依赖运行期数据。
        # 否则首次刷新拿不到 alias/imei 时会退化成兜底值，下一次刷新又变回来，
        # HA 会当成另一个实体重建 —— 表现为「要重载一次才正常」。
        #
        # ⚠️ 名称只认「别名」，**不要**回退到型号。
        # 型号（如 `iQOO Neo10 Pro`）是产品线名，两台同型号手机必然撞名，
        # 而别名（如 `iQOOO`）才是用户给这台机器起的唯一名字。用型号当名称
        # 会让实体 ID 变成 `device_tracker.iqoo_neo10pro`，既与用户预期不符，
        # 也无法区分同型号的两台设备。
        self._attr_name = resolve_device_name(entry)
        device_key = (
            entry.data.get(CONF_DEVICE_IMEI)
            or entry.data.get(CONF_DEVICE_EMMCID)
            or (data.imei if data else None)
            or (data.emmc_id if data else None)
            or entry.entry_id
        )
        self._attr_unique_id = f"{DOMAIN}_{device_key}"

    @property
    def _data(self):
        return self.coordinator.data

    @property
    def available(self) -> bool:
        """只要有坐标就保持可用。

        刻意不看 last_update_success：单轮失败（限流、网络抖动）不该让地图上
        的点消失 —— 位置的语义本来就是「最后已知」，zone / person 做到家判定
        时更需要它一直在。数据是否陈旧看 fix_time 属性。
        """
        data = self._data
        return data is not None and data.has_coordinates

    @property
    def device_info(self) -> dict[str, Any]:
        data = self._data
        entry = self.coordinator.entry
        imei = (
            entry.data.get(CONF_DEVICE_IMEI)
            or (data.imei if data else None)
            or entry.data.get(CONF_DEVICE_EMMCID)
        )
        return {
            "identifiers": {(DOMAIN, imei or entry.entry_id)},
            "name": self._attr_name,
            "manufacturer": MANUFACTURER,
            "model": (data.device_model if data else None) or "查找设备",
            "configuration_url": "https://find.vivo.com.cn/",
        }

    # ---------- 地图定位所需的属性 ----------

    @property
    def latitude(self) -> float | None:
        return self._data.latitude if self._data else None

    @property
    def longitude(self) -> float | None:
        return self._data.longitude if self._data else None

    @property
    def location_accuracy(self) -> int:
        """误差半径（米）。没有的话给个保守值。"""
        data = self._data
        if data and data.accuracy:
            return int(data.accuracy)
        return 100

    @property
    def battery_level(self) -> int | None:
        return self._data.battery if self._data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._data
        if data is None:
            return {}
        return {
            "address": data.address,
            # 地址是哪一刻拿到的。地址只随定位指令成功返回，可能比 fix_time
            # 旧很多 —— 想判断「地址是不是刚刷新的」看这个，不是看 fix_time。
            "address_time": (
                data.address_time.isoformat() if data.address_time else None
            ),
            "address_age_s": (
                int((dt_util.utcnow() - data.address_time).total_seconds())
                if data.address_time
                else None
            ),
            # 地图上那个点的坐标（已按配置换算到 target_crs）
            "latitude": data.latitude,
            "longitude": data.longitude,
            "coordinates": (
                f"{data.longitude:.6f},{data.latitude:.6f}"
                if data.has_coordinates
                else None
            ),
            # 接口原样返回的坐标，用于实地核对偏移
            "raw_coordinates": (
                f"{data.raw_longitude:.6f},{data.raw_latitude:.6f}"
                if data.raw_longitude is not None and data.raw_latitude is not None
                else None
            ),
            "source_crs": data.source_crs,
            "target_crs": data.target_crs,
            "online": data.online,
            "online_raw": data.online_raw,
            "located_live": data.located_live,
            "locate_throttled": data.locate_throttled,
            # 本轮定位指令的结果，见 README 的状态码表。
            # 位置/地址没更新时，先看这里，一眼知道是限流、超时还是冷却跳过。
            "locate_status": data.locate_status,
            "fix_time": data.fix_time.isoformat() if data.fix_time else None,
            # 坐标距今多少秒 —— 一眼看出地图上的点是新的还是几小时前的
            "position_age_s": (
                int((dt_util.utcnow() - data.fix_time).total_seconds())
                if data.fix_time
                else None
            ),
            # 本轮拉取是否成功。false 说明这些值来自缓存/上一次有效读数，
            # 实体仍可用（地图上的点不会消失），但要知道数据是旧的
            "last_update_success": self.coordinator.last_update_success,
            "accuracy": data.accuracy,
            "network": data.network,
            "signal_strength": data.signal,
            "operator": data.operator,
            "charging": data.charging,
            "device_model": data.device_model,
            "imei": data.imei,
            "source": "vivo_find",
        }
