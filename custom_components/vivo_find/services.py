"""VIVO 查找设备 - 自定义服务。

目前只提供一个 ``vivo_find.locate_now``：立刻下发一次定位指令。

为什么需要它：地址（``locationDesc``）**只随定位指令成功返回**，而常规轮询
要等一个周期（默认 10 分钟），被限流时还要更久。想在「到家前查一下」或者
「刚改完 cookie 想验证」时立刻看到结果，用这个服务比缩小轮询间隔安全得多
—— 它不绕过限流冷却，连点也不会把接口撞得更深。
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import ATTR_FORCE, DOMAIN, SERVICE_LOCATE_NOW
from .coordinator import VivoFindCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_LOCATE_NOW_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_FORCE, default=False): cv.boolean,
        vol.Optional("entry_id"): cv.string,
    }
)


async def async_register_services(hass: HomeAssistant) -> None:
    """注册服务（重复调用安全）。"""
    if hass.services.has_service(DOMAIN, SERVICE_LOCATE_NOW):
        return

    async def _handle_locate_now(call: ServiceCall) -> dict[str, Any]:
        force: bool = call.data.get(ATTR_FORCE, False)
        wanted_entry: str | None = call.data.get("entry_id")

        entries = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
            and (wanted_entry is None or entry.entry_id == wanted_entry)
        ]
        if not entries:
            raise HomeAssistantError(
                "没有已加载的 VIVO 查找设备配置项"
                + (f"（entry_id={wanted_entry}）" if wanted_entry else "")
            )

        results: list[dict[str, str]] = []
        for entry in entries:
            coordinator: VivoFindCoordinator | None = hass.data.get(DOMAIN, {}).get(
                entry.entry_id
            )
            if coordinator is None:
                continue
            try:
                message = await coordinator.async_locate_now(force=force)
            except Exception as err:  # noqa: BLE001 - 服务不该因单个条目失败而中断
                _LOGGER.exception("手动定位失败: %s", entry.title)
                message = f"出错：{err}"
            _LOGGER.info("locate_now → %s：%s", entry.title, message)
            results.append({"entry": entry.title, "result": message})

        if not results:
            raise HomeAssistantError("找到配置项但未取到协调器，集成可能正在重载")

        return {"results": results}

    hass.services.async_register(
        DOMAIN,
        SERVICE_LOCATE_NOW,
        _handle_locate_now,
        schema=SERVICE_LOCATE_NOW_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
