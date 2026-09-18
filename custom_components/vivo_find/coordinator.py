"""VIVO 查找设备 - 数据协调器。

每次刷新做两件事：
1. devicestatus 读在线状态 / 电量 / 网络 / 位置；
2. 若开启 locate_on_update 且设备在线，再下发一次定位指令刷新实时位置。

三个来自实测的硬约束（2026-09-18 验证）：
* operate 会被限流（返回「操作过于频繁」），**可恢复**，几分钟后自动解除
  → 必须做冷却，且绝不能当成致命错误。
* 限流状态下 devicestatus 会返回**空的 batteryInfo / signalInfo 且不报错**
  → 必须保留上一次的有效值，不能拿空值覆盖。
* online 稳定返回 1；离网为 0。曾观察到限流期间返回 2，
  → 因此只要非 0 即视为在线，并把原始值透出便于排查。

为什么需要「持久化 + 首轮避让 + 快速重试」这三件事
---------------------------------------------------
现象：HA 重启或集成重载后，第一轮刷新经常拿不全数据（电量、网络、位置
为空），要再重载一次才齐。原因有两个，叠加在一起：

1. **首轮没有回退源。** 全新构造的 coordinator 里 ``self.data`` 是 None，
   一旦这一轮 vivo 返回不全，没有任何历史值可以补 —— 而 vivo 在限流状态
   下返回空字段是**不报错**的，所以表现为「静默地什么都没读到」。
   → 用 ``Store`` 把上次成功的数据落盘，重载后先恢复，首轮就有东西兜底。

2. **首轮最容易撞限流。** HA 重启/重载通常紧跟在上一轮定位之后（改配置、
   重启服务），vivo 端的限流窗口还没过。此时首轮就发 ``operate``，大概率
   直接被拒，并把接下来几分钟的定位全部锁死。
   → 首轮若 devicestatus 已经给了坐标，就**不发定位指令**，安静地把缓存
   位置用起来；等下一轮再正常定位。
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import crs
from .api import (
    VivoFindAuthError,
    VivoFindClient,
    VivoFindConnectionError,
    VivoFindError,
    VivoFindRateLimitError,
)
from .const import (
    CONF_COOKIE,
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
    FIRST_REFRESH_RETRIES,
    LOCATE_COOLDOWN,
    LOCATE_FAILED,
    LOCATE_OK,
    LOCATE_RATE_LIMIT_COOLDOWN,
    LOCATE_SKIP_COOLDOWN,
    LOCATE_SKIP_DISABLED,
    LOCATE_SKIP_FIRST,
    LOCATE_SKIP_OFFLINE,
    LOCATE_THROTTLED,
    LOCATE_TIMEOUT,
    RETRY_DELAY,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class VivoFindData:
    """一次刷新得到的设备快照。"""

    online: bool = False
    online_raw: int | None = None
    # latitude/longitude 是**转换后**的坐标，直接交给 HA 使用
    latitude: float | None = None
    longitude: float | None = None
    # 接口原样返回的坐标（BD-09），仅用于诊断与对照，不参与地图定位
    raw_latitude: float | None = None
    raw_longitude: float | None = None
    source_crs: str = DEFAULT_SOURCE_CRS
    target_crs: str = DEFAULT_TARGET_CRS
    accuracy: float | None = None
    address: str | None = None
    fix_time: datetime | None = None
    # 地址是哪一刻拿到的。实测地址**只随定位指令成功返回**，所以它可能比
    # fix_time 旧很多（甚至是几小时前那次定位的产物）—— 单独记一个时间，
    # 免得用户以为地址是实时的。
    address_time: datetime | None = None
    # 本轮定位指令的结果（见 const 里的 LOCATE_* 状态码）。
    # 这是回答「为什么位置/地址没更新」的唯一可靠依据。
    locate_status: str | None = None
    located_live: bool = False
    locate_throttled: bool = False
    battery: int | None = None
    charging: bool | None = None
    network: str | None = None
    signal: str | None = None
    operator: str | None = None
    device_alias: str | None = None
    device_model: str | None = None
    imei: str | None = None
    emmc_id: str | None = None

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pick(new: Any, old: Any) -> Any:
    """新值为空时回退到旧值 —— 限流期间 vivo 会返回空字段。"""
    if new is None or new == "" or new == [] or new == {}:
        return old
    return new


def _describe(data: VivoFindData | None) -> str:
    """给日志用的一句话摘要，排查「首轮缺什么」时直接看这里。"""
    if data is None:
        return "无数据"
    return (
        f"位置={'有' if data.has_coordinates else '无'} "
        f"电量={data.battery if data.battery is not None else '无'} "
        f"网络={data.network or '无'} "
        f"在线={'是' if data.online else '否'}"
    )


def _has_enough(data: VivoFindData, fallback: VivoFindData | None) -> bool:
    """本轮结果是否够用。不够才值得快速重试 —— 否则只是白等。

    标准刻意定得低：位置是核心，电量次之。网络/信号这类字段在限流时
    本来就拿不到，重试 5 秒也救不回来（限流是分钟级的），不值得等。
    """
    if data.has_coordinates:
        return data.battery is not None or (fallback is not None)
    if fallback is not None and fallback.has_coordinates:
        return True
    return False


def serialize_data(data: VivoFindData) -> dict[str, Any]:
    """VivoFindData → 可 JSON 序列化的 dict（datetime 转 ISO 字符串）。"""
    payload: dict[str, Any] = {}
    for field in dataclasses.fields(data):
        value = getattr(data, field.name)
        payload[field.name] = value.isoformat() if isinstance(value, datetime) else value
    return payload


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def deserialize_data(raw: Any) -> VivoFindData:
    """dict → VivoFindData。

    容错优先：字段缺失、类型不对、时间戳格式变了，一律退回默认值而不是报错。
    缓存读不出来最多是少了个兜底，绝不该让集成起不来。
    """
    if not isinstance(raw, dict):
        return VivoFindData()

    known = {field.name for field in dataclasses.fields(VivoFindData)}
    # 所有 datetime 字段都要走 ISO 解析 —— 写死单个字段名容易在加字段时漏掉
    datetime_fields = {
        field.name
        for field in dataclasses.fields(VivoFindData)
        if field.type in ("datetime | None", datetime)
        or (isinstance(field.type, str) and "datetime" in field.type)
    }
    kwargs: dict[str, Any] = {}
    for name, value in raw.items():
        if name not in known or value is None:
            continue
        if name in datetime_fields:
            parsed = _parse_iso(value)
            if parsed is None:
                continue
            kwargs[name] = parsed
        else:
            kwargs[name] = value

    try:
        return VivoFindData(**kwargs)
    except TypeError:
        return VivoFindData()


def convert_coordinates(
    lng: float | None, lat: float | None, source: str, target: str
) -> tuple[float | None, float | None]:
    """接口坐标 → HA 坐标。

    任一坐标为 None 时原样返回 (None, None)，不猜也不补。
    source == target 时是恒等变换，开销可忽略。
    """
    if lng is None or lat is None:
        return None, None
    return crs.convert(lng, lat, source, target)


def _rough_distance_m(lng1: float, lat1: float, lng2: float, lat2: float) -> int:
    """两点粗略距离（米），仅用于日志里体现偏移量级。"""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lam = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    )
    return int(2 * 6371000.0 * math.asin(math.sqrt(a)))


def _parse_fix_time(raw: Any) -> datetime | None:
    """location.time 是毫秒时间戳（服务器时钟，可能比本机快几秒）。"""
    stamp = _safe_int(raw)
    if not stamp or stamp <= 0:
        return None
    moment = datetime.fromtimestamp(stamp / 1000, tz=timezone.utc)
    now = dt_util.utcnow()
    # 服务器时钟略快时会出现"未来时间"，钳到当前时刻避免歧义
    return min(moment, now)


def _parse_network(signal_info: dict[str, Any]) -> str | None:
    if not signal_info:
        return None
    ssid = signal_info.get("wifiSSID")
    if ssid:
        return f"WiFi: {ssid}"
    raw = str(signal_info.get("simNetWorkType") or "").lower().replace(" ", "")
    if not raw:
        return None
    return {
        "5g": "5G",
        "nr": "5G",
        "4g": "4G",
        "lte": "4G",
        "3g": "3G",
        "2g": "2G",
    }.get(raw, raw.upper())


def merge_with_previous(
    data: VivoFindData, previous: VivoFindData | None
) -> VivoFindData:
    """新值为空时回退到上一次的读数。

    为什么必须这么做：实测 vivo 在限流状态下会返回**空的 batteryInfo /
    signalInfo 且不报错**，如果直接覆盖，HA 里的电量、网络会被清成未知。
    位置同理 —— 离线或限流时保留最后一次有效坐标，地图上的点不会闪掉。
    """
    if previous is None:
        return data

    return replace(
        data,
        battery=_pick(data.battery, previous.battery),
        charging=_pick(data.charging, previous.charging),
        network=_pick(data.network, previous.network),
        signal=_pick(data.signal, previous.signal),
        operator=_pick(data.operator, previous.operator),
        latitude=_pick(data.latitude, previous.latitude),
        longitude=_pick(data.longitude, previous.longitude),
        raw_latitude=_pick(data.raw_latitude, previous.raw_latitude),
        raw_longitude=_pick(data.raw_longitude, previous.raw_longitude),
        accuracy=_pick(data.accuracy, previous.accuracy),
        address=_pick(data.address, previous.address),
        # 地址与它的时间戳必须成对回退：地址留着但时间戳没了，
        # 用户就无从判断手里这个地址有多旧。
        address_time=_pick(data.address_time, previous.address_time),
        fix_time=_pick(data.fix_time, previous.fix_time),
    )


class VivoFindCoordinator(DataUpdateCoordinator[VivoFindData]):
    """集中拉取设备数据，实体只读 coordinator.data。"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=int(interval)),
        )
        self.client = VivoFindClient(
            async_get_clientsession(hass), entry.data[CONF_COOKIE]
        )
        self.device_name: str = entry.data.get(CONF_DEVICE_NAME) or ""
        self.locate_on_update: bool = entry.options.get(
            CONF_LOCATE_ON_UPDATE,
            entry.data.get(CONF_LOCATE_ON_UPDATE, DEFAULT_LOCATE_ON_UPDATE),
        )
        # 坐标系：接口给什么（source）→ 输出给 HA 什么（target）
        self.source_crs: str = entry.options.get(
            CONF_SOURCE_CRS,
            entry.data.get(CONF_SOURCE_CRS, DEFAULT_SOURCE_CRS),
        )
        self.target_crs: str = entry.options.get(
            CONF_TARGET_CRS,
            entry.data.get(CONF_TARGET_CRS, DEFAULT_TARGET_CRS),
        )
        self.device: dict[str, Any] | None = None
        self._locate_unlock_at: datetime | None = None
        self._crs_logged = False
        # 「有位置但没地址」只提示一次，拿到地址后重置 —— 否则每轮刷屏
        self._address_warned = False
        # 上次运行持久化的数据，首轮刷新失败/取不齐时用它兜底
        self._store: Store = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}"
        )
        self._restored: VivoFindData | None = None
        # 首轮刷新尚未完成 —— 用于「避让限流窗口」与「允许快速重试」两处判断
        self._first_refresh_pending = True

    # ---------- 持久化 ----------

    async def async_restore(self) -> None:
        """把上次成功的数据读回来。必须在首次刷新之前调用。"""
        try:
            raw = await self._store.async_load()
        except Exception as err:  # noqa: BLE001 - 缓存坏了不该拖垮集成
            _LOGGER.debug("读取上次数据失败（忽略）: %s", err)
            return

        if not raw:
            return

        data = deserialize_data(raw)
        if not data.has_coordinates and data.battery is None:
            _LOGGER.debug("缓存里没有可用字段，忽略")
            return

        # 恢复的数据不是"本次实时定位"的产物，这两个语义位必须归零，
        # 否则 HA 里会显示成"刚刚实时定位过"，误导排查。
        data.located_live = False
        data.locate_throttled = False
        self._restored = data
        _LOGGER.debug(
            "已恢复上次数据（%s），fix_time=%s",
            _describe(data),
            data.fix_time.isoformat() if data.fix_time else "无",
        )

    async def _async_persist(self, data: VivoFindData) -> None:
        try:
            await self._store.async_save(serialize_data(data))
        except Exception as err:  # noqa: BLE001 - 存不上不影响本次刷新
            _LOGGER.debug("保存上次数据失败（忽略）: %s", err)

    async def async_forget(self) -> None:
        """删除缓存（目前仅测试与排错用）。"""
        try:
            await self._store.async_remove()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("删除缓存失败: %s", err)

    # ---------- 手动定位（服务调用）----------

    async def async_locate_now(self, *, force: bool = False) -> str:
        """立刻下发一次定位指令，并把结果直接推给实体。

        为什么不走 ``async_request_refresh``：常规刷新会尊重定位冷却，
        而手动定位刚刚锁上冷却，下一轮必然跳过 —— 结果就是「点了没反应」。
        这里拿到结果后直接 ``async_set_updated_data``，实体当场刷新。

        ``force=False`` 仍然尊重限流冷却：连点不会把接口撞得更深。
        ``force=True`` 无视冷却强行下发，用于确认限流是否已经解除。
        返回一句结果说明，服务调用者可直接在日志/自动化里看到。
        """
        if self.device is None:
            self.device = await self.client.async_resolve_device(self.device_name)

        now = dt_util.utcnow()
        if not self._locate_ready(now) and not force:
            left = 0
            if self._locate_unlock_at is not None:
                left = max(0, int((self._locate_unlock_at - now).total_seconds()))
            return f"冷却中，{left} 秒后可再试（force: true 可强制下发）"

        try:
            fresh = await self.client.async_locate(self.device)
        except VivoFindAuthError as err:
            raise ConfigEntryAuthFailed(f"cookie 已失效：{err}") from err
        except VivoFindRateLimitError as err:
            self._lock_locate(now, LOCATE_RATE_LIMIT_COOLDOWN)
            return f"被限流：{err}（{LOCATE_RATE_LIMIT_COOLDOWN} 秒内不再尝试）"
        except VivoFindError as err:
            self._lock_locate(now, LOCATE_COOLDOWN)
            return f"定位失败：{err}"

        raw_lng = _safe_float(fresh.get("longitude"))
        raw_lat = _safe_float(fresh.get("latitude"))
        if raw_lng is None or raw_lat is None:
            self._lock_locate(now, LOCATE_COOLDOWN)
            return "定位指令已执行，但接口未返回坐标"

        self._lock_locate(now, LOCATE_COOLDOWN)

        out_lng, out_lat = convert_coordinates(
            raw_lng, raw_lat, self.source_crs, self.target_crs
        )
        base = self.data or VivoFindData()
        new_address = fresh.get("locationDesc") or None
        fix_time = _parse_fix_time(fresh.get("time"))
        updated = replace(
            base,
            latitude=out_lat,
            longitude=out_lng,
            raw_latitude=raw_lat,
            raw_longitude=raw_lng,
            accuracy=_safe_float(fresh.get("radius")),
            address=_pick(new_address, base.address),
            address_time=(fix_time if new_address else None) or base.address_time,
            fix_time=fix_time or base.fix_time,
            source_crs=self.source_crs,
            target_crs=self.target_crs,
            located_live=True,
            locate_throttled=False,
            locate_status=LOCATE_OK,
        )
        self.async_set_updated_data(updated)
        await self._async_persist(updated)
        _LOGGER.info("手动定位成功：%s", _describe(updated))
        return f"成功：{updated.address or '（接口未返回地址）'}"

    # ---------- 设备信息 ----------

    async def async_ensure_device(self) -> dict[str, Any]:
        """解析并缓存目标设备（列表接口较重，只在必要时调用）。"""
        if self.device is None:
            self.device = await self.client.async_resolve_device(self.device_name)
            _LOGGER.debug(
                "已解析设备: %s (%s)",
                self.device.get("alias"),
                self.device.get("imei"),
            )
        return self.device

    async def async_reload_device(self) -> None:
        """目录变化后重新解析设备。"""
        self.device = None
        await self.async_ensure_device()

    # ---------- 定位指令的冷却控制 ----------

    def _locate_ready(self, now: datetime) -> bool:
        return self._locate_unlock_at is None or now >= self._locate_unlock_at

    def _lock_locate(self, now: datetime, seconds: int) -> None:
        self._locate_unlock_at = now + timedelta(seconds=seconds)

    # ---------- 周期刷新 ----------

    async def _async_update_data(self) -> VivoFindData:
        # 回退源：上一轮的数据优先（它本身已累积了历史有效值），
        # 没有就用上次运行持久化的数据 —— 这是重启后首轮的关键兜底。
        fallback = self.data if self.data is not None else self._restored
        is_first = self._first_refresh_pending

        attempt = 0
        while True:
            try:
                data = await self._async_fetch_once(fallback)
            except UpdateFailed as err:
                # 首轮失败但有缓存：不要抛 ConfigEntryNotReady 让集成整个起不来，
                # 先用缓存把实体撑起来，等下一轮再取真数据。
                if is_first and self._restored is not None:
                    _LOGGER.warning(
                        "首次读取失败（%s），先用上次缓存的数据启动：%s",
                        err,
                        _describe(self._restored),
                    )
                    self._first_refresh_pending = False
                    return self._restored
                raise

            if (
                not is_first
                or _has_enough(data, fallback)
                or attempt >= FIRST_REFRESH_RETRIES
            ):
                break

            attempt += 1
            _LOGGER.warning(
                "本轮数据不完整（%s），%d 秒后重试（第 %d/%d 次）",
                _describe(data),
                RETRY_DELAY,
                attempt,
                FIRST_REFRESH_RETRIES,
            )
            await asyncio.sleep(RETRY_DELAY)

        self._first_refresh_pending = False
        await self._async_persist(data)
        return data

    async def _async_fetch_once(
        self, fallback: VivoFindData | None
    ) -> VivoFindData:
        try:
            device = await self.async_ensure_device()
            raw_status = await self.client.async_get_status(device)
        except VivoFindAuthError as err:
            # 抛这个异常 HA 会自动弹出「重新认证」流程
            raise ConfigEntryAuthFailed(f"cookie 已失效：{err}") from err
        except VivoFindRateLimitError as err:
            raise UpdateFailed(f"读取状态被限流：{err}") from err
        except (VivoFindConnectionError, VivoFindError) as err:
            raise UpdateFailed(str(err)) from err

        device_vo = raw_status.get("deviceVO") or {}
        location = device_vo.get("location") or {}
        signal_info = raw_status.get("signalInfo") or device_vo.get("signalInfo") or {}
        battery_info = raw_status.get("batteryInfo") or device_vo.get("batteryInfo") or {}

        online_raw = _safe_int(device_vo.get("online"))
        # 1 = 在线；0 = 离线。曾观测限流期间返回 2，故只要非 0 即视为在线
        online = online_raw not in (0, None)

        raw_lng = _safe_float(location.get("longitude"))
        raw_lat = _safe_float(location.get("latitude"))

        # ---- 刷新实时定位 ----
        #
        # 必须先说清一个实测事实，否则下面每一步都看不懂：
        #   **地址（locationDesc）只在下发定位指令并成功后才会返回。**
        #   devicestatus 给的缓存位置只有经纬度/半径/时间，没有 locationDesc。
        # 所以「有没有地址」完全取决于这一轮有没有成功发出定位指令 ——
        # 一旦这一轮跳过定位（首轮避让 / 冷却中 / 设备离线 / 关了开关），
        # 地址就只能沿用上一次的，没有就一直是空。
        located_live = False
        locate_throttled = False
        locate_status: str
        now = dt_util.utcnow()

        fallback_has_address = bool(fallback is not None and fallback.address)
        has_raw_coords = raw_lng is not None and raw_lat is not None

        if not self.locate_on_update:
            locate_status = LOCATE_SKIP_DISABLED
        elif not online:
            locate_status = LOCATE_SKIP_OFFLINE
        elif self._first_refresh_pending and has_raw_coords and fallback_has_address:
            # 首轮避让：只有「已经有坐标**且**已经有地址」才允许跳过。
            # 若只判断坐标，重启后的首轮必然不发定位 → 地址当场变空
            # （缓存里恰好没有地址时更是永远补不回来）。
            locate_status = LOCATE_SKIP_FIRST
            _LOGGER.debug("首轮已有坐标和地址，跳过下发定位指令以避开限流窗口")
        elif not self._locate_ready(now):
            locate_status = LOCATE_SKIP_COOLDOWN
            _LOGGER.debug(
                "定位指令冷却中，跳过本次（%s 后可再试）", self._locate_unlock_at
            )
        else:
            try:
                fresh = await self.client.async_locate(device)
                if fresh.get("longitude") and fresh.get("latitude"):
                    location = fresh
                    raw_lng = _safe_float(fresh.get("longitude"))
                    raw_lat = _safe_float(fresh.get("latitude"))
                    located_live = True
                    locate_status = LOCATE_OK
                else:
                    locate_status = LOCATE_FAILED
                self._lock_locate(now, LOCATE_COOLDOWN)
            except VivoFindAuthError as err:
                raise ConfigEntryAuthFailed(f"cookie 已失效：{err}") from err
            except VivoFindRateLimitError as err:
                locate_throttled = True
                locate_status = LOCATE_THROTTLED
                self._lock_locate(now, LOCATE_RATE_LIMIT_COOLDOWN)
                _LOGGER.warning(
                    "定位指令被 vivo 限流（%s），%d 秒内不再下发，"
                    "本次沿用最近一次位置。这是可恢复的，无需处理",
                    err,
                    LOCATE_RATE_LIMIT_COOLDOWN,
                )
            except VivoFindError as err:
                # 定位失败不算整体失败，沿用 devicestatus 的位置。
                # 但超时与一般失败要分开记 —— 用户排查时最想知道的就是这个。
                locate_status = (
                    LOCATE_TIMEOUT if "超时" in str(err) else LOCATE_FAILED
                )
                self._lock_locate(now, LOCATE_COOLDOWN)
                _LOGGER.warning("刷新实时定位失败，沿用最近一次位置: %s", err)

        # ---- 坐标系转换 ----
        # vivo 给的是 BD-09，HA 需要 WGS84。不转的话地图上会偏约 1.2 公里。
        out_lng, out_lat = convert_coordinates(
            raw_lng, raw_lat, self.source_crs, self.target_crs
        )
        if (
            raw_lng is not None
            and raw_lat is not None
            and (out_lng, out_lat) != (raw_lng, raw_lat)
            and not self._crs_logged
        ):
            self._crs_logged = True
            _LOGGER.info(
                "坐标已换算 %s → %s：%s,%s → %s,%s（约 %d 米偏移）",
                self.source_crs,
                self.target_crs,
                f"{raw_lng:.6f}",
                f"{raw_lat:.6f}",
                f"{out_lng:.6f}",
                f"{out_lat:.6f}",
                _rough_distance_m(raw_lng, raw_lat, out_lng, out_lat),
            )

        # ---- 地址 ----
        # locationDesc 只在「下发定位指令成功」的那份 location 里出现。
        # 时间和地址必须成对记录：地址可能已经存在几小时，而 fix_time 是新的。
        new_address = location.get("locationDesc") or None
        fix_time = _parse_fix_time(location.get("time"))
        address_time = fix_time if new_address else None

        # ---- 组装数据（空值回退到上一次，避免限流期间被清空）----
        data = VivoFindData(
            online=online,
            online_raw=online_raw,
            latitude=out_lat,
            longitude=out_lng,
            raw_latitude=raw_lat,
            raw_longitude=raw_lng,
            source_crs=self.source_crs,
            target_crs=self.target_crs,
            accuracy=_safe_float(location.get("radius")),
            address=new_address,
            address_time=address_time,
            fix_time=fix_time,
            locate_status=locate_status,
            located_live=located_live,
            locate_throttled=locate_throttled,
            battery=_safe_int(battery_info.get("batteryCapacity")),
            charging=(
                str(battery_info.get("isCharging")) == "1"
                if battery_info.get("isCharging") is not None
                else None
            ),
            network=_parse_network(signal_info),
            signal=str(signal_info.get("simSignalStrength") or "") or None,
            operator=signal_info.get("simOperator") or None,
            device_alias=device.get("alias") or self.device_name or None,
            device_model=device.get("model") or device.get("modelName") or None,
            imei=str(device.get("imei") or "") or None,
            emmc_id=str(device.get("emmcId") or "") or None,
        )

        if fallback is not None:
            data = merge_with_previous(data, fallback)

        if not data.has_coordinates:
            # 从没拿到过坐标：实体自己会进入不可用，而不是在地图上乱放一个点
            _LOGGER.warning("本次没有拿到任何有效坐标（%s）", _describe(data))

        # 有位置但没地址：这是用户最容易困惑的状态，明确说清原因与出路。
        # 只提示一次（拿到地址后重置），否则每轮刷屏反而淹掉真正的问题。
        if not data.address:
            if data.has_coordinates and not self._address_warned:
                self._address_warned = True
                _LOGGER.warning(
                    "有位置但拿不到地址（locate_status=%s）。原因：地址只随"
                    "「定位指令成功」返回，设备自己上报的位置不带地址。"
                    "可在「开发者工具 → 服务」调用 vivo_find.locate_now 补一次",
                    locate_status,
                )
        else:
            self._address_warned = False

        return data
