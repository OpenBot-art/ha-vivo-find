#!/usr/bin/env python3
"""manifest.json version 与 git tag 一致性检查。

规则分两种触发场景：

1. **tag 推送**（`refs/tags/v*`）：tag 的核心版本必须与 manifest.json 的 version
   **一致**。测试 tag（`vX.Y.Z-test.N`，见 docs/RELEASE.md）取核心三段比较。
   这是硬性规则 —— HACS 按 tag 拉版本，号对不上会出现
   「装上了但不是新版」。
2. **普通推送 / PR**：manifest 版本不得**落后于**最新 tag（允许提前 bump
   到下一个待发布版本，因为发版流程就是先在 develop 上改版本号再打 tag）。

退出码：0 通过，1 失败（带人类可读的原因）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

MANIFEST = Path("custom_components/vivo_find/manifest.json")
# 允许 vX.Y.Z 与 vX.Y.Z-<后缀>（如 v1.4.0-test.1 测试 tag）；只取核心三段比较
TAG_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    ).stdout.strip()


def parse_version(value: str) -> tuple[int, int, int] | None:
    matched = SEMVER.match(value.strip().lstrip("v"))
    if not matched:
        return None
    return tuple(int(part) for part in matched.groups())  # type: ignore[return-value]


def parse_tag(value: str) -> tuple[tuple[int, int, int] | None, str]:
    """解析 tag 名，返回 (核心版本或 None, 原始 tag 名)。

    `v1.4.0-test.1` 这类测试 tag 取核心 `1.4.0` 参与比较 —— 测试 tag 是
    发布流程的一部分（见 docs/RELEASE.md），不该被版本检查拦下。
    """
    matched = TAG_PATTERN.match(value.strip())
    if not matched:
        return None, value.strip()
    return tuple(int(part) for part in matched.groups()), value.strip()  # type: ignore[return-value]


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    version = str(manifest.get("version") or "")
    parsed = parse_version(version)
    if parsed is None:
        print(f"FAIL: manifest.json version={version!r} 不是 X.Y.Z 形式的语义化版本")
        return 1

    ref = os.environ.get("GITHUB_REF", "")
    latest_tag = git("describe", "--tags", "--abbrev=0", "--match", "v*")

    if ref.startswith("refs/tags/"):
        tag_name = ref.rsplit("/", 1)[-1]
        tag_version, _ = parse_tag(tag_name)
        if tag_version is None:
            print(f"FAIL: tag {tag_name!r} 不是 vX.Y.Z（或 vX.Y.Z-后缀）形式")
            return 1
        if tag_version != parsed:
            print(
                f"FAIL: tag {tag_name} 与 manifest version={version} "
                "不一致。HACS 按 tag 识别版本，发版时必须先改 manifest 再打 tag"
            )
            return 1
        print(f"OK: tag {tag_name} 与 manifest version={version} 一致")
        return 0

    if not latest_tag:
        print(f"OK: 尚无 tag，manifest version={version}")
        return 0

    tag_version, _ = parse_tag(latest_tag)
    if tag_version is None:
        print(f"OK: 最新 tag {latest_tag} 不是语义化版本，跳过比较")
        return 0

    if parsed < tag_version:
        print(
            f"FAIL: manifest version={version} 落后于最新 tag {latest_tag}。"
            "发版后记得同步 manifest（见 docs/RELEASE.md）"
        )
        return 1

    print(f"OK: manifest version={version} >= 最新 tag {latest_tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
