"""终端输出工具：固定屏幕宽度、中文对齐的简洁表格，无交互。"""

from __future__ import annotations

import re
import shutil
import sys
from collections.abc import Sequence
from typing import TextIO

from common.console import emit, paint, rule
from common.textwidth import char_width

SEPARATOR = "  "
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", str(text))


def display_width(text: str) -> int:
    return sum(char_width(ch) for ch in strip_ansi(text))


def _tokens(text: str):
    """把 ANSI 转义序列作为一个零宽 token，其余按字符切分。"""
    position = 0
    for match in ANSI_RE.finditer(text):
        if match.start() > position:
            yield from text[position:match.start()]
        yield match.group(0)
        position = match.end()
    if position < len(text):
        yield from text[position:]


def screen_width(indent: int = 2) -> int:
    columns = shutil.get_terminal_size((120, 24)).columns
    return max(40, columns - indent)


def fit_widths(columns: int, total: int, fixed: dict[int, int] | None = None,
               weights: Sequence[float] | None = None) -> list[int]:
    """在固定总宽下分配列宽；等权的文本列会得到完全相同的宽度。"""
    fixed = dict(fixed or {})
    weights = list(weights or [1.0] * columns)
    widths = [max(4, int(fixed.get(i, 4))) for i in range(columns)]
    flexible = [i for i in range(columns) if i not in fixed]
    if not flexible:
        return widths
    remaining = total - len(SEPARATOR) * (columns - 1) - sum(fixed.values())
    if remaining < 4 * len(flexible):
        for index in flexible:
            widths[index] = 4
        return widths
    if len({round(weights[i], 6) for i in flexible}) == 1:
        each = remaining // len(flexible)
        for index in flexible:
            widths[index] = each
        return widths
    weight_sum = sum(max(0.01, weights[i]) for i in flexible)
    allocated = 0
    for index in flexible:
        value = max(4, int(remaining * max(0.01, weights[index]) / weight_sum))
        widths[index] = value
        allocated += value
    diff = remaining - allocated
    position = 0
    while diff > 0:
        index = flexible[position % len(flexible)]
        widths[index] += 1
        diff -= 1
        position += 1
    while diff < 0:
        index = max(flexible, key=lambda i: widths[i])
        if widths[index] <= 4:
            break
        widths[index] -= 1
        diff += 1
    return widths


def _wrap(text: str, width: int) -> list[str]:
    width = max(1, int(width))
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        if not paragraph:
            lines.append("")
            continue
        line = ""
        used = 0
        for token in _tokens(paragraph):
            cw = 0 if ANSI_RE.fullmatch(token) else char_width(token)
            if used + cw > width and line:
                space = line.rfind(" ")
                if space >= max(1, width // 2):
                    lines.append(line[:space].rstrip())
                    line = line[space + 1:] + token
                    used = display_width(line)
                else:
                    lines.append(line.rstrip())
                    line = token
                    used = cw
            else:
                line += token
                used += cw
        if line or not lines:
            lines.append(line.rstrip())
    return lines or [""]


def _pad(text: str, width: int) -> str:
    return str(text) + " " * max(0, width - display_width(text))


def _auto_widths(headers: list[str], rows: list[list[str]], total: int) -> list[int]:
    columns = len(headers)
    widths: list[int] = []
    for index in range(columns):
        values = [headers[index]] + [row[index] for row in rows if index < len(row)]
        natural = 4
        for value in values:
            for line in str(value).split("\n") or [""]:
                natural = max(natural, display_width(line))
        widths.append(natural)
    while sum(widths) + len(SEPARATOR) * (columns - 1) > total:
        index = max(range(columns), key=lambda item: widths[item])
        if widths[index] <= 6:
            break
        widths[index] -= 1
    return widths


def render_table(headers: Sequence[str], rows: Sequence[Sequence[object]],
                 max_width: int | None = None, indent: int = 2,
                 widths: Sequence[int] | None = None, stream: TextIO | None = None) -> list[str]:
    """渲染对齐表格；行尾不补空格，表头和分隔线在终端里灰显。"""
    headers = [str(item) for item in headers]
    rows = [[str(item) for item in row] for row in rows]
    columns = len(headers)
    if not columns:
        return []

    total = (max_width - indent) if max_width is not None else screen_width(indent)
    total = max(20, total)
    if widths is None:
        widths = _auto_widths(headers, rows, total)
    else:
        widths = [max(4, int(value)) for value in widths]

    lines: list[str] = []
    header_lines = [_wrap(headers[i], widths[i]) for i in range(columns)]
    height = max(len(item) for item in header_lines)
    for line in range(height):
        cells = [
            _pad(header_lines[i][line] if line < len(header_lines[i]) else "", widths[i])
            for i in range(columns)
        ]
        lines.append(paint(SEPARATOR.join(cells).rstrip(), "bold", stream=stream))
    lines.append(paint(SEPARATOR.join("-" * width for width in widths), "dim", stream=stream))

    for row in rows:
        cell_lines = [
            _wrap(row[i] if i < len(row) else "", widths[i])
            for i in range(columns)
        ]
        height = max(len(item) for item in cell_lines)
        for line in range(height):
            cells = [
                _pad(cell_lines[i][line] if line < len(cell_lines[i]) else "", widths[i])
                for i in range(columns)
            ]
            lines.append(SEPARATOR.join(cells).rstrip())

    prefix = " " * max(0, indent)
    return [prefix + line for line in lines]


def print_table(title: str, headers: Sequence[str], rows: Sequence[Sequence[object]],
                file: TextIO | None = None, max_width: int | None = None,
                widths: Sequence[int] | None = None, note: str = "") -> None:
    file = file or sys.stderr
    if title:
        print("", file=file)
        print(paint(title, "bold", stream=file), file=file)
    if not rows:
        print(paint("  （无）", "dim", stream=file), file=file)
    else:
        for line in render_table(headers, rows, max_width=max_width, widths=widths, stream=file):
            print(line, file=file)
    if note:
        print(paint(f"  {note}", "dim", stream=file), file=file)
    file.flush()


def section(title: str, file: TextIO | None = None) -> None:
    file = file or sys.stderr
    print("", file=file)
    print(rule(title, file), file=file, flush=True)


def info(text: str, file: TextIO | None = None) -> None:
    emit(f"  {text}", file=file or sys.stderr)
