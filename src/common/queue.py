"""队列模式：从控制台收集拖入的文件，并按顺序逐个执行。

双击启动器（不带文件参数）时进入队列模式：可以多次把文件拖进控制台，
每批按回车换行，最后按一次空行回车开始。文件之间严格串行，单个失败
不影响后续，结束时统一汇总。

把文件拖到启动器图标上时路径直接作为参数传入（`resolve_files`），
不再询问拖入，同样按顺序逐个处理。
"""
from __future__ import annotations

import os
import shlex
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from .console import decorate, format_duration, paint, rule

DRAG_HINT = "把文件拖到本窗口，可多次拖入，每批回车换行；拖完后按一次空行回车开始。"


def split_drag_line(line: str) -> list[str]:
    """把控制台拖拽粘贴的一行拆成路径列表。

    Windows 控制台会把含空格的路径用双引号包起来，多个文件之间用空格分隔。
    """
    text = line.strip()
    if not text:
        return []
    try:
        parts = shlex.split(text, posix=False)
    except ValueError:
        # 引号不配对时退回按空白拆分，避免整行丢失。
        parts = text.split()
    paths: list[str] = []
    for part in parts:
        part = part.strip()
        if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'":
            part = part[1:-1].strip()
        if part:
            paths.append(part)
    return paths


def _check_path(raw: str, base_dir: Path, accept_exts: set[str]) -> tuple[Path | None, str]:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    try:
        path = path.resolve()
    except OSError:
        path = Path(os.path.abspath(path))
    if not path.exists():
        return None, "文件不存在"
    if not path.is_file():
        return None, "不是文件"
    if path.suffix.lower() not in accept_exts:
        allowed = " / ".join(sorted(accept_exts))
        return None, f"扩展名不受支持；仅接受 {allowed}"
    return path, ""


def resolve_files(
    items: Iterable[str],
    *,
    base_dir: Path,
    accept_exts: Iterable[str],
) -> tuple[list[Path], list[tuple[str, str]]]:
    """校验并去重一批路径（控制台拖入或命令行参数）。返回 (可用路径, 问题列表)。"""
    accepted = {ext.lower() for ext in accept_exts}
    paths: list[Path] = []
    issues: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in items:
        path, problem = _check_path(raw, base_dir, accepted)
        if path is None:
            issues.append((raw, problem))
            continue
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths, issues


def collect_files(
    accept_exts: Iterable[str],
    *,
    base_dir: Path,
    title: str,
    stream=None,
    stdin=None,
) -> list[Path]:
    """读取控制台输入直到空行，返回去重、校验后的文件列表。

    有无效项时列出全部问题、清空本次输入并要求重新拖入整批。
    一个文件都没收到就按了空行时返回空列表，由调用方决定是否显示用法。
    """
    out = stream or sys.stdout
    source = stdin or sys.stdin
    accepted = {ext.lower() for ext in accept_exts}
    allowed = " ".join(sorted(accepted))

    while True:
        print(rule(title, out), file=out)
        print(f"  {DRAG_HINT}", file=out)
        print(paint(f"  支持的文件：{allowed}", "dim", stream=out), file=out)
        raw_items: list[str] = []
        while True:
            count = f"已加入 {len(raw_items)} 个 " if raw_items else ""
            print(paint(f"{count}> ", "cyan", stream=out), end="", file=out, flush=True)
            line = source.readline()
            if line == "":
                break
            line = line.rstrip("\r\n")
            if not line.strip():
                break
            raw_items.extend(split_drag_line(line))

        if not raw_items:
            return []

        paths, issues = resolve_files(raw_items, base_dir=base_dir, accept_exts=accepted)
        if not issues:
            return paths

        print("", file=out)
        print(decorate("[错误] 以下文件无法加入队列：", out), file=out)
        for raw, problem in issues:
            print(f"  - {raw}：{problem}", file=out)
        print("本次输入已清空，请重新拖入整批文件。", file=out)
        print("", file=out)


def run_serial(
    paths: list[Path],
    action: Callable[[Path], bool],
    *,
    stream=None,
) -> int:
    """逐个执行 action，返回退出码：全部成功 0，有失败 1，中断 130。"""
    out = stream or sys.stdout
    total = len(paths)
    done = 0
    failed: list[str] = []
    started = time.monotonic()

    def say(line: str = "") -> None:
        print(decorate(line, out), file=out, flush=True)

    def summary(head: str) -> None:
        say("")
        say(rule(head, out))
        say(paint(f"  用时 {format_duration(time.monotonic() - started)}", "dim", stream=out))

    try:
        for index, path in enumerate(paths, 1):
            say("")
            say(f"[队列 {index}/{total}] {path.name}")
            item_started = time.monotonic()
            try:
                success = bool(action(path))
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # 单个文件失败不影响后续
                say(f"[错误] {path.name}: {type(exc).__name__}: {exc}")
                success = False
            elapsed = format_duration(time.monotonic() - item_started)
            if success:
                done += 1
                say(paint(f"  ✓ {path.name} 完成（{elapsed}）", "green", stream=out))
            else:
                failed.append(path.name)
                say(paint(f"  ✗ {path.name} 失败（{elapsed}）", "red", stream=out))
    except KeyboardInterrupt:
        summary(f"队列已中断：成功 {done} 个，失败 {len(failed)} 个，未完成 {total - done - len(failed)} 个")
        if failed:
            say(f"失败的文件：{', '.join(failed)}")
        return 130

    message = f"队列结束：成功 {done} 个"
    if failed:
        message += f"，失败 {len(failed)} 个（{', '.join(failed)}）"
    summary(message)
    return 0 if not failed else 1
