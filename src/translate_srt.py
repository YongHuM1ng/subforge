#!/usr/bin/env python3
import argparse
import asyncio
import difflib
import json
import os
import sys
import time
from pathlib import Path

from common.console import color_enabled, emit, format_duration, kv_lines, paint, setup_streams
from common.env import load_env_file
from common.io import write_text_atomic
from common.paths import unique_output_path
from srt_translator import (
    Cue,
    LLMClient,
    SubtitleTranslator,
    Track,
    TranslatorOptions,
    analysis_sidecar,
    derive_output_path,
    dump_srt,
    parse_srt,
    parse_track_name,
    renumber_if_duplicated,
    tui,
    wrap_text,
)
from srt_translator.config import apply_environment, load_config, resolve_models, validate_config

ROOT = Path(__file__).resolve().parent.parent
STAGE_LABELS = {"analysis": "分析", "translation": "翻译", "polish": "润色"}



def save_analysis(path: Path, analysis: dict, input_path: Path,
                  source: str, target: str) -> None:
    payload = {
        "version": 1,
        "input": str(input_path.resolve()),
        "source": source,
        "target": target,
        "analysis": analysis,
    }
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    emit(f"  分析已保存：{path.name}", file=sys.stderr)


def load_analysis(path: Path, input_path: Path, target: str) -> dict:
    """读取 save_analysis 写出的分析文件；目标语言不一致时报错。"""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    analysis = data.get("analysis") if isinstance(data, dict) else None
    if not isinstance(analysis, dict):
        raise ValueError(f"分析文件格式无效：{path}；请删除它后重新分析")
    saved_target = data.get("target")
    if saved_target != target:
        raise ValueError(
            f"分析文件的目标语言是 {saved_target}，当前是 {target}；"
            "请使用对应的分析文件，或删除它后重新分析"
        )
    saved_input = data.get("input")
    if saved_input and Path(saved_input).resolve() != input_path.resolve():
        emit(f"[提示] 分析文件来自 {saved_input}，当前输入是 {input_path}", file=sys.stderr)
    return analysis


def load_translated_texts(cues: list[Cue], path: Path) -> list[str]:
    """读取已有译文 SRT，按字幕编号对回原文；只用于跳过翻译、直接润色。"""
    translated = parse_srt(path.read_text(encoding="utf-8-sig"))
    numbers = [cue.number for cue in translated]
    if len(set(numbers)) != len(numbers):
        raise ValueError(f"译文文件 {path.name} 的字幕编号有重复，无法按编号对回原文")
    by_id = {cue.number: cue.text for cue in translated}
    missing = [cue.number for cue in cues if not by_id.get(cue.number, "").strip()]
    if missing:
        preview = "、".join(missing[:5]) + ("…" if len(missing) > 5 else "")
        raise ValueError(
            f"译文文件缺少字幕编号 {preview}；"
            "请确认它是由本工具对同一份输入生成的译文 SRT"
        )
    return [by_id[cue.number] for cue in cues]


def highlight_text(before: str, after: str, before_side: bool) -> str:
    """用黄色高亮润色发生变化的片段。"""
    before = before.replace("\n", " / ")
    after = after.replace("\n", " / ")
    matcher = difflib.SequenceMatcher(None, before, after)
    parts = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        text = before[i1:i2] if before_side else after[j1:j2]
        if not text:
            continue
        if tag == "equal":
            parts.append(text)
        elif tag in ("replace", "delete", "insert") and (
            (before_side and tag != "insert") or (not before_side and tag != "delete")
        ):
            parts.append(f"\033[33m{text}\033[0m")
    return "".join(parts)


def _id_range(cues: list[Cue]) -> str:
    if not cues:
        return ""
    first, last = cues[0].number, cues[-1].number
    return f"#{first}" if first == last else f"#{first}–{last}"


