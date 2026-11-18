"""识别配置、常量与环境变量覆盖。"""
from __future__ import annotations

import os
import shutil
import sys
import tomllib
from pathlib import Path

from common.env import read_env_file

from .util import log

API_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
MODEL = "microsoft/mai-transcribe-2"
SAMPLE_RATE = 16000
MIN_CHUNK = 20.0
MAX_CHUNK = 60.0
TARGET_CHUNK = 45.0
SILENCE_NOISE = "-32dB"
SILENCE_MIN = 0.35
FALLBACK_CHUNK = 15.0
LINE_WIDTH = 42
MAX_LINES = 2
MIN_CUE = 1.0
MAX_CUE = 7.0
MIN_GAP = 0.06
DEFAULT_WORKERS = 8
DEFAULT_JOBS = 1
MAX_RETRY = 6
PRICE_PER_HOUR = 0.10
PROXY = "system"
# 时间戳粒度：word = 词级（最准）；segment = 分段级；none = 不要时间戳，改用定长切片。
# 接口不接受当前粒度时直接报错并提示改这里，不在运行中自动降级。
TIMESTAMPS = "word"
TIMESTAMP_MODES = {"word": 2, "segment": 1, "none": 0}

ROOT = Path(__file__).resolve().parents[2]
TOOLS_BIN = ROOT / "tools" / "ffmpeg" / "bin"
TEMP_DIR = Path(os.environ.get("TRANSLATE_TEMP_DIR") or (ROOT / "temp"))


def _find_tool(name: str) -> str:
    """按 环境变量 → PATH → 项目内 tools/ffmpeg/bin 的顺序找 ffmpeg/ffprobe。"""
    override = os.environ.get(f"{name.upper()}_BIN")
    if override:
        return override
    found = shutil.which(name)
    if found:
        return found
    local = TOOLS_BIN / f"{name}.exe"
    if local.exists():
        return str(local)
    return name


FFMPEG = _find_tool("ffmpeg")
FFPROBE = _find_tool("ffprobe")
VIDEO_EXTS = {
    ".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".webm", ".m4v", ".ts",
    ".mpg", ".mpeg", ".rmvb", ".rm", ".3gp", ".m2ts", ".vob", ".ogv",
}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff"}


ASR_DEFAULTS = {
    "api_url": API_URL,
    "model": MODEL,
    "workers": DEFAULT_WORKERS,
    "jobs": DEFAULT_JOBS,
    "min_chunk": MIN_CHUNK,
    "max_chunk": MAX_CHUNK,
    "target_chunk": TARGET_CHUNK,
    "silence_noise": SILENCE_NOISE,
    "silence_min": SILENCE_MIN,
    "fallback_chunk": FALLBACK_CHUNK,
    "line_width": LINE_WIDTH,
    "max_lines": MAX_LINES,
    "min_cue": MIN_CUE,
    "max_cue": MAX_CUE,
    "min_gap": MIN_GAP,
    "price_per_hour": PRICE_PER_HOUR,
    "proxy": PROXY,
    "timestamps": TIMESTAMPS,
}


ASR_ENV = {
    "ASR_API_URL": "api_url",
    "ASR_MODEL": "model",
    "ASR_WORKERS": "workers",
    "ASR_PROXY": "proxy",
    "ASR_TIMESTAMPS": "timestamps",
}


ASR_RANGES = {
    "workers": (int, 1, 64),
    "jobs": (int, 1, 32),
    "min_chunk": (float, 1.0, 600.0),
    "max_chunk": (float, 1.0, 600.0),
    "target_chunk": (float, 1.0, 600.0),
    "silence_min": (float, 0.0, 60.0),
    "fallback_chunk": (float, 1.0, 600.0),
    "line_width": (int, 10, 200),
    "max_lines": (int, 1, 6),
    "min_cue": (float, 0.1, 60.0),
    "max_cue": (float, 0.1, 600.0),
    "min_gap": (float, 0.0, 10.0),
    "price_per_hour": (float, 0.0, 1000.0),
}


