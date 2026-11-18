"""字幕分析、翻译、润色的提示词。

组织原则：
- 每条规则在一次请求里只出现一次；各阶段只放和本阶段有关的规则。
- 指令（静态、整次运行不变）放在前面，便于服务商做前缀缓存；批次数据放在最后，
  用 <标签> 包起来，和指令分开。
- system 只写角色和输出格式；翻译取向只由「翻译策略」一段决定，避免互相矛盾。
- JSON 字段名和枚举值保持英文，其余一律中文。
"""

import json

from .languages import language_profile
from .models import LANGUAGE_NAMES

SOURCE_GUIDANCE = {
    "ocr": "这些字幕来自图片字幕 OCR，可能存在视觉识别错误：形近字、假名混淆、漏字、错标点、长音符和促音识别错误、错误断行，以及装饰文字混入。",
    "asr": "这些字幕来自语音识别（ASR），可能存在同音字、音近词、人名地名识别错误、错误分词、口语缩略、不完整句子和拟声词识别错误。",
    "text": "这是文本字幕，不要主动假设存在 OCR 或 ASR 错误。只有在语法明显错误、上下文矛盾或文本自身明显不通时，才提出修正。",
    "auto": "字幕来源未知。只修正有充分上下文依据的明显错误，不要武断地猜测或凭空补充内容。",
}

# 按（来源, 语言）追加的细分提示；未标注语言时只用上面的通用说明。
LANGUAGE_SOURCE_GUIDANCE = {
    ("asr", "ja"): "日语 ASR 常见问题：同音异义词、长音/促音/拨音遗漏、助词（は/が/を/に）误识、汉字转换错误、人名与专有名词读音错误、口语缩略（〜てる/〜ちゃう/〜じゃん）、拟声拟态词误识。明显不合理的字面词要结合上下文判断，不要直接照字面翻译。",
    ("asr", "zh"): "中文 ASR 常见问题：同音字/近音字、多音字、轻声与儿化、网络用语、人名地名、错误分词、语气词丢失。",
    ("asr", "en"): "英语 ASR 常见问题：同音词、缩约形式（如 gonna / I'd）、专有名词和发音相近的人名、口头填充词丢失、标点与断句错误。",
    ("asr", "ko"): "韩语 ASR 常见问题：同音异义、紧音/送气音混淆、助词误识、敬语层级、空格分词错误。",
    ("ocr", "ja"): "日语 OCR 常见问题：假名混淆（シ/ツ、ソ/ン、ク/ワ）、浊音/半浊音、长音符、促音、竖排断行和装饰文字混入。",
    ("ocr", "zh"): "中文 OCR 常见问题：形近字、繁简混用、错标点、漏字、装饰文字混入。",
    ("ocr", "en"): "英语 OCR 常见问题：l/I/1、O/0、rn/m 混淆，单词被拆断，以及零散的杂字符。",
}

FIDELITY_GUIDANCE = {
    "faithful": "完全忠于原文。保持语义、信息量、人物关系、语气、情绪方向和表达强度；不添加、删除或虚构信息。只做必要的语序调整，不追求文采或过度本地化。",
    "natural": "自然表达。在不改变原意、事实、信息量、语气和表达强度的前提下，使用目标语言自然、流畅、符合字幕习惯的表达。允许适度调整语序和句式，但不得凭空添加剧情。",
    "creative": "允许风格化发挥。可以更大胆地调整措辞、节奏、口语感和修辞，但只能改变表达方式，不能改变核心语义、事实、人物关系、情绪方向或原文表达强度，不得虚构人物、动作或剧情。",
}

CORRECTION_TYPES = ("asr", "ocr", "ruby", "punctuation", "segmentation", "term")
CONFIDENCE_LEVELS = ("high", "medium", "low")

OUTPUT_FORMAT = '{"translations":[{"id":"字幕编号","text":"字幕文本"}]}'
ANALYSIS_FORMAT = (
    '{"summary":"……","style":"……",'
    '"corrections":[{"id":"字幕编号","span":"……","type":"asr","original":"……",'
    '"corrected":"……","confidence":"high","reason":"……"}],'
    '"terms":[{"source":"……","target":"……","note":"……"}]}'
)


def _get(mapping: dict[str, str], value: str, kind: str) -> str:
    if value not in mapping:
        raise ValueError(f"不支持的{kind}：{value}")
    return mapping[value]


