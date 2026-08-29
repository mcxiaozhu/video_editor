# -*- coding: utf-8 -*-
"""从 avatar.jpg 生成标准多尺寸 icon.ico（Pillow 正确用法：单张大图 + sizes 自动缩放）。"""
from PIL import Image, ImageDraw

SRC = "avatar.jpg"
OUT = "icon.ico"

img = Image.open(SRC).convert("RGB")

# 居中裁剪为正方形（取较短边）
w, h = img.size
side = min(w, h)
left = (w - side) // 2
top = (h - side) // 2
img = img.crop((left, top, left + side, top + side))

# 统一缩放为 256（图标基准尺寸）
img = img.resize((256, 256), Image.Resampling.LANCZOS)

# 加圆角蒙版（视觉更精致）
radius = 52
mask = Image.new("L", (256, 256), 0)
md = ImageDraw.Draw(mask)
md.rounded_rectangle([0, 0, 256, 256], radius=radius, fill=255)
out = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
out.paste(img, (0, 0), mask)

# 标准 ICO 尺寸：Pillow 会根据 sizes 自动从 256 缩放生成所有帧
sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
out.save(OUT, format="ICO", sizes=sizes)

# 验证帧数与尺寸
check = Image.open(OUT)
count = 0
try:
    while True:
        check.seek(count)
        print(f"  帧 {count}: {check.size} {check.mode}")
        count += 1
except EOFError:
    pass
print(f"已生成 {OUT}，帧数: {count}")
