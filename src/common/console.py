"""终端输出：UTF-8 输出流、Windows 控制台颜色、统一的标题 / 标签 / 键值行样式。

只用 ASCII 画线和进度条：中文 Windows 控制台会把制表符、方块字符按双宽显示，
容易把整行挤乱。颜色只在真实终端里输出；重定向到文件或管道时自动关闭，
也可以用环境变量 NO_COLOR=1 关闭、FORCE_COLOR=1 强制开启。
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from typing import TextIO

from .textwidth import display_width

_CODES = {
    "bold": "1", "dim": "2",
    "red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36",
}

# 行首 [标签] 的颜色：同一种含义在 ASR、翻译、队列三处保持一致。
TAG_STYLES = {
    "错误": ("red", "bold"),
    "失败": ("red", "bold"),
    "回退": ("yellow", "bold"),
    "审查": ("yellow",),
    "重试": ("yellow",),
    "降并发": ("yellow",),
    "提示": ("yellow",),
    "配置": ("yellow",),
    "跳过": ("yellow",),
    "模型": ("cyan",),
    "代理": ("dim",),
    "复用": ("green",),
    "完成": ("green", "bold"),
    "翻译": ("cyan",),
    "润色": ("magenta",),
    "队列": ("blue", "bold"),
}

_TAG_RE = re.compile(r"^(\s*)\[([^\]\s]+?)(\s[^\]]*)?\]")
_vt_checked = False
_vt_ok = True


def _enable_windows_vt() -> bool:
    """Windows 10+ 控制台默认不解析 ANSI 颜色，需要显式打开 VT 模式。"""
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        ok = False
        for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE / STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(handle_id)
            mode = wintypes.DWORD()
            if handle and kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                if kernel32.SetConsoleMode(handle, mode.value | 0x0004):
                    ok = True
        return ok
    except Exception:
        return False


def setup_streams() -> None:
    """统一把 stdout/stderr 设为 UTF-8，并尝试打开 Windows 控制台颜色。"""
    global _vt_checked, _vt_ok
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if not _vt_checked:
        _vt_ok = _enable_windows_vt()
        _vt_checked = True


def color_enabled(stream: TextIO | None = None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    stream = stream or sys.stdout
    try:
        tty = stream.isatty()
    except Exception:
        return False
    return bool(tty and _vt_ok)


def paint(text: str, *styles: str, stream: TextIO | None = None) -> str:
    codes = [_CODES[name] for name in styles if name in _CODES]
    if not codes or not color_enabled(stream):
        return str(text)
    return f"\033[{';'.join(codes)}m{text}\033[0m"


def screen_width(default: int = 100) -> int:
    columns = shutil.get_terminal_size((default, 24)).columns
    return max(40, min(columns, 140))


def rule(title: str = "", stream: TextIO | None = None, char: str = "=") -> str:
    """整行分隔标题：== 全文分析 ======…"""
    width = min(screen_width(), 100) - 1
    if not title:
        return paint(char * width, "dim", stream=stream)
    head = f"{char * 2} {title} "
    tail = char * max(2, width - display_width(head))
    return paint(char * 2, "dim", stream=stream) + paint(f" {title} ", "bold", stream=stream) + \
        paint(tail, "dim", stream=stream)


def decorate(line: str, stream: TextIO | None = None) -> str:
    """给行首 [标签] 上色；没有标签或无颜色时原样返回。"""
    if not color_enabled(stream):
        return line
    match = _TAG_RE.match(line)
    if not match:
        return line
    styles = TAG_STYLES.get(match.group(2))
    if not styles:
        return line
    return match.group(1) + paint(match.group(0).strip(), *styles, stream=stream) + line[match.end():]


def emit(line: str = "", file: TextIO | None = None) -> None:
    """打印一行，并按标签着色。"""
    file = file or sys.stdout
    print(decorate(str(line), file), file=file, flush=True)


def kv_lines(pairs: list[tuple[str, str]], stream: TextIO | None = None, indent: int = 2) -> list[str]:
    """对齐的键值行：标签列按最长的标签补齐，标签灰显。"""
    pairs = [(key, value) for key, value in pairs if value not in (None, "")]
    if not pairs:
        return []
    width = max(display_width(key) for key, _ in pairs)
    prefix = " " * indent
    return [
        prefix + paint(key + " " * (width - display_width(key)), "dim", stream=stream) + "  " + str(value)
        for key, value in pairs
    ]


def format_duration(seconds: float) -> str:
    value = max(0, int(round(seconds)))
    hours, rest = divmod(value, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
