"""覆盖本轮修复：配置校验、失败时停止计费、编号去重、命名别名、润色失败保留译文、控制台输出。"""
import asyncio
import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import workflow
from asr.engine import ProcessResult
from common import console
from common.env import read_env_file
from common.queue import run_serial
from common.textwidth import display_width, split_at_width
from srt_translator.client import TRANSLATION_SCHEMA, LLMClient
from srt_translator.config import DEFAULT_CONFIG, _copy, resolve_models, validate_config, warn_unknown_keys
from srt_translator.languages import language_profile
from srt_translator.models import Cue
from srt_translator.pipeline import SubtitleTranslator, TranslatorOptions
from srt_translator.srt import dump_srt, renumber_if_duplicated
from srt_translator.track import analysis_sidecar, derive_output_path, polished_output, target_code
from tests._prompt import batch_items
from translate_srt import load_translated_texts


def cue(number: str, text: str, second: int = 1) -> Cue:
    return Cue(number, f"00:00:{second:02d},000 --> 00:00:{second:02d},900", text)


class ConfigValidationTest(unittest.TestCase):
    def config(self, **sections):
        data = _copy(DEFAULT_CONFIG)
        for section, values in sections.items():
            data[section].update(values)
        return data

    def test_defaults_are_valid(self):
        validate_config(self.config())

    def test_rejects_bad_numbers_and_types(self):
        cases = [
            {"processing": {"batch_size": -5}},
            {"processing": {"batch_size": 0}},
            {"processing": {"max_workers": "3"}},
            {"translation": {"polish": "false"}},
            {"api": {"structured_output": "json"}},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError) as ctx:
                validate_config(self.config(**case))
            self.assertIn("config.toml 配置有误", str(ctx.exception))

    def test_lists_every_error(self):
        with self.assertRaises(ValueError) as ctx:
            validate_config(self.config(processing={"batch_size": 0, "context": -1}))
        self.assertIn("batch_size", str(ctx.exception))
        self.assertIn("context", str(ctx.exception))

    def test_warns_unknown_keys(self):
        with redirect_stderr(io.StringIO()) as err:
            unknown = warn_unknown_keys({"processing": {"workers": 5}, "modles": {}, "asr": {"x": 1}})
        self.assertEqual(unknown, ["processing.workers", "[modles]"])
        self.assertIn("processing.workers", err.getvalue())

    def test_resolve_models(self):
        config = self.config(models={"translation": "big", "fallback": "fb", "polish_fallback": "pfb"})
        stage, fallback, enabled = resolve_models(config, {"analysis": "cli", "translation": None})
        self.assertEqual(stage, {"analysis": "cli", "translation": "big"})
        self.assertEqual(fallback, {"analysis": "fb", "translation": "fb", "polish": "pfb"})
        self.assertTrue(enabled)
        self.assertFalse(resolve_models(config, {}, no_fallback=True)[2])


class NamingTest(unittest.TestCase):
    def test_traditional_chinese_targets(self):
        for name in ("繁體中文", "繁体中文", "zh-TW", "zh_Hant", "Traditional Chinese"):
            with self.subTest(name=name):
                self.assertEqual(target_code(name), "zh")
                self.assertEqual(language_profile(name).code, "zh")
        self.assertEqual(derive_output_path(Path("movie.asr.ja.srt"), "繁體中文").name, "movie.zh.srt")

    def test_polished_files_find_original_analysis(self):
        self.assertEqual(analysis_sidecar(Path("movie.zh.srt")).name, "movie.zh.analysis.json")
        self.assertEqual(analysis_sidecar(Path("movie.zh.polished.srt")).name, "movie.zh.analysis.json")
        self.assertEqual(analysis_sidecar(Path("movie.zh.polished.2.srt")).name, "movie.zh.analysis.json")
        self.assertEqual(polished_output(Path("movie.zh.polished.srt")).name, "movie.zh.polished.srt")
        self.assertEqual(polished_output(Path("movie.zh.srt")).name, "movie.zh.polished.srt")


class DuplicateNumberTest(unittest.TestCase):
    def test_renumber_only_when_duplicated(self):
        unique = [cue("1", "a"), cue("2", "b")]
        self.assertEqual(renumber_if_duplicated(unique), (unique, False))
        cues, changed = renumber_if_duplicated([cue("1", "a"), cue("1", "b"), cue("2", "c")])
        self.assertTrue(changed)
        self.assertEqual([c.number for c in cues], ["1", "2", "3"])
        self.assertEqual([c.text for c in cues], ["a", "b", "c"])

    def test_translated_file_with_duplicates_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "movie.zh.srt"
            path.write_text(dump_srt([cue("1", "甲"), cue("1", "乙")]), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_translated_texts([cue("1", "a"), cue("2", "b")], path)
            self.assertIn("编号有重复", str(ctx.exception))


class _FailingBatchClient:
    """第 1 批立即失败，其余批次慢慢返回；用来确认失败后其余批次被取消。"""
    retries = 0
    model = "m"

    def __init__(self):
        self.finished: list[str] = []

    async def chat_json(self, system, user, schema=None, label="request", model=None):
        if label == "translation-batch-1":
            raise RuntimeError("远端 API 请求失败：boom")
        await asyncio.sleep(0.2)
        self.finished.append(label)
        items = batch_items(user)
        return json.dumps({"translations": [{"id": i["id"], "text": "x"} for i in items]})

    async def aclose(self):
        pass


class _PolishFailsClient(_FailingBatchClient):
    async def chat_json(self, system, user, schema=None, label="request", model=None):
        if label.startswith("polish"):
            raise RuntimeError("远端 API 请求失败：polish down")
        items = batch_items(user)
        return json.dumps({"translations": [{"id": i["id"], "text": f"译{i['id']}"} for i in items]})


class PipelineFailureTest(unittest.TestCase):
    cues = [cue(str(i), f"t{i}", i) for i in range(1, 9)]

    def test_failed_batch_cancels_other_batches(self):
        client = _FailingBatchClient()
        translator = SubtitleTranslator(client, TranslatorOptions(
            batch_size=2, max_workers=4, global_analysis=False, polish=False))
        with self.assertRaises(RuntimeError):
            translator.translate(self.cues)
        self.assertEqual(client.finished, [])

    def test_translation_kept_when_polish_fails(self):
        translator = SubtitleTranslator(_PolishFailsClient(), TranslatorOptions(
            batch_size=4, global_analysis=False, polish=True))
        with self.assertRaises(RuntimeError):
            translator.translate(self.cues)
        self.assertEqual([c.text for c in translator.translated_result],
                         [f"译{i}" for i in range(1, 9)])


class _BadModelHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        data = json.dumps({"error": {"message": "invalid model ID", "type": "invalid_request_error"}}).encode()
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class ClientErrorTest(unittest.TestCase):
    def test_generic_400_is_not_blamed_on_structured_output(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _BadModelHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        client = LLMClient(f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                           "k", "m", timeout=10, retries=0, structured_output="json_schema", proxy="none")
        try:
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(client.chat_json("s", "u", TRANSLATION_SCHEMA))
        finally:
            asyncio.run(client.aclose())
        self.assertIn("invalid model ID", str(ctx.exception))
        self.assertNotIn("structured_output", str(ctx.exception))


class WorkflowReuseTest(unittest.TestCase):
    def run_workflow(self, root: Path, *extra: str):
        video = root / "movie.mp4"
        video.write_bytes(b"x")
        (root / "movie.asr.ja.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nx\n", encoding="utf-8")
        config = root / "config.toml"
        config.write_text("", encoding="utf-8")
        with patch.object(workflow.asr_config, "apply_asr_config"), \
                patch.object(workflow.asr_config, "load_asr_config", return_value={}), \
                patch.object(workflow, "get_api_key") as key, \
                patch.object(workflow, "process_file", return_value=ProcessResult()) as asr, \
                patch.object(workflow, "run_translation", return_value=0) as translate, \
                redirect_stdout(io.StringIO()):
            code = workflow.main([str(video), "--config", str(config), *extra])
        return code, key, asr, translate

    def test_existing_translation_is_skipped_and_no_key_needed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "movie.zh.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\n译\n", encoding="utf-8")
            code, key, asr, translate = self.run_workflow(root)
        self.assertEqual(code, 0)
        key.assert_not_called()
        asr.assert_not_called()
        translate.assert_not_called()

    def test_redo_translate_forces_translation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "movie.zh.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\n译\n", encoding="utf-8")
            code, _, _, translate = self.run_workflow(root, "--redo-translate")
        self.assertEqual(code, 0)
        translate.assert_called_once()


class ConsoleTest(unittest.TestCase):
    def test_no_color_when_not_a_terminal(self):
        stream = io.StringIO()
        self.assertEqual(console.paint("x", "red", stream=stream), "x")
        self.assertEqual(console.decorate("[错误] 坏了", stream), "[错误] 坏了")

    def test_force_color_tags(self):
        with patch.dict(os.environ, {"FORCE_COLOR": "1"}, clear=False):
            os.environ.pop("NO_COLOR", None)
            line = console.decorate("  [错误] 坏了", io.StringIO())
        self.assertTrue(line.startswith("  \033["))
        self.assertTrue(line.endswith(" 坏了"))

    def test_no_color_env_wins(self):
        with patch.dict(os.environ, {"FORCE_COLOR": "1", "NO_COLOR": "1"}):
            self.assertEqual(console.paint("x", "red"), "x")

    def test_rule_and_kv(self):
        stream = io.StringIO()
        self.assertIn(" 完成 ", console.rule("完成", stream))
        lines = console.kv_lines([("输出", "a.srt"), ("已有译文", "b.srt"), ("空", "")], stream)
        self.assertEqual(len(lines), 2)
        self.assertEqual(display_width(lines[0][:lines[0].index("a.srt")]),
                         display_width(lines[1][:lines[1].index("b.srt")]))

    def test_format_duration(self):
        self.assertEqual(console.format_duration(65), "01:05")
        self.assertEqual(console.format_duration(3725), "1:02:05")

    def test_queue_reports_each_item(self):
        out = io.StringIO()
        code = run_serial([Path("a.srt"), Path("b.srt")], lambda p: p.name == "a.srt", stream=out)
        text = out.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("✓ a.srt 完成", text)
        self.assertIn("✗ b.srt 失败", text)


class SmallFixesTest(unittest.TestCase):
    def test_env_parser(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text('﻿# c\nA="1"\nexport B=2\nC\n', encoding="utf-8")
            self.assertEqual(read_env_file(path), {"A": "1", "B": "2"})

    def test_split_prefers_space_by_display_width(self):
        # 空格前是宽字符：按显示宽度判断，空格位置足够靠右，应在空格处断开。
        lines = split_at_width("日本語日本語 abcdefgh", 14)
        self.assertEqual(lines[0], "日本語日本語")


if __name__ == "__main__":
    unittest.main()