def load_asr_config(path: Path | None = None, env_path: Path | None = None) -> dict:
    """读取 [asr] 配置；文件不存在或字段缺失时使用默认值。"""
    values = dict(ASR_DEFAULTS)
    path = Path(path) if path else (ROOT / "config.toml")
    env_path = Path(env_path) if env_path else (ROOT / ".env")
    if path.exists():
        try:
            with path.open("rb") as file:
                data = tomllib.load(file)
            section = data.get("asr", {})
            if not isinstance(section, dict):
                section = {}
            for key in ASR_DEFAULTS:
                if key in section:
                    values[key] = section[key]
            # 没有单独的 [asr] proxy 时沿用翻译侧的 [api] proxy，避免只给翻译配了代理。
            api_section = data.get("api", {})
            if ("proxy" not in section
                    and isinstance(api_section, dict) and "proxy" in api_section):
                values["proxy"] = api_section["proxy"]
        except (OSError, tomllib.TOMLDecodeError) as exc:
            print(f"[配置] 读取 {path.name} 的 [asr] 失败：{exc}", file=sys.stderr)
    file_env = read_env_file(env_path)
    for env_name, key in ASR_ENV.items():
        env_value = os.environ.get(env_name) or file_env.get(env_name)
        if env_value:
            values[key] = env_value
    return values


def apply_asr_config(values: dict | None = None) -> None:
    """把配置写入模块级参数；无效项回退到默认值，不中断任务。"""
    global API_URL, MODEL, DEFAULT_WORKERS, DEFAULT_JOBS
    global MIN_CHUNK, MAX_CHUNK, TARGET_CHUNK, SILENCE_NOISE, SILENCE_MIN
    global FALLBACK_CHUNK, LINE_WIDTH, MAX_LINES, MIN_CUE, MAX_CUE, MIN_GAP
    global PRICE_PER_HOUR, PROXY, TIMESTAMPS

    values = load_asr_config() if values is None else values

    def text(key: str) -> str:
        raw = values.get(key, ASR_DEFAULTS[key])
        value = str(raw).strip() if raw is not None else ""
        if value:
            return value
        log(f"[配置] asr.{key} 为空，使用默认 {ASR_DEFAULTS[key]!r}")
        return ASR_DEFAULTS[key]

    def number(key: str):
        cast, low, high = ASR_RANGES[key]
        raw = values.get(key, ASR_DEFAULTS[key])
        try:
            value = cast(raw)
        except (TypeError, ValueError):
            log(f"[配置] asr.{key}={raw!r} 无效，使用默认 {ASR_DEFAULTS[key]}")
            return ASR_DEFAULTS[key]
        if not low <= value <= high:
            log(f"[配置] asr.{key}={value} 超出范围 {low}–{high}，使用默认 {ASR_DEFAULTS[key]}")
            return ASR_DEFAULTS[key]
        return value

    API_URL = text("api_url")
    MODEL = text("model")
    DEFAULT_WORKERS = number("workers")
    DEFAULT_JOBS = number("jobs")
    MIN_CHUNK = number("min_chunk")
    MAX_CHUNK = number("max_chunk")
    TARGET_CHUNK = number("target_chunk")
    SILENCE_NOISE = text("silence_noise")
    SILENCE_MIN = number("silence_min")
    FALLBACK_CHUNK = number("fallback_chunk")
    LINE_WIDTH = number("line_width")
    MAX_LINES = number("max_lines")
    MIN_CUE = number("min_cue")
    MAX_CUE = number("max_cue")
    MIN_GAP = number("min_gap")
    PRICE_PER_HOUR = number("price_per_hour")
    PROXY = text("proxy")
    TIMESTAMPS = text("timestamps").lower()
    if TIMESTAMPS not in TIMESTAMP_MODES:
        log(f"[配置] asr.timestamps={TIMESTAMPS!r} 无效（可选 word / segment / none），"
            f"使用默认 {ASR_DEFAULTS['timestamps']!r}")
        TIMESTAMPS = ASR_DEFAULTS["timestamps"]

    if MIN_CHUNK > MAX_CHUNK:
        log(f"[配置] asr.min_chunk({MIN_CHUNK}) 大于 max_chunk({MAX_CHUNK})，恢复默认切片范围")
        MIN_CHUNK, MAX_CHUNK = ASR_DEFAULTS["min_chunk"], ASR_DEFAULTS["max_chunk"]
    if not MIN_CHUNK <= TARGET_CHUNK <= MAX_CHUNK:
        log(f"[配置] asr.target_chunk({TARGET_CHUNK}) 不在切片范围内，恢复默认值")
        TARGET_CHUNK = ASR_DEFAULTS["target_chunk"]
    if MIN_CUE > MAX_CUE:
        log(f"[配置] asr.min_cue({MIN_CUE}) 大于 max_cue({MAX_CUE})，恢复默认值")
        MIN_CUE, MAX_CUE = ASR_DEFAULTS["min_cue"], ASR_DEFAULTS["max_cue"]
