"""视频/音频转字幕的命令行入口。

`1_视频转字幕.cmd` 调用本文件；实现位于 asr.cli。
"""

from __future__ import annotations

import sys

from asr.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))