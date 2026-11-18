"""显示宽度与折行禁则：终端表格、ASR 字幕、译文折行共用一份实现。"""
from __future__ import annotations

import unicodedata

OPEN_BRACKETS = "「『（【〈《([{“‘"
CLOSE_PUNCT = "」』）】〉》]）」、，。．！？…：；,.;:!?"


def is_cjk(ch: str) -> bool:
    if not ch:
        return False
    o = ord(ch)
    return (
        0x2E80 <= o <= 0x9FFF      # CJK 部首 / 假名 / 统一汉字
        or 0xF900 <= o <= 0xFAFF
        or 0xFF00 <= o <= 0xFF60   # 全角标点
        or 0x3000 <= o <= 0x303F   # CJK 标点
        or 0x3040 <= o <= 0x30FF   # 平假名 / 片假名
        or 0xAC00 <= o <= 0xD7AF   # 韩文
    )


def char_width(ch: str) -> int:
    if is_cjk(ch):
        return 2
    if unicodedata.combining(ch):
        return 0
    ea = unicodedata.east_asian_width(ch)
    return 2 if ea in ("W", "F") else 1


def display_width(text: str) -> int:
    return sum(char_width(ch) for ch in text)


def split_at_width(text: str, max_width: int) -> list[str]:
    """按显示宽度折行；优先在空格处断开，CJK 按字断开。"""
    text = text.strip()
    if not text:
        return []
    if display_width(text) <= max_width:
        return [text]
    pieces: list[str] = []
    cur = ""
    width = 0
    for ch in text:
        cw = char_width(ch)
        if width + cw > max_width and cur.strip():
            cut = -1
            if not is_cjk(ch) and " " in cur:
                pos = cur.rfind(" ")
                if display_width(cur[:pos]) >= max_width // 2:   # 空格太靠左就不在空格处断
                    cut = pos
            if cut > 0:
                pieces.append(cur[:cut].strip())
                cur = cur[cut + 1:] + ch       # 空格已被消费，直接接上当前字符
            else:
                pieces.append(cur.strip())
                cur = ch
            width = display_width(cur)
        else:
            cur += ch
            width += cw
    if cur.strip():
        pieces.append(cur.strip())
    return pieces


def fix_line_breaks(lines: list[str], limit: int) -> list[str]:
    """简单禁则处理：收尾标点不放行首，开括号不放行尾。"""
    for i in range(len(lines) - 1):
        while lines[i + 1] and lines[i + 1][0] in CLOSE_PUNCT:
            moved = lines[i + 1][0]
            if display_width(lines[i]) + char_width(moved) > limit + 2:
                break
            lines[i] += moved
            lines[i + 1] = lines[i + 1][1:]
        while lines[i] and lines[i][-1] in OPEN_BRACKETS:
            moved = lines[i][-1]
            lines[i] = lines[i][:-1]
            lines[i + 1] = moved + lines[i + 1]
    return [line.strip() for line in lines if line.strip()]