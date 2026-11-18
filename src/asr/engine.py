"""识别主流程：抽取 → 切片 → 转写 → 字幕。"""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from common.console import format_duration, paint, rule
from common.paths import unique_output_path

from . import config
from .cues import build_cues, finalize_cues, write_srt, write_txt
from .ffmpeg import ensure_ffmpeg
from .media import (
    detect_silences,
    extract_wav,
    fixed_chunks,
    plan_chunks,
    probe_has_audio,
    slice_wav,
    wav_duration,
    workdir_for,
)
from .transcribe import detect_language, run_chunks, summarize
from .util import log


@dataclass
class ProcessResult:
    """识别结果：path=成功产物；dry_run=True 表示预演完成；两者皆空表示失败。"""
    path: Path | None = None
    dry_run: bool = False

    def __bool__(self) -> bool:
        return self.path is not None or self.dry_run


def process_file(src: Path, api_key: str, opts: dict) -> ProcessResult:
    """成功返回产物路径，dry-run 返回 dry_run=True，失败返回空结果。"""

    log("")
    log(rule(f"识别 · {src.name}"))

    if not src.exists():
        log(f"[错误] 文件不存在：{src}")
        return ProcessResult()
    if src.suffix.lower() not in config.VIDEO_EXTS | config.AUDIO_EXTS:
        log(f"[跳过] 不支持的扩展名：{src.suffix}")
        return ProcessResult()
    if not ensure_ffmpeg():
        return ProcessResult()
    if not probe_has_audio(src):
        log("[错误] 这个文件里没有音轨，无法识别。")
        return ProcessResult()

    wd = workdir_for()
    try:
        return _process(src, api_key, opts, wd)
    finally:
        # 成功、失败、中断都清理临时音频，失败重跑本来就从头开始。
        if opts.get("keep_audio"):
            log(f"  临时文件保留在：{wd}")
        else:
            shutil.rmtree(wd, ignore_errors=True)


def _process(src: Path, api_key: str, opts: dict, wd: Path) -> ProcessResult:
    wav_path = wd / "audio16k.wav"
    log("· 抽取音轨…")
    extract_wav(src, wav_path)
    duration = wav_duration(wav_path)
    log(f"· 音频时长 {format_duration(duration)}（{duration:.1f}s）")

    timing_mode = config.TIMESTAMP_MODES.get(config.TIMESTAMPS, 2)
    if timing_mode == 0:
        # [asr] timestamps = "none"：接口不给时间戳，直接用定长短切片保住时间轴精度。
        log(f"· 时间戳：none，按 {config.FALLBACK_CHUNK:.0f} 秒定长切片")
        chunks = fixed_chunks(duration, config.FALLBACK_CHUNK)
    else:
        log("· 检测静音并规划切片…")
        silences = detect_silences(wav_path)
        chunks = plan_chunks(duration, silences)
    log(f"· 切为 {len(chunks)} 片："
        + ", ".join(f"{a:.0f}-{b:.0f}s" for a, b in chunks[:8])
        + (" …" if len(chunks) > 8 else ""))

    if opts.get("dry_run"):
        est = duration / 3600.0 * config.PRICE_PER_HOUR
        log(f"· [dry-run] 预计费用 ${est:.4f}，不调用接口。")
        return ProcessResult(dry_run=True)

    wavs = slice_wav(wav_path, chunks, wd, "c")

    log(f"[模型] ASR：{config.MODEL}（预设 {config.PRESET}，协议 {config.PROTOCOL}，"
        f"时间戳 {config.TIMESTAMPS}，并发 {opts['workers']}）")
    t0 = time.time()

    results = run_chunks(wavs, chunks, api_key, opts["workers"],
                         probe_timing=timing_mode > 0,
                         label=src.name)

    if results is None:
        # 请求本身被接受，只是响应里没有时间戳；不是改请求参数，而是换更短的切片。
        log(f"[提示] 接口没有返回分段/词级时间戳，改用 {config.FALLBACK_CHUNK:.0f} 秒定长切片重新识别；"
            "可在 config.toml 设 [asr] timestamps = \"none\" 跳过这次探测")
        chunks = fixed_chunks(duration, config.FALLBACK_CHUNK)
        wavs = slice_wav(wav_path, chunks, wd, "f")
        results = run_chunks(wavs, chunks, api_key, opts["workers"],
                             probe_timing=False,
                             label=src.name)

    lang = detect_language(results)
    stem = src.stem
    base = stem
    if lang and base.lower().endswith(f".{lang}"):
        base = base[: -(len(lang) + 1)]
    if base.lower().endswith(".asr"):
        base = base[:-4]
    tag = f".asr.{lang}" if lang else ".asr"
    # 与翻译侧一致：同名文件不静默覆盖，自动改名 movie.asr.ja.2.srt。
    out_srt = unique_output_path(src.with_name(base + tag + ".srt"))
    out_txt = out_srt.with_suffix(".txt")
    log(f"· 识别语言：{lang or '未知（文件名不加语种）'}")

    cues = finalize_cues(build_cues(results), duration)
    if not cues:
        log("[提示] 没有识别到任何语音内容，未生成字幕。")
        return ProcessResult()

    write_srt(cues, out_srt)
    if opts.get("txt"):
        write_txt(cues, out_txt)

    secs, tokens, cost = summarize(results)
    log("")
    log(f"[完成] {paint(out_srt.name, 'bold')}（{len(cues)} 条字幕，{format_duration(duration)} 音频）")
    if opts.get("txt"):
        log(f"  纯文本：{out_txt.name}")
    log(f"  用量 ≈ {format_duration(secs or duration)} 音频 · {tokens:,.0f} tokens · ${cost:.4f}")
    log(f"  耗时 {format_duration(time.time() - t0)}")

    return ProcessResult(path=out_srt)
