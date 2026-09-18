"""端到端验证 api.py —— 真实调用 vivo 云服务（不依赖 Home Assistant）。

用法（在仓库根目录）：
    python dev/test_api.py

cookie 来源见 dev/_loader.py。operate 接口有限流，撞限流算软失败不算测试失败。
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aiohttp  # noqa: E402

from _loader import get_cookie, prepare_api  # noqa: E402

api = prepare_api()
FAILS: list[str] = []


def fmt(ts_ms) -> str:
    if not ts_ms:
        return "-"
    return (
        datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
        .astimezone()
        .strftime("%Y-%m-%d %H:%M:%S")
    )


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"    {'PASS' if condition else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if not condition:
        FAILS.append(label)


async def main() -> int:
    cookie = get_cookie()

    async with aiohttp.ClientSession() as session:
        print("=" * 64)
        print("[1] 构造客户端 / csrftoken 提取")
        client = api.VivoFindClient(session, cookie)
        check("csrftoken 提取成功", bool(client._csrftoken), client._csrftoken[:16] + "...")
        try:
            api.VivoFindClient(session, "a=1; b=2")
            check("缺 csrftoken 抛 VivoFindAuthError", False, "居然没报错")
        except api.VivoFindAuthError:
            check("缺 csrftoken 抛 VivoFindAuthError", True)

        print("=" * 64)
        print("[2] 设备列表 v3/devices")
        devices = await client.async_get_devices()
        check("拿到设备", bool(devices), f"{len(devices)} 台")
        for d in devices:
            print(
                f"         alias={d.get('alias')!r} model={d.get('model')!r} "
                f"imei={d.get('imei')} online={d.get('online')!r}"
            )

        print("=" * 64)
        print("[3] 设备解析 async_resolve_device")
        alias = (devices[0].get("alias") or "").strip()
        device = await client.async_resolve_device(alias)
        check("用真实别名可解析", device.get("imei") == devices[0].get("imei"), alias)
        if len(devices) == 1:
            # 单设备时按设计忽略名称（对应 JS 版「只有一个设备时可留空」）
            fallback = await client.async_resolve_device("随便一个不存在的名字")
            check("单设备时忽略名称（设计如此）", fallback.get("imei") == device.get("imei"))
        else:
            try:
                await client.async_resolve_device("__不存在的设备__")
                check("多设备时错误名称应报错", False, "居然没报错")
            except api.VivoFindError:
                check("多设备时错误名称应报错", True)

        print("=" * 64)
        print("[4] 设备状态 devicestatus")
        status = await client.async_get_status(device)
        vo = status.get("deviceVO") or {}
        loc = vo.get("location") or {}
        bat = status.get("batteryInfo") or {}
        sig = status.get("signalInfo") or {}
        check("deviceVO 存在", bool(vo))
        check("location 存在", bool(loc))
        # 实测：batteryInfo / signalInfo 在 data 顶层，不是 deviceVO 里面。
        # 但限流期间 vivo 会返回**空对象且不报错**（集成里靠 _pick 回退保住上次读数），
        # 所以这里做成软断言：有值才校验，为空只提示，不算失败。
        if bat or sig:
            check("batteryInfo 在 data 顶层", bool(bat), str(bat.get("batteryCapacity")))
            check("signalInfo 在 data 顶层", bool(sig), str(sig.get("simNetWorkType")))
        else:
            print("  [SOFT] batteryInfo / signalInfo 为空 —— 命中 vivo 限流，"
                  "属已知现象，集成会用上一次读数回退，不算失败")
        check("online 有值", vo.get("online") is not None, repr(vo.get("online")))
        print(f"         坐标 lat={loc.get('latitude')} lon={loc.get('longitude')}")
        print(f"         地址 {loc.get('locationDesc')}")
        print(f"         半径 {loc.get('radius')} 米 | fix {fmt(loc.get('time'))}")
        print(
            f"         电量 {bat.get('batteryCapacity')}% 充电={bat.get('isCharging')!r} "
            f"网络={sig.get('simNetWorkType')!r} 运营商={sig.get('simOperator')!r}"
        )

        lat = float(loc.get("latitude") or 0)
        lon = float(loc.get("longitude") or 0)
        # 武汉在 lat 30.x / lon 114.x，用来抓「经纬度写反」这类低级错误
        check("纬度在合理范围", 20 < lat < 45, f"lat={lat}")
        check("经度在合理范围", 100 < lon < 125, f"lon={lon}")

        print("=" * 64)
        print("[5] 定位指令 operate + polling（限流算软失败）")
        try:
            fresh = await client.async_locate(device)
            check(
                "返回经纬度",
                bool(fresh.get("latitude") and fresh.get("longitude")),
                f"{fresh.get('latitude')},{fresh.get('longitude')}",
            )
            print(f"         地址 {fresh.get('locationDesc')} | 半径 {fresh.get('radius')} 米")
        except api.VivoFindRateLimitError as err:
            print(f"    SKIP  撞上限流: {err}  ← 属可恢复，集成已按冷却处理")
        except api.VivoFindError as err:
            FAILS.append(f"定位失败: {err}")
            print(f"    FAIL  {err}")

        print("=" * 64)
        print("[6] round 计数器应随每次请求递增")
        before = client._round
        await client.async_get_status(device)
        after = client._round
        check("round 递增 +1", after == before + 1, f"{before} -> {after}")

    print("=" * 64)
    if FAILS:
        print(f"结果: {len(FAILS)} 项失败")
        for item in FAILS:
            print("  -", item)
        return 1
    print("结果: 全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
