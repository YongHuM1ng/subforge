import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import translate_srt
from srt_translator.models import Cue
from srt_translator.srt import dump_srt, parse_srt
from srt_translator.track import analysis_sidecar
from tests._prompt import batch_items
from translate_srt import highlight_text, load_analysis, load_translated_texts, save_analysis


def cue(number: str, text: str) -> Cue:
    return Cue(number, "00:00:01,000 --> 00:00:02,000", text)


class TranslateCliTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def test_load_translated_texts_by_number(self):
        base = [cue("1", "原文1"), cue("2", "原文2")]
        path = self.root / "out.zh.srt"
        path.write_text(dump_srt([cue("1", "译文1"), cue("2", "译文2")]), encoding="utf-8")
        self.assertEqual(load_translated_texts(base, path), ["译文1", "译文2"])

    def test_load_translated_texts_reports_missing_ids(self):
        base = [cue("1", "原文1"), cue("2", "原文2")]
        path = self.root / "out.zh.srt"
        path.write_text(dump_srt([cue("1", "译文1")]), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            load_translated_texts(base, path)
        self.assertIn("2", str(ctx.exception))

    def test_analysis_sidecar_name(self):
        self.assertEqual(analysis_sidecar(Path("movie.zh.srt")),
                         Path("movie.zh.analysis.json"))

    def test_highlight_text_marks_changed_sides(self):
        old = highlight_text("abc", "abd", before_side=True)
        new = highlight_text("abc", "abd", before_side=False)
        self.assertIn("\033[33mc\033[0m", old)
        self.assertIn("\033[33md\033[0m", new)

    def test_save_and_load_analysis(self):
        analysis = {"summary": "主题", "style": "口语", "corrections": [], "terms": []}
        input_path = self.root / "movie.asr.ja.srt"
        input_path.write_text(dump_srt([cue("1", "原文")]), encoding="utf-8")
        path = self.root / "movie.zh.analysis.json"
        save_analysis(path, analysis, input_path, "日语", "简体中文")
        self.assertEqual(load_analysis(path, input_path, "简体中文"), analysis)
        with self.assertRaises(ValueError):
            load_analysis(path, input_path, "英语")


class _FakeAPI(BaseHTTPRequestHandler):
    counts = {"analysis": 0, "translation": 0, "polish": 0}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        user = (body.get("messages") or [{}])[-1].get("content", "")
        if "<字幕轨>" in user:
            kind = "analysis"
            content = json.dumps({"summary": "测试", "style": "口语", "corrections": [], "terms": []},
                                 ensure_ascii=False)
        else:
            kind = "polish" if "<原文>" in user else "translation"
            items = batch_items(user)
            content = json.dumps({"translations": [
                {"id": str(item["id"]), "text": f"{kind}-{item['id']}"} for item in items
            ]}, ensure_ascii=False)
        type(self).counts[kind] += 1
        data = json.dumps({
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


async def _no_sleep(*args, **kwargs):
    return None


class _FlakyPolishAPI(BaseHTTPRequestHandler):
    fail = True
    log: list[str] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        user = (body.get("messages") or [{}])[-1].get("content", "")
        if "<原文>" not in user:
            type(self).log.append("other")
            payload = {"choices": [{"message": {"content": "{}"}}]}
        else:
            items = batch_items(user)
            ids = [str(item["id"]) for item in items]
            type(self).log.append("polish:" + ",".join(ids))
            rows = [] if (type(self).fail and "2" in ids) else [
                {"id": item_id, "text": f"polish-{item_id}"} for item_id in ids
            ]
            payload = {"choices": [{"message": {"content": json.dumps(
                {"translations": rows}, ensure_ascii=False)}}]}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class TranslateCliFailureTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        _FlakyPolishAPI.fail = True
        _FlakyPolishAPI.log = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FlakyPolishAPI)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.config = self.root / "config.toml"
        self.config.write_text("", encoding="utf-8")
        self.input = self.root / "movie.asr.ja.srt"
        self.input.write_text(dump_srt([cue("1", "原文1"), cue("2", "原文2")]), encoding="utf-8")
        self.translated = self.root / "movie.zh.srt"
        self.translated.write_text(dump_srt([cue("1", "translation-1"), cue("2", "translation-2")]),
                                   encoding="utf-8")
        self.sidecar = self.root / "movie.zh.analysis.json"
        self.sidecar.write_text(json.dumps({
            "version": 1, "input": str(self.input.resolve()), "source": "日语", "target": "简体中文",
            "analysis": {"summary": "测试", "style": "口语", "corrections": [], "terms": []},
        }, ensure_ascii=False), encoding="utf-8")
        self.output = self.root / "movie.zh.polished.srt"
        self.env = {
            "LLM_API_KEY": "test",
            "LLM_API_URL": f"http://127.0.0.1:{self.server.server_port}/v1/chat/completions",
            "LLM_PROXY": "none",
        }

    def run_main(self, *args):
        old = sys.argv
        sys.argv = ["translate_srt.py", *args]
        try:
            return translate_srt.main()
        finally:
            sys.argv = old

    def args(self):
        return [
            str(self.input), str(self.output), "--translated", str(self.translated),
            "--analysis-file", str(self.sidecar), "--config", str(self.config),
            "--batch-size", "1", "--workers", "1", "--quiet",
        ]

    def test_polish_failure_restarts_all_batches(self):
        with mock.patch.dict(os.environ, self.env, clear=False), \
                mock.patch("srt_translator.pipeline.asyncio.sleep", new=_no_sleep):
            self.assertEqual(self.run_main(*self.args()), 1)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.root / "cache").exists())

        _FlakyPolishAPI.fail = False
        _FlakyPolishAPI.log = []
        with mock.patch.dict(os.environ, self.env, clear=False), \
                mock.patch("srt_translator.pipeline.asyncio.sleep", new=_no_sleep):
            self.assertEqual(self.run_main(*self.args()), 0)
        self.assertTrue(self.output.exists())
        self.assertEqual(sorted(_FlakyPolishAPI.log), ["polish:1", "polish:2"])


class TranslateCliIntegrationTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        _FakeAPI.counts = {"analysis": 0, "translation": 0, "polish": 0}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeAPI)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.config = self.root / "config.toml"
        self.config.write_text("", encoding="utf-8")
        self.input = self.root / "movie.asr.ja.srt"
        self.input.write_text(dump_srt([cue("1", "原文1"), cue("2", "原文2")]), encoding="utf-8")
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/v1/chat/completions"
        self._old_key = os.environ.get("LLM_API_KEY")
        os.environ["LLM_API_KEY"] = "test"
        self.addCleanup(self._restore_key)

    def _restore_key(self):
        if self._old_key is None:
            os.environ.pop("LLM_API_KEY", None)
        else:
            os.environ["LLM_API_KEY"] = self._old_key

    def run_main(self, *args):
        old = sys.argv
        sys.argv = ["translate_srt.py", *args]
        try:
            return translate_srt.main()
        finally:
            sys.argv = old

    def common(self):
        return ["--config", str(self.config), "--endpoint", self.endpoint,
                "--proxy", "none", "--quiet", "--batch-size", "2"]

    def test_translate_then_polish_from_saved_stage(self):
        translated = self.root / "movie.zh.srt"
        self.assertEqual(self.run_main(str(self.input), str(translated), "--no-polish", *self.common()), 0)
        self.assertTrue(translated.exists())
        self.assertTrue(analysis_sidecar(translated).exists())
        self.assertEqual(_FakeAPI.counts, {"analysis": 1, "translation": 1, "polish": 0})
        self.assertEqual([c.text for c in parse_srt(translated.read_text(encoding="utf-8"))],
                         ["translation-1", "translation-2"])

        polished = self.root / "movie.zh.polished.srt"
        self.assertEqual(self.run_main(str(self.input), str(polished), "--translated", str(translated),
                                       *self.common()), 0)
        self.assertTrue(polished.exists())
        self.assertEqual(_FakeAPI.counts, {"analysis": 1, "translation": 1, "polish": 1})
        self.assertEqual([c.text for c in parse_srt(polished.read_text(encoding="utf-8"))],
                         ["polish-1", "polish-2"])


if __name__ == "__main__":
    unittest.main()