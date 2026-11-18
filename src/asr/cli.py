"""视频/音频 -> SRT 字幕（默认 OpenRouter: microsoft/mai-transcribe-2）

识别接口支持两种协议，在 config.toml 的 [asr] 段配置：
    transcriptions     OpenAI/OpenRouter 的 /audio/transcriptions（默认）
    chat_completions   把音频 base64 放进 messages 的 OpenAI-compatible 接口

用法：把视频文件拖到 1_视频转字幕.cmd 上（可一次拖多个），或在命令行：
    python asr2srt.py 视频.mp4 [视频2.mkv ...] [选项]

选项：
    --txt         额外输出 .txt 纯文本（方便交给 AI 翻译）
    --keep-audio  保留抽取的音轨与切片（排查问题用）
    --workers N   单个文件内部的分片并发数，默认 8
    --jobs N      同时处理的文件数，默认 1
    --dry-run     只做抽音轨 + 切片规划，不调用接口（不花钱）

工作方式：
    1. ffmpeg 抽取 16k 单声道 wav
    2. 检测静音，把音频切成 20~60 秒、尽量落在静音处的片段
    3. 每片调用一次 ASR；transcriptions 协议请求 verbose_json + 词级时间戳，
       chat_completions 协议只取文本，按定长切片分配时间轴
    4. 时间轴 = 切片起点 + 片内偏移；响应里没有时间戳时改用 15 秒定长切片重新识别
       接口不接受时间戳参数时直接报错，按提示修改 [asr] timestamps（word / segment / none）
    5. 按标点断句、按显示宽度换行，写出 UTF-8(BOM) 的 .srt
       输出命名遵循翻译工具的标准：作品名.asr.语言.srt
       例如 movie.asr.ja.srt（语种取自接口返回，取不到则按文本猜）

计费：$0.10 / 小时音频，按实际音频秒数计，切片多少不影响价格。

配置：项目根目录 config.toml 的 [asr] 段可覆盖接口、模型、并发、切片、排版与计费参数；
环境变量 ASR_API_URL / ASR_MODEL / ASR_WORKERS 优先级更高。"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from common.console import kv_lines, paint, rule, setup_streams
from common.net import resolve_proxy
from common.queue import collect_files, run_serial

from . import config
from .config import apply_asr_config, load_asr_config
from .engine import process_file
from .keys import get_api_key
from .transcribe import ApiError
from .util import log


def _positive(name: str, raw: str) -> int:
    try:
        return max(1, int(raw))
    except ValueError:
        raise SystemExit(f"{name} 需要一个正整数") from None


def parse_args(argv: list[str]) -> tuple[list[Path], dict]:
    opts = {"txt": False, "keep_audio": False, "workers": config.DEFAULT_WORKERS,
            "dry_run": False, "jobs": config.DEFAULT_JOBS}
    files: list[Path] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(__doc__)
            raise SystemExit(0)
        elif a == "--txt":
            opts["txt"] = True
        elif a == "--keep-audio":
            opts["keep_audio"] = True
        elif a == "--dry-run":
            opts["dry_run"] = True
        elif a in ("--workers", "-j"):
            i += 1
            try:
                opts["workers"] = max(1, int(argv[i]))
            except (IndexError, ValueError):
                raise SystemExit("--workers 需要一个正整数") from None
        elif a.startswith("--workers="):
            opts["workers"] = _positive("--workers", a.split("=", 1)[1])
        elif a in ("--jobs", "-J"):
            i += 1
            try:
                opts["jobs"] = max(1, int(argv[i]))
            except (IndexError, ValueError):
                raise SystemExit("--jobs 需要一个正整数") from None
        elif a.startswith("--jobs="):
            opts["jobs"] = _positive("--jobs", a.split("=", 1)[1])
        elif a.startswith("-"):
            raise SystemExit(f"未知参数：{a}")
        else:
            files.append(Path(a))
        i += 1
    return files, opts


def main(argv: list[str]) -> int:
    setup_streams()
    apply_asr_config(load_asr_config())
    files, opts = parse_args(argv)
    proxy = resolve_proxy(config.API_URL, config.PROXY)
    for line in kv_lines([
        ("模型", config.MODEL),
        ("预设", config.PRESET),
        ("协议", config.PROTOCOL),
        ("接口", config.API_URL),
        ("代理", proxy or "直连"),
    ], sys.stdout, indent=0):
        log(line)

    queue_mode = not files
    if queue_mode:
        files = collect_files(
            config.VIDEO_EXTS | config.AUDIO_EXTS,
            base_dir=Path.cwd(),
            title="[队列] 视频/音频转字幕",
        )
    if not files:
        print(__doc__)
        return 1
    if queue_mode:
        # 队列模式文件之间严格串行；文件内部的 workers 并发保持不变。
        opts["jobs"] = 1

    api_key = "" if opts["dry_run"] else get_api_key()

    def run_one(src: Path) -> bool:
        try:
            return bool(process_file(src, api_key, opts))
        except ApiError as e:
            code = e.status
            hint = {
                401: "API Key 无效或已被禁用。",
                402: "余额不足，或并发请求的预扣额度占满了可用额度；可调低 --workers 或充值。",
                403: "Key 被限制 / 达到额度上限。",
                429: "请求过于频繁，稍后重试或调低 --workers。",
                502: "上游服务失败（本次不计费），可重试。",
            }.get(code, "")
            log(f"[错误] HTTP {code}: {e.message()} {hint}")
            return False
        except Exception as e:
            log(f"[错误] {type(e).__name__}: {e}")
            return False

    if queue_mode:
        return run_serial(files, run_one)

    ok = 0
    failed: list[str] = []
    jobs = max(1, int(opts.get("jobs", 1)))
    try:
        if jobs > 1:
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                futures = {pool.submit(run_one, src): src for src in files}
                for future in as_completed(futures):
                    src = futures[future]
                    if future.result():
                        ok += 1
                    else:
                        failed.append(src.name)
        else:
            for src in files:
                if run_one(src):
                    ok += 1
                else:
                    failed.append(src.name)
    except KeyboardInterrupt:
        log("\n已中断。")
        return 130

    log("")
    log(rule("全部结束"))
    summary = paint(f"成功 {ok} 个", "green", stream=sys.stdout)
    if failed:
        summary += "，" + paint(f"失败 {len(failed)} 个", "red", "bold", stream=sys.stdout) + f"（{', '.join(failed)}）"
    log(f"  {summary}")
    return 0 if not failed else 1
