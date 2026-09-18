"""把 vivo devicestatus 的原始响应完整打印出来。

vivo 是私有接口，字段结构随时可能变。哪天集成里某个属性突然变未知，
先跑这个脚本看真实结构，再改 coordinator.py 的解析。

用法（在仓库根目录）：
    python dev/dump_status.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aiohttp  # noqa: E402

from _loader import get_cookie, prepare_api  # noqa: E402

api = prepare_api()


async def main() -> None:
    cookie = get_cookie()

    async with aiohttp.ClientSession() as session:
        client = api.VivoFindClient(session, cookie)
        device = await client.async_resolve_device("")

        print("### 设备对象完整字段（v3/devices）###")
        print(json.dumps(device, ensure_ascii=False, indent=2))
        print()

        status = await client.async_get_status(device)
        print("### devicestatus data 顶层键 ###")
        print(sorted(status.keys()))
        print()
        print("--- deviceVO ---")
        print(json.dumps(status.get("deviceVO"), ensure_ascii=False, indent=2))
        print()
        print("--- data.signalInfo（顶层，不在 deviceVO 里）---")
        print(json.dumps(status.get("signalInfo"), ensure_ascii=False, indent=2))
        print()
        print("--- data.batteryInfo（顶层，不在 deviceVO 里）---")
        print(json.dumps(status.get("batteryInfo"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