class Reporter:
    """翻译流程的终端输出：阶段标题、批次表格 / 进度行、耗时。"""

    def __init__(self, quiet: bool = False, stream=None):
        self.quiet = quiet
        self.stream = stream
        self.started = time.monotonic()
        self._sections: set[str] = set()

    @property
    def out(self):
        return self.stream or sys.stderr

    def elapsed(self) -> str:
        return format_duration(time.monotonic() - self.started)

    def _section_once(self, key: str, title: str) -> None:
        if key not in self._sections:
            self._sections.add(key)
            tui.section(title, file=self.out)

    def __call__(self, stage: str, original: list[Cue], result: list[Cue] | None,
                 detail: dict | None = None) -> None:
        detail = detail or {}
        out = self.out
        if stage == "analyzing":
            self._section_once("analysis", "全文分析")
            tui.info("正在分析主题、风格、术语和识别错误…", file=out)
        elif stage == "analyzed":
            self._show_analysis(detail)
        elif stage.startswith("retrying"):
            name = {"retrying_polish": "润色", "retrying_analysis": "分析"}.get(stage, "翻译")
            error = str(detail.get("error", "")).replace("\n", " ")[:120]
            emit(f"[重试] {name}批次 {detail.get('batch', '?')}/{detail.get('total', '?')}"
                 f" 返回无效（{error}），第 {detail.get('attempt', '?')}/{detail.get('attempts', '?')} 次",
                 file=out)
        elif stage == "translated":
            self._show_translated(original, result or [], detail)
        elif stage == "polished":
            self._show_polished(original, result or [], detail)

    def _show_analysis(self, analysis: dict) -> None:
        out = self.out
        self._section_once("analysis", "全文分析")
        terms = [
            [row.get("source", ""), row.get("target", ""), row.get("note", "")]
            for row in analysis.get("terms") or [] if isinstance(row, dict)
        ]
        corrections = [
            [row.get("id", ""), row.get("span", row.get("original", "")),
             row.get("corrected", ""), row.get("type", ""),
             row.get("confidence", ""), row.get("reason", "")]
            for row in analysis.get("corrections") or [] if isinstance(row, dict)
        ]
        for line in kv_lines([
            ("主题", analysis.get("summary") or "—"),
            ("风格", analysis.get("style") or "—"),
            ("术语", f"{len(terms)} 条"),
            ("纠错", f"{len(corrections)} 条"),
        ], out):
            print(line, file=out)
        if self.quiet:
            return
        total_width = tui.screen_width()
        tui.print_table("术语表", ["原文", "译文", "备注"], terms,
                        file=out, widths=tui.fit_widths(3, total_width))
        tui.print_table("局部纠错", ["编号", "原文", "修正", "类型", "置信度", "理由"],
                        corrections, file=out,
                        widths=tui.fit_widths(6, total_width, fixed={0: 5, 3: 8, 4: 8},
                                              weights=[0, 1, 1, 0, 0, 2]))

    def _batch_head(self, detail: dict) -> tuple[str, str]:
        batch = f"{detail.get('batch', '?')}/{detail.get('total', '?')}"
        model = detail.get("model") or "默认模型"
        return batch, model

    def _show_translated(self, original: list[Cue], result: list[Cue], detail: dict) -> None:
        out = self.out
        self._section_once("translation", "翻译")
        batch, model = self._batch_head(detail)
        if self.quiet:
            emit(f"[翻译 {batch}] {_id_range(original)} 共 {len(original)} 条 · 模型 {model} · {self.elapsed()}",
                 file=out)
            return
        rows = [
            [source.number, source.text.replace("\n", " / "),
             (target.text if target else "").replace("\n", " / ")]
            for source, target in zip(original, result, strict=False)
        ]
        tui.print_table(f"翻译 {batch} · {_id_range(original)} · 模型 {model} · {self.elapsed()}",
                        ["编号", "原文", "译文"], rows, file=out,
                        widths=tui.fit_widths(3, tui.screen_width(), fixed={0: 5}, weights=[0, 1, 1]))

    def _show_polished(self, original: list[Cue], result: list[Cue], detail: dict) -> None:
        out = self.out
        self._section_once("polish", "润色")
        batch, model = self._batch_head(detail)
        pairs = list(zip(original, result, strict=False))
        changed_pairs = [(before, after) for before, after in pairs
                         if before.text.strip() != (after.text if after else "").strip()]
        changed = len(changed_pairs)
        if self.quiet:
            emit(f"[润色 {batch}] {_id_range(original)} 改动 {changed}/{len(pairs)} 条 · 模型 {model} · "
                 f"{self.elapsed()}", file=out)
            return
        color = color_enabled(out)
        rows = []
        for before, after in changed_pairs:
            after_text = after.text if after else ""
            if color:
                rows.append([before.number, highlight_text(before.text, after_text, True),
                             highlight_text(before.text, after_text, False)])
            else:
                rows.append([before.number, before.text.replace("\n", " / "), after_text.replace("\n", " / ")])
        unchanged = len(pairs) - changed
        title = (f"润色 {batch} · {_id_range(original)} · 改动 {changed}/{len(pairs)} 条"
                 f" · 模型 {model} · {self.elapsed()}")
        if not rows:
            print("", file=out)
            print(paint(title, "bold", stream=out), file=out)
            print(paint("  本批没有改动", "dim", stream=out), file=out, flush=True)
            return
        tui.print_table(title, ["编号", "润色前", "润色后"], rows, file=out,
                        widths=tui.fit_widths(3, tui.screen_width(), fixed={0: 5}, weights=[0, 1, 1]),
                        note=f"其余 {unchanged} 条未改动，已省略" if unchanged else "")


