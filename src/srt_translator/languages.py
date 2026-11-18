"""Per-language display profiles.

新增一个目标语言时，只需要在 PROFILES 里加一条：提示词里的排版规则、阅读速度、
示例句和译文自动折行的宽度都会同步生效。
"""

from dataclasses import dataclass

from .track import target_code


@dataclass(frozen=True)
class LanguageProfile:
    code: str
    name: str
    max_columns: int   # 显示宽度：全角字符按 2 列计算
    max_lines: int
    typography: str    # 写进提示词的排版要求
    reading_speed: str = "按正常阅读速度"   # 写进提示词的长度参考
    example: str = ""  # 一句目标语言的示例，帮助模型锁定输出语言和标点


PROFILES: dict[str, LanguageProfile] = {
    "zh": LanguageProfile(
        code="zh", name="简体中文", max_columns=32, max_lines=2,
        typography="排版：每条字幕最多 2 行，每行不超过 16 个汉字；"
                   "使用中文全角标点（，。！？、：；“”），不要使用英文半角标点或多余空格。",
        reading_speed="每秒约 6–8 个汉字",
        example="“你今天也来了啊，我好开心！”",
    ),
    "ja": LanguageProfile(
        code="ja", name="日语", max_columns=40, max_lines=2,
        typography="排版：每条字幕最多 2 行，每行不超过 20 个全角字符；"
                   "使用日文标点（、。「」！？），不要混用中文简体标点。",
        reading_speed="每秒约 6–8 个全角字符",
        example="「今日も来てくれたんだ、うれしい！」",
    ),
    "en": LanguageProfile(
        code="en", name="英语", max_columns=42, max_lines=2,
        typography="排版：每条字幕最多 2 行，每行不超过 42 个字符；使用英文半角标点。",
        reading_speed="每秒约 15–17 个字符",
        example='"You came again today? I\'m so happy!"',
    ),
    "ko": LanguageProfile(
        code="ko", name="韩语", max_columns=40, max_lines=2,
        typography="排版：每条字幕最多 2 行，每行不超过 20 个全角字符。",
        reading_speed="每秒约 7–9 个音节",
        example="“오늘도 와 줬구나, 정말 기뻐!”",
    ),
}

DEFAULT_PROFILE = LanguageProfile(
    code="", name="未知语言", max_columns=42, max_lines=2,
    typography="排版：每条字幕最多 2 行，单行不超过约 42 个字符宽度。",
)


def language_profile(target: str) -> LanguageProfile:
    """Return the display profile for a target language name or code."""
    raw = (target or "").strip().lower().replace("_", "-")
    code = target_code(target) or raw.split("-")[0]
    return PROFILES.get(code, DEFAULT_PROFILE)
