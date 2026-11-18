import asyncio
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from common.console import emit

from .client import ANALYSIS_SCHEMA, TRANSLATION_SCHEMA, ContentFilteredError, LLMClient
from .json_utils import extract_json
from .models import Cue
from .prompts import (
    analysis_guidance,
    block,
    correction_limit,
    polish_guidance,
    source_guidance,
    source_label,
    system_prompt,
    translation_guidance,
)
from .srt import parse_timing

MODERATION_ATTEMPTS = 3
MODERATION_DELAYS = (1.0, 2.0)
STAGE_NAMES = {"analysis": "分析", "translation": "翻译", "polish": "润色"}
_ID_SPLIT_RE = re.compile(r"[,，、;；\s]+")
_ID_RANGE_RE = re.compile(r"^(\d+)\s*[-–—~～]\s*(\d+)$")
MAX_ID_RANGE = 50
ANALYSIS_FIELDS = {"summary": str, "style": str, "corrections": list, "terms": list}


def validate_analysis(value) -> dict:
    """检查分析结果的顶层字段；接口忽略 JSON Schema 时立即报错重试，而不是显示空结果。"""
    if not isinstance(value, dict):
        raise ValueError("分析结果不是 JSON 对象")
    bad = [name for name, expected in ANALYSIS_FIELDS.items()
           if not isinstance(value.get(name), expected)]
    if bad:
        actual = "、".join(str(key) for key in value) or "无"
        raise ValueError(f"分析结果缺少或类型错误的字段：{'、'.join(bad)}（实际字段：{actual}）")
    for name in ("corrections", "terms"):
        if any(not isinstance(item, dict) for item in value[name]):
            raise ValueError(f"分析结果的 {name} 每项必须是 JSON 对象")
    return value


def correction_ids(value) -> set[str] | None:
    """解析纠错项的 id：支持 "12"、"139-140"、"3、5"。无法解析时返回 None（视为全局纠错）。"""
    text = str(value or "").strip().strip("[]#")
    if not text:
        return None
    ids: set[str] = set()
    for part in _ID_SPLIT_RE.split(text):
        part = part.strip().lstrip("#")
        if not part:
            continue
        if part.isdigit():
            ids.add(str(int(part)))
            continue
        match = _ID_RANGE_RE.match(part)
        if not match:
            return None
        lo, hi = sorted((int(match.group(1)), int(match.group(2))))
        if hi - lo > MAX_ID_RANGE:
            return None
        ids.update(str(i) for i in range(lo, hi + 1))
    return ids or None


@dataclass
class TranslatorOptions:
    """翻译流水线的全部配置；避免二十个位置参数静默错位。"""
    source: str = "自动识别"
    target: str = "简体中文"
    batch_size: int = 20
    context: int = 3
    polish: bool = True
    progress: Callable[..., None] | None = None
    global_analysis: bool = True
    max_workers: int = 3
    additional_prompt: str = ""
    pause_before_polish: bool = False
    manual_polish_prompt: str = ""
    natural_segmentation: bool = True
    subtitle_source: str = "auto"
    translation_fidelity: str = "natural"
    base_name: str = ""
    base_label: str = ""
    base_language: str = ""
    stage_models: dict[str, str] = field(default_factory=dict)
    fallback_models: dict[str, str] = field(default_factory=dict)
    fallback_enabled: bool = True