def load_track(path: Path, parser: argparse.ArgumentParser) -> Track:
    if not path.exists():
        parser.error(f"字幕文件不存在：{path}")
    meta = parse_track_name(path)
    if meta.warning:
        emit(f"[提示] {meta.warning}", file=sys.stderr)
    cues, renumbered = renumber_if_duplicated(parse_srt(path.read_text(encoding="utf-8-sig")))
    if renumbered:
        emit(f"[提示] {path.name} 的字幕编号有重复，已按顺序重新编号为 1–{len(cues)}", file=sys.stderr)
    return Track(path=path, cues=cues, language=meta.language, source=meta.source)


def _int_at_least(minimum: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"需要整数，收到 {value!r}") from None
        if number < minimum:
            raise argparse.ArgumentTypeError(f"不能小于 {minimum}，收到 {number}")
        return number
    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="使用 TOML 配置，通过远端 API 翻译并润色 SRT")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, nargs="?", help="输出 SRT；省略时自动生成 作品名.目标语言代码.srt")
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("--source")
    parser.add_argument("--target")
    parser.add_argument("--subtitle-source", choices=("ocr", "asr", "text", "auto"),
                        help="覆盖文件名中的来源标注；默认按文件名，未标注时为 auto")
    parser.add_argument("--fidelity", choices=("faithful", "natural", "creative"))
    parser.add_argument("--model")
    parser.add_argument("--analysis-model", help="仅分析阶段使用的模型")
    parser.add_argument("--translation-model", help="仅翻译阶段使用的模型")
    parser.add_argument("--polish-model", help="仅润色阶段使用的模型")
    parser.add_argument("--endpoint")
    parser.add_argument("--proxy", help="system = 使用系统代理（无则直连，默认）；none = 从不走代理；也可填 http://host:port")
    parser.add_argument("--batch-size", type=_int_at_least(1))
    parser.add_argument("--context", type=_int_at_least(0))
    parser.add_argument("--workers", type=_int_at_least(1))
    parser.add_argument("--debug-api", action="store_true")
    parser.add_argument("--no-analysis", action="store_true")
    parser.add_argument("--no-polish", action="store_true",
                        help="只翻译；会自动保存分析结果，之后可用 --translated 直接润色")
    parser.add_argument("--translated", type=Path,
                        help="已有译文 SRT：跳过翻译，只做润色（原文仍从 input 读取）")
    parser.add_argument("--analysis-file", type=Path,
                        help="读取已保存的分析 JSON；默认自动查找译文旁的 .analysis.json")
    parser.add_argument("--save-analysis", type=Path,
                        help="把本次全文分析保存为 JSON，供之后直接润色")
    parser.add_argument("--quiet", action="store_true", help="只输出批次进度，不逐条打印字幕")
    parser.add_argument("--force", action="store_true", help="输出文件已存在时直接覆盖（默认自动改名）")
    parser.add_argument("--no-wrap", action="store_true", help="不按目标语言宽度自动折行")
    parser.add_argument("--no-fallback", action="store_true",
                        help="本次运行关闭模型回退（审查时仍会重试 3 次）")
    parser.add_argument("--polish-prompt",
                        help="本次润色的附加意见；只对本次运行生效")
    return parser


def wrap_cues(cues: list[Cue], target: str) -> list[Cue]:
    wrapped = []
    for cue in cues:
        lines = wrap_text(cue.text, target)
        wrapped.append(Cue(cue.number, cue.timing, "\n".join(lines) if lines else cue.text))
    return wrapped


