#!/usr/bin/env python3
"""README 中英双语同步检查。

用户约定：README 默认中文在前、英文全文在后，顶部有语言跳转链接，
英文段以 `## English` 锚定。最常见的翻车情形是「只改了一半」——
中文加了新章节，英文段没跟上（或反过来）。

检查三项：
1. 顶部存在语言跳转链接（`[English](#english)`）
2. 存在 `## English` 锚点，且前后两段都非空
3. 英文段行数不低于中文段的 50%（阈值刻意留足翻译自然的长度差，
   只抓「整段没更新」级别的漂移）

退出码：0 通过，1 失败（带人类可读的原因）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

README = Path("README.md")
ANCHOR = "## English"
MIN_RATIO = 0.5


def main() -> int:
    text = README.read_text(encoding="utf-8")
    lines = text.splitlines()

    jump_link = re.search(r"\[English\]\(#english\)", text, re.IGNORECASE)
    if not jump_link:
        print("FAIL: README 顶部缺少语言跳转链接（应为 [English](#english) | **简体中文**）")
        return 1

    anchor_idx = [i for i, line in enumerate(lines) if line.strip() == ANCHOR]
    if not anchor_idx:
        print(f"FAIL: README 缺少 {ANCHOR!r} 锚点，英文段无从定位")
        return 1
    if len(anchor_idx) > 1:
        print(f"FAIL: README 出现多个 {ANCHOR!r} 锚点（{len(anchor_idx)} 个）")
        return 1

    idx = anchor_idx[0]
    zh_lines = [line for line in lines[:idx] if line.strip()]
    en_lines = [line for line in lines[idx + 1 :] if line.strip()]
    if len(zh_lines) < 10 or len(en_lines) < 10:
        print(
            f"FAIL: 中文段（{len(zh_lines)} 行）或英文段（{len(en_lines)} 行）"
            "内容过少，疑似被误删"
        )
        return 1

    ratio = len(en_lines) / len(zh_lines)
    if ratio < MIN_RATIO:
        print(
            f"FAIL: 英文段仅 {len(en_lines)} 行，不足中文段（{len(zh_lines)} 行）的 "
            f"{MIN_RATIO:.0%}（当前 {ratio:.0%}）。两段必须同步更新，"
            "不要只改一半"
        )
        return 1

    print(
        f"OK: 跳转链接在位，英文段 {len(en_lines)} 行 / 中文段 {len(zh_lines)} 行"
        f"（{ratio:.0%} ≥ {MIN_RATIO:.0%}）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
