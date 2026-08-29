# -*- coding: utf-8 -*-
"""
视频编辑器 (Video Editor)
=========================
一个基于 tkinter 图形界面 + FFmpeg 后端的视频编辑工具。

功能：
    - 导入视频文件，显示基本信息（时长、分辨率、编码、帧率）
    - 时间裁剪（保留指定时间段）
    - 多视频合并（concat）
    - 格式转码（mp4 / mkv / avi / mov / webm / gif / mp3 等）
    - 提取音频
    - 调整播放速度（加速/减速）
    - 修改分辨率
    - 实时进度显示

依赖：
    - Python 3.8+（tkinter 为标准库）
    - FFmpeg / FFprobe 已加入系统 PATH（推荐 gyan.dev 的 full build）

用法：
    python main.py
"""

import json
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------------------------------------------------------------------------
# 常量与工具函数
# ---------------------------------------------------------------------------

TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.?\d*)")

# 打包为 windowed 程序（无控制台）时，用该标志隐藏 ffmpeg/ffprobe 弹出的 cmd 黑窗。
# 仅 Windows 有效；非 Windows 传 None。
NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else None


def run_process(args, **kwargs):
    """运行 subprocess，自动附加隐藏窗口标志，避免 GUI 程序弹出 cmd 黑窗。

    等价于 subprocess.run(args, creationflags=NO_WINDOW_FLAGS, **kwargs)。
    """
    return subprocess.run(args, creationflags=NO_WINDOW_FLAGS, **kwargs)


def resource_path(relative_path):
    """返回打包资源（如图标）的绝对路径。

    兼容 PyInstaller 两种模式：
    - 源码运行：返回脚本所在目录
    - onefile 打包：返回运行时解压目录 sys._MEIPASS
    """
    base_path = getattr(
        sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))
    )
    return os.path.join(base_path, relative_path)