def main() -> int:
    setup_streams()
    parser = build_parser()
    args = parser.parse_args()
    load_env_file(ROOT / ".env")
    try:
        config = validate_config(apply_environment(load_config(args.config)))
    except (OSError, ValueError) as exc:
        emit(f"[错误] {exc}", file=sys.stderr)
        return 1
    api, translation, processing = config["api"], config["translation"], config["processing"]
    model = args.model or api["model"]
    api_key = api["api_key"] or os.getenv("LLM_API_KEY")
    if not api_key:
        parser.error("请在项目根目录 .env 设置 LLM_API_KEY"
                     "（或设置同名环境变量 / 在 config.toml 设置 api_key）")
    reporter = Reporter(quiet=args.quiet)
    try:
        base = load_track(Path(args.input), parser)
        cues = base.cues

        source = args.source or translation["source"]
        target = args.target or translation["target"]
        output = args.output or derive_output_path(args.input, target)
        if output.resolve() == args.input.resolve():
            parser.error(f"输出路径不能与输入相同：{output}")
        if not args.force:
            output = unique_output_path(output)
        if args.translated:
            if args.no_polish:
                parser.error("--translated 用于润色已有译文，不能再加 --no-polish")
            if not args.translated.exists():
                parser.error(f"译文文件不存在：{args.translated}")
            if args.translated.resolve() == args.input.resolve():
                parser.error("--translated 不能与输入文件相同")
            if output.resolve() == args.translated.resolve():
                parser.error(f"输出路径不能与 --translated 相同：{output}")
        if args.analysis_file and not args.translated:
            parser.error("--analysis-file 只能和 --translated 一起使用")
        if args.analysis_file and args.no_analysis:
            parser.error("--analysis-file 和 --no-analysis 不能同时使用")
        if args.save_analysis and args.no_analysis:
            parser.error("--save-analysis 需要启用全文分析")

        translated_texts = None
        if args.translated:
            translated_texts = load_translated_texts(cues, args.translated)

        analysis_load_path = args.analysis_file
        if args.translated and analysis_load_path is None:
            candidate = analysis_sidecar(args.translated)
            if candidate.exists():
                analysis_load_path = candidate
        loaded_analysis = None
        if analysis_load_path:
            loaded_analysis = load_analysis(analysis_load_path, args.input, target)

        analysis_save_path = args.save_analysis
        if args.translated and analysis_save_path is None:
            analysis_save_path = analysis_sidecar(args.translated)
        elif args.no_polish and not args.no_analysis and analysis_save_path is None:
            analysis_save_path = analysis_sidecar(output)

        # 来源提示：命令行优先；否则取文件名里的来源标注，未标注时用 auto。
        subtitle_source = args.subtitle_source or base.source or "auto"

        batch_size = args.batch_size or processing["batch_size"]
        context = args.context if args.context is not None else processing["context"]
        polish = (translation["polish"] or bool(args.translated)) and not args.no_polish
        workers = args.workers or processing["max_workers"]
        fidelity = args.fidelity or translation["translation_fidelity"]
        global_analysis = processing["global_analysis"] and not args.no_analysis
        stage_models, fallback_models, fallback_enabled = resolve_models(config, {
            "analysis": args.analysis_model,
            "translation": args.translation_model,
            "polish": args.polish_model,
        }, no_fallback=args.no_fallback)

        client = LLMClient(
            args.endpoint or api["endpoint"],
            api_key,
            model,
            api["timeout"],
            api["retries"],
            api["structured_output"],
            args.debug_api,
            args.proxy or api["proxy"],
            reasoning_effort=api["reasoning_effort"],
        )

        # ---- 任务概览 ----
        if translated_texts is not None:
            steps = ["读取已有分析" if loaded_analysis is not None else ("分析" if global_analysis else "")]
            steps += ["润色"]
        else:
            steps = ["分析" if global_analysis else "", "翻译", "润色" if polish else ""]
        overrides = "，".join(f"{STAGE_LABELS[k]} {v}" for k, v in stage_models.items())
        fallbacks = "，".join(f"{STAGE_LABELS[k]} {v}" for k, v in fallback_models.items())
        if fallbacks and not fallback_enabled:
            fallbacks = "已关闭（[models] fallback_enabled 或 --no-fallback）"
        pairs = [
            ("输入", f"{base.path.name}（{base.label}，{len(cues)} 条）"),
        ]
        if translated_texts is not None:
            pairs.append(("已有译文", args.translated.name))
        if analysis_load_path:
            pairs.append(("已有分析", analysis_load_path.name))
        pairs += [
            ("输出", paint(output.name, "bold", stream=sys.stderr)),
            ("目录", str(output.resolve().parent)),
            ("目标", f"{target} · {fidelity} · 每批 {batch_size} 条 · 并发 {workers}"),
            ("流程", " → ".join(step for step in steps if step)),
            ("模型", model + (f"（{overrides}）" if overrides else "")),
            ("回退", fallbacks),
        ]
        tui.section("翻译任务")
        for line in kv_lines(pairs, sys.stderr):
            print(line, file=sys.stderr)
        sys.stderr.flush()

        def progress(stage: str, original: list[Cue], result: list[Cue] | None,
                     detail: dict | None = None) -> None:
            reporter(stage, original, result, detail)
            if stage == "analyzed" and analysis_save_path and loaded_analysis is None:
                save_analysis(analysis_save_path, detail or {}, args.input, source, target)

        translator = SubtitleTranslator(client, TranslatorOptions(
            source=source,
            target=target,
            batch_size=batch_size,
            context=context,
            polish=polish,
            progress=progress,
            global_analysis=global_analysis,
            max_workers=workers,
            additional_prompt=config["prompts"]["additional"],
            pause_before_polish=translation["pause_before_polish"],
            manual_polish_prompt=args.polish_prompt or "",
            natural_segmentation=translation["natural_segmentation"],
            subtitle_source=subtitle_source,
            translation_fidelity=fidelity,
            base_name=base.path.name,
            base_label=base.label,
            base_language=base.language,
            stage_models=stage_models,
            fallback_models=fallback_models,
            fallback_enabled=fallback_enabled,
        ))
        try:
            if translated_texts is not None:
                async def run_polish() -> list[Cue]:
                    try:
                        translator.prepare(cues)
                        if loaded_analysis is not None:
                            translator.set_analysis(loaded_analysis)
                            reporter("analyzed", [], [], loaded_analysis)
                        elif global_analysis:
                            await translator.analyze(cues)
                        return await translator.polish_cues(cues, translated_texts)
                    finally:
                        await client.aclose()
                result = asyncio.run(run_polish())
            else:
                try:
                    result = translator.translate(cues)
                except Exception:
                    _save_unpolished(translator, output, args, source, target)
                    raise
        finally:
            # translator 内部已尝试关闭；这里兜底，避免异常路径留下 aiohttp session。
            try:
                asyncio.run(client.aclose())
            except Exception:
                pass
        if not args.no_wrap:
            result = wrap_cues(result, target)
        write_text_atomic(output, dump_srt(result), encoding="utf-8-sig")
        usage = client.usage_summary()
        tui.section("完成")
        for line in kv_lines([
            ("输出", paint(str(output), "green", "bold", stream=sys.stderr)),
            ("字幕", f"{len(result)} 条"),
            ("用时", reporter.elapsed()),
            ("用量", usage),
        ], sys.stderr):
            print(line, file=sys.stderr)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print("", file=sys.stderr)
        emit(f"[错误] {exc}", file=sys.stderr)
        return 1


def _save_unpolished(translator: SubtitleTranslator, output: Path, args: argparse.Namespace,
                     source: str, target: str) -> None:
    """润色阶段失败时，把已完成的翻译另存为正式产物，之后可直接拖到 4 号启动器只做润色。"""
    translated = translator.translated_result
    if translated is None or not translator.polish:
        return
    try:
        result = translated if args.no_wrap else wrap_cues(translated, target)
        write_text_atomic(output, dump_srt(result), encoding="utf-8-sig")
        if translator.analysis_result:
            save_analysis(analysis_sidecar(output), translator.analysis_result, args.input, source, target)
    except OSError as exc:
        emit(f"[错误] 保存未润色译文失败：{exc}", file=sys.stderr)
        return
    print("", file=sys.stderr)
    emit(f"[提示] 润色失败，已保存未润色的译文：{output}", file=sys.stderr)
    emit("  修好问题后把它拖到 4_只润色SRT.bat 继续润色，不用重新翻译。", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
