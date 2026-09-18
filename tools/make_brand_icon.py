"""生成 brand 图标（icon.png / icon@2x.png）。

HACS 与 HA 品牌规范要求 `custom_components/<domain>/brand/icon.png`（1x）
与 `icon@2x.png`（2x，即 256×256）。缺了会在 HACS 校验里报：

    <Validation brands> failed: The repository does not provide brand assets
    and is not listed in the Home Assistant brands repository.

图形语义：手机轮廓 + 定位图钉，直白对应「查找设备」这个功能。
配色用 vivo 品牌蓝。

用法（仓库根目录）：
    python tools/make_brand_icon.py
"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw

BRAND_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components"
    / "vivo_find"
    / "brand"
)

# vivo 品牌蓝 + 定位图钉用的强调色
BLUE = (65, 105, 225, 255)
BLUE_DARK = (32, 66, 160, 255)
WHITE = (255, 255, 255, 255)

# 所有尺寸按 256 画布设计，最后按倍率缩放，保证线条粗细一致
BASE = 256


def _draw(size: int) -> Image.Image:
    scale = size / BASE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def s(v: float) -> float:
        return v * scale

    # --- 手机机身（圆角矩形）---
    body = [s(68), s(24), s(188), s(232)]
    d.rounded_rectangle(body, radius=s(26), fill=BLUE)

    # --- 屏幕（内嵌浅色圆角矩形，留出上下的边框感）---
    screen = [s(82), s(42), s(174), s(214)]
    d.rounded_rectangle(screen, radius=s(16), fill=WHITE)

    # --- 听筒（顶部小横条）---
    d.rounded_rectangle(
        [s(112), s(30), s(144), s(36)], radius=s(3), fill=(255, 255, 255, 210)
    )

    # --- Home 键（底部小圆）---
    d.ellipse([s(120), s(220), s(136), s(236)], fill=(255, 255, 255, 210))

    # --- 定位图钉（压在屏幕中央，代表「查找设备」）---
    cx, cy = s(128), s(118)
    r = s(34)          # 图钉头部半径
    tip_y = s(178)     # 图钉尖端

    # 圆头
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BLUE)
    # 尖角（三角形连到圆头下缘）
    d.polygon(
        [(cx - r * 0.62, cy + r * 0.62), (cx + r * 0.62, cy + r * 0.62), (cx, tip_y)],
        fill=BLUE,
    )
    # 图钉内孔
    ir = s(13)
    d.ellipse([cx - ir, cy - ir, cx + ir, cy + ir], fill=WHITE)
    # 内孔加深一点，避免高光下糊掉
    ir2 = s(7)
    d.ellipse([cx - ir2, cy - ir2, cx + ir2, cy + ir2], fill=BLUE_DARK)

    return img


def main() -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    for name, size in (("icon.png", 128), ("icon@2x.png", 256)):
        path = BRAND_DIR / name
        _draw(size).save(path, "PNG")
        print(f"wrote {path}  ({size}x{size})")


if __name__ == "__main__":
    main()
