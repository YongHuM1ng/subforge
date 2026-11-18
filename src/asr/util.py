"""线程安全的日志输出。"""
from __future__ import annotations

import sys

from common.console import decorate

from . import tui


def log(msg: str = "", end: str = "\n") -> None:
    """线程安全地打印一行；行首 [标签] 着色，进度条会在日志之后重画。"""
    with tui._lock:
        stream = tui.suspend()
        text = decorate(str(msg), sys.stdout)
        try:
            print(text, end=end, flush=True)
        except UnicodeEncodeError:
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            safe = text.encode(enc, "replace").decode(enc, "replace")
            sys.stdout.write(safe + end)
            sys.stdout.flush()
        tui.resume(stream)