def source_guidance(source: str, language: str = "") -> str:
    base = _get(SOURCE_GUIDANCE, source, "字幕来源")
    hint = LANGUAGE_SOURCE_GUIDANCE.get((source, (language or "").lower()))
    return f"{base}\n{hint}" if hint else base


def typography_guidance(target: str) -> str:
    return language_profile(target).typography


def source_label(source: str, language: str = "") -> str:
    """源语言写法：用户写了就用；自动识别时优先用文件名标注的语言。"""
    value = (source or "").strip()
    if value.lower() not in ("", "auto", "自动识别", "自动"):
        return value
    name = LANGUAGE_NAMES.get((language or "").lower())
    if name:
        return f"{name}（按文件名标注；如实际内容不同，以实际内容为准）"
    return "自动判断（字幕中可能混合多语言，请按实际内容识别）"


def _section(title: str, *lines: str) -> str:
    body = "\n".join(line for line in lines if line)
    return f"## {title}\n{body}" if body else ""


def _join(*sections: str) -> str:
    return "\n\n".join(section.strip() for section in sections if section and section.strip())


def block(tag: str, value) -> str:
    """数据块：<标签>内容</标签>；列表和字典按 JSON 写出。"""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return f"<{tag}>\n{text}\n</{tag}>"


def system_prompt(stage: str, target: str) -> str:
    if stage == "analysis":
        return ("你是字幕项目的语言分析员：找出源字幕中的识别错误，整理术语表、主题和说话风格，"
                f"供后续分批翻译成{target}时参考。只输出符合 JSON Schema 的 JSON。")
    if stage == "polish":
        return (f"你是专业的{target}字幕校对编辑：在不改变原意的前提下，改进已有译文的自然度、一致性和准确性。"
                "只输出符合 JSON Schema 的 JSON。")
    return f"你是专业字幕译者，把字幕翻译成{target}。只输出符合 JSON Schema 的 JSON。"


