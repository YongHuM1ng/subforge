"""Parse the unified subtitle filename standard: 作品名.来源.语言.srt."""

import re
from dataclasses import dataclass
from pathlib import Path

from .models import LANGUAGE_NAMES, SOURCE_NAMES

# Non-standard aliases used only to detect and warn about filenames that do not
# follow 作品名.语言.来源.srt. They are NOT accepted as valid metadata.
LANGUAGE_ALIASES = {
    "jp", "jap", "eng", "chi", "chs", "cht", "cn", "tc", "kr", "kor",
    "fre", "fra", "ger", "deu", "spa", "rus", "por", "ita", "tha", "vie", "ind",
}
SOURCE_ALIASES = {"stt", "vad", "pgs", "sdh", "cc", "hc"}


@dataclass
class TrackMeta:
    language: str = ""
    source: str = ""
    warning: str = ""


def _looks_like_metadata(token: str) -> bool:
    lowered = token.lower()
    return (
        lowered in LANGUAGE_NAMES
        or lowered in SOURCE_NAMES
        or lowered in LANGUAGE_ALIASES
        or lowered in SOURCE_ALIASES
        or lowered.startswith("whisper")
    )


def _strip_collision_suffix(tokens: list[str]) -> list[str]:
    """去掉自动改名产生的序号：movie.asr.ja.2.srt -> movie.asr.ja。

    只在序号紧跟在标准来源/语言标记之后时才剥离，避免误伤
    movie.2024.zh.srt 这类以数字结尾的作品名。
    """
    if (len(tokens) >= 2 and tokens[-1].isdigit()
            and tokens[-2].lower() in (set(LANGUAGE_NAMES) | set(SOURCE_NAMES))):
        return tokens[:-1]
    return tokens


def parse_track_name(path: Path) -> TrackMeta:
    """Read language/source metadata from the filename.

    Standard: 作品名.来源.语言.srt (separator: dot, order: source then language,
    both optional). Anything else is reported as a warning and treated as
    unlabeled.
    """
    name = path.name
    if not name.lower().endswith(".srt"):
        return TrackMeta(warning=f"{name} 不是 .srt 文件，将按“未标注”处理。")

    tokens = _strip_collision_suffix(name[:-4].split("."))
    language = ""
    source = ""

    if tokens and tokens[-1].lower() in LANGUAGE_NAMES:
        language = tokens[-1].lower()
        tokens = tokens[:-1]
    if tokens and tokens[-1].lower() in SOURCE_NAMES:
        source = tokens[-1].lower()
        tokens = tokens[:-1]

    tail = tokens[-1] if tokens else ""
    parsed = bool(language or source)
    # Metadata in the wrong position (e.g. movie.ja.asr) or a non-standard alias
    # (e.g. movie.whisper3.ja).
    misplaced = _looks_like_metadata(tail)
    # A combined, non-standard token such as whisper3_ja when nothing was parsed.
    combined = not parsed and "_" in tail
    if misplaced or combined:
        return TrackMeta(
            warning=(
                f"{name} 不符合命名标准「作品名.来源.语言.srt」，将按“未标注”处理。"
                f"标准示例：movie.asr.ja.srt"
            )
        )
    return TrackMeta(language=language, source=source)


# Target language -> filename code used for the translated output.
TARGET_CODES = {
    "zh": "zh", "中文": "zh", "简体中文": "zh", "繁体中文": "zh", "中文简体": "zh", "中文繁体": "zh", "chinese": "zh",
    "簡體中文": "zh", "繁體中文": "zh", "正體中文": "zh", "中文繁體": "zh", "中文簡體": "zh",
    "简中": "zh", "繁中": "zh",
    "simplified chinese": "zh", "traditional chinese": "zh",
    "ja": "ja", "日语": "ja", "日文": "ja", "japanese": "ja",
    "en": "en", "英语": "en", "英文": "en", "english": "en",
    "ko": "ko", "韩语": "ko", "韩文": "ko", "korean": "ko",
    "fr": "fr", "法语": "fr", "法文": "fr", "french": "fr",
    "de": "de", "德语": "de", "德文": "de", "german": "de",
    "es": "es", "西班牙语": "es", "spanish": "es",
    "ru": "ru", "俄语": "ru", "russian": "ru",
    "pt": "pt", "葡萄牙语": "pt", "portuguese": "pt",
    "it": "it", "意大利语": "it", "italian": "it",
    "th": "th", "泰语": "th", "thai": "th",
    "vi": "vi", "越南语": "vi", "vietnamese": "vi",
    "id": "id", "印尼语": "id", "indonesian": "id",
}


def target_code(target: str) -> str:
    """Return a filename language code for the target language, or '' if unknown."""
    key = " ".join(target.strip().lower().replace("_", "-").split())
    if key in TARGET_CODES:
        return TARGET_CODES[key]
    if len(key) == 2 and key.isalpha():
        return key
    # BCP 47 写法：zh-TW / zh-Hant / pt-BR -> 取主语言代码
    match = re.fullmatch(r"([a-z]{2})(-[a-z0-9]{2,8})+", key)
    if match:
        return match.group(1)
    return ""


def output_stem(path: Path) -> str:
    """Return the work name, with trailing standard language/source tokens removed.

    e.g. 26.09 兔田佩克拉.asr.ja.srt -> 26.09 兔田佩克拉
         kaguya.en.srt              -> kaguya
    """
    name = path.name
    stem = name[:-4] if name.lower().endswith(".srt") else path.stem
    tokens = _strip_collision_suffix(stem.split("."))
    if tokens and tokens[-1].lower() in LANGUAGE_NAMES:
        tokens = tokens[:-1]
    if tokens and tokens[-1].lower() in SOURCE_NAMES:
        tokens = tokens[:-1]
    return ".".join(tokens) if tokens else path.stem


def derive_output_path(input_path: Path, target: str) -> Path:
    """Build the output path: 作品名.<目标语言代码>.srt, keeping the input directory."""
    stem = output_stem(input_path) or input_path.stem or "output"
    code = target_code(target)
    suffix = f"{code}.srt" if code else "translated.srt"
    candidate = input_path.with_name(f"{stem}.{suffix}")
    if candidate.resolve() == input_path.resolve():
        candidate = input_path.with_name(f"{stem}.translated.srt")
    return candidate


_POLISHED_RE = re.compile(r"\.polished(?:\.\d+)?$", re.IGNORECASE)


def translation_stem(path: Path) -> str:
    """去掉润色产物后缀：movie.zh.polished.2.srt -> movie.zh。"""
    stem = path.name[:-4] if path.name.lower().endswith(".srt") else path.stem
    return _POLISHED_RE.sub("", stem)


def analysis_sidecar(path: Path) -> Path:
    """译文对应的分析文件：movie.zh.srt / movie.zh.polished.srt -> movie.zh.analysis.json。"""
    return path.with_name(translation_stem(path) + ".analysis.json")


def polished_output(path: Path) -> Path:
    """润色输出路径：movie.zh.srt / movie.zh.polished.srt -> movie.zh.polished.srt（已存在时由调用方改名）。"""
    return path.with_name(translation_stem(path) + ".polished.srt")
