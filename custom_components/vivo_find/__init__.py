"""VIVO 查找设备 - HA 自定义集成入口。

把 vivo 云服务（find.vivo.com.cn）的设备位置接入 Home Assistant，
核心产物是一个 GPS device_tracker 实体，可直接用于地图卡片与 zone 自动化。
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import VivoFindCoordinator
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """建立一个配置项。"""
    coordinator = VivoFindCoordinator(hass, entry)
    # 先把上次运行的数据读回来，再刷新。
    # 顺序不能反 —— 首次刷新要用它当兜底值：重启/重载后的第一轮经常取不齐
    # 数据（限流窗口未过、设备刚联网），有缓存兜底就不会出现
    # 「刚加载完电量、位置全是空的，得再重载一次」。
    await coordinator.async_restore()
    # 首次刷新失败（网络不通 / cookie 失效）会抛 ConfigEntryNotReady，
    # HA 会自动稍后重试，不会把集成标记为失败。
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # 服务是域级别的，注册一次即可（内部有幂等判断）
    await async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform(platform) for platform in PLATFORMS]
    )

    # 用户在「选项」里改了间隔/定位开关后自动重载
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置项。"""
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, [Platform(platform) for platform in PLATFORMS]
    )
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """选项变更后重新加载集成。"""
    await hass.config_entries.async_reload(entry.entry_id)
