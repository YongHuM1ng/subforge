"""确保 ffmpeg 可用：PATH 或项目内 tools/ffmpeg/bin。

本项目不自动下载、不随源码分发 ffmpeg。发布包分为「自带 ffmpeg」和
「需要手动放置/安装」两种；这里只负责检查并给出明确路径。
"""
from __future__ import annotations

import shutil

from . import config
from .util import log

_checked = False
_ok = False


def ensure_ffmpeg() -> bool:
    global _checked, _ok
    if _checked:
        return _ok
    _checked = True

    if shutil.which(config.FFMPEG):
        _ok = True
        return True

    log("[错误] 找不到 ffmpeg。")
    log("  请二选一：")
    log("  · 安装 ffmpeg 并加入 PATH：https://ffmpeg.org/download.html")
    log(f"  · 把 ffmpeg.exe 放到：{config.TOOLS_BIN}")
    _ok = False
    return False
