"""VIVO 查找设备 - 配置流程（UI 添加 / 重认证 / 选项）。"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    VivoFindAuthError,
    VivoFindClient,
    VivoFindConnectionError,
    VivoFindError,
)
from .const import (
    CONF_COOKIE,
    CONF_DEVICE_ALIAS,
    CONF_DEVICE_EMMCID,
    CONF_DEVICE_IMEI,
    CONF_DEVICE_MODEL,
    CONF_DEVICE_NAME,
    CONF_LOCATE_ON_UPDATE,
    CONF_SCAN_INTERVAL,
    CONF_SOURCE_CRS,
    CONF_TARGET_CRS,
    DEFAULT_LOCATE_ON_UPDATE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SOURCE_CRS,
    DEFAULT_TARGET_CRS,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# 下拉选项的展示文案写死在代码里（而非 translations），
# 因为这些选项本身就带中文说明，翻译文件反而更难维护。
_SOURCE_CRS_OPTIONS = [
    SelectOptionDict(
        value="bd09",
        label="BD-09 百度坐标（推荐 · vivo 接口实测返回的就是它）",
    ),
    SelectOptionDict(value="gcj02", label="GCJ-02 火星坐标（高德 / 腾讯）"),
    SelectOptionDict(value="wgs84", label="WGS84 GPS 原始坐标"),
]

_TARGET_CRS_OPTIONS = [
    SelectOptionDict(
        value="wgs84",
        label="WGS84（推荐 · HA 默认 OSM 地图、zone/person 判定都用它）",
    ),
    SelectOptionDict(
        value="gcj02",
        label="GCJ-02（仅当你用高德底图的自定义卡片时才选这个）",
    ),
    SelectOptionDict(value="bd09", label="BD-09 百度坐标"),
]


def _crs_selector(options: list[SelectOptionDict]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
    )


def _build_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_COOKIE, default=defaults.get(CONF_COOKIE, vol.UNDEFINED)
            ): TextSelector(TextSelectorConfig(multiline=True)),
            vol.Optional(
                CONF_DEVICE_NAME, default=defaults.get(CONF_DEVICE_NAME, "")
            ): TextSelector(),
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=30,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="秒",
                )
            ),
            vol.Optional(
                CONF_LOCATE_ON_UPDATE,
                default=defaults.get(
                    CONF_LOCATE_ON_UPDATE, DEFAULT_LOCATE_ON_UPDATE
                ),
            ): bool,
            vol.Optional(
                CONF_SOURCE_CRS,
                default=defaults.get(CONF_SOURCE_CRS, DEFAULT_SOURCE_CRS),
            ): _crs_selector(_SOURCE_CRS_OPTIONS),
            vol.Optional(
                CONF_TARGET_CRS,
                default=defaults.get(CONF_TARGET_CRS, DEFAULT_TARGET_CRS),
            ): _crs_selector(_TARGET_CRS_OPTIONS),
        }
    )


async def _validate(hass, user_input: dict[str, Any]) -> dict[str, Any]:
    """校验 cookie 与设备名，返回解析到的设备。"""
    client = VivoFindClient(
        async_get_clientsession(hass), user_input[CONF_COOKIE]
    )
    device = await client.async_resolve_device(user_input.get(CONF_DEVICE_NAME))
    await client.async_get_status(device)
    return device


def _device_identity(device: dict[str, Any]) -> dict[str, str]:
    """把校验时解析到的设备身份固化下来。

    为什么要在配置阶段就存：实体的 unique_id 与名称必须稳定。若让它们依赖
    运行期数据（coordinator.data.imei），那么某次刷新拿不到 imei 时
    unique_id 会退化成兜底值，下一次刷新拿全了又变回真值 —— HA 会当成两个
    不同实体，表现为「实体凭空多一个、旧的变不可用」，用户配好的地图卡片和
    自动化全部指向失效的实体。存进 entry.data 就与运行期彻底解耦。
    """
    return {
        CONF_DEVICE_IMEI: str(device.get("imei") or ""),
        CONF_DEVICE_EMMCID: str(device.get("emmcId") or ""),
        CONF_DEVICE_ALIAS: (device.get("alias") or "").strip(),
        CONF_DEVICE_MODEL: str(device.get("model") or device.get("modelName") or ""),
    }


class VivoFindConfigFlow(ConfigFlow, domain=DOMAIN):
    """添加集成时的流程。"""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: ConfigEntry | None = None

    # ---------- 首次添加 ----------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                device = await _validate(self.hass, user_input)
            except VivoFindAuthError as err:
                _LOGGER.warning("VIVO 认证失败: %s", err)
                errors["base"] = "auth"
            except VivoFindConnectionError as err:
                _LOGGER.warning("VIVO 连接失败: %s", err)
                errors["base"] = "cannot_connect"
            except VivoFindError as err:
                _LOGGER.warning("VIVO 配置校验失败: %s", err)
                errors["base"] = "no_device"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("VIVO 配置校验出现未预期错误")
                errors["base"] = "unknown"
            else:
                imei = str(device.get("imei") or device.get("emmcId") or "")
                await self.async_set_unique_id(f"{DOMAIN}_{imei}")
                self._abort_if_unique_id_configured()

                alias = (device.get("alias") or "").strip() or "VIVO 设备"
                # 设备身份一并写进 entry.data，供实体生成稳定的 unique_id
                # （title 也用它，是 entity_id 的稳定来源）
                return self.async_create_entry(
                    title=alias,
                    data={**user_input, **_device_identity(device)},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(user_input),
            errors=errors,
        )

    # ---------- Cookie 过期后重认证 ----------

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        entry = self._reauth_entry
        if entry is None:
            return self.async_abort(reason="reauth_failed")

        if user_input is not None:
            merged = {**entry.data, CONF_COOKIE: user_input[CONF_COOKIE]}
            try:
                device = await _validate(self.hass, merged)
            except VivoFindAuthError:
                errors["base"] = "auth"
            except VivoFindConnectionError:
                errors["base"] = "cannot_connect"
            except VivoFindError:
                errors["base"] = "no_device"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("VIVO 重认证出现未预期错误")
                errors["base"] = "unknown"
            else:
                # 顺手把设备身份补进 entry.data —— 老版本装的集成没有这几个
                # 字段，重认证正好是一次无损的补齐时机
                identity = _device_identity(device)
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **merged,
                        **{k: v for k, v in identity.items() if v},
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_COOKIE): TextSelector(
                        TextSelectorConfig(multiline=True)
                    )
                }
            ),
            description_placeholders={"name": entry.title},
            errors=errors,
        )

    # ---------- 选项 ----------

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return VivoFindOptionsFlow()


class VivoFindOptionsFlow(OptionsFlow):
    """调整轮询间隔与是否下发定位指令，无需删除重加。"""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self.config_entry
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {
            CONF_SCAN_INTERVAL: entry.options.get(
                CONF_SCAN_INTERVAL,
                entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ),
            CONF_LOCATE_ON_UPDATE: entry.options.get(
                CONF_LOCATE_ON_UPDATE,
                entry.data.get(CONF_LOCATE_ON_UPDATE, DEFAULT_LOCATE_ON_UPDATE),
            ),
            CONF_SOURCE_CRS: entry.options.get(
                CONF_SOURCE_CRS,
                entry.data.get(CONF_SOURCE_CRS, DEFAULT_SOURCE_CRS),
            ),
            CONF_TARGET_CRS: entry.options.get(
                CONF_TARGET_CRS,
                entry.data.get(CONF_TARGET_CRS, DEFAULT_TARGET_CRS),
            ),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=current[CONF_SCAN_INTERVAL]
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=30,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="秒",
                        )
                    ),
                    vol.Optional(
                        CONF_LOCATE_ON_UPDATE,
                        default=current[CONF_LOCATE_ON_UPDATE],
                    ): bool,
                    vol.Optional(
                        CONF_SOURCE_CRS, default=current[CONF_SOURCE_CRS]
                    ): _crs_selector(_SOURCE_CRS_OPTIONS),
                    vol.Optional(
                        CONF_TARGET_CRS, default=current[CONF_TARGET_CRS]
                    ): _crs_selector(_TARGET_CRS_OPTIONS),
                }
            ),
        )
