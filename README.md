# 视频编辑器（Video Editor）

基于 **Python tkinter 图形界面** + **FFmpeg/FFprobe** 后端的视频编辑工具，无需安装额外 Python 第三方库（仅使用标准库）。

## ✨ 功能

| 功能 | 说明 |
|------|------|
| 📥 导入视频 | 支持 mp4 / mkv / avi / mov / webm / flv / wmv / m4v / ts / mpg 等常见格式，导入后自动解析时长、分辨率、编码、帧率、码率等元信息 |
| ✂️ 裁剪 | 按开始/结束时间截取片段（支持 `秒`、`MM:SS`、`HH:MM:SS` 三种输入格式） |
| 🔗 合并 | 将列表中所有视频按顺序拼接为一个文件（自动重编码以保证参数一致） |
| 🔄 转码 | 一键转换格式：MP4(H.264/H.265)、MKV、AVI、MOV、WebM、GIF 动图、MP3、WAV |
| 🎵 提取音频 | 提取视频中的音轨为 MP3 / WAV / M4A 等 |
| ⏩ 调速 | 加速或减速播放（支持 0.5x ~ 8x+，自动串联 atempo 滤镜） |
| 📐 改分辨率 | 自定义宽高，留空自动按比例缩放，自动保证偶数尺寸 |
| ■ 停止 | 随时中止当前 ffmpeg 任务 |

所有转码操作均通过后台线程运行，界面实时显示进度百分比。

## 📦 环境要求

1. **Python 3.8+**（tkinter 为标准库自带，Windows 官方安装包默认包含）
2. **FFmpeg**：请确保 `ffmpeg` 和 `ffprobe` 已加入系统 `PATH`。
   - 推荐下载 Windows 版本（full build）：<https://www.gyan.dev/ffmpeg/builds/>
   - 下载后解压，将 `bin` 目录加入环境变量 PATH，然后重新打开终端。

验证是否安装成功：

```bash
ffmpeg -version
ffprobe -version
```

## 🚀 使用方法

### 图形界面（推荐）

```bash
cd video_editor
python main.py
```

启动后：

1. 点击 **「导入视频文件」** 选择一个或多个视频；
2. 在列表中选中一个视频，右侧会显示详细信息；
3. 设置编辑参数（时间、输出格式、速度、分辨率）；
4. 点击对应操作按钮（裁剪 / 合并 / 转码 / 提取音频 / 调速 / 改分辨率）；
5. 选择输出位置，等待进度条完成即可。

### ⚙ GPU 加速设置

点击顶部工具栏的 **「⚙ 设置」** 按钮，可在设置对话框中启用 GPU 硬件加速：

1. 程序启动时会自动检测本机的可用 GPU 硬件编码器（NVIDIA NVENC / Intel QSV / AMD AMF）；
2. 检测成功后，勾选 **「启用 GPU 加速」**，并从下拉框选择要使用的 GPU 编码器；
3. 启用后，裁剪、合并、转码、调速、改分辨率等操作都会自动改用硬件编码，大幅提升转码速度。

> 注意：如果检测不到可用的 GPU 硬件编码器，设置对话框会显示红色提示。这通常是因为
> 当前 ffmpeg 未编译硬件编码支持、未安装对应 GPU 驱动，或显卡驱动版本过旧
> （例如 NVIDIA 驱动低于 610.00 时不支持新版 NVENC）。此时程序会自动回退到 CPU 软件编码，
> 不影响正常使用。

### 命令行模式（可选）

也可通过命令行直接调用底层函数（适合脚本化处理）：

```python
from main import probe_video, build_trim_args, build_convert_args
import subprocess

info = probe_video("input.mp4")
print(info.details())

args = build_trim_args("input.mp4", "output.mp4", 0, 10)
subprocess.run(args, check=True)
```

## 📁 文件结构

```
video_editor/
├── main.py            # 主程序（GUI + FFmpeg 封装）
├── icon.ico           # 应用图标（exe 用，由 avatar.jpg 生成）
├── avatar.jpg         # 用户提供的原始图标图片
├── _make_icon.py      # 图标生成脚本（avatar.jpg → icon.ico）
├── dist/
│   └── VideoEditor.exe   # 已编译的 Windows 可执行文件（含自定义图标）
└── README.md          # 本说明文档
```

## 📦 编译为 exe（可选）

已提供编译好的可执行文件 `dist/VideoEditor.exe`（单文件，无需安装 Python 即可运行）。
如需自行重新编译：

```bash
pip install pyinstaller pillow
# 若更换图标，先运行：python _make_icon.py（由 avatar.jpg 生成 icon.ico）
pyinstaller --noconfirm --onefile --windowed --icon icon.ico --name VideoEditor main.py
```

编译结果位于 `dist/VideoEditor.exe`，可直接双击运行。

> 注意：exe 依赖系统中的 `ffmpeg`/`ffprobe`（需在 PATH 中）。若目标电脑没有安装 FFmpeg，
> 可把 `ffmpeg.exe`、`ffprobe.exe` 及 `ffmpeg` 的 DLL 放到与 exe 同目录下，程序会自动找到。

## 🛠 常见问题

- **提示缺少 FFmpeg**：按上方「环境要求」安装并把 `bin` 目录加入 PATH。
- **合并视频参数不一致**：本程序合并时会对所有片段统一重编码为 H.264+AAC，可正常拼接不同分辨率/帧率的视频。
- **GIF 太大**：GIF 输出默认 640 宽、15fps 以控制体积，可在代码中调整 `build_convert_args` 内的 `fps` 与 `scale` 参数。
- **进度条不更新**：仅当视频时长已知时才会显示百分比；拷贝流（无编码）任务可能瞬间完成，属正常现象。
- **检测不到 GPU 加速**：请确认已安装显卡厂商驱动（NVIDIA/Intel/AMD），且 ffmpeg 为支持硬件编码的 full build；驱动版本过旧也会导致检测失败。
- **启用 GPU 后报编码错误**：说明该编码器在当前显卡/驱动上无法工作，请回到「设置」取消勾选 GPU 加速，改用 CPU 编码。
