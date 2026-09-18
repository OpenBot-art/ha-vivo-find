"""VIVO 云服务（查找手机）HTTP 客户端。

参考接口（webcloud.vivo.com.cn/findphone）：
  POST v3/devices     获取设备列表
  POST devicestatus   获取在线状态 / 位置 / 电量 / 网络（需 x-yun-csrftoken 头）
  POST operate        下发「查找设备」指令，拿到 cmdId
  POST polling        轮询指令执行状态，execStatus==2 表示定位成功

注意：devicestatus 返回的位置在未下发定位指令前是**上一次定位的缓存值**，
所以想要地图上看到实时位置，需要配合 async_locate()。判断新鲜度看 location.time。
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import (
    MAX_POLLING_TIMES,
    POLLING_INTERVAL,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://webcloud.vivo.com.cn/findphone"
REFERER = "https://find.vivo.com.cn/"
USER_AGENT = (
    "Mozilla/5.0 (Linux; U; Android 8.0.0; zh-cn; Mi Note 2 "
    "Build/OPR1.170623.032) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)

CSRF_PATTERN = re.compile(r"vivo_yun_csrftoken=([^;]+)")


class VivoFindError(Exception):
    """VIVO 接口通用错误。"""


class VivoFindAuthError(VivoFindError):
    """Cookie 失效（接口 code 21005）或 Cookie 缺少必要字段。"""


class VivoFindConnectionError(VivoFindError):
    """网络层错误。"""


class VivoFindRateLimitError(VivoFindError):
    """被 vivo 限流（实测 operate 会返回「操作过于频繁」）。

    重要：这是**可恢复**错误，几分钟后自动解除，不应视为致命失败。
    另外实测发现限流状态下 devicestatus 会返回**空的 batteryInfo / signalInfo
    且不报错**，所以上层不能拿空值覆盖已有数据。
    """


class VivoFindClient:
    """无状态（除 round 计数外）的 VIVO 云服务客户端。"""

    def __init__(self, session: aiohttp.ClientSession, cookie: str) -> None:
        self._session = session
        self._cookie = cookie.strip()
        matched = CSRF_PATTERN.search(self._cookie)
        if not matched:
            raise VivoFindAuthError(
                "Cookie 中缺少 vivo_yun_csrftoken 字段，请在浏览器 F12 复制完整 Cookie"
            )
        self._csrftoken = matched.group(1)
        self._round = 0

    # ---------- 底层请求 ----------

    def _next_round(self) -> int:
        self._round += 1
        return self._round

    def _headers(self, *, with_csrf: bool = False) -> dict[str, str]:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Referer": REFERER,
            "Cookie": self._cookie,
            "User-Agent": USER_AGENT,
        }
        if with_csrf:
            headers["x-yun-csrftoken"] = self._csrftoken
        return headers

    async def _post(
        self, path: str, body: str, *, with_csrf: bool = False
    ) -> dict[str, Any]:
        """发送表单请求并返回解析后的 JSON。"""
        url = f"{BASE_URL}/{path}"
        try:
            async with self._session.post(
                url,
                data=body,
                headers=self._headers(with_csrf=with_csrf),
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    raise VivoFindConnectionError(f"{path} 返回 HTTP {resp.status}")
                text = await resp.text()
        except asyncio.TimeoutError as err:
            raise VivoFindConnectionError(f"{path} 请求超时") from err
        except aiohttp.ClientError as err:
            raise VivoFindConnectionError(f"{path} 网络错误: {err}") from err

        import json

        try:
            payload = json.loads(text)
        except ValueError as err:
            raise VivoFindConnectionError(
                f"{path} 返回的不是 JSON（可能被风控拦截）: {text[:120]}"
            ) from err

        if not isinstance(payload, dict):
            raise VivoFindConnectionError(f"{path} 返回结构异常")

        if payload.get("code") == 21005:
            raise VivoFindAuthError("vivo cookie 已过期，请重新获取后更新集成配置")

        # 实测：限流时接口不返回专用 code，只在 msg 里写「操作过于频繁」
        message = str(payload.get("msg") or "")
        if "频繁" in message or "限流" in message:
            raise VivoFindRateLimitError(message or "请求过于频繁")

        return payload

    # ---------- 业务接口 ----------

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """获取账号下的设备列表。"""
        payload = await self._post("v3/devices", "round=0")
        if payload.get("code") != 0:
            raise VivoFindError(
                f"获取设备列表失败: {payload.get('msg') or payload}"
            )
        devices = (payload.get("data") or {}).get("myDevices") or []
        if not isinstance(devices, list):
            raise VivoFindError("设备列表返回结构异常")
        return devices

    async def async_resolve_device(self, device_name: str | None) -> dict[str, Any]:
        """按别名挑出目标设备；只有一个设备时直接返回。"""
        devices = await self.async_get_devices()
        if not devices:
            raise VivoFindError("该账号下没有可用设备")

        if len(devices) == 1:
            return devices[0]

        wanted = (device_name or "").strip()
        for device in devices:
            if (device.get("alias") or "").strip() == wanted:
                return device

        available = "、".join(
            sorted({(d.get("alias") or "未命名").strip() for d in devices})
        )
        raise VivoFindError(
            f"未找到名称为「{wanted}」的设备，账号下可选设备：{available}"
        )

    async def async_get_status(self, device: dict[str, Any]) -> dict[str, Any]:
        """读取设备状态（在线、位置、电量、网络）。位置可能是缓存值。"""
        body = "&".join(
            [
                "version=4",
                f"model={quote(str(device.get('alias') or ''))}",
                f"imei={device.get('imei') or ''}",
                f"round={self._next_round()}",
                "source=devicepage",
                f"emmcId={device.get('emmcId') or ''}",
            ]
        )
        payload = await self._post("devicestatus", body, with_csrf=True)
        return payload.get("data") or {}

    async def async_locate(self, device: dict[str, Any]) -> dict[str, Any]:
        """下发「查找设备」指令并轮询，返回最新的 location 对象。"""
        imei = device.get("imei") or ""
        emmc_id = device.get("emmcId") or ""

        operate_body = "&".join(
            ["cmdType=1", f"imei={imei}", "version=4", f"emmcId={emmc_id}"]
        )
        payload = await self._post("operate", operate_body)
        cmd_id = (payload.get("data") or {}).get("cmdId")
        if not cmd_id:
            raise VivoFindError(
                f"下发定位指令失败: {payload.get('msg') or payload}"
            )

        for attempt in range(1, MAX_POLLING_TIMES + 1):
            await asyncio.sleep(POLLING_INTERVAL)
            polling_body = "&".join(
                [
                    "version=4",
                    f"cmdId={cmd_id}",
                    f"round={self._next_round()}",
                    f"emmcId={emmc_id}",
                    f"imei={imei}",
                ]
            )
            payload = await self._post("polling", polling_body)
            data = payload.get("data") or {}
            exec_status = data.get("execStatus")

            if exec_status == 2:
                _LOGGER.debug("定位成功，第 %s 次轮询", attempt)
                return data.get("location") or {}
            if exec_status == 3:
                raise VivoFindError("设备定位失败（设备可能已关机或未开启查找功能）")

        raise VivoFindError(f"定位超时（轮询 {MAX_POLLING_TIMES} 次仍未返回结果）")
