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
# 识别协议：
# transcriptions = OpenRouter 的 JSON 音频转写接口
# openai_transcriptions = 标准 OpenAI /audio/transcriptions（multipart 文件上传）
# chat_completions = 把音频 base64 放进 messages 的 OpenAI-compatible Chat Completions
PROTOCOLS = {"transcriptions", "openai_transcriptions", "chat_completions"}
PROTOCOL = "transcriptions"
PRESET = "openrouter"
# 从 .env / 环境变量读取 Key 时使用的变量名；不绑定具体供应商
API_KEY_ENV = "ASR_API_KEY"
API_KEY_HEADER = "Authorization"
API_KEY_PREFIX = "Bearer "
# 仅 chat_completions：input_audio.data 的格式
# data_url = "data:audio/wav;base64,..."（小米 MiMo 等）；base64 = 纯 base64 + format = "wav"（OpenAI 标准）
AUDIO_FORMATS = {"data_url", "base64"}
AUDIO_FORMAT = "data_url"
# 仅 chat_completions：写入 asr_options.language；留空不发送
LANGUAGE = ""
# 时间戳粒度：word = 词级（最准）；segment = 分段级；none = 不要时间戳，改用定长切片。
# 接口不接受当前粒度时直接报错并提示改这里，不在运行中自动降级。
TIMESTAMPS = "word"
TIMESTAMP_MODES = {"word": 2, "segment": 1, "none": 0}

ROOT = Path(__file__).resolve().parents[2]
TOOLS_BIN = ROOT / "tools" / "ffmpeg" / "bin"
TEMP_DIR = Path(os.environ.get("TRANSLATE_TEMP_DIR") or (ROOT / "temp"))


def _find_tool(name: str) -> str:
    """按 环境变量 → PATH → 项目内 tools/ffmpeg/bin 的顺序找 ffmpeg。"""
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
VIDEO_EXTS = {
    ".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".webm", ".m4v", ".ts",
    ".mpg", ".mpeg", ".rmvb", ".rm", ".3gp", ".m2ts", ".vob", ".ogv",
}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff"}


