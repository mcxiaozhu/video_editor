# -*- coding: utf-8 -*-
"""从 avatar.jpg 生成 icon.png（窗口图标用，32x32 足够任务栏/标题栏清晰显示）。

同时输出多个常用尺寸，供 iconphoto 一次性加载多个 PhotoImage，
让 Windows 在任务栏/标题栏/Alt-Tab 各取所需的分辨率。
"""
from PIL import Image, ImageDraw

SRC = "avatar.jpg"
OUT = "icon.png"

img = Image.open(SRC).convert("RGB")
w, h = img.size
side = min(w, h)
left = (w - side) // 2
top = (h - side) // 2
img = img.crop((left, top, left + side, top + side))
img = img.resize((256, 256), Image.Resampling.LANCZOS)

radius = 52
mask = Image.new("L", (256, 256), 0)
md = ImageDraw.Draw(mask)
md.rounded_rectangle([0, 0, 256, 256], radius=radius, fill=255)
base = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
base.paste(img, (0, 0), mask)

# 输出 256 大图（保留高清源）
base.save(OUT, format="PNG")

# 额外输出小尺寸供窗口图标使用（32 和 16）
for size in (32, 16):
    small = base.resize((size, size), Image.Resampling.LANCZOS)
    small.save(f"icon_{size}.png", format="PNG")

print(f"已生成 {OUT} (256), icon_32.png, icon_16.png")
