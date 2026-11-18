from dataclasses import dataclass
from pathlib import Path


@dataclass
class Cue:
    number: str
    timing: str
    text: str


# Standard filename language tokens: ISO 639-1 lowercase.
LANGUAGE_NAMES = {
    "zh": "中文",
    "ja": "日语",
    "en": "英语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "es": "西班牙语",
    "ru": "俄语",
    "pt": "葡萄牙语",
    "it": "意大利语",
    "th": "泰语",
    "vi": "越南语",
    "id": "印尼语",
}

# Standard filename source tokens.
SOURCE_NAMES = {
    "ocr": "OCR 图像字幕",
    "asr": "ASR 语音识别",
    "text": "文本字幕",
}


@dataclass
class Track:
    path: Path
    cues: list[Cue]
    language: str = ""
    source: str = ""

    @property
    def label(self) -> str:
        language = LANGUAGE_NAMES.get(self.language, self.language) if self.language else "语言未标注"
        source = SOURCE_NAMES.get(self.source, self.source) if self.source else "来源未标注"
        return f"{language} / {source}"
