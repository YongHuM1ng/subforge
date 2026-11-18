import re

from .models import Cue

TIMING_RE = re.compile(r"^\s*\d{2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[,.]\d{3}")
_TIME_RE = re.compile(r"(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})")


def parse_srt(content: str) -> list[Cue]:
    # 兼容带 BOM 的 UTF-8 字幕（本工具输出即为 utf-8-sig）。
    content = content.lstrip("\ufeff")
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").strip())
    cues = []
    for block in blocks:
        lines = block.splitlines()
        timing_index = next((i for i, line in enumerate(lines) if TIMING_RE.match(line)), None)
        if timing_index is None or timing_index == 0 or timing_index + 1 >= len(lines):
            continue
        cues.append(Cue(
            lines[timing_index - 1].strip(),
            lines[timing_index].strip(),
            "\n".join(lines[timing_index + 1:]),
        ))
    if not cues:
        raise ValueError("输入文件中没有有效的 SRT 字幕")
    return cues


def renumber_if_duplicated(cues: list[Cue]) -> tuple[list[Cue], bool]:
    """编号重复（常见于拼接过的字幕）时按顺序重新编号为 1..n。

    翻译请求、纠错项和润色回填都按编号对应；编号重复会让两条字幕拿到同一句译文。
    返回 (字幕, 是否重新编号)。
    """
    numbers = [cue.number for cue in cues]
    if len(set(numbers)) == len(numbers):
        return cues, False
    return [Cue(str(index), cue.timing, cue.text) for index, cue in enumerate(cues, 1)], True


def dump_srt(cues: list[Cue]) -> str:
    return "\n\n".join(f"{c.number}\n{c.timing}\n{c.text}" for c in cues) + "\n"


def parse_timing(timing: str) -> tuple[float, float]:
    """Return (start, end) in seconds for a SRT timing line."""
    matches = _TIME_RE.findall(timing)
    if len(matches) < 2:
        raise ValueError(f"无法解析时间轴：{timing}")

    def to_seconds(parts: tuple[str, str, str, str]) -> float:
        hours, minutes, seconds, millis = parts
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000

    return to_seconds(matches[0]), to_seconds(matches[1])
