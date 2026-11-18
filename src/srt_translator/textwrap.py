"""Wrap translated subtitle text to the target language's display width.

Language-specific widths live in languages.py; this module only knows how to
measure and break text, so adding a language never requires touching it.
"""

import math

from common.textwidth import display_width, fix_line_breaks, is_cjk, split_at_width

from .languages import LanguageProfile, language_profile


def _join_lines(parts: list[str]) -> str:
    out = parts[0]
    for part in parts[1:]:
        if out and part and is_cjk(out[-1]) and is_cjk(part[0]):
            out += part
        else:
            out += " " + part
    return out


def wrap_text(text: str, target: str) -> list[str]:
    """Wrap one cue's text; never returns more than max_lines lines."""
    profile: LanguageProfile = language_profile(target)
    text = " ".join((text or "").replace("\r", " ").replace("\n", " ").split())
    if not text:
        return []

    limit = profile.max_columns
    lines = split_at_width(text, limit)
    if len(lines) > profile.max_lines:
        # 单条过长时按行数均分，宁可略超宽度也不截断内容
        limit = max(limit, math.ceil(display_width(text) / profile.max_lines))
        lines = split_at_width(text, limit)
    if len(lines) > profile.max_lines:
        lines = lines[: profile.max_lines - 1] + [_join_lines(lines[profile.max_lines - 1:])]
    return fix_line_breaks(lines, limit)