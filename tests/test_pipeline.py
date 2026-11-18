import asyncio
import io
import json
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from srt_translator.client import ContentFilteredError
from srt_translator.models import Cue
from srt_translator.pipeline import SubtitleTranslator, TranslatorOptions, correction_ids
from tests._prompt import batch_items

ANALYSIS = {
    "summary": "test",
    "style": "neutral",
    "corrections": [
        {"id": "2", "span": "x", "type": "asr", "original": "a", "corrected": "b", "confidence": "high", "reason": "r"},
        {"id": "99", "span": "y", "type": "asr", "original": "c", "corrected": "d", "confidence": "low", "reason": "r"},
    ],
    "terms": [],
}


class FakeClient:
    retries = 1
    model = "primary"

    def __init__(self):
        self.calls: list[tuple[str, str | None, str]] = []

    async def chat_json(self, system, user, schema=None, label="request", model=None):
        self.calls.append((label, model, user))
        if label == "project-analysis":
            return json.dumps(ANALYSIS, ensure_ascii=False)
        data = batch_items(user)
        return json.dumps({"translations": [
            {"id": str(item["id"]), "text": f"译文{item['id']}"} for item in data
        ]}, ensure_ascii=False)

    async def aclose(self):
        pass


class ModeratingClient(FakeClient):
    """前 N 次匹配 label 的请求抛审查错误，之后正常返回。"""

    def __init__(self, label_prefix: str = "translation", failures: int = 3):
        super().__init__()
        self.label_prefix = label_prefix
        self.remaining = failures
        self.models: list[tuple[str, str | None]] = []

    async def chat_json(self, system, user, schema=None, label="request", model=None):
        self.models.append((label, model))
        if label.startswith(self.label_prefix) and self.remaining > 0:
            self.remaining -= 1
            raise ContentFilteredError("moderated", model=model)
        return await super().chat_json(system, user, schema, label, model)


async def _no_sleep(*args, **kwargs):
    return None