class SubtitleTranslator:
    def __init__(self, client: LLMClient, options: TranslatorOptions | None = None):
        options = options or TranslatorOptions()
        self.client = client
        self.source, self.target = options.source, options.target
        self.batch_size = options.batch_size
        self.context = options.context
        self.max_workers = max(1, options.max_workers)
        self.polish, self.progress = options.polish, options.progress
        self.global_analysis = options.global_analysis
        self.additional_prompt = options.additional_prompt.strip()
        self.pause_before_polish = options.pause_before_polish
        self.manual_polish_prompt = options.manual_polish_prompt.strip()
        self.natural_segmentation = options.natural_segmentation
        self.subtitle_source = options.subtitle_source
        self.translation_fidelity = options.translation_fidelity
        self.base_name = options.base_name or "字幕文件"
        self.base_label = options.base_label or "未标注"
        self.base_language = options.base_language
        self.stage_models = {str(k): str(v) for k, v in options.stage_models.items() if v}
        self.fallback_models = {
            str(k): str(v).strip() for k, v in options.fallback_models.items() if str(v).strip()
        }
        self.fallback_enabled = options.fallback_enabled
        self._active_models: dict[str, str | None] = {}
        self._fallback_stages: set[str] = set()
        self._used_models: dict[str, str | None] = {}
        self.base_cues: list[Cue] = []
        self.reference_compact = ""
        self.analysis_result: dict = {}
        # 翻译阶段的结果；润色失败时调用方可以先把它保存下来，不必整份重翻。
        self.translated_result: list[Cue] | None = None
        self._instruction_cache: dict[str, str] = {}

    def _track_note(self) -> str:
        return f"字幕文件：{self.base_name}（{self.base_label}）。"

    def _analysis_track(self, cues: list[Cue]) -> str:
        body = "\n".join(f"[{cue.number}] {cue.text}" for cue in cues)
        if len(body) > 200_000:
            emit(f"[提示] 全局分析输入约 {len(body):,} 字符，可能超出模型上下文；"
                 "若失败可关闭全局分析（--no-analysis）。", file=sys.stderr)
        return f"{self.base_name} | {self.base_label}\n{body}"

    def _analysis_user(self, cues: list[Cue]) -> str:
        source_section = f"## 来源\n{source_guidance(self.subtitle_source, self.base_language)}"
        parts = [
            self.additional_prompt,
            "## 任务\n分析 <字幕轨> 中的字幕，为后续分批翻译建立参考资料：找出疑似识别错误、整理术语表、"
            "概括主题和说话风格。不要翻译全文。\n"
            "字幕可能包含成人向、暴力或粗俗内容。只做语言分析，不要审查、评价、弱化或回避这些内容。\n"
            f"源语言：{source_label(self.source, self.base_language)}\n目标语言：{self.target}",
            source_section,
            analysis_guidance(self.target, correction_limit(len(cues))),
            block("字幕轨", self._analysis_track(cues)),
        ]
        return "\n\n".join(part.strip() for part in parts if part and part.strip())

    async def analyze(self, cues: list[Cue]) -> None:
        if not self.global_analysis:
            return
        user = self._analysis_user(cues)
        if self.progress:
            self.progress("analyzing", [], [])
        attempts = max(3, int(getattr(self.client, "retries", 3)) + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                reference = await self._call_model(
                    "analysis", "全文分析", system_prompt("analysis", self.target), user,
                    ANALYSIS_SCHEMA, "project-analysis", announce=True)
                result = validate_analysis(extract_json(reference))
                break
            except (ValueError, json.JSONDecodeError) as exc:
                # 长视频的分析结果最容易被截断成半截 JSON；和批次一样重试，而不是直接整次失败。
                last_error = exc
                if attempt < attempts - 1:
                    if self.progress:
                        self.progress("retrying_analysis", cues, None, {
                            "batch": 1, "total": 1, "attempt": attempt + 2, "attempts": attempts,
                            "error": str(exc),
                        })
                    await asyncio.sleep(1 + attempt)
        else:
            raise RuntimeError(f"全文分析失败：{last_error}；可用 --no-analysis 跳过分析") \
                from last_error
        self.analysis_result = result
        self.reference_compact = self._compact_reference()
        self._instruction_cache.clear()
        if self.progress:
            self.progress("analyzed", [], [], self.analysis_result)

    def prepare(self, cues: list[Cue]) -> None:
        """记录本次运行的字幕，供纠错项按批过滤。"""
        self.base_cues = cues

    def set_analysis(self, analysis: dict) -> None:
        """从已保存的分析文件恢复参考资料。"""
        validate_analysis(analysis)
        self._instruction_cache.clear()
        self.analysis_result = analysis
        self.reference_compact = self._compact_reference()

    async def translate_cues(self, cues: list[Cue]) -> list[Cue]:
        """只执行翻译，不做分析和润色。"""
        self.prepare(cues)
        original = [c.text for c in cues]
        batches = [(offset, cues[offset:offset + self.batch_size])
                   for offset in range(0, len(cues), self.batch_size)]
        translated_all = [""] * len(cues)
        results = await self._run_parallel(batches, original, False, translated_all)
        for offset, _batch in batches:
            texts = results.get(offset, [])
            translated_all[offset:offset + len(texts)] = texts
        return [Cue(c.number, c.timing, text) for c, text in zip(cues, translated_all, strict=False)]

    async def polish_cues(self, cues: list[Cue],
                                translated_texts: list[str]) -> list[Cue]:
        """只执行润色；translated_texts 是当前目标语言文本。"""
        self.prepare(cues)
        original = [c.text for c in cues]
        translated_all = list(translated_texts)
        if len(translated_all) < len(cues):
            translated_all += [""] * (len(cues) - len(translated_all))
        batches = [(offset, cues[offset:offset + self.batch_size])
                   for offset in range(0, len(cues), self.batch_size)]
        polish_batches = [
            (offset, [Cue(c.number, c.timing, translated_all[offset + i])
                      for i, c in enumerate(batch)])
            for offset, batch in batches
        ]
        results = await self._run_parallel(polish_batches, original, True, translated_all)
        final_all = translated_all[:]
        for offset, _batch in polish_batches:
            texts = results.get(offset, [])
            final_all[offset:offset + len(texts)] = texts
        return [Cue(c.number, c.timing, text) for c, text in zip(cues, final_all, strict=False)]

    def _pause_before_polish(self) -> None:
        print("\n翻译已完成。现在可以在命令行输入本次润色要求。", flush=True)
        print("直接按 Enter 跳过；输入 quit 可取消润色。", flush=True)
        self.manual_polish_prompt = input("人工润色要求：").strip()
        if self.manual_polish_prompt.lower() == "quit":
            self.polish = False
            print("已取消润色。", flush=True)

    def _model_for(self, stage: str) -> str | None:
        """按阶段取主模型；未配置时返回 None，由 client 使用默认模型。"""
        return self.stage_models.get(stage)

    def _model_display(self, model: str | None) -> str:
        return model or getattr(self.client, "model", "") or "默认模型"

    def _current_model(self, stage: str) -> str | None:
        """当前阶段实际使用的模型；回退后指向回退模型。"""
        if stage in self._active_models:
            return self._active_models[stage]
        return self._model_for(stage)

    def _fallback_for(self, stage: str) -> str | None:
        if not self.fallback_enabled:
            return None
        fallback = self.fallback_models.get(stage)
        if not fallback:
            return None
        primary = self._model_for(stage) or getattr(self.client, "model", "")
        if fallback == primary:
            return None
        return fallback

    def _switch_fallback(self, stage: str) -> str | None:
        """把该阶段切到回退模型；已经切过或未配置时返回 None。"""
        if stage in self._fallback_stages:
            return None
        fallback = self._fallback_for(stage)
        if not fallback:
            return None
        self._fallback_stages.add(stage)
        self._active_models[stage] = fallback
        return fallback

    async def _call_model(self, stage: str, display: str, system: str, user: str,
                          schema: dict | None, label: str, announce: bool = False) -> str:
        """按阶段调用模型；审查/拒答时重试，仍失败则切到回退模型。"""
        failures = 0
        attempt_model = self._current_model(stage)
        while True:
            model = self._current_model(stage)
            if model != attempt_model:
                # 其他并发批次已经触发回退：本批次也按新模型重新计数。
                attempt_model = model
                failures = 0
            if announce:
                if stage in self._fallback_stages:
                    suffix = "（回退）"
                elif failures:
                    suffix = f"（重试 {failures + 1}/{MODERATION_ATTEMPTS}）"
                else:
                    suffix = ""
                emit(f"[模型] {display}：{self._model_display(model)}{suffix}", file=sys.stderr)
            try:
                content = await self.client.chat_json(
                    system, user, schema, label=label, model=model)
                self._used_models[label] = model
                return content
            except ContentFilteredError as exc:
                failures += 1
                detail = str(exc).strip().replace("\n", " ")
                if len(detail) > 160:
                    detail = detail[:160] + "…"
                if failures < MODERATION_ATTEMPTS:
                    delay = MODERATION_DELAYS[min(failures - 1, len(MODERATION_DELAYS) - 1)]
                    emit(
                        f"[审查] {display}：{self._model_display(model)} 被拒绝"
                        f"（{failures}/{MODERATION_ATTEMPTS}）：{detail}；{delay:.1f}s 后重试",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(delay)
                    continue
                emit(
                    f"[审查] {display}：{self._model_display(model)} 被拒绝"
                    f"（{failures}/{MODERATION_ATTEMPTS}）：{detail}",
                    file=sys.stderr,
                )
                fallback = self._switch_fallback(stage)
                if fallback:
                    emit(
                        f"[回退] {STAGE_NAMES.get(stage, stage)}阶段："
                        f"{self._model_display(model)} → {fallback}",
                        file=sys.stderr,
                    )
                    failures = 0
                    attempt_model = fallback
                    continue
                current = self._current_model(stage)
                if current != model:
                    # 其他并发批次刚刚切到回退模型，本批次也跟过去。
                    attempt_model = current
                    failures = 0
                    continue
                if stage in self._fallback_stages:
                    role = "回退模型"
                    reason = "回退模型也连续触发内容审查"
                else:
                    role = "主模型"
                    if not self.fallback_enabled:
                        reason = "模型回退已关闭（[models] fallback_enabled = false）"
                    elif self.fallback_models.get(stage):
                        reason = "回退模型与主模型相同，已跳过"
                    else:
                        reason = "未配置回退模型（[models] fallback）"
                raise RuntimeError(
                    f"{display}失败：{role} {self._model_display(model)} 连续 "
                    f"{MODERATION_ATTEMPTS} 次触发内容审查；{reason}"
                ) from exc

    def _compact_reference(self) -> str:
        """项目参考资料里不再重复全量纠错项（纠错项按批单独注入）。"""
        data = {k: v for k, v in self.analysis_result.items() if k != "corrections"}
        return json.dumps(data, ensure_ascii=False)

    def _relevant_corrections(self, cues: list[Cue], offset: int) -> list[dict]:
        """只带与本批（含前后文）相关的纠错项，避免长视频每个请求都重复全量纠错。

        id 支持范围（"139-140"）与列表（"3、5"）：跨多条字幕的纠错项会进入涉及的每个批次。
        """
        corrections = self.analysis_result.get("corrections") or []
        if not corrections:
            return []
        all_ids = {str(c.number) for c in self.base_cues}
        parsed = [(item, correction_ids(item.get("id")) if isinstance(item, dict) else None)
                  for item in corrections]
        # 模型如果没给出能对应到字幕 ID 的纠错项，就无法按批过滤，全部保留。
        if not any(ids and ids & all_ids for _, ids in parsed):
            return corrections
        lo = max(0, offset - self.context)
        hi = offset + len(cues) + self.context
        allowed = {str(c.number) for c in self.base_cues[lo:hi]}
        return [item for item, ids in parsed if ids is None or ids & allowed]

    def _instructions(self, polishing: bool) -> str:
        """本阶段的静态指令；整次运行不变，缓存起来让每批请求的前缀完全一致。"""
        key = "polish" if polishing else "translation"
        if key not in self._instruction_cache:
            common = dict(natural_segmentation=self.natural_segmentation,
                          track_note=self._track_note())
            if polishing:
                text = polish_guidance(self.subtitle_source, self.translation_fidelity, self.target,
                                       manual_prompt=self.manual_polish_prompt, **common)
            else:
                text = translation_guidance(self.subtitle_source, self.translation_fidelity, self.base_language,
                                            self.target, source_name=self.source, **common)
            static = [self.additional_prompt, text, block("项目参考", self.reference_compact or "{}")]
            self._instruction_cache[key] = "\n\n".join(part.strip() for part in static if part and part.strip())
        return self._instruction_cache[key]

    @staticmethod
    def _duration(cue: Cue) -> float | None:
        try:
            start, end = parse_timing(cue.timing)
        except ValueError:
            return None
        return round(max(0.0, end - start), 1)

    def _items(self, cues: list[Cue], texts: list[str] | None = None) -> list[dict]:
        items = []
        for index, cue in enumerate(cues):
            item: dict = {"id": cue.number, "text": cue.text if texts is None else texts[index]}
            duration = self._duration(cue)
            if duration is not None:
                item["dur"] = duration
            items.append(item)
        return items

    async def _request(self, cues: list[Cue], all_text: list[str], offset: int, polishing: bool,
                       translated_all: list[str], batch_index: int = 1,
                       batch_total: int = 1) -> list[str]:
        corrections = self._relevant_corrections(cues, offset)
        end = offset + len(cues)
        context_source = translated_all if polishing else all_text
        before = context_source[max(0, offset - self.context):offset]
        after = context_source[end:end + self.context]
        # 静态指令在前（前缀缓存），批次数据在后，用标签与指令分开；<输入> 永远放在最后。
        parts = [
            self._instructions(polishing),
            block("批次", f"第 {batch_index}/{batch_total} 批"),
            block("纠错参考", corrections),
            block("前文", before),
            block("后文", after),
        ]
        if polishing:
            parts.append(block("原文", [{"id": c.number, "text": all_text[offset + i]} for i, c in enumerate(cues)]))
        parts.append(block("输入", self._items(cues)))
        user = "\n\n".join(parts)
        if self.progress:
            self.progress("requesting", [], [])
        stage = "polish" if polishing else "translation"
        display = f"{STAGE_NAMES[stage]}批次 {batch_index}/{batch_total}"
        result = extract_json(await self._call_model(
            stage, display, system_prompt(stage, self.target),
            user, TRANSLATION_SCHEMA, f"{stage}-batch-{batch_index}",
        ))
        rows = result.get("translations", []) if isinstance(result, dict) else []
        by_id = {str(row.get("id")): row.get("text") for row in rows if isinstance(row, dict)}
        output = [by_id.get(c.number) for c in cues]
        if len(rows) != len(cues) or any(not isinstance(x, str) or not x.strip() for x in output):
            raise ValueError("模型返回的字幕数量、编号或内容无效")
        return [x.strip() for x in output]

    async def _request_with_retry(self, cues, all_text, offset, polishing, translated_all,
                                  batch_index: int = 1, batch_total: int = 1):
        last_error = None
        attempts = max(3, int(getattr(self.client, "retries", 3)) + 1)
        for attempt in range(attempts):
            try:
                return await self._request(cues, all_text, offset, polishing, translated_all,
                                           batch_index, batch_total)
            except (ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < attempts - 1:
                    if self.progress:
                        self.progress("retrying_polish" if polishing else "retrying_translation", cues, None, {
                            "batch": batch_index, "total": batch_total,
                            "attempt": attempt + 2, "attempts": attempts, "error": str(exc),
                        })
                    await asyncio.sleep(1 + attempt)
        raise RuntimeError(f"批次{'润色' if polishing else '翻译'}失败：{last_error}") from last_error

    async def _run_parallel(self, batches, all_text, polishing, translated_all):
        semaphore = asyncio.Semaphore(self.max_workers)
        result_lock = asyncio.Lock()
        completed: dict[int, tuple[list[Cue], list[str]]] = {}
        next_index = 0
        stage = "polished" if polishing else "translated"
        stage_name = "polish" if polishing else "translation"
        total = len(batches)

        async def emit_completed_in_order() -> None:
            nonlocal next_index
            while next_index < total:
                expected_offset, _ = batches[next_index]
                item = completed.get(expected_offset)
                if item is None:
                    return
                batch, texts = completed.pop(expected_offset)
                if self.progress:
                    result = [Cue(c.number, c.timing, text) for c, text in zip(batch, texts, strict=False)]
                    label = f"{stage_name}-batch-{next_index + 1}"
                    model = self._used_models.get(
                        label, self._current_model(stage_name))
                    self.progress(stage, batch, result, {
                        "batch": next_index + 1,
                        "total": total,
                        "model": self._model_display(model),
                    })
                next_index += 1

        async def run(index, offset, batch):
            async with semaphore:
                texts = await self._request_with_retry(batch, all_text, offset, polishing, translated_all,
                                                       index + 1, total)
                # Requests remain concurrent, but completed batches are emitted in
                # source order. A later batch is buffered until earlier batches finish.
                async with result_lock:
                    completed[offset] = (batch, texts)
                    await emit_completed_in_order()
                return offset, texts

        tasks = [asyncio.create_task(run(i, offset, batch)) for i, (offset, batch) in enumerate(batches)]
        try:
            return dict(await asyncio.gather(*tasks))
        except BaseException:
            # 一个批次最终失败，整次运行就会失败：取消其余批次，不再继续计费。
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def translate_async(self, cues: list[Cue]) -> list[Cue]:
        try:
            return await self._translate(cues)
        finally:
            await self.client.aclose()

    async def _translate(self, cues: list[Cue]) -> list[Cue]:
        self.prepare(cues)
        await self.analyze(cues)
        translated = await self.translate_cues(cues)
        self.translated_result = translated
        if not self.polish:
            return translated
        if self.pause_before_polish:
            self._pause_before_polish()
        if not self.polish:
            return translated
        return await self.polish_cues(cues, [c.text for c in translated])

    def translate(self, cues: list[Cue]) -> list[Cue]:
        return asyncio.run(self.translate_async(cues))