ASR_DEFAULTS = {
    "preset": PRESET,
    "api_url": API_URL,
    "model": MODEL,
    "protocol": PROTOCOL,
    "api_key_env": API_KEY_ENV,
    "api_key_header": API_KEY_HEADER,
    "api_key_prefix": API_KEY_PREFIX,
    "audio_format": AUDIO_FORMAT,
    "language": LANGUAGE,
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


# 预设只覆盖下面写出的字段；显式写在 [asr] 里的字段优先。
ASR_PRESETS = {
    "openrouter": {},
    "openai": {
        "protocol": "openai_transcriptions",
        "api_url": "https://api.openai.com/v1/audio/transcriptions",
        "model": "whisper-1",
        "api_key_env": "ASR_API_KEY",
        "api_key_header": "Authorization",
        "api_key_prefix": "Bearer ",
        "audio_format": "data_url",
        "language": "",
        "timestamps": "word",
    },
    "mimo": {
        "protocol": "chat_completions",
        "api_url": "https://api.xiaomimimo.com/v1/chat/completions",
        "model": "mimo-v2.5-asr",
        "api_key_env": "ASR_API_KEY",
        "api_key_header": "api-key",
        "api_key_prefix": "",
        "audio_format": "data_url",
        "language": "zh",
        "timestamps": "none",
    },
}


ASR_ENV = {
    "ASR_PRESET": "preset",
    "ASR_API_URL": "api_url",
    "ASR_MODEL": "model",
    "ASR_PROTOCOL": "protocol",
    "ASR_API_KEY_ENV": "api_key_env",
    "ASR_API_KEY_HEADER": "api_key_header",
    "ASR_API_KEY_PREFIX": "api_key_prefix",
    "ASR_AUDIO_FORMAT": "audio_format",
    "ASR_LANGUAGE": "language",
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
    """读取 [asr] 配置：先套预设，再叠加显式字段和环境变量。"""
    path = Path(path) if path else (ROOT / "config.toml")
    env_path = Path(env_path) if env_path else (ROOT / ".env")
    data: dict = {}
    section: dict = {}
    if path.exists():
        try:
            with path.open("rb") as file:
                data = tomllib.load(file)
            raw = data.get("asr", {})
            if isinstance(raw, dict):
                section = raw
        except (OSError, tomllib.TOMLDecodeError) as exc:
            print(f"[配置] 读取 {path.name} 的 [asr] 失败：{exc}", file=sys.stderr)

    file_env = read_env_file(env_path)
    env_values: dict = {}
    for env_name, key in ASR_ENV.items():
        env_value = os.environ.get(env_name) or file_env.get(env_name)
        if env_value:
            env_values[key] = env_value

    # 预设的来源优先级：环境变量 > [asr].preset > 默认 openrouter。
    preset = str(env_values.get("preset")
                 or section.get("preset")
                 or ASR_DEFAULTS["preset"]).strip().lower()
    values = dict(ASR_DEFAULTS)
    values.update(ASR_PRESETS.get(preset, {}))
    for key in ASR_DEFAULTS:
        if key in section and key != "preset":
            values[key] = section[key]
    values["preset"] = preset

    # 没有单独的 [asr] proxy 时沿用翻译侧的 [api] proxy，避免只给翻译配了代理。
    api_section = data.get("api", {})
    if ("proxy" not in section and "proxy" not in env_values
            and isinstance(api_section, dict) and "proxy" in api_section):
        values["proxy"] = api_section["proxy"]

    values.update(env_values)
    return values


def apply_asr_config(values: dict | None = None) -> None:
    """把配置写入模块级参数；无效项回退到默认值，不中断任务。"""
    global API_URL, MODEL, DEFAULT_WORKERS, DEFAULT_JOBS
    global MIN_CHUNK, MAX_CHUNK, TARGET_CHUNK, SILENCE_NOISE, SILENCE_MIN
    global FALLBACK_CHUNK, LINE_WIDTH, MAX_LINES, MIN_CUE, MAX_CUE, MIN_GAP
    global PRICE_PER_HOUR, PROXY, TIMESTAMPS
    global PROTOCOL, API_KEY_ENV, API_KEY_HEADER, API_KEY_PREFIX, LANGUAGE
    global AUDIO_FORMAT, PRESET

    values = load_asr_config() if values is None else values
    preset_name = str(values.get("preset", ASR_DEFAULTS["preset"])).strip().lower()
    resolved = dict(ASR_DEFAULTS)
    resolved.update(ASR_PRESETS.get(preset_name, {}))
    resolved.update({key: value for key, value in values.items() if key != "preset"})
    resolved["preset"] = preset_name
    values = resolved

    def text(key: str) -> str:
        raw = values.get(key, ASR_DEFAULTS[key])
        value = str(raw).strip() if raw is not None else ""
        if value:
            return value
        log(f"[配置] asr.{key} 为空，使用默认 {ASR_DEFAULTS[key]!r}")
        return ASR_DEFAULTS[key]

    def string(key: str) -> str:
        """保留原始字符串（api_key_prefix 的尾随空格有意义）。"""
        raw = values.get(key, ASR_DEFAULTS[key])
        return "" if raw is None else str(raw)

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
    PRESET = text("preset").lower()
    if PRESET not in ASR_PRESETS:
        log(f"[配置] asr.preset={PRESET!r} 无效（可选 {' / '.join(ASR_PRESETS)}），"
            "使用默认 openrouter")
        PRESET = "openrouter"
    PROTOCOL = string("protocol").strip().lower()
    if PROTOCOL not in PROTOCOLS:
        log(f"[配置] asr.protocol={PROTOCOL!r} 无效"
            "（可选 transcriptions / openai_transcriptions / chat_completions），"
            "使用默认 transcriptions")
        PROTOCOL = "transcriptions"
    API_KEY_ENV = string("api_key_env").strip() or "ASR_API_KEY"
    if not API_KEY_ENV.isidentifier():
        log(f"[配置] asr.api_key_env={API_KEY_ENV!r} 不是合法变量名，使用 ASR_API_KEY")
        API_KEY_ENV = "ASR_API_KEY"
    API_KEY_HEADER = string("api_key_header").strip() or "Authorization"
    API_KEY_PREFIX = string("api_key_prefix")
    AUDIO_FORMAT = string("audio_format").strip().lower()
    if AUDIO_FORMAT not in AUDIO_FORMATS:
        log(f"[配置] asr.audio_format={AUDIO_FORMAT!r} 无效（可选 data_url / base64），"
            "使用默认 data_url")
        AUDIO_FORMAT = "data_url"
    LANGUAGE = string("language").strip()
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
    if PROTOCOL == "chat_completions" and TIMESTAMPS != "none":
        log("[配置] chat_completions 只返回文本，时间戳按 none 处理（使用固定长度切片）")
        TIMESTAMPS = "none"

    if MIN_CHUNK > MAX_CHUNK:
        log(f"[配置] asr.min_chunk({MIN_CHUNK}) 大于 max_chunk({MAX_CHUNK})，恢复默认切片范围")
        MIN_CHUNK, MAX_CHUNK = ASR_DEFAULTS["min_chunk"], ASR_DEFAULTS["max_chunk"]
    if not MIN_CHUNK <= TARGET_CHUNK <= MAX_CHUNK:
        log(f"[配置] asr.target_chunk({TARGET_CHUNK}) 不在切片范围内，恢复默认值")
        TARGET_CHUNK = ASR_DEFAULTS["target_chunk"]
    if MIN_CUE > MAX_CUE:
        log(f"[配置] asr.min_cue({MIN_CUE}) 大于 max_cue({MAX_CUE})，恢复默认值")
        MIN_CUE, MAX_CUE = ASR_DEFAULTS["min_cue"], ASR_DEFAULTS["max_cue"]
