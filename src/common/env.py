""".env 读取：识别侧与翻译侧共用一份解析规则。"""
from __future__ import annotations

import os
from pathlib import Path


def read_env_file(path: Path) -> dict[str, str]:
    """解析 KEY=VALUE 行；忽略空行、注释和没有 = 的行，值两侧引号会被去掉。"""
    values: dict[str, str] = {}
    try:
        if not path.exists():
            return values
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        if name:
            values[name] = value.strip().strip('"').strip("'")
    return values


def load_env_file(path: Path) -> None:
    """把 .env 中的变量加载到 os.environ；已存在的环境变量优先。"""
    for name, value in read_env_file(path).items():
        if value and name not in os.environ:
            os.environ[name] = value
