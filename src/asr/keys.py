"""识别 API Key 的读取与写入。"""
from __future__ import annotations

import os
from pathlib import Path

from common.env import read_env_file
from common.io import write_text_atomic

from . import config
from .util import log


def read_env_key() -> tuple[str, Path]:
    env_file = config.ROOT / ".env"
    return read_env_file(env_file).get(config.API_KEY_ENV, ""), env_file


def save_key(env_file: Path, key: str, name: str | None = None) -> None:
    name = name or config.API_KEY_ENV
    lines: list[str] = []
    if env_file.exists():
        try:
            lines = env_file.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except Exception:
            lines = []
    out: list[str] = []
    replaced = False
    for line in lines:
        env_name, sep, _ = line.partition("=")
        if sep and env_name.strip() == name:
            out.append(f"{name}={key}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{name}={key}")
    write_text_atomic(env_file, "\n".join(out).strip() + "\n", encoding="utf-8")
    try:
        os.chmod(env_file, 0o600)
    except Exception:
        pass


def get_api_key() -> str:
    name = config.API_KEY_ENV
    key, env_file = read_env_key()
    if not key:
        key = (os.environ.get(name) or "").strip()
    if key:
        return key

    log("")
    log(f"未找到 {name}（项目根目录的 .env 里没有）。")
    log("请把对应识别服务的 API Key 粘贴到这里。")
    try:
        import getpass
        key = getpass.getpass("API Key (输入时不显示): ").strip()
    except Exception:
        key = input("API Key: ").strip()
    if not key:
        raise SystemExit("没有提供 API Key，已退出。")
    try:
        save_key(env_file, key, name)
        log(f"已保存到 {env_file}（下次不用再输入；请勿外传此文件）。")
    except Exception as e:
        log(f"[提示] 保存 .env 失败：{e}")
    return key