def _find_executable(name):
    """查找可执行文件：优先程序/脚本所在目录，其次系统 PATH。

    返回 (路径, 是否找到)。这样把 ffmpeg.exe、ffprobe.exe 放到 exe 旁
    即可直接使用，无需安装或配置 PATH。
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, "frozen", False):  # 已打包成 exe
        base_dir = os.path.dirname(sys.executable)
    exe_name = f"{name}.exe" if os.name == "nt" else name
    candidates = [os.path.join(base_dir, exe_name), name]
    for cand in candidates:
        try:
            run_process(
                [cand, "-version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return cand, True
        except (OSError, subprocess.SubprocessError):
            continue
    return name, False


FFMPEG, FFMPEG_OK = _find_executable("ffmpeg")
FFPROBE, FFPROBE_OK = _find_executable("ffprobe")


def seconds_to_hms(seconds: float | None) -> str:
    """把秒数转换为 HH:MM:SS.mmm 格式。"""
    if seconds is None or seconds < 0:
        return "未知"
    seconds = float(seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def hms_to_seconds(text: str) -> float:
    """把用户输入的时间（支持 秒 / MM:SS / HH:MM:SS）转换为秒数。"""
    text = text.strip().replace("：", ":")
    if not text:
        return 0.0
    parts = text.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        pass
    raise ValueError(f"无法解析时间：{text!r}")


def is_ffmpeg_available() -> bool:
    """检查 ffmpeg 与 ffprobe 是否可用（已自动探测路径）。"""
    return FFMPEG_OK and FFPROBE_OK


# ---------------------------------------------------------------------------
# FFmpeg / FFprobe 封装
# ---------------------------------------------------------------------------

class VideoInfo:
    """保存单个视频（或纯音频）的媒体信息。"""

    def __init__(self, path):
        self.path = path
        self.filename = os.path.basename(path)
        self.duration: float | None = None          # 秒
        self.video_codec: str = "无"
        self.width: int | None = None
        self.height: int | None = None
        self.fps: float | None = None
        self.audio_codec: str = "无"
        self.format_name: str = ""
        self.bit_rate: float | None = None
        self.error: str | None = None

    @property
    def is_audio_only(self) -> bool:
        """是否纯音频文件（没有视频流）。"""
        return self.video_codec == "无"

    @property
    def summary(self) -> str:
        """用于列表显示的简要描述。"""
        if self.is_audio_only:
            return (
                f"{self.filename}  |  {seconds_to_hms(self.duration)}  |  "
                f"音频:{self.audio_codec}"
            )
        return (
            f"{self.filename}  |  {seconds_to_hms(self.duration)}  |  "
            f"{self.width}x{self.height}  |  {self.video_codec}"
        )

    def details(self) -> str:
        """用于详情面板的完整描述。"""
        if self.is_audio_only:
            lines = [
                f"文件：{self.path}",
                f"类型：纯音频",
                f"容器格式：{self.format_name or '未知'}",
                f"时长：{seconds_to_hms(self.duration)}",
                f"音频编码：{self.audio_codec}",
                f"码率：{int(self.bit_rate / 1000)} kbps" if self.bit_rate else "码率：未知",
            ]
            return "\n".join(lines)
        lines = [
            f"文件：{self.path}",
            f"容器格式：{self.format_name or '未知'}",
            f"时长：{seconds_to_hms(self.duration)}",
            f"视频编码：{self.video_codec}",
            f"分辨率：{self.width}x{self.height}" if self.width else "分辨率：未知",
            f"帧率：{self.fps:.3f} fps" if self.fps else "帧率：未知",
            f"音频编码：{self.audio_codec}",
            f"码率：{int(self.bit_rate / 1000)} kbps" if self.bit_rate else "码率：未知",
        ]
        return "\n".join(lines)


def probe_video(path: str) -> VideoInfo:
    """使用 ffprobe 解析视频信息，返回 VideoInfo 对象。"""
    info = VideoInfo(path)
    try:
        result = run_process(
            [
                FFPROBE, "-v", "error",
                "-print_format", "json",
                "-show_format", "-show_streams",
                path,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if result.returncode != 0:
            info.error = result.stderr.strip() or "ffprobe 解析失败"
            return info
        data = json.loads(result.stdout or "{}")

        fmt = data.get("format", {})
        info.format_name = fmt.get("format_name", "")
        info.duration = _to_float(fmt.get("duration"))
        info.bit_rate = _to_float(fmt.get("bit_rate"))

        video_stream = None
        audio_stream = None
        for stream in data.get("streams", []):
            ctype = stream.get("codec_type")
            if ctype == "video":
                # 跳过专辑封面图等 attached_pic 流（不是真正的视频轨道）
                if stream.get("disposition", {}).get("attached_pic") == 1:
                    continue
                if video_stream is None:
                    video_stream = stream
            elif ctype == "audio" and audio_stream is None:
                audio_stream = stream

        if video_stream:
            info.video_codec = video_stream.get("codec_name", "未知")
            info.width = video_stream.get("width")
            info.height = video_stream.get("height")
            info.fps = _extract_fps(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
            if info.duration is None:
                info.duration = _to_float(video_stream.get("duration"))

        if audio_stream:
            info.audio_codec = audio_stream.get("codec_name", "未知")

    except json.JSONDecodeError:
        info.error = "ffprobe 输出解析失败"
    except subprocess.TimeoutExpired:
        info.error = "ffprobe 执行超时"
    except OSError as exc:
        info.error = str(exc)
    return info


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_fps(rate_text):
    """把 '30000/1001' 之类的帧率字符串转为浮点数。"""
    if not rate_text:
        return None
    try:
        if "/" in rate_text:
            num, den = rate_text.split("/")
            den = float(den)
            if den == 0:
                return None
            return float(num) / den
        return float(rate_text)
    except (ValueError, ZeroDivisionError):
        return None


class FFmpegTask:
    """在后台线程运行 ffmpeg，并实时回调进度。"""

    def __init__(self, args, total_duration=None, callback=None, done_callback=None):
        self.args = args
        self.total_duration = total_duration
        self.callback = callback        # 进度回调 (percent, time_text)
        self.done_callback = done_callback  # 完成回调 (success, message)
        self.proc = None
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self.proc = subprocess.Popen(
                self.args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=NO_WINDOW_FLAGS,
            )
        except OSError as exc:
            if self.done_callback:
                self.done_callback(False, f"无法启动 ffmpeg：{exc}")
            return

        last_time = -1.0
        stderr = self.proc.stderr
        if not stderr:
            if self.done_callback:
                self.done_callback(False, "无法读取 ffmpeg 输出")
            return
        for line in stderr:
            match = TIME_RE.search(line)
            if not match:
                continue
            try:
                t = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
            except ValueError:
                continue
            if t <= last_time:  # ffmpeg 会重复输出同一时间点
                continue
            last_time = t
            if self.callback and self.total_duration:
                percent = min(99.9, (t / self.total_duration) * 100.0)
                self.callback(percent, t)

        self.proc.wait()
        success = self.proc.returncode == 0
        message = "处理完成" if success else f"ffmpeg 出错（退出码 {self.proc.returncode}）"
        if self.done_callback:
            self.callback and self.callback(100.0, last_time if success else 0)
            self.done_callback(success, message)

    def cancel(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


# ---------------------------------------------------------------------------
# 编辑命令构造
# ---------------------------------------------------------------------------

def build_trim_args(input_path, output_path, start, end, vcodec="libx264", acodec="aac",
                    hw_display_name=None):
    """裁剪命令：保留 [start, end] 时间段。hw_display_name 为 GPU 编码器显示名。"""
    vcodec = resolve_vcodec(vcodec, hw_display_name)
    args = [FFMPEG, "-y", "-i", input_path, "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}"]
    if vcodec:
        args += ["-c:v", vcodec] + hw_extra_args(hw_display_name)
    if acodec:
        args += ["-c:a", acodec]
    args += ["-movflags", "+faststart", output_path]
    return args


def build_convert_args(input_path, output_path, vcodec, acodec, vbr=None, crf=23,
                       hw_display_name=None):
    """转码命令。vcodec/acodec 为 None 表示拷贝对应流。hw_display_name 为 GPU 编码器显示名。"""
    args = [FFMPEG, "-y", "-i", input_path]
    if vcodec:
        vcodec = resolve_vcodec(vcodec, hw_display_name)
        args += ["-c:v", vcodec] + hw_extra_args(hw_display_name)
        if vbr == "crf" and vcodec in ("libx264", "libx265", "libvpx-vp9"):
            args += ["-crf", str(crf)]
        elif vbr == "cbr":
            args += ["-b:v", "4M"]
    else:
        args += ["-c:v", "copy"]
    if acodec:
        args += ["-c:a", acodec]
    else:
        args += ["-c:a", "copy"]
    if output_path.lower().endswith(".mp4"):
        args += ["-movflags", "+faststart"]
    args += [output_path]
    return args


def build_extract_audio_args(input_path, output_path, acodec=None):
    """提取音频命令。acodec=None 时拷贝原音频流。"""
    args = [FFMPEG, "-y", "-i", input_path, "-vn"]
    args += ["-c:a", acodec] if acodec else ["-c:a", "copy"]
    args += [output_path]
    return args


def build_audio_trim_args(input_path, output_path, start, end, acodec=None):
    """纯音频裁剪命令：保留 [start, end] 时间段。acodec=None 时拷贝原音频流。"""
    args = [FFMPEG, "-y", "-i", input_path, "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}"]
    args += ["-c:a", acodec] if acodec else ["-c:a", "copy"]
    args += [output_path]
    return args


def build_audio_convert_args(input_path, output_path, acodec=None):
    """纯音频转码命令（整段转码，不裁剪）。acodec=None 时拷贝原音频流。"""
    args = [FFMPEG, "-y", "-i", input_path]
    args += ["-c:a", acodec] if acodec else ["-c:a", "copy"]
    args += [output_path]
    return args


def build_speed_args(input_path, output_path, speed, vcodec="libx264", acodec="aac",
                     hw_display_name=None):
    """调整播放速度。speed>1 加速，speed<1 减速。hw_display_name 为 GPU 编码器显示名。"""
    if speed <= 0:
        raise ValueError("速度必须大于 0")
    vcodec = resolve_vcodec(vcodec, hw_display_name)
    args = [
        FFMPEG, "-y", "-i", input_path,
        "-filter_complex",
        f"[0:v]setpts={1.0 / speed:.4f}*PTS[v];"
        f"[0:a]atempo={_atempo_factors(speed)}[a]",
        "-map", "[v]", "-map", "[a]",
    ]
    if vcodec:
        args += ["-c:v", vcodec] + hw_extra_args(hw_display_name)
    if acodec:
        args += ["-c:a", acodec]
    if output_path.lower().endswith(".mp4"):
        args += ["-movflags", "+faststart"]
    args += [output_path]
    return args


def _atempo_factors(speed: float) -> str:
    """atempo 滤镜只支持 0.5~2.0，超范围需串联多个滤镜。"""
    speed = float(speed)
    factors = []
    remaining = speed
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(round(remaining, 4))
    return ",".join(f"{f:g}" for f in factors)


def build_resize_args(input_path, output_path, width, height, vcodec="libx264", acodec="aac",
                      hw_display_name=None):
    """修改分辨率命令。width/height 可为 None 表示保持比例自动计算。"""
    if not width and not height:
        raise ValueError("宽和高至少提供一个")
    vcodec = resolve_vcodec(vcodec, hw_display_name)
    scale = ""
    if width and height:
        scale = f"scale={width}:{height}"
    elif width:
        scale = f"scale={width}:-2"
    else:
        scale = f"scale=-2:{height}"
    args = [
        FFMPEG, "-y", "-i", input_path,
        "-vf", scale,
    ]
    if vcodec:
        args += ["-c:v", vcodec] + hw_extra_args(hw_display_name)
    if acodec:
        args += ["-c:a", acodec]
    if output_path.lower().endswith(".mp4"):
        args += ["-movflags", "+faststart"]
    args += [output_path]
    return args


def build_volume_args(input_path, output_path, volume, acodec="aac", audio_only=False,
                      hw_display_name=None):
    """调整音量命令。volume 为音量倍数（如 0.5 减半、2.0 加倍）。

    - audio_only=True（纯音频）：直接对音频流应用 volume 滤镜
    - audio_only=False（视频）：保留视频流不变，仅重新编码音频流
    """
    if volume <= 0:
        raise ValueError("音量必须是大于 0 的倍数")
    vol_text = f"{volume:.2f}"
    if audio_only:
        args = [FFMPEG, "-y", "-i", input_path, "-af", f"volume={vol_text}"]
        args += ["-c:a", acodec]
        args += [output_path]
        return args
    # 视频文件：保持视频流，仅处理音频
    args = [
        FFMPEG, "-y", "-i", input_path,
        "-filter_complex", f"[0:a]volume={vol_text}[a]",
        "-map", "0:v", "-map", "[a]",
    ]
    if output_path.lower().endswith((".mp4", ".mov")):
        # 视频流直接拷贝（保持画质与速度），音频按指定编码器重编码
        args += ["-c:v", "copy"]
    else:
        vcodec = resolve_vcodec("libx264", hw_display_name)
        args += ["-c:v", vcodec] + hw_extra_args(hw_display_name)
    args += ["-c:a", acodec]
    if output_path.lower().endswith((".mp4", ".mov")):
        args += ["-movflags", "+faststart"]
    args += [output_path]
    return args


def build_concat_args(input_paths, output_path, vcodec="libx264", acodec="aac",
                      hw_display_name=None):
    """多文件合并（concat）命令。重新编码以保证参数一致。"""
    inputs = []
    filter_inputs_v = []
    filter_inputs_a = []
    total_n = len(input_paths)
    for i, p in enumerate(input_paths):
        inputs += ["-i", p]
        filter_inputs_v.append(f"[{i}:v]")
        filter_inputs_a.append(f"[{i}:a]")
    filter_inputs_v.append(f"concat=n={total_n}:v=1:a=0[v]")
    filter_inputs_a.append(f"concat=n={total_n}:v=0:a=1[a]")
    args = [FFMPEG, "-y"] + inputs + [
        "-filter_complex",
        "".join(filter_inputs_v) + ";" + "".join(filter_inputs_a),
        "-map", "[v]", "-map", "[a]",
    ]
    if vcodec:
        vcodec = resolve_vcodec(vcodec, hw_display_name)
        args += ["-c:v", vcodec] + hw_extra_args(hw_display_name)
    if acodec:
        args += ["-c:a", acodec]
    if output_path.lower().endswith(".mp4"):
        args += ["-movflags", "+faststart"]
    args += [output_path]
    return args


# ---------------------------------------------------------------------------
# GPU 硬件加速
# ---------------------------------------------------------------------------

# 可选硬件编码器：显示名 -> (编码器名, 对应的 hwaccel 解码器)
HW_ENCODERS = {
    "NVIDIA (NVENC)": ("h264_nvenc", "cuda"),
    "Intel (QSV)": ("h264_qsv", "qsv"),
    "AMD (AMF)": ("h264_amf", "d3d11va"),
}


def _summarize_hw_error(enc, err):
    """从 ffmpeg 报错中提炼一句可读的中文原因，便于用户自行修复。"""
    err = err or ""
    low = err.lower()
    if "nvenc" in enc:
        if "minimum required nvidia driver" in low:
            return "NVIDIA 驱动版本过旧（ffmpeg 需 610.00 以上），请更新显卡驱动"
        if "required nvenc api" in low:
            return "NVIDIA 驱动版本过旧（NVENC API 不匹配），请更新显卡驱动"
        return "NVENC 初始化失败，请更新 NVIDIA 显卡驱动"
    if "amf" in enc:
        if "amfrt64.dll" in low:
            return "未安装 AMD 显卡驱动（缺少 amfrt64.dll）"
        return "AMD AMF 初始化失败，请安装 AMD 显卡驱动"
    if "qsv" in enc:
        return "Intel QSV 初始化失败（需要 Intel 核显及正确驱动）"
    first = next((l.strip() for l in err.splitlines() if l.strip()), "")
    return first[:80]


def detect_hw_encoders():
    """检测硬件编码器的可用性与失败原因。

    返回 (可用字典, 失败原因字典)：
        available: {显示名: (编码器, hwaccel)}
        errors:    {显示名: 一句中文原因}（编码器已编译但无法使用，或未编译）
    检测方法：列出编译的编码器后，用 lavfi 生成 1 秒测试帧，
    用真实硬件编码器实际编码到 null，编码成功才算可用。
    """
    available = {}
    errors = {}
    if not FFMPEG_OK:
        return available, errors
    try:
        result = run_process(
            [FFMPEG, "-hide_banner", "-encoders"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        compiled = result.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return available, errors

    # 用独立、无颜色/音频流的测试源（lavfi）快速验证编码器
    null_out = "NUL" if os.name == "nt" else "/dev/null"
    for display, (enc, hwaccel) in HW_ENCODERS.items():
        if enc not in compiled:
            errors[display] = "当前 ffmpeg 未编译该硬件编码器"
            continue
        test_cmd = [
            FFMPEG, "-hide_banner", "-v", "error",
            "-f", "lavfi", "-i", "color=c=black:s=128x128:d=1:r=10",
            "-c:v", enc, "-f", "null", null_out,
        ]
        try:
            result = run_process(
                test_cmd,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30,
            )
            if result.returncode == 0:
                available[display] = (enc, hwaccel)
            else:
                err = (result.stderr or result.stdout or "").strip()
                errors[display] = _summarize_hw_error(enc, err)
        except (OSError, subprocess.SubprocessError):
            errors[display] = "编码器测试执行异常"
    return available, errors


def get_available_hw_encoders():
    """检测 ffmpeg 中实际可用的硬件编码器。

    返回 {显示名: (编码器名, hwaccel)} 的字典。
    """
    available, _ = detect_hw_encoders()
    return available


def _hw_device_init(hwaccel):
    """返回 -init_hw_device 使用的设备名。"""
    return {
        "cuda": "cuda=cu0",
        "qsv": "qsv=qs0",
        "d3d11va": "d3d11va=d11",
    }.get(hwaccel, hwaccel)


# 硬件编码器名到 hwaccel 的推断（由 HW_ENCODERS 的显示名决定）
_HW_SUFFIX = {
    "NVIDIA (NVENC)": "nvenc",
    "Intel (QSV)": "qsv",
    "AMD (AMF)": "amf",
}


def resolve_vcodec(base_vcodec, hw_display_name=None):
    """根据是否启用 GPU 加速，返回实际使用的视频编码器名。

    base_vcodec       : 软件编码器（libx264 / libx265 / libvpx-vp9）
    hw_display_name   : 硬件编码器显示名（如 'NVIDIA (NVENC)'），None 表示不启用
    """
    if not hw_display_name:
        return base_vcodec
    suffix = _HW_SUFFIX.get(hw_display_name)
    if not suffix:
        return base_vcodec
    mapping = {
        "libx264": f"h264_{suffix}",
        "libx265": f"hevc_{suffix}",
        "libvpx-vp9": f"vp9_{suffix}",
    }
    return mapping.get(base_vcodec, base_vcodec)


def hw_extra_args(hw_display_name):
    """返回硬件编码所需的附加参数（如像素格式适配）。"""
    if not hw_display_name:
        return []
    suffix = _HW_SUFFIX.get(hw_display_name)
    if suffix == "amf":
        # AMF 编码器不接受常见非 yuv 输入，显式指定 yuv420p
        return ["-pix_fmt", "yuv420p"]
    if suffix == "nvenc":
        return ["-pix_fmt", "yuv420p"]
    return ["-pix_fmt", "yuv420p"]


# ---------------------------------------------------------------------------
# 图形界面
# ---------------------------------------------------------------------------

OUTPUT_FORMATS = {
    "MP4 (H.264 + AAC)": (".mp4", "libx264", "aac"),
    "MP4 (H.265/HEVC + AAC)": (".mp4", "libx265", "aac"),
    "MKV (H.264 + AAC)": (".mkv", "libx264", "aac"),
    "AVI (H.264 + AAC)": (".avi", "libx264", "aac"),
    "MOV (H.264 + AAC)": (".mov", "libx264", "aac"),
    "WebM (VP9 + Opus)": (".webm", "libvpx-vp9", "libopus"),
    "GIF 动画": (".gif", None, None),
    "MP3 音频": (".mp3", None, "libmp3lame"),
    "WAV 音频": (".wav", None, "pcm_s16le"),
}


class VideoEditorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("视频编辑器 - FFmpeg")
        self.root.geometry("820x640")
        self.root.minsize(720, 560)
        self._set_window_icon()

        self.videos = []          # 已导入的 VideoInfo 列表
        self.current_task = None  # 正在运行的任务
        self.output_dir = os.path.expanduser("~/Desktop")

        # GPU 加速设置
        self.hw_encoders, self.hw_errors = detect_hw_encoders()
        # {显示名: (编码器, hwaccel)}，以及 {显示名: 失败原因}
        self.use_gpu = tk.BooleanVar(value=False)
        self.hw_choice = tk.StringVar(
            value=list(self.hw_encoders.keys())[0] if self.hw_encoders else ""
        )

        self._check_ffmpeg()
        self._build_ui()

    # ---------------- 界面搭建 ----------------

    def _set_window_icon(self):
        """设置窗口标题栏/任务栏图标。

        优先用 iconphoto（tk.PhotoImage 从 PNG 读取，数据常驻 tk 内存，
        不依赖打包后的文件路径，onefile 打包后也能正常工作）；
        若 PNG 缺失再回退到 iconbitmap（icon.ico）。
        """
        self._icon_images = []
        # 1) iconphoto：从 PNG 加载多个尺寸，图标数据常驻内存
        for size in (32, 16):
            png_path = resource_path(f"icon_{size}.png")
            if os.path.isfile(png_path):
                try:
                    img = tk.PhotoImage(file=png_path)
                    self._icon_images.append(img)  # 保持引用，防止被回收
                except tk.TclError:
                    self._icon_images = []
                    break
        if self._icon_images:
            try:
                self.root.iconphoto(True, *self._icon_images)
                return
            except tk.TclError:
                pass
        # 2) 回退：iconbitmap（icon.ico）
        try:
            icon_path = resource_path("icon.ico")
            if os.path.isfile(icon_path):
                self.root.iconbitmap(icon_path)
        except tk.TclError:
            # 图标缺失或格式不受支持时静默跳过，不影响程序运行
            pass

    def _check_ffmpeg(self):
        if not is_ffmpeg_available():
            messagebox.showwarning(
                "缺少 FFmpeg",
                "未检测到 ffmpeg/ffprobe。\n\n"
                "解决方法（任选其一）：\n"
                "1) 将 ffmpeg.exe 和 ffprobe.exe 放到本程序所在目录；\n"
                "2) 安装 FFmpeg 并加入系统 PATH。\n\n"
                "下载：https://www.gyan.dev/ffmpeg/builds/ （选择 full build）",
            )

    def _open_settings(self):
        """打开设置对话框：GPU 加速选项。"""
        dialog = tk.Toplevel(self.root)
        dialog.title("设置")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="硬件加速（GPU）", font=("", 11, "bold")).pack(anchor="w")
        if not self.hw_encoders:
            ttk.Label(
                frame,
                text="未检测到可用的 GPU 硬件编码器。",
                foreground="#c00", justify="left",
            ).pack(anchor="w", pady=(6, 4))
            if self.hw_errors:
                # 展示每个编码器的具体失败原因，便于用户自行排查/更新驱动
                ttk.Label(
                    frame, text="各编码器无法使用的原因：",
                    foreground="#555", justify="left",
                ).pack(anchor="w", pady=(6, 2))
                for display, reason in self.hw_errors.items():
                    ttk.Label(
                        frame, text=f"• {display}：{reason}",
                        foreground="#666", justify="left", wraplength=360,
                    ).pack(anchor="w")
        else:
            ttk.Checkbutton(
                frame, text="启用 GPU 加速（推荐，显著提升转码速度）",
                variable=self.use_gpu,
            ).pack(anchor="w", pady=(6, 4))

            gpu_row = ttk.Frame(frame)
            gpu_row.pack(anchor="w", pady=2)
            ttk.Label(gpu_row, text="GPU 编码器：").pack(side="left")
            hw_box = ttk.Combobox(
                gpu_row, textvariable=self.hw_choice, state="readonly", width=22,
                values=list(self.hw_encoders.keys()),
            )
            hw_box.pack(side="left")

            hint = "、".join(f"{k}（{v[0]}）" for k, v in self.hw_encoders.items())
            ttk.Label(frame, text=f"已检测到：{hint}", foreground="#555").pack(anchor="w", pady=(4, 0))

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=10)

        btns = ttk.Frame(frame)
        btns.pack(fill="x")
        ttk.Button(btns, text="确定", command=dialog.destroy).pack(side="right")

        # 居中显示
        dialog.update_idletasks()
        w, h = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - h) // 2
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _build_ui(self):
        # 顶部：导入按钮
        top = ttk.Frame(self.root, padding=(10, 8))
        top.pack(fill="x")
        ttk.Button(top, text="导入媒体文件", command=self._import_files).pack(side="left")
        ttk.Button(top, text="清除列表", command=self._clear_list).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="⚙ 设置", command=self._open_settings).pack(side="left", padx=(6, 0))
        self.status_label = ttk.Label(top, text="就绪", foreground="#555")
        self.status_label.pack(side="right")

        # 中部：文件列表 + 详情
        middle = ttk.PanedWindow(self.root, orient="horizontal")
        middle.pack(fill="both", expand=True, padx=10)

        left = ttk.Frame(middle)
        ttk.Label(left, text="已导入的媒体文件：").pack(anchor="w")
        self.tree = ttk.Treeview(left, columns=("type", "info"), show="tree", height=12)
        self.tree.heading("#0", text="文件")
        self.tree.heading("type", text="类型")
        self.tree.heading("info", text="信息")
        self.tree.column("#0", width=250)
        self.tree.column("type", width=48, anchor="center")
        self.tree.column("info", width=260)
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ttk.Frame(middle)
        ttk.Label(right, text="文件详情：").pack(anchor="w")
        self.detail_text = tk.Text(right, width=42, height=12, state="disabled")
        self.detail_text.pack(fill="both", expand=True)
        middle.add(left, weight=3)
        middle.add(right, weight=2)

        # 编辑参数区
        params = ttk.LabelFrame(self.root, text="编辑参数", padding=8)
        params.pack(fill="x", padx=10, pady=6)

        row1 = ttk.Frame(params)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="开始时间 (秒或 HH:MM:SS)：").pack(side="left")
        self.start_var = tk.StringVar(value="0")
        ttk.Entry(row1, textvariable=self.start_var, width=14).pack(side="left")
        ttk.Label(row1, text="结束时间：").pack(side="left", padx=(12, 0))
        self.end_var = tk.StringVar(value="")
        ttk.Entry(row1, textvariable=self.end_var, width=14).pack(side="left")
        ttk.Label(row1, text="（留空=到结尾）").pack(side="left", padx=(6, 0))

        row2 = ttk.Frame(params)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="输出格式：").pack(side="left")
        self.format_var = tk.StringVar(value=list(OUTPUT_FORMATS)[0])
        fmt_box = ttk.Combobox(
            row2, textvariable=self.format_var, state="readonly", width=28,
            values=list(OUTPUT_FORMATS),
        )
        fmt_box.pack(side="left")
        ttk.Label(row2, text="速度：").pack(side="left", padx=(16, 0))
        self.speed_var = tk.StringVar(value="1.0")
        ttk.Entry(row2, textvariable=self.speed_var, width=8).pack(side="left")
        ttk.Label(row2, text="分辨率：").pack(side="left", padx=(16, 0))
        self.width_var = tk.StringVar(value="")
        ttk.Entry(row2, textvariable=self.width_var, width=6).pack(side="left")
        ttk.Label(row2, text="x").pack(side="left")
        self.height_var = tk.StringVar(value="")
        ttk.Entry(row2, textvariable=self.height_var, width=6).pack(side="left")
        ttk.Label(row2, text="（留空保持比例）").pack(side="left", padx=(4, 0))

        row3 = ttk.Frame(params)
        row3.pack(fill="x", pady=2)
        ttk.Label(row3, text="音量：").pack(side="left")
        self.volume_var = tk.StringVar(value="1.0")
        ttk.Entry(row3, textvariable=self.volume_var, width=8).pack(side="left")
        ttk.Label(row3, text="（倍数，0.5=减半 2.0=加倍）").pack(side="left", padx=(6, 0))

        # 操作按钮区（保存引用以便根据所选文件类型禁用/启用）
        actions = ttk.Frame(self.root, padding=(10, 4))
        actions.pack(fill="x")
        self.btn_trim = ttk.Button(actions, text="✂ 裁剪", command=self._trim)
        self.btn_trim.pack(side="left")
        self.btn_merge = ttk.Button(actions, text="🔗 合并全部", command=self._merge)
        self.btn_merge.pack(side="left", padx=(6, 0))
        self.btn_convert = ttk.Button(actions, text="🔄 转码", command=self._convert)
        self.btn_convert.pack(side="left", padx=(6, 0))
        self.btn_volume = ttk.Button(actions, text="🔊 调节音量", command=self._apply_volume)
        self.btn_volume.pack(side="left", padx=(6, 0))
        self.btn_extract = ttk.Button(actions, text="🎵 提取音频", command=self._extract_audio)
        self.btn_extract.pack(side="left", padx=(6, 0))
        self.btn_speed = ttk.Button(actions, text="⏩ 调整速度", command=self._apply_speed)
        self.btn_speed.pack(side="left", padx=(6, 0))
        self.btn_resize = ttk.Button(actions, text="📐 改分辨率", command=self._apply_resize)
        self.btn_resize.pack(side="left", padx=(6, 0))
        self.btn_stop = ttk.Button(actions, text="■ 停止", command=self._cancel_task)
        self.btn_stop.pack(side="right")

        self._update_action_buttons()

        # 底部：进度条
        bottom = ttk.Frame(self.root, padding=(10, 8))
        bottom.pack(fill="x")
        self.progress = ttk.Progressbar(bottom, maximum=100, length=600)
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_label = ttk.Label(bottom, text="0%", width=8, anchor="e")
        self.progress_label.pack(side="right")

    # ---------------- 文件导入与选择 ----------------

    def _import_files(self):
        paths = filedialog.askopenfilenames(
            title="选择媒体文件",
            filetypes=[
                ("视频文件", "*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv *.m4v *.ts *.mpg *.mpeg"),
                ("音频文件", "*.mp3 *.wav *.flac *.aac *.m4a *.ogg *.opus *.wma *.ape *.aiff"),
                ("所有文件", "*.*"),
            ],
        )
        for path in paths:
            info = probe_video(path)
            if info.error:
                messagebox.showwarning("解析失败", f"{info.filename}:\n{info.error}")
                continue
            self.videos.append(info)
            label = "音频" if info.is_audio_only else "视频"
            self.tree.insert("", "end", iid=str(len(self.videos) - 1), text=info.filename,
                             values=(label, seconds_to_hms(info.duration)))
        self._update_status()
        self._update_action_buttons()

    def _clear_list(self):
        if self.current_task and self.current_task.proc and self.current_task.proc.poll() is None:
            messagebox.showwarning("提示", "请先停止当前任务")
            return
        self.videos.clear()
        self.tree.delete(*self.tree.get_children())
        self._set_detail("")
        self._update_status()

    def _on_select(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        index = int(selection[0])
        info = self.videos[index]
        self._set_detail(info.details())
        if self.end_var.get() == "" and info.duration:
            self.end_var.set(f"{info.duration:.3f}")
        self._update_action_buttons()

    def _set_detail(self, text):
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.config(state="disabled")

    def _update_status(self):
        n = len(self.videos)
        if n == 0:
            self.status_label.config(text="就绪")
        else:
            nv = sum(1 for v in self.videos if not v.is_audio_only)
            na = sum(1 for v in self.videos if v.is_audio_only)
            self.status_label.config(text=f"已导入 {n} 个文件（视频 {nv} / 音频 {na}）")

    def _update_action_buttons(self):
        """根据所选文件类型启用/禁用操作按钮。

        - 纯音频：提取音频、调整速度、改分辨率 属于视频专属操作，置灰禁用；音量可用
        - 无音频轨道的视频：音量调节禁用
        - 未选择文件：除合并外全部禁用
        """
        selection = self.tree.selection()
        selected = None
        if selection:
            selected = self.videos[int(selection[0])]
        if selected is None:
            self.btn_trim.config(state="disabled")
            self.btn_convert.config(state="disabled")
            self.btn_volume.config(state="disabled")
            self.btn_extract.config(state="disabled")
            self.btn_speed.config(state="disabled")
            self.btn_resize.config(state="disabled")
            self.btn_merge.config(state="normal" if len(self.videos) >= 2 else "disabled")
            return
        if selected.is_audio_only:
            self.btn_trim.config(state="normal")
            self.btn_convert.config(state="normal")
            self.btn_volume.config(state="normal")
            self.btn_extract.config(state="disabled")
            self.btn_speed.config(state="disabled")
            self.btn_resize.config(state="disabled")
            self.btn_merge.config(state="normal" if len(self.videos) >= 2 else "disabled")
        else:
            for btn in (self.btn_trim, self.btn_merge, self.btn_convert,
                        self.btn_extract, self.btn_speed, self.btn_resize):
                btn.config(state="normal")
            # 音量调节需要音频轨道
            self.btn_volume.config(
                state="normal" if selected.audio_codec != "无" else "disabled")

    # ---------------- 辅助方法 ----------------

    def _selected_info(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先在列表中选择一个媒体文件")
            return None
        return self.videos[int(selection[0])]

    def _get_output_format(self):
        key = self.format_var.get()
        return OUTPUT_FORMATS.get(key, OUTPUT_FORMATS["MP4 (H.264 + AAC)"])

    def _current_hw_display(self):
        """当前是否启用 GPU 加速。返回编码器显示名或 None。"""
        if self.use_gpu.get() and self.hw_choice.get() in self.hw_encoders:
            return self.hw_choice.get()
        return None

    def _ask_output_path(self, source_path, suffix, default_ext=".mp4"):
        """弹出保存对话框，默认放到输出目录。"""
        base = os.path.splitext(os.path.basename(source_path))[0]
        suggested = os.path.join(self.output_dir, f"{base}_{suffix}{default_ext}")
        path = filedialog.asksaveasfilename(
            title="选择输出位置",
            initialfile=os.path.basename(suggested),
            initialdir=os.path.dirname(suggested),
            defaultextension=default_ext,
        )
        return path

    def _get_speed(self):
        try:
            speed = float(self.speed_var.get())
            if speed <= 0:
                raise ValueError
            return speed
        except ValueError:
            messagebox.showerror("参数错误", "速度必须是大于 0 的数字（如 0.5、1.0、2.0）")
            return None

    def _get_resize(self):
        w = self.width_var.get().strip()
        h = self.height_var.get().strip()
        try:
            width = int(w) if w else None
            height = int(h) if h else None
            if width and width % 2:
                width += 1  # 保证偶数，避免编码失败
            if height and height % 2:
                height += 1
            return width, height
        except ValueError:
            messagebox.showerror("参数错误", "分辨率必须是整数")
            return None

    def _run_task(self, args, total_duration, label):
        """启动后台任务并绑定进度回调。"""
        if self.current_task and self.current_task.proc and self.current_task.proc.poll() is None:
            messagebox.showwarning("提示", "已有任务正在运行，请先停止")
            return

        self.status_label.config(text=f"正在{label}...")
        self.progress.config(value=0)
        self.progress_label.config(text="0%")

        task = FFmpegTask(
            args,
            total_duration=total_duration,
            callback=self._update_progress,
            done_callback=lambda ok, msg: self._on_task_done(ok, msg, label),
        )
        self.current_task = task
        task.start()

    def _update_progress(self, percent, _time):
        self.progress.config(value=percent)
        self.progress_label.config(text=f"{percent:.1f}%")

    def _on_task_done(self, success, message, label):
        if success:
            self.status_label.config(text=f"{label}完成")
            messagebox.showinfo("完成", f"{label}成功！")
        else:
            self.status_label.config(text=f"{label}失败")
            messagebox.showerror("失败", message)
        self.progress.config(value=100 if success else 0)

    def _cancel_task(self):
        if self.current_task and self.current_task.proc and self.current_task.proc.poll() is None:
            self.current_task.cancel()
            self.status_label.config(text="已停止")
            self.progress_label.config(text="已停止")

    # ---------------- 编辑操作 ----------------

    def _trim(self):
        info = self._selected_info()
        if not info:
            return
        try:
            start = hms_to_seconds(self.start_var.get())
            end_text = self.end_var.get().strip()
            end = info.duration if not end_text else hms_to_seconds(end_text)
        except ValueError as exc:
            messagebox.showerror("时间格式错误", str(exc))
            return
        if end <= start:
            messagebox.showerror("参数错误", "结束时间必须大于开始时间")
            return
        if start >= info.duration:
            messagebox.showerror("参数错误", "开始时间超出文件时长")
            return

        out_ext, vcodec, acodec = self._get_output_format()
        if info.is_audio_only:
            # 纯音频裁剪：输出应为音频格式；若用户选了视频格式则提示
            if out_ext not in (".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac", ".aac"):
                messagebox.showwarning(
                    "输出格式", "当前选中的是视频格式，纯音频文件请选择音频输出格式。\n"
                    "已自动切换为 MP3 音频输出。"
                )
                out_ext, vcodec, acodec = (".mp3", None, "libmp3lame")
            out_path = self._ask_output_path(info.path, "trim", out_ext)
            if not out_path:
                return
            args = build_audio_trim_args(info.path, out_path, start, end, acodec)
        else:
            out_path = self._ask_output_path(info.path, "trim", out_ext)
            if not out_path:
                return
            if out_ext == ".gif":
                args = [FFMPEG, "-y", "-i", info.path, "-ss", f"{start:.3f}",
                        "-t", f"{end - start:.3f}",
                        "-vf", "fps=15,scale=640:-1:flags=lanczos", out_path]
            else:
                args = build_trim_args(info.path, out_path, start, end, vcodec, acodec,
                                       self._current_hw_display())
        self._run_task(args, total_duration=end - start, label="裁剪")

    def _merge(self):
        if len(self.videos) < 2:
            messagebox.showwarning("提示", "合并至少需要 2 个文件")
            return
        if any(v.is_audio_only for v in self.videos):
            messagebox.showerror("不支持", "合并目前仅支持视频文件，请移除列表中的音频文件")
            return
        total = sum(v.duration or 0 for v in self.videos)
        out_ext, vcodec, acodec = self._get_output_format()
        if out_ext in (".gif", ".mp3", ".wav"):
            messagebox.showerror("不支持", "合并请选择视频输出格式（mp4/mkv/avi/mov/webm）")
            return
        out_path = self._ask_output_path(self.videos[0].path, "merged", out_ext)
        if not out_path:
            return
        args = build_concat_args([v.path for v in self.videos], out_path, vcodec, acodec,
                                 self._current_hw_display())
        self._run_task(args, total_duration=total, label="合并")

    def _convert(self):
        info = self._selected_info()
        if not info:
            return
        out_ext, vcodec, acodec = self._get_output_format()
        if info.is_audio_only:
            # 纯音频转码：输出应为音频格式；若选了视频格式则提示并切换
            if out_ext not in (".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac", ".aac"):
                messagebox.showwarning(
                    "输出格式", "当前选中的是视频格式，纯音频文件请选择音频输出格式。\n"
                    "已自动切换为 MP3 音频输出。"
                )
                out_ext, vcodec, acodec = (".mp3", None, "libmp3lame")
            out_path = self._ask_output_path(info.path, "convert", out_ext)
            if not out_path:
                return
            args = build_audio_convert_args(info.path, out_path, acodec)
        elif out_ext == ".gif":
            out_path = self._ask_output_path(info.path, "gif", ".gif")
            if not out_path:
                return
            args = [FFMPEG, "-y", "-i", info.path, "-vf",
                    "fps=15,scale=640:-1:flags=lanczos", out_path]
        else:
            out_path = self._ask_output_path(info.path, "convert", out_ext)
            if not out_path:
                return
            args = build_convert_args(info.path, out_path, vcodec, acodec,
                                      hw_display_name=self._current_hw_display())
        self._run_task(args, total_duration=info.duration, label="转码")

    def _extract_audio(self):
        info = self._selected_info()
        if not info:
            return
        if info.is_audio_only:
            messagebox.showwarning("提示", "该文件已是纯音频，无需再提取音频")
            return
        if info.audio_codec == "无":
            messagebox.showwarning("提示", "该视频没有音频轨道")
            return
        _, _, acodec = self._get_output_format()
        ext_map = {"libmp3lame": ".mp3", "pcm_s16le": ".wav", "aac": ".m4a", "libopus": ".opus"}
        out_ext = ext_map.get(acodec, ".mp3")
        out_path = self._ask_output_path(info.path, "audio", out_ext)
        if not out_path:
            return
        args = build_extract_audio_args(info.path, out_path, acodec)
        self._run_task(args, total_duration=info.duration, label="提取音频")

    def _apply_speed(self):
        info = self._selected_info()
        if not info:
            return
        if info.is_audio_only:
            messagebox.showwarning("提示", "调整速度需要视频轨道，请选择视频文件")
            return
        speed = self._get_speed()
        if speed is None:
            return
        out_ext, vcodec, acodec = self._get_output_format()
        out_path = self._ask_output_path(info.path, f"x{speed:g}", out_ext)
        if not out_path:
            return
        args = build_speed_args(info.path, out_path, speed, vcodec, acodec,
                                self._current_hw_display())
        total = (info.duration or 0) / speed
        self._run_task(args, total_duration=total, label="调速")

    def _apply_resize(self):
        info = self._selected_info()
        if not info:
            return
        if info.is_audio_only:
            messagebox.showwarning("提示", "修改分辨率需要视频轨道，请选择视频文件")
            return
        resize = self._get_resize()
        if resize is None:
            return
        width, height = resize
        if not width and not height:
            messagebox.showerror("参数错误", "请至少输入宽或高")
            return
        out_ext, vcodec, acodec = self._get_output_format()
        out_path = self._ask_output_path(info.path, "resized", out_ext)
        if not out_path:
            return
        args = build_resize_args(info.path, out_path, width, height, vcodec, acodec,
                                 self._current_hw_display())
        self._run_task(args, total_duration=info.duration, label="改分辨率")

    def _apply_volume(self):
        info = self._selected_info()
        if not info:
            return
        if info.audio_codec == "无":
            messagebox.showwarning("提示", "该文件没有音频轨道，无法调节音量")
            return
        try:
            volume = float(self.volume_var.get())
            if volume <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("参数错误", "音量必须是大于 0 的倍数（如 0.5、1.0、2.0）")
            return

        out_ext, vcodec, acodec = self._get_output_format()
        if info.is_audio_only:
            # 纯音频：输出应为音频格式；若选了视频格式则提示并切换
            if out_ext not in (".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac", ".aac"):
                messagebox.showwarning(
                    "输出格式", "当前选中的是视频格式，纯音频文件请选择音频输出格式。\n"
                    "已自动切换为 MP3 音频输出。"
                )
                out_ext, vcodec, acodec = (".mp3", None, "libmp3lame")
            out_path = self._ask_output_path(info.path, f"vol{volume:g}", out_ext)
            if not out_path:
                return
            args = build_volume_args(info.path, out_path, volume, acodec, audio_only=True)
        else:
            out_path = self._ask_output_path(info.path, f"vol{volume:g}", out_ext)
            if not out_path:
                return
            if out_ext in (".gif",):
                messagebox.showerror("不支持", "调节音量请选择视频或音频输出格式（不能输出 GIF）")
                return
            args = build_volume_args(info.path, out_path, volume, acodec,
                                     audio_only=False, hw_display_name=self._current_hw_display())
        self._run_task(args, total_duration=info.duration, label="音量调节")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    VideoEditorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
