"""VIVO 查找设备 - 附加传感器。

地图上的点只能看位置，看不到电量和网络，这里补齐。
所有实体都挂在同一个 HA 设备下，方便归类。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEVICE_ALIAS,
    CONF_DEVICE_EMMCID,
    CONF_DEVICE_IMEI,
    CONF_DEVICE_MODEL,
    DOMAIN,
    LOCATE_FAILED,
    LOCATE_SKIP_COOLDOWN,
    LOCATE_SKIP_DISABLED,
    LOCATE_SKIP_FIRST,
    LOCATE_SKIP_OFFLINE,
    LOCATE_THROTTLED,
    LOCATE_TIMEOUT,
    MANUFACTURER,
)
from .coordinator import VivoFindCoordinator, VivoFindData

# 地址为空时，按「本轮定位结果」给一句人话解释
_ADDRESS_HINTS = {
    LOCATE_THROTTLED: "被 vivo 限流了，等冷却结束后会自动补上；"
    "也可调用 vivo_find.locate_now 手动补一次",
    LOCATE_TIMEOUT: "定位指令超时（设备可能未联网/关机），会自动重试",
    LOCATE_FAILED: "定位指令执行失败，会自动重试",
    LOCATE_SKIP_COOLDOWN: "本轮处于定位冷却中，地址沿用上次的；"
    "等下一轮会自动重试",
    LOCATE_SKIP_FIRST: "首轮避让（已有地址，跳过定位以避开限流窗口）",
    LOCATE_SKIP_OFFLINE: "设备当前离线，拿不到新地址",
    LOCATE_SKIP_DISABLED: "「每次刷新下发定位指令」已关闭 —— "
    "地址只随定位指令返回，关闭后地址不会更新",
}


@dataclass(frozen=True, kw_only=True)
class VivoSensorDescription(SensorEntityDescription):
    """带取值函数的传感器描述。"""

    value_fn: Callable[[VivoFindData], Any]


SENSORS: tuple[VivoSensorDescription, ...] = (
    VivoSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda d: d.battery,
    ),
    VivoSensorDescription(
        key="charging",
        translation_key="charging",
        icon="mdi:power-plug-battery",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            None if d.charging is None else ("充电中" if d.charging else "未充电")
        ),
    ),
    VivoSensorDescription(
        key="online",
        translation_key="online",
        icon="mdi:access-point-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: "在线" if d.online else "离线",
    ),
    VivoSensorDescription(
        key="address",
        translation_key="address",
        icon="mdi:map-marker-radius",
        value_fn=lambda d: d.address,
    ),
    VivoSensorDescription(
        key="network",
        translation_key="network",
        icon="mdi:signal",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.network,
    ),
    VivoSensorDescription(
        key="fix_time",
        translation_key="fix_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.fix_time,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VivoFindCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        VivoFindSensor(coordinator, description) for description in SENSORS
    )


class VivoFindSensor(CoordinatorEntity[VivoFindCoordinator], SensorEntity):
    """单个只读传感器。"""

    _attr_has_entity_name = True
    entity_description: VivoSensorDescription

    def __init__(
        self, coordinator: VivoFindCoordinator, description: VivoSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.entry
        data = coordinator.data
        # 与 device_tracker 同理：unique_id 必须来自配置项里的静态值，
        # 否则运行期数据一变（首次刷新取不到 imei）实体就会被重建
        device_key = (
            entry.data.get(CONF_DEVICE_IMEI)
            or entry.data.get(CONF_DEVICE_EMMCID)
            or (data.imei if data else None)
            or (data.emmc_id if data else None)
            or entry.entry_id
        )
        self._attr_unique_id = f"{DOMAIN}_{device_key}_{description.key}"

    @property
    def device_info(self) -> dict[str, Any]:
        data = self.coordinator.data
        entry = self.coordinator.entry
        imei = (
            entry.data.get(CONF_DEVICE_IMEI)
            or (data.imei if data else None)
            or entry.data.get(CONF_DEVICE_EMMCID)
        )
        return {
            "identifiers": {(DOMAIN, imei or entry.entry_id)},
            "name": entry.data.get(CONF_DEVICE_ALIAS) or entry.title,
            "manufacturer": MANUFACTURER,
            "model": (data.device_model if data else None)
            or entry.data.get(CONF_DEVICE_MODEL)
            or "查找设备",
            "configuration_url": "https://find.vivo.com.cn/",
        }

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """给地址传感器补上「这个地址有多旧 + 为什么没更新」。

        地址只随定位指令成功返回，所以它变空/不更新时，用户最想知道两件事：
        手里这个是多久前拿到的、这一轮到底是因为什么没拿到新的。
        直接把答案挂在这个实体上，比让人去翻 14 个属性方便。
        """
        if self.entity_description.key != "address":
            return None
        data = self.coordinator.data
        if data is None:
            return None
        return {
            "address_time": (
                data.address_time.isoformat() if data.address_time else None
            ),
            "address_age_s": (
                int((dt_util.utcnow() - data.address_time).total_seconds())
                if data.address_time
                else None
            ),
            "locate_status": data.locate_status,
            "hint": _ADDRESS_HINTS.get(
                data.locate_status or "",
                None if data.address else "地址只随定位指令成功返回；"
                "可在「开发者工具 → 服务」里调用 vivo_find.locate_now 手动补一次",
            ),
        }
