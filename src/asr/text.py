"""文本断句、宽度与折行。"""
from __future__ import annotations

import re

from common.textwidth import display_width, fix_line_breaks, is_cjk, split_at_width

from . import config

ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "fig",
    "no", "inc", "ltd", "co", "e.g", "i.e", "a.m", "p.m", "u.s", "u.k",
}


SENT_END_CJK = "。！？…；"


SENT_END_ASCII = ".!?;"


def split_sentences(text: str) -> list[str]:
    """按中英文标点切句，尽量不误切 Mr. / e.g. 之类缩写。"""
    text = text.strip()
    if not text:
        return []
    out: list[str] = []
    cur = ""
    for i, ch in enumerate(text):
        cur += ch
        if ch in SENT_END_CJK:
            out.append(cur)
            cur = ""
            continue
        if ch in SENT_END_ASCII:
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if nxt and not (nxt.isspace() or is_cjk(nxt)):
                continue
            if ch == ".":
                m = re.search(r"([A-Za-z.]+)\.$", cur)
                word = m.group(1).lower().strip(".") if m else ""
                if word in ABBREV or (len(word) == 1 and word.isalpha()):
                    continue
            out.append(cur)
            cur = ""
    if cur.strip():
        out.append(cur)
    return [s.strip() for s in out if s.strip()]


def split_for_cue(text: str, max_w: int) -> list[str]:
    """把一段识别文本切成适合单条字幕的片段。"""
    parts: list[str] = []
    for sent in split_sentences(text):
        if display_width(sent) <= max_w:
            parts.append(sent)
            continue
        for clause in re.split(r"(?<=[，,、])\s*", sent):
            clause = clause.strip()
            if not clause:
                continue
            if display_width(clause) <= max_w:
                parts.append(clause)
            else:
                parts.extend(split_at_width(clause, max_w))
    return parts


def wrap_lines(text: str, max_w: int | None = None, max_lines: int | None = None) -> list[str]:
    max_w = config.LINE_WIDTH if max_w is None else max_w
    max_lines = config.MAX_LINES if max_lines is None else max_lines
    text = text.strip()
    if not text:
        return []
    lines = split_at_width(text, max_w)
    if len(lines) > max_lines:
        # 合并多余行，避免字幕超过 max_lines 行
        lines = lines[: max_lines - 1] + [join_tokens(lines[max_lines - 1:])]
    return fix_line_breaks(lines, max_w)


def join_tokens(tokens: list[str]) -> str:
    text = ""
    for tok in tokens:
        if not tok:
            continue
        if not text:
            text = tok
        elif text.endswith(" ") or tok.startswith(" "):
            text += tok
        elif is_cjk(text[-1]) or is_cjk(tok[0]):
            text += tok
        else:
            text += " " + tok
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    # 去掉中日文字符之间多余的空格
    out = []
    for i, ch in enumerate(text):
        if ch == " " and 0 < i < len(text) - 1 and is_cjk(text[i - 1]) and is_cjk(text[i + 1]):
            continue
        out.append(ch)
    return "".join(out)


def norm_key(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text).lower()
