"""测试脚本共用的模块加载器。

两个职责：
1. 绕过 custom_components/vivo_find/__init__.py（它依赖 Home Assistant），
   用构造假包的方式单独加载 const / api / coordinator 这些纯逻辑模块；
2. 统一从环境变量或本地文件取 cookie，避免把凭据硬编码进仓库。

cookie 优先级：环境变量 VIVO_COOKIE > dev/cookie.txt（已 gitignore）
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import types

DEV_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = DEV_DIR.parent
PKG_DIR = REPO_ROOT / "custom_components" / "vivo_find"
COOKIE_FILE = DEV_DIR / "cookie.txt"


def get_cookie() -> str:
    """取 cookie，取不到就给一句能照着做的提示。"""
    cookie = os.environ.get("VIVO_COOKIE", "").strip()
    if not cookie and COOKIE_FILE.exists():
        cookie = COOKIE_FILE.read_text(encoding="utf-8").strip()
    if not cookie:
        raise SystemExit(
            "缺少 cookie。两种办法任选其一：\n"
            "  1) 设置环境变量 VIVO_COOKIE；\n"
            f"  2) 把 cookie 单行写入 {COOKIE_FILE}\n"
            "cookie 从浏览器打开 find.vivo.com.cn 登录后，F12 → 网络 → 任意请求 → "
            "复制完整 Cookie（须含 vivo_yun_csrftoken）。"
        )
    return cookie


def register_package() -> None:
    """把集成目录注册成一个名为 _vfpkg 的假包。

    这样集成内部 `from .const import ...` 这类相对导入才能被单独加载，
    同时绕过 __init__.py（它依赖 Home Assistant，测试环境里没有）。
    """
    if "_vfpkg" in sys.modules:
        return
    pkg = types.ModuleType("_vfpkg")
    pkg.__path__ = [str(PKG_DIR)]
    sys.modules["_vfpkg"] = pkg


def load_module(name: str):
    """把 PKG_DIR 下某个模块当作 _vfpkg 包的子模块加载。

    **同一进程内只加载一次。** 这点很关键：重复 exec 同一个文件会产生两个
    互不相干的模块对象，于是 `isinstance` 判定失效、`except` 也捕获不到 ——
    表现为「api 抛 VivoFindRateLimitError，coordinator 的 except 却接不住」，
    极易被误判成集成代码有 bug。缓存住就杜绝了这类假象。
    """
    register_package()
    full_name = f"_vfpkg.{name}"
    cached = sys.modules.get(full_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(full_name, PKG_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


def prepare_api():
    """注册假包并返回 api 模块。"""
    register_package()
    load_module("const")
    return load_module("api")


def install_ha_stubs() -> None:
    """最小可用的 homeassistant 桩，只为让 coordinator.py 能 import。"""

    class ConfigEntry:
        pass

    class HomeAssistant:
        pass

    class ConfigEntryAuthFailed(Exception):
        pass

    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator:
        # 让 DataUpdateCoordinator[VivoFindData] 这种写法能通过
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, *args, **kwargs):
            self.data = None
            self.last_update_success = True
            # 记录被推送的数据，供测试断言「手动定位有没有当场推给实体」
            self.pushed: list = []

        def async_set_updated_data(self, data):
            self.data = data
            self.last_update_success = True
            self.pushed.append(data)

    class Store:
        """最小 Store 桩：进程内共享一份字典，够用来验证「重启后恢复」。"""

        memory: dict = {}

        def __init__(self, hass, version, key):
            self.hass = hass
            self.version = version
            self.key = key

        async def async_load(self):
            return Store.memory.get(self.key)

        async def async_save(self, data):
            Store.memory[self.key] = data

        async def async_remove(self):
            Store.memory.pop(self.key, None)

    def stub(name: str, **attrs):
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        sys.modules[name] = module

    from datetime import datetime, timezone

    stub("homeassistant")
    stub("homeassistant.config_entries", ConfigEntry=ConfigEntry)
    stub("homeassistant.core", HomeAssistant=HomeAssistant)
    stub("homeassistant.exceptions", ConfigEntryAuthFailed=ConfigEntryAuthFailed)
    stub("homeassistant.helpers")
    stub(
        "homeassistant.helpers.aiohttp_client",
        async_get_clientsession=lambda hass: None,
    )
    stub("homeassistant.helpers.storage", Store=Store)
    stub(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=DataUpdateCoordinator,
        UpdateFailed=UpdateFailed,
    )
    stub("homeassistant.util")
    stub("homeassistant.util.dt", utcnow=lambda: datetime.now(timezone.utc))


class FakeEntry:
    """够用的 ConfigEntry 替身（coordinator 只用到这几个字段）。"""

    def __init__(
        self,
        *,
        entry_id: str = "test_entry",
        title: str = "iQOOO",
        data: dict | None = None,
        options: dict | None = None,
    ) -> None:
        self.entry_id = entry_id
        self.title = title
        self.data = {
            "cookie": "a=1; vivo_yun_csrftoken=fake-csrf-token",
            **(data or {}),
        }
        self.options = dict(options or {})


def make_coordinator(coord, entry, **kwargs):
    """构造一个 coordinator 并换上假 client。"""
    coordinator = coord.VivoFindCoordinator(hass=None, entry=entry, **kwargs)
    client = FakeVivoClient(**kwargs)
    coordinator.client = client
    return coordinator, client


class FakeVivoClient:
    """可编程的 API 客户端替身：想让它返回什么就返回什么。"""

    DEVICE = {
        "imei": "868856076839295",
        "emmcId": "EMMC-TEST",
        "alias": "iQOOO",
        "model": "iQOO Neo10 Pro",
    }

    def __init__(
        self,
        status: dict | None = None,
        status_error: Exception | None = None,
        locate: dict | None = None,
        locate_error: Exception | None = None,
    ) -> None:
        self.status = status if status is not None else {}
        self.status_error = status_error
        self.locate = locate if locate is not None else {}
        self.locate_error = locate_error
        self.status_calls = 0
        self.locate_calls = 0

    async def async_resolve_device(self, device_name):
        return dict(self.DEVICE)

    async def async_get_status(self, device):
        self.status_calls += 1
        if self.status_error is not None:
            raise self.status_error
        return self.status

    async def async_locate(self, device):
        self.locate_calls += 1
        if self.locate_error is not None:
            raise self.locate_error
        return self.locate


def make_status(
    *,
    online: int = 1,
    lng: float | None = 114.350962,
    lat: float | None = 30.558978,
    radius: float | None = 40,
    # ⚠️ 默认 None 是**故意的**，为了贴合真实接口：
    # 实测（2026-09-18）devicestatus 返回的 location 里**没有 locationDesc**，
    # 地址只随「定位指令成功」返回。这里若默认给一个地址，就会掩盖
    # 「首轮跳过定位 → 地址变空」那类 bug —— 之前正是这么被骗过一次。
    desc: str | None = None,
    fix_ms: int | None = None,
    battery: int | None = 41,
    charging: int | None = 0,
    net: str | None = "nr",
    operator: str | None = "中国联通",
) -> dict:
    """拼一个 devicestatus 响应。传 None 就是不包含该字段（模拟限流返回空）。"""
    location: dict = {}
    if lng is not None:
        location["longitude"] = lng
    if lat is not None:
        location["latitude"] = lat
    if radius is not None:
        location["radius"] = radius
    if desc is not None:
        location["locationDesc"] = desc
    if fix_ms is not None:
        location["time"] = fix_ms

    battery_info: dict = {}
    if battery is not None:
        battery_info["batteryCapacity"] = battery
    if charging is not None:
        battery_info["isCharging"] = charging

    signal_info: dict = {}
    if net is not None:
        signal_info["simNetWorkType"] = net
        signal_info["simSignalStrength"] = "4"
    if operator is not None:
        signal_info["simOperator"] = operator

    return {
        "deviceVO": {"online": online, "location": location},
        "batteryInfo": battery_info,
        "signalInfo": signal_info,
    }
