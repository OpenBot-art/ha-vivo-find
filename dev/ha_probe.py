# -*- coding: utf-8 -*-
"""直接读线上 Home Assistant 的实体状态与日志，定位「位置/地址未知」。

凭据从 dev/ha_token.txt 读（两行：base_url、长期令牌），该文件已 gitignore。
也可用环境变量 HA_URL / HA_TOKEN 覆盖。

用法：
    python dev/ha_probe.py            # 概览
    python dev/ha_probe.py log 120    # 抓最近 120 行含 vivo_find 的日志
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

DEV = pathlib.Path(__file__).resolve().parent
CRED = DEV / "ha_token.txt"

TIMEOUT = 20


def load_cred() -> tuple[str, str]:
    url = os.environ.get("HA_URL", "").strip()
    token = os.environ.get("HA_TOKEN", "").strip()
    if url and token:
        return url.rstrip("/"), token
    if not CRED.exists():
        raise SystemExit(
            f"缺少 {CRED}（第一行 base_url，第二行长期令牌）"
            "或设置环境变量 HA_URL / HA_TOKEN"
        )
    lines = [x.strip() for x in CRED.read_text(encoding="utf-8").splitlines()]
    lines = [x for x in lines if x]
    if len(lines) < 2:
        raise SystemExit(f"{CRED} 需要两行：base_url 与长期令牌")
    return lines[0].rstrip("/"), lines[1]


class HA:
    def __init__(self, base: str, token: str) -> None:
        self.base = base
        self.token = token

    def get(self, path: str, *, raw: bool = False):
        req = urllib.request.Request(
            f"{self.base}{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")[:300]
            raise SystemExit(f"HTTP {err.code}  {path}\n{detail}") from err
        except urllib.error.URLError as err:
            raise SystemExit(
                f"连不上 {self.base}：{err.reason}\n"
                "确认 HA 正在运行、端口可达，且令牌未失效。"
            ) from err
        return body if raw else json.loads(body)


def rule(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    ha = HA(*load_cred())

    cfg = ha.get("/api/config")
    rule("[0] 环境")
    print(f"  HA 版本      : {cfg.get('version')}")
    print(f"  地址         : {ha.base}")
    print(f"  location_name: {cfg.get('location_name')}")
    print(f"  时区         : {cfg.get('time_zone')}")
    print(f"  单位制       : {cfg.get('unit_system', {}).get('length')}")

    states = ha.get("/api/states")
    mine = [
        s for s in states
        if s["entity_id"].startswith("device_tracker.")
        and (s.get("attributes") or {}).get("source") == "vivo_find"
    ] or [
        s for s in states
        if "vivo" in s["entity_id"] or "iqoo" in s["entity_id"].lower()
    ]

    rule("[1] 本次集成创建的实体")
    if not mine:
        print("  ❌ 一个都没找到 —— 集成可能没加载，或实体被改名/禁用")
    for s in sorted(mine, key=lambda x: x["entity_id"]):
        print(f"  {s['entity_id']:42s} {s['state']}")

    tracker = next(
        (s for s in mine if s["entity_id"].startswith("device_tracker.")), None
    )
    if tracker:
        a = tracker.get("attributes") or {}
        rule("[2] device_tracker 关键属性（位置/地址的核心）")
        print(f"  state（HA 状态）     : {tracker['state']}")
        print(f"  last_updated         : {tracker.get('last_updated')}")
        print(f"  last_changed         : {tracker.get('last_changed')}")
        print()
        keys = [
            "source", "latitude", "longitude", "coordinates", "raw_coordinates",
            "address", "address_time", "address_age_s",
            "fix_time", "position_age_s", "accuracy", "online", "online_raw",
            "located_live", "locate_throttled", "locate_status",
            "last_update_success", "source_crs", "target_crs",
            "battery_level", "network", "signal_strength", "operator", "charging",
            "device_model", "imei",
        ]
        for k in keys:
            if k in a:
                print(f"  {k:22s}: {a[k]}")
        extra = [k for k in a if k not in keys]
        if extra:
            print(f"  （其余属性：{', '.join(sorted(extra))}）")

        # ---- 直接判定 ----
        rule("[3] 判定")
        lat, lng = a.get("latitude"), a.get("longitude")
        addr = a.get("address")
        status = a.get("locate_status")
        if tracker["state"] in ("unknown", "unavailable"):
            print(f"  ⚠️ 实体状态是 {tracker['state']}")
        if lat is None or lng is None:
            print("  ❌ 没有坐标 → 地图上不会有这个点（这就是「位置未知」）")
            if status in (None, "skipped_disabled"):
                print("     locate_status 不在 → 说明跑的是**旧版本代码**，没有这个属性")
        else:
            print(f"  ✅ 有坐标 {lat}, {lng}")
        if addr:
            print(f"  ✅ 有地址：{addr}")
            age = a.get("address_age_s")
            if isinstance(age, int):
                print(f"     地址距今 {age} 秒（{age/60:.1f} 分钟）")
            else:
                print("     ⚠️ 没有 address_age_s → 说明跑的是**旧版本代码**")
        else:
            print("  ❌ 没有地址（address 为空）")
            if status:
                print(f"     locate_status = {status}")
        print()
        if "locate_status" not in a:
            print("  >>> 结论：实体属性里没有 locate_status / address_age_s，")
            print("      说明加载的还是旧版代码，先把新版装上去再看。")
        else:
            print("  >>> 结论：跑的是新版代码，可直接按上面 locate_status 解读原因。")

    # ---- 日志 ----
    rule("[4] 日志里与 vivo 相关的行")
    try:
        log = ha.get("/api/error_log", raw=True)
    except SystemExit as err:
        print(f"  读取日志失败：{err}")
        log = ""
    lines = [
        ln for ln in log.splitlines()
        if "vivo_find" in ln or "VIVO" in ln or "定位" in ln or "地址" in ln
    ]
    if not lines:
        print("  （日志里没有 vivo_find 相关记录）")
    else:
        for ln in lines[-60:]:
            print("  " + ln)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "log":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 100
        ha = HA(*load_cred())
        log = ha.get("/api/error_log", raw=True)
        keep = [
            ln for ln in log.splitlines()
            if "vivo_find" in ln or "VIVO" in ln or "定位" in ln or "地址" in ln
        ]
        for ln in keep[-n:]:
            print(ln)
        sys.exit(0)
    sys.exit(main())
