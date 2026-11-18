"""识别结果到字幕条：时间轴、断句、折行与 SRT 输出。"""
from __future__ import annotations

from pathlib import Path

from common.io import write_text_atomic
from common.textwidth import display_width, split_at_width

from . import config
from .text import (
    SENT_END_ASCII,
    SENT_END_CJK,
    join_tokens,
    norm_key,
    split_for_cue,
    wrap_lines,
)


def words_to_segments(words: list) -> list[tuple[float, float, str]]:
    toks: list[tuple[float, float, str]] = []
    for w in words:
        if not isinstance(w, dict):
            continue
        txt = w.get("word")
        if txt is None:
            txt = w.get("text")
        try:
            s = float(w.get("start", 0.0))
            e = float(w.get("end", s))
        except (TypeError, ValueError):
            continue
        if txt is None or not str(txt).strip():
            continue
        toks.append((s, max(e, s), str(txt)))
    if not toks:
        return []

    groups: list[list[tuple[float, float, str]]] = []
    cur: list[tuple[float, float, str]] = []
    cur_w = 0.0
    for tok in toks:
        tok_w = display_width(tok[2])
        if cur:
            gap = tok[0] - cur[-1][1]
            last_char = cur[-1][2].rstrip()[-1:] if cur[-1][2].strip() else ""
            too_wide = cur_w + tok_w > config.LINE_WIDTH * config.MAX_LINES
            too_long = (cur[-1][1] - cur[0][0]) > config.MAX_CUE
            ends_sent = bool(last_char) and (last_char in SENT_END_CJK or last_char in SENT_END_ASCII)
            if gap > 0.65 or ends_sent or too_wide or too_long or len(cur) > 80:
                groups.append(cur)
                cur = []
                cur_w = 0.0
        cur.append(tok)
        cur_w += tok_w
    if cur:
        groups.append(cur)

    out: list[tuple[float, float, str]] = []
    for group in groups:
        text = join_tokens([t[2] for t in group])
        if text:
            out.append((group[0][0], group[-1][1], text))
    return out


def extract_segments(resp: dict) -> list[tuple[float, float, str]]:
    words = resp.get("words")
    if isinstance(words, list) and words:
        segs = words_to_segments(words)
        if segs:
            return segs
    segs = resp.get("segments")
    out: list[tuple[float, float, str]] = []
    if isinstance(segs, list):
        for s in segs:
            if not isinstance(s, dict):
                continue
            txt = str(s.get("text") or "").strip()
            if not txt:
                continue
            try:
                a = float(s.get("start", 0.0))
                b = float(s.get("end", a))
            except (TypeError, ValueError):
                continue
            out.append((a, max(b, a), txt))
    return out


def allocate(parts: list[str], start: float, end: float) -> list[tuple[float, float, str]]:
    if not parts:
        return []
    dur = max(0.05, end - start)
    weights = [max(1.0, float(display_width(p))) for p in parts]
    total = sum(weights)
    res: list[tuple[float, float, str]] = []
    t = start
    for p, w in zip(parts[:-1], weights[:-1], strict=False):
        d = dur * w / total
        res.append((t, t + d, p))
        t += d
    res.append((t, end, parts[-1]))
    return res


def text_to_cues(text: str, start: float, end: float) -> list[tuple[float, float, str]]:
    parts: list[str] = []
    for part in split_for_cue(text, config.LINE_WIDTH * config.MAX_LINES):
        # 一条字幕排版后若仍超过 config.MAX_LINES 行，就拆成多条，而不是硬挤
        lines = split_at_width(part, config.LINE_WIDTH)
        if len(lines) > config.MAX_LINES:
            parts.extend(lines)
        else:
            parts.append(part)
    return allocate(parts, start, end)


def _merge_boundary(prev: tuple, cur: tuple):
    """相邻切片接缝处的重复行（同句被两个切片各识别一次）。"""
    pk = norm_key(prev[2])
    ck = norm_key(cur[2])
    if not pk or not ck or cur[0] - prev[1] > 1.0:
        return None
    if pk == ck:
        keep = prev[2] if len(pk) >= len(ck) else cur[2]
        return (prev[0], max(prev[1], cur[1]), keep)
    if len(pk) >= 6 and len(ck) >= 6 and (ck in pk or pk in ck):
        keep = cur[2] if len(ck) > len(pk) else prev[2]
        return (prev[0], max(prev[1], cur[1]), keep)
    return None


def build_cues(results: list[tuple[float, float, dict]]) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    for cs, ce, resp in sorted(results, key=lambda x: x[0]):
        chunk_cues: list[tuple[float, float, str]] = []
        segs = extract_segments(resp)
        if segs:
            for a, b, txt in segs:
                sa = max(0.0, min(ce - cs, a))
                sb = max(sa, min(ce - cs, b))
                chunk_cues.extend(text_to_cues(txt, cs + sa, cs + sb))
        else:
            text = str(resp.get("text") or "").strip()
            if text:
                chunk_cues.extend(text_to_cues(text, cs, ce))

        if cues and chunk_cues:
            merged = _merge_boundary(cues[-1], chunk_cues[0])
            if merged:
                cues[-1] = merged
                chunk_cues.pop(0)
        cues.extend(chunk_cues)
    return cues


def finalize_cues(cues: list[tuple[float, float, str]], duration: float) -> list[tuple[float, float, str]]:
    cues = [(max(0.0, a), max(a, b), t.strip()) for a, b, t in cues if t.strip()]
    cues.sort(key=lambda c: (c[0], c[1]))

    fixed: list[tuple[float, float, str]] = []
    for a, b, t in cues:
        a = min(a, max(0.0, duration - 0.2))
        b = min(max(b, a + 0.2), duration if duration > 0 else b + config.MAX_CUE)
        if fixed:
            pa, pb, pt = fixed[-1]
            if a < pb + config.MIN_GAP:
                new_end = a - config.MIN_GAP
                if new_end - pa >= 0.5:
                    fixed[-1] = (pa, new_end, pt)
                else:
                    # 前一条短到留不出独立时长：把文本并入当前条，绝不整句丢弃。
                    fixed.pop()
                    a = min(pa, a)
                    t = join_tokens([pt, t])
        fixed.append((a, b, t))

    adjusted: list[tuple[float, float, str]] = []
    for i, (a, b, t) in enumerate(fixed):
        limit = fixed[i + 1][0] - config.MIN_GAP if i + 1 < len(fixed) else (duration or b + config.MAX_CUE)
        if b - a < config.MIN_CUE:
            b = max(b, min(a + config.MIN_CUE, max(a + 0.3, limit)))
        if b - a > config.MAX_CUE + 1.0:
            b = a + config.MAX_CUE + 1.0
        adjusted.append((a, b, t))
    return adjusted


def ts(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: list[tuple[float, float, str]], path: Path) -> None:
    blocks: list[str] = []
    idx = 0
    for a, b, text in cues:
        lines = wrap_lines(text)
        if not lines:
            continue
        idx += 1
        blocks.append(f"{idx}\n{ts(a)} --> {ts(b)}\n" + "\n".join(lines) + "\n\n")
    write_text_atomic(path, "".join(blocks), encoding="utf-8-sig", newline="\n")


def write_txt(cues: list[tuple[float, float, str]], path: Path) -> None:
    text = "".join(cue_text.strip() + "\n" for _, _, cue_text in cues)
    write_text_atomic(path, text, encoding="utf-8-sig", newline="\r\n")