def correction_limit(cue_count: int) -> int:
    """纠错条数上限：防止长视频的分析结果撑爆输出、被截断成半截 JSON。"""
    return max(20, min(150, cue_count // 4))


def analysis_guidance(target: str, limit: int) -> str:
    """分析阶段的纠错、术语与主题要求。"""
    return _join(
        _section(
            "纠错要求",
            "- 只标注存在疑问的局部片段；没有问题的字幕不要生成纠错项，也不要逐条复述全文。",
            "- 结合整段上下文、重复表达和相邻字幕判断，可以做有依据的推测，但不要添加新的事实、动作、人物或情节。",
            "- id 只写一个字幕编号；同一处错误跨多条字幕时，按字幕拆成多条，每条写各自的编号。",
            "- span 是该条原文中有问题的片段；original 是该条完整原文；corrected 是修正后的该条原文（仍是源语言，不是译文）。",
            "- type 取值：asr=同音/音近；ocr=形近/漏字；ruby=注音或假名标注；punctuation=标点；segmentation=断句/分词；term=专有名词。",
            "- confidence 取值：high=上下文几乎可以确定；medium=较可能，但存在其他解释；low=只是推测。",
            f"- 最多 {limit} 条；超出时优先保留 high 和影响理解的错误。",
        ),
        _section(
            "术语表要求",
            "- 列出角色名、人名、组织名、作品名、称呼、固定梗、反复出现的专有名词和拟声词；不要漏掉反复出现的称呼。",
            f"- target 只写一个首选的{target}译名；有备选写法或不确定时，写在 note 里。",
        ),
        _section(
            "主题与风格",
            "- summary：用一两句话概括内容和场景。",
            "- style：说话人的语气、口癖、称呼习惯和整体风格，供翻译保持一致。",
        ),
        _section(
            "输出格式",
            f"只返回一个 JSON 对象，不要 Markdown 代码块或说明文字；字段名固定如下：{ANALYSIS_FORMAT}",
            "顶层字段必须是 summary、style、corrections、terms；不要改名为 analysis、glossary、correction，"
            "也不要把 summary/style 嵌套到其他对象里。corrections 和 terms 没有内容时返回空数组 []。",
        ),
    )


def _length_section(target: str) -> str:
    profile = language_profile(target)
    return _section(
        "长度与排版",
        profile.typography,
        f"每条输入带有 dur（显示秒数）。按{profile.reading_speed}的阅读速度控制长度："
        "显示时间短的字幕要更精炼，但不能丢掉信息、语气或称呼。",
    )


def _output_section(target: str, verb: str = "翻译") -> str:
    profile = language_profile(target)
    language_rule = f"text 只用{target}书写"
    if profile.code and profile.code != "zh":
        language_rule += "，不要混入中文用词或中文标点"
    language_rule += "；专有名词按术语表处理。"
    return _section(
        "输出",
        f"严格返回 {OUTPUT_FORMAT}：每个 <输入> 中的 id 恰好一条，顺序一致，text 非空。",
        language_rule,
        f"书写与标点示例（只示范格式，不要套用内容）：{profile.example}" if profile.example else "",
        f"<前文> 和 <后文> 只用于理解语境：不要{verb}它们，也不要把后文内容提前写进本批。",
    )


def _source_section(subtitle_source: str, base_language: str) -> str:
    return _section("来源", source_guidance(subtitle_source, base_language))


def translation_guidance(source: str, fidelity: str, language: str, target: str,
                         *, source_name: str = "", natural_segmentation: bool = True,
                         track_note: str = "") -> str:
    """翻译阶段的静态指令（整次运行不变）。"""
    if natural_segmentation:
        segmentation = (
            "字幕按时间切分，不一定是完整句子。请把相邻字幕当作连续文本理解，可以按"
            f"{target}的语序在相邻字幕之间调整短语或半句话的位置；但每个 id 的译文要对应该时间段说出的内容，"
            "不能把整句挪到别的字幕，也不能留空。"
        )
    else:
        segmentation = "每个 id 只翻译该条字幕自己的内容，不要在字幕之间移动内容。"
    return _join(
        _section("任务",
                 f"把 <输入> 中的字幕从{source_label(source_name, language)}翻译成{target}。",
                 segmentation, track_note),
        _source_section(source, language),
        _section("翻译策略", _get(FIDELITY_GUIDANCE, fidelity, "翻译模式")),
        _length_section(target),
        _section(
            "纠错与术语",
            "- <纠错参考> 只列出局部疑点，不是完整修正版；未列出的字幕按原文翻译。",
            "- confidence=high 的修正直接采用；medium 结合上下文决定；low 只作参考，按原文保守翻译。",
            "- <项目参考> 术语表中的人名、称呼和专有名词按给定译名统一。",
        ),
        _section(
            "表达要求",
            "- 保留原文的拟声词、语气词、口癖和重复强调；重复出现的内容分别保留，不要为了通顺合并。",
            "- 保留原文的表达方式和强度；不确定时保守处理，不要为了通顺补全原文没有的信息。",
        ),
        _output_section(target),
    )


def polish_guidance(source: str, fidelity: str, target: str,
                    *, natural_segmentation: bool = True, track_note: str = "",
                    manual_prompt: str = "") -> str:
    """润色阶段的静态指令（整次运行不变）。润色只带通用来源说明，不需要源语言细分提示。"""
    if natural_segmentation:
        segmentation = "可以在相邻字幕之间微调短语位置让衔接更自然，但不要大幅搬动内容，也不能留空。"
    else:
        segmentation = "每个 id 只润色该条自身，不要在字幕之间移动内容。"
    return _join(
        _section("本次润色要求（优先遵守）", manual_prompt),
        _section("任务",
                 f"校对并润色 <输入> 中已经翻译成{target}的字幕。<原文> 是对应的源字幕，只用于核对语义。",
                 segmentation, track_note),
        _source_section(source, ""),
        _section("翻译策略", _get(FIDELITY_GUIDANCE, fidelity, "翻译模式")),
        _length_section(target),
        _section(
            "润色原则",
            "- 只改确实不自然、生硬、直译腔、语气不符或衔接不好的地方；译文已经自然时保持原样，不做同义替换。",
            "- 发现误译、漏译或与 <原文> 不符时直接修正；<纠错参考> 中 confidence=high 的修正应体现在译文里。",
            "- 统一 <项目参考> 术语表中的译名和称呼。",
            "- 保留口癖、语气词、拟声词、重复强调和说话风格，不要为了简洁删减或合并。",
            "- 保持原文含义与表达强度，不得弱化、净化或删减；不要添加原文没有的信息。",
        ),
        _output_section(target, "润色"),
    )
