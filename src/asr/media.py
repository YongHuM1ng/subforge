"""音视频探测、抽音轨、静音切片与工作目录。"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import wave
from pathlib import Path

from . import config


def run_ok(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, **kw)


def probe_has_audio(path: Path) -> bool:
    proc = run_ok([config.FFPROBE, "-v", "error", "-print_format", "json",
                   "-show_streams", "-select_streams", "a:0", str(path)])
    try:
        info = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except Exception:
        return False
    return bool(info.get("streams"))


def extract_wav(src: Path, wav_path: Path) -> None:
    cmd = [
        config.FFMPEG, "-hide_banner", "-nostdin", "-y", "-i", str(src),
        "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-ac", "1", "-ar", str(config.SAMPLE_RATE), "-c:a", "pcm_s16le",
        str(wav_path),
    ]
    proc = run_ok(cmd)
    if proc.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size <= 44:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError("抽取音轨失败：" + ("\n".join(err[-6:]) if err else "未知错误"))


def wav_duration(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as w:
        return w.getnframes() / float(w.getframerate() or config.SAMPLE_RATE)


def detect_silences(wav_path: Path) -> list[tuple[float, float]]:
    cmd = [
        config.FFMPEG, "-hide_banner", "-nostdin", "-i", str(wav_path),
        "-af", f"silencedetect=noise={config.SILENCE_NOISE}:d={config.SILENCE_MIN}",
        "-f", "null", "-",
    ]
    proc = run_ok(cmd)
    text = proc.stderr.decode("utf-8", "replace")
    starts = [float(m) for m in re.findall(r"silence_start:\s*(-?[\d.]+)", text)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*(-?[\d.]+)", text)]
    pairs = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        if e is None:
            continue
        pairs.append((max(0.0, s), max(0.0, e)))
    return pairs


def plan_chunks(duration: float, silences: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if duration <= config.MAX_CHUNK:
        return [(0.0, duration)]

    mids = sorted((s + e) / 2.0 for s, e in silences if e - s >= config.SILENCE_MIN)
    chunks: list[tuple[float, float]] = []
    start = 0.0
    while duration - start > config.MAX_CHUNK:
        lo, hi = start + config.MIN_CHUNK, start + config.MAX_CHUNK
        ideal = start + config.TARGET_CHUNK
        candidates = [m for m in mids if lo <= m <= hi]
        if candidates:
            cut = min(candidates, key=lambda m: abs(m - ideal))
        else:
            cut = min(ideal, start + config.MAX_CHUNK)
        if cut <= start + 1.0:
            cut = start + config.MAX_CHUNK
        chunks.append((start, cut))
        start = cut

    tail = (start, duration)
    if chunks and tail[1] - tail[0] < 3.0:
        chunks[-1] = (chunks[-1][0], duration)
    else:
        chunks.append(tail)

    merged: list[tuple[float, float]] = []
    for a, b in chunks:
        if merged and (b - a) < 3.0 and (b - merged[-1][0]) <= config.MAX_CHUNK * 1.4:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return merged


def fixed_chunks(duration: float, size: float) -> list[tuple[float, float]]:
    out = []
    t = 0.0
    while t < duration:
        out.append((t, min(t + size, duration)))
        t += size
    return out


def slice_wav(src_wav: Path, chunks: list[tuple[float, float]],
              outdir: Path, prefix: str = "c") -> list[Path]:
    paths: list[Path] = []
    with wave.open(str(src_wav), "rb") as r:
        nch = r.getnchannels()
        sw = r.getsampwidth()
        fr = r.getframerate()
        total = r.getnframes()
        for i, (a, b) in enumerate(chunks):
            p = outdir / f"{prefix}{i:03d}.wav"
            sa = max(0, min(total, int(round(a * fr))))
            sb = max(sa, min(total, int(round(b * fr))))
            r.setpos(sa)
            data = r.readframes(sb - sa)
            with wave.open(str(p), "wb") as w:
                w.setnchannels(nch)
                w.setsampwidth(sw)
                w.setframerate(fr)
                w.writeframes(data)
            paths.append(p)
    return paths


def workdir_for() -> Path:
    """每次识别创建独立工作目录，不复用上一次的音频或分片。"""
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="asr2srt-", dir=str(config.TEMP_DIR)))