def make_translator(client, **overrides):
    options = dict(
        batch_size=2, context=1, polish=True, global_analysis=True, max_workers=2,
        subtitle_source="asr", translation_fidelity="natural",
        base_name="movie.asr.ja.srt", base_label="日语 / ASR",
        base_language="ja",
    )
    options.update(overrides)
    return SubtitleTranslator(
        client, TranslatorOptions(source="自动识别", target="简体中文", **options))


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.cues = [Cue(str(i + 1), f"00:00:0{i},000 --> 00:00:0{i+1},000", f"原文{i + 1}")
                     for i in range(5)]

    def test_stage_models_are_used(self):
        client = FakeClient()
        translator = make_translator(client, stage_models={
            "analysis": "small-model",
            "translation": "big-model",
            "polish": "mid-model",
        })
        result = translator.translate(self.cues)
        self.assertEqual(len(result), 5)
        by_label = {label: model for label, model, _ in client.calls}
        self.assertEqual(by_label["project-analysis"], "small-model")
        self.assertEqual(by_label["translation-batch-1"], "big-model")
        self.assertEqual(by_label["polish-batch-1"], "mid-model")

    def test_prompt_uses_batch_position_and_language_hint(self):
        client = FakeClient()
        make_translator(client).translate(self.cues)
        analysis = next(user for label, _, user in client.calls if label == "project-analysis")
        translations = [user for label, _, user in client.calls if label.startswith("translation")]
        self.assertIn("日语 ASR 常见问题", analysis)
        self.assertTrue(all("<批次>\n第 " in user for user in translations))

    def test_corrections_are_filtered_per_batch(self):
        client = FakeClient()
        make_translator(client).translate(self.cues)
        translations = [user for label, _, user in client.calls if label.startswith("translation")]
        self.assertIn('"id": "2"', translations[0])
        self.assertNotIn('"id": "99"', translations[0])
        self.assertNotIn('"id": "2"', translations[2])
        self.assertNotIn('"id": "99"', translations[2])

    def test_range_ids_reach_every_batch_they_cover(self):
        client = FakeClient()
        translator = make_translator(client)
        translator.prepare(self.cues)
        translator.set_analysis({**ANALYSIS, "corrections": [
            {"id": "4-5", "span": "z", "type": "asr", "original": "e", "corrected": "f",
             "confidence": "high", "reason": "r"},
        ]})
        # batch_size=2, context=1：第 2 批（3–4）和第 3 批（5）都应拿到 4-5 这一条。
        self.assertEqual(len(translator._relevant_corrections(self.cues[2:4], 2)), 1)
        self.assertEqual(len(translator._relevant_corrections(self.cues[4:5], 4)), 1)
        self.assertEqual(len(translator._relevant_corrections(self.cues[0:2], 0)), 0)

    def test_correction_ids_parsing(self):
        self.assertEqual(correction_ids("12"), {"12"})
        self.assertEqual(correction_ids("139-140"), {"139", "140"})
        self.assertEqual(correction_ids("3、5"), {"3", "5"})
        self.assertEqual(correction_ids("#007"), {"7"})
        self.assertIsNone(correction_ids(""))
        self.assertIsNone(correction_ids("全篇"))
        self.assertIsNone(correction_ids("1-999"))

    def test_batch_prompt_layout(self):
        client = FakeClient()
        make_translator(client).translate(self.cues)
        user = next(user for label, _, user in client.calls if label == "translation-batch-2")
        # 静态指令在前，<输入> 在最后，并带有显示时长。
        self.assertLess(user.index("## 任务"), user.index("<批次>"))
        self.assertTrue(user.rstrip().endswith("</输入>"))
        self.assertEqual(batch_items(user)[0]["dur"], 1.0)
        self.assertEqual(user.count("日语 ASR 常见问题"), 1)
        first = next(user for label, _, user in client.calls if label == "translation-batch-1")
        self.assertEqual(first[:first.index("<批次>")], user[:user.index("<批次>")],
                         "各批次的静态前缀必须完全一致，便于前缀缓存")

    def test_analysis_prompt_states_source_once(self):
        client = FakeClient()
        make_translator(client).translate(self.cues)
        analysis = next(user for label, _, user in client.calls if label == "project-analysis")
        self.assertEqual(analysis.count("这些字幕来自语音识别"), 1)
        self.assertNotIn("翻译策略", analysis)
        self.assertIn("源语言：日语", analysis)

    def test_analysis_retries_wrong_shape(self):
        class WrongShape(FakeClient):
            async def chat_json(self, system, user, schema=None, label="request", model=None):
                if label == "project-analysis":
                    self.calls.append((label, model, user))
                    return json.dumps({"analysis": {"summary": "x", "style": "y"},
                                       "glossary": [], "correction": []}, ensure_ascii=False)
                return await super().chat_json(system, user, schema, label, model)

        client = WrongShape()
        with patch("srt_translator.pipeline.asyncio.sleep", _no_sleep), \
                self.assertRaises(RuntimeError) as ctx:
            make_translator(client).translate(self.cues)
        self.assertIn("缺少或类型错误的字段", str(ctx.exception))
        self.assertEqual([label for label, _, _ in client.calls].count("project-analysis"), 3)

    def test_set_analysis_rejects_wrong_shape(self):
        translator = make_translator(FakeClient())
        with self.assertRaises(ValueError) as ctx:
            translator.set_analysis({"analysis": {"summary": "x"}, "glossary": []})
        self.assertIn("summary、style、corrections、terms", str(ctx.exception))

    def test_analysis_retries_invalid_json(self):
        class Flaky(FakeClient):
            broken = 2

            async def chat_json(self, system, user, schema=None, label="request", model=None):
                if label == "project-analysis" and self.broken:
                    self.broken -= 1
                    self.calls.append((label, model, user))
                    return '{"summary": "截断'
                return await super().chat_json(system, user, schema, label, model)

        client = Flaky()
        with patch("srt_translator.pipeline.asyncio.sleep", _no_sleep):
            make_translator(client).translate(self.cues)
        self.assertEqual([label for label, _, _ in client.calls].count("project-analysis"), 3)

    def test_second_run_requests_again(self):
        first = FakeClient()
        make_translator(first).translate(self.cues)
        second = FakeClient()
        result = make_translator(second).translate(self.cues)
        self.assertTrue(second.calls)
        self.assertEqual(len(result), 5)

    def test_polish_only_skips_analysis_and_translation(self):
        client = FakeClient()
        translator = make_translator(client)
        translator.set_analysis(ANALYSIS)
        translated = [f"旧译{i + 1}" for i in range(5)]
        result = asyncio.run(translator.polish_cues(self.cues, translated))
        self.assertEqual(len(result), 5)
        labels = [label for label, _, _ in client.calls]
        self.assertTrue(labels)
        self.assertTrue(all(label.startswith("polish") for label in labels))

    def test_manual_polish_prompt_is_included(self):
        client = FakeClient()
        translator = make_translator(client, manual_polish_prompt="保留关西腔")
        translator.set_analysis(ANALYSIS)
        translated = [f"旧译{i + 1}" for i in range(5)]
        asyncio.run(translator.polish_cues(self.cues, translated))
        polish_users = [user for label, _, user in client.calls if label.startswith("polish")]
        self.assertTrue(polish_users)
        self.assertTrue(all("保留关西腔" in user for user in polish_users))

    def test_logs_model_for_each_batch(self):
        client = FakeClient()
        events: list[tuple[str, str]] = []

        def progress(stage, original, result, detail=None):
            if stage in ("translated", "polished"):
                events.append((stage, detail.get("model")))

        stream = io.StringIO()
        with redirect_stderr(stream):
            make_translator(client, max_workers=1, progress=progress).translate(self.cues)
        self.assertIn("[模型] 全文分析：primary", stream.getvalue())
        self.assertEqual([model for stage, model in events if stage == "translated"],
                         ["primary", "primary", "primary"])
        self.assertEqual([model for stage, model in events if stage == "polished"],
                         ["primary", "primary", "primary"])

    def test_moderation_retry_success_stays_primary(self):
        client = ModeratingClient(failures=2)
        stream = io.StringIO()
        with patch("srt_translator.pipeline.asyncio.sleep", new=_no_sleep), \
                redirect_stderr(stream):
            make_translator(client, max_workers=1,
                            fallback_models={"translation": "fallback"}).translate(self.cues)
        models = [model for label, model in client.models if label.startswith("translation")]
        self.assertEqual(models, [None, None, None, None, None])
        self.assertNotIn("[回退]", stream.getvalue())

    def test_moderation_falls_back_for_current_and_later_batches(self):
        client = ModeratingClient(failures=3)
        stream = io.StringIO()
        events: list[str] = []

        def progress(stage, original, result, detail=None):
            if stage == "translated":
                events.append(detail.get("model"))

        with patch("srt_translator.pipeline.asyncio.sleep", new=_no_sleep), \
                redirect_stderr(stream):
            result = make_translator(
                client, max_workers=1, progress=progress,
                fallback_models={"translation": "fallback"}).translate(self.cues)
        self.assertEqual(len(result), 5)
        models = [model for label, model in client.models if label.startswith("translation")]
        self.assertEqual(models, [None, None, None, "fallback", "fallback", "fallback"])
        polish_models = [model for label, model in client.models if label.startswith("polish")]
        self.assertTrue(polish_models)
        self.assertTrue(all(model is None for model in polish_models))
        self.assertEqual(events, ["fallback", "fallback", "fallback"])
        output = stream.getvalue()
        self.assertIn("[审查] 翻译批次 1/3：primary 被拒绝（3/3）", output)
        self.assertIn("[回退] 翻译阶段：primary → fallback", output)

    def test_moderation_without_fallback_raises(self):
        client = ModeratingClient(failures=3)
        with patch("srt_translator.pipeline.asyncio.sleep", new=_no_sleep), \
                self.assertRaises(RuntimeError) as ctx:
            make_translator(client, max_workers=1).translate(self.cues)
        self.assertIn("未配置回退模型", str(ctx.exception))

    def test_moderation_fallback_can_be_disabled(self):
        client = ModeratingClient(failures=3)
        with patch("srt_translator.pipeline.asyncio.sleep", new=_no_sleep), \
                self.assertRaises(RuntimeError) as ctx:
            make_translator(
                client, max_workers=1, fallback_enabled=False,
                fallback_models={"translation": "fallback"}).translate(self.cues)
        self.assertIn("模型回退已关闭", str(ctx.exception))

    def test_fallback_model_failure_raises(self):
        client = ModeratingClient(failures=6)
        with patch("srt_translator.pipeline.asyncio.sleep", new=_no_sleep), \
                self.assertRaises(RuntimeError) as ctx:
            make_translator(
                client, max_workers=1,
                fallback_models={"translation": "fallback"}).translate(self.cues)
        self.assertIn("回退模型也连续", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()