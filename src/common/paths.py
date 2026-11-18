"""输出路径工具。"""
from __future__ import annotations

from pathlib import Path


def unique_output_path(path: Path) -> Path:
    """已存在时自动改名：movie.zh.srt -> movie.zh.2.srt。"""
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}.{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1