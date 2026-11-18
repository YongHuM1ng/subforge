"""确保 ffmpeg/ffprobe 可用：PATH 或项目内 tools/ffmpeg/bin。

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

    missing = [name for name, tool in (("ffmpeg", config.FFMPEG),
                                       ("ffprobe", config.FFPROBE))
               if shutil.which(tool) is None]
    if not missing:
        _ok = True
        return True

    log(f"[错误] 找不到 {'、'.join(missing)}。")
    log("  请二选一：")
    log("  · 安装 ffmpeg 并加入 PATH：https://ffmpeg.org/download.html")
    log(f"  · 把 ffmpeg.exe 和 ffprobe.exe 放到：{config.TOOLS_BIN}")
    _ok = False
    return False
