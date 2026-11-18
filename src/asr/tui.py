"""终端进度显示：单行进度条（含预计剩余时间），无交互。

终端里进度条原地刷新；中途有日志要打印时先擦掉进度行、打印日志、再重画进度，
避免「[重试] …」和进度条挤在同一行。重定向到文件时每次刷新单独成行。
"""

from __future__ import annotations

import sys
import threading
from typing import TextIO

from common.console import format_duration, paint

BAR_WIDTH = 28

_lock = threading.RLock()
_active: tuple[TextIO, str] | None = None


def format_bar(done: int, total: int, width: int = BAR_WIDTH) -> str:
    total = max(1, int(total))
    ratio = max(0.0, min(1.0, int(done) / total))
    filled = int(round(width * ratio))
    return "[" + "#" * filled + "." * (width - filled) + f"] {int(round(ratio * 100)):3d}%"


def progress_line(label: str, done: int, total: int, elapsed: float,
                  width: int = BAR_WIDTH, stream: TextIO | None = None) -> str:
    parts = []
    if label:
        parts.append(label)
    parts.append(paint(format_bar(done, total, width), "cyan", stream=stream))
    parts.append(f"{done}/{total}")
    timing = format_duration(elapsed)
    if 0 < done < total and elapsed > 0:
        remaining = elapsed / done * (total - done)
        timing += f"，剩余约 {format_duration(remaining)}"
    parts.append(timing)
    return "  " + "  ".join(parts)


def _is_tty(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except Exception:
        return False


def write_progress(line: str, stream: TextIO | None = None, done: bool = False) -> None:
    global _active
    stream = stream or sys.stdout
    with _lock:
        if _is_tty(stream):
            stream.write("\r\033[K" + line + ("\n" if done else ""))
            _active = None if done else (stream, line)
        else:
            stream.write(line + "\n")
        stream.flush()


def end_progress() -> None:
    """进度中途失败时收尾：换行，后续日志从新行开始。"""
    global _active
    with _lock:
        if _active is not None:
            stream, _ = _active
            stream.write("\n")
            stream.flush()
            _active = None


def suspend() -> TextIO | None:
    """打印日志前擦掉进度行；返回需要重画的流。调用方须持有 lock。"""
    if _active is None:
        return None
    stream, _ = _active
    stream.write("\r\033[K")
    return stream


def resume(stream: TextIO | None) -> None:
    if stream is not None and _active is not None:
        stream.write(_active[1])
        stream.flush()
