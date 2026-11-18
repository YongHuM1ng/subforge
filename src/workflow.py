#!/usr/bin/env python3
"""
视频 -> 原文 SRT -> 译文 SRT 一体化工作流。

只做「串联」：识别交给 asr 包（入口 asr2srt.py），翻译交给 translate_srt.py，
本文件不复制、不合并两者的任何逻辑。

用法（也可以把视频拖到 拖视频字幕并翻译.cmd 上）：
    .venv\\Scripts\\python.exe workflow.py 视频.mp4 [视频2.mkv ...]
    .venv\\Scripts\\python.exe workflow.py 视频.mp4 --no-translate
    .venv\\Scripts\\python.exe workflow.py 视频.mp4 --target 繁體中文 --no-polish

流程：
    1. ASR：生成 作品名.asr.语言.srt（与翻译工具的文件名标准一致）
    2. 翻译：调用 translate_srt.py，生成 作品名.目标语言.srt
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from asr import config as asr_config
from asr.engine import process_file
from asr.keys import get_api_key
from common.console import emit, format_duration, paint, rule, setup_streams
from common.queue import collect_files, run_serial
from srt_translator.config import load_config
from srt_translator.track import derive_output_path

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="视频 -> ASR 原文 SRT -> 翻译 SRT")
    p.add_argument("videos", nargs="*", type=Path,
                   help="视频或音频文件，可多个；省略时进入队列模式")
    p.add_argument("--config", type=Path, default=ROOT / "config.toml",
                   help="翻译工具的配置文件（默认 config.toml）")
    p.add_argument("--target", help="目标语言，传给 translate_srt.py --target")
    p.add_argument("--model", help="翻译模型，传给 translate_srt.py --model")
    p.add_argument("--analysis-model", help="仅分析阶段使用的模型")
    p.add_argument("--translation-model", help="仅翻译阶段使用的模型")
    p.add_argument("--polish-model", help="仅润色阶段使用的模型")
    p.add_argument("--no-polish", action="store_true", help="跳过润色阶段")
    p.add_argument("--asr-workers", type=int, default=None,
                   help="ASR 并发数（默认取 config.toml 的 [asr] workers）")
    p.add_argument("--tr-workers", type=int, help="翻译并发数，传给 translate_srt.py --workers")
    p.add_argument("--jobs", type=int, default=None,
                   help="同时处理几个视频（默认取 config.toml 的 [asr] jobs）；每个文件内部仍按 asr/tr workers 并发")
    p.add_argument("--quiet", action="store_true", help="翻译阶段只输出批次进度")
    p.add_argument("--txt", action="store_true", help="ASR 额外输出纯文本")
    p.add_argument("--keep-audio", action="store_true", help="保留 ASR 中间音频")
    p.add_argument("--redo-asr", action="store_true",
                   help="即使已有识别 SRT，也重新做 ASR（默认复用已有字幕，跳过识别）")
    p.add_argument("--redo-translate", action="store_true",
                   help="即使已有译文，也重新翻译（默认跳过已翻译的视频）")
    p.add_argument("--no-translate", action="store_true", help="只做识别，不翻译")
    p.add_argument("--dry-run", action="store_true", help="只做识别规划，不调用接口")
    return p


def find_existing_asr_srt(video: Path) -> Path | None:
    """找该视频已有的 ASR 字幕，供失败后重跑时跳过识别。

    识别产物命名为 <base>.asr.srt 或 <base>.asr.<lang>.srt。
    同目录有多份时取最新的一份；要强制重新识别请用 --redo-asr。
    """
    bases = {video.stem}
    lower = video.stem.lower()
    if lower.endswith(".asr"):
        bases.add(video.stem[:-4])
    if ".asr." in lower:
        bases.add(video.stem[:lower.index(".asr.")])
    candidates: dict[Path, Path] = {}
    for base in bases:
        for pattern in (base + ".asr.srt", base + ".asr.*.srt"):
            for path in video.parent.glob(pattern):
                if path.is_file():
                    candidates[path.resolve()] = path
    if not candidates:
        return None
    return max(candidates.values(), key=lambda path: path.stat().st_mtime)


def existing_translation(srt: Path, target: str) -> Path | None:
    """translate_srt.py 默认会写到的译文路径；已存在则返回它。"""
    path = derive_output_path(srt, target)
    return path if path.exists() else None


def run_translation(srt: Path, args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        str(SRC / "translate_srt.py"),
        str(srt),
        "--config", str(args.config),
    ]
    if args.target:
        cmd += ["--target", args.target]
    if args.model:
        cmd += ["--model", args.model]
    for flag, value in (
        ("--analysis-model", args.analysis_model),
        ("--translation-model", args.translation_model),
        ("--polish-model", args.polish_model),
    ):
        if value:
            cmd += [flag, value]
    if args.no_polish:
        cmd += ["--no-polish"]
    if args.tr_workers:
        cmd += ["--workers", str(args.tr_workers)]
    if args.quiet:
        cmd += ["--quiet"]
    emit(f"\n· 调用翻译：{srt.name}")
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def main(argv: list[str]) -> int:
    setup_streams()
    args = build_parser().parse_args(argv)

    if not args.config.exists():
        emit(f"[错误] 找不到翻译配置：{args.config}", file=sys.stderr)
        return 2
    try:
        target = args.target or load_config(args.config)["translation"]["target"]
    except (OSError, ValueError) as exc:
        emit(f"[错误] 读取翻译配置失败：{exc}", file=sys.stderr)
        return 2

    queue_mode = not args.videos
    if queue_mode:
        args.videos = collect_files(
            asr_config.VIDEO_EXTS | asr_config.AUDIO_EXTS,
            base_dir=Path.cwd(),
            title="[队列] 视频转字幕并翻译",
        )
        if not args.videos:
            build_parser().print_help()
            print("用法：把视频/音频拖到启动器上；双击启动器可按队列模式处理多个文件。")
            return 1
        # 队列模式文件之间严格串行；文件内部的 ASR/翻译并发保持不变。
        args.jobs = 1

    asr_config.apply_asr_config(asr_config.load_asr_config(args.config))
    asr_workers = args.asr_workers if args.asr_workers is not None else asr_config.DEFAULT_WORKERS
    jobs = args.jobs if args.jobs is not None else asr_config.DEFAULT_JOBS
    opts = {
        "txt": args.txt,
        "keep_audio": args.keep_audio,
        "workers": max(1, asr_workers),
        "dry_run": args.dry_run,
    }
    key_lock = threading.Lock()
    key_cache: list[str] = []

    def asr_key() -> str:
        """只有真正要做 ASR 时才读取 / 询问识别密钥；全部复用已有字幕时不打扰用户。"""
        if args.dry_run:
            return ""
        with key_lock:
            if not key_cache:
                key_cache.append(get_api_key())
            return key_cache[0]

    def run_one(video: Path) -> bool:
        srt: Path | None = None
        if not args.redo_asr and not args.no_translate and not args.dry_run:
            existing = find_existing_asr_srt(video)
            if existing is not None:
                srt = existing
                emit(f"[复用] 已有识别字幕：{srt.name}（跳过 ASR；要重新识别加 --redo-asr）")

        if srt is None:
            try:
                result = process_file(video, asr_key(), opts)
            except Exception as exc:  # 单个文件失败不影响后续
                emit(f"[错误] {video.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
                return False

            if not result:
                return False
            if args.no_translate or args.dry_run:
                return True

            srt = result.path
            if srt is None:
                return False

        if not args.redo_translate:
            done_path = existing_translation(srt, target)
            if done_path is not None:
                emit(f"[复用] 已有译文：{done_path.name}（跳过翻译；要重新翻译加 --redo-translate）")
                return True

        code = run_translation(srt, args)
        if code != 0:
            emit(f"[错误] 翻译失败（退出码 {code}）：{srt.name}", file=sys.stderr)
            return False
        return True

    if queue_mode:
        return run_serial(args.videos, run_one)

    done, failed = 0, []
    started = time.monotonic()
    jobs = max(1, jobs)
    try:
        if jobs > 1:
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                futures = {pool.submit(run_one, video): video for video in args.videos}
                for future in as_completed(futures):
                    if future.result():
                        done += 1
                    else:
                        failed.append(futures[future].name)
        else:
            for video in args.videos:
                if run_one(video):
                    done += 1
                else:
                    failed.append(video.name)
    except KeyboardInterrupt:
        emit("\n已中断。", file=sys.stderr)
        return 130

    message = f"工作流结束：成功 {done} 个" + (f"，失败 {len(failed)} 个（{', '.join(failed)}）" if failed else "")
    print("")
    print(rule(message, sys.stdout))
    print(paint(f"  用时 {format_duration(time.monotonic() - started)}", "dim", stream=sys.stdout), flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))