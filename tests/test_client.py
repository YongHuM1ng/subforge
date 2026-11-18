import asyncio
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from srt_translator.client import (
    ANALYSIS_SCHEMA,
    TRANSLATION_SCHEMA,
    ContentFilteredError,
    LLMClient,
    looks_like_moderation,
)


class _EmptyChoicesHandler(BaseHTTPRequestHandler):
    modes: list[str] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        mode = (body.get("response_format") or {}).get("type") or "none"
        type(self).modes.append(mode)
        payload = {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 0}}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class _UnsupportedFormatHandler(BaseHTTPRequestHandler):
    modes: list[str] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        mode = (body.get("response_format") or {}).get("type") or "none"
        type(self).modes.append(mode)
        payload = {"error": {"message": "response_format json_schema is not supported"}}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class ClientBodyTest(unittest.TestCase):
    def make(self, mode: str) -> LLMClient:
        return LLMClient("http://127.0.0.1:9/v1/chat/completions", "k", "m",
                         structured_output=mode, proxy="none")

    def test_schema_mode(self):
        body = self.make("json_schema")._build_body("s", "u", TRANSLATION_SCHEMA, "json_schema")
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])

    def test_object_mode(self):
        body = self.make("json_object")._build_body("s", "u", TRANSLATION_SCHEMA, "json_object")
        self.assertEqual(body["response_format"], {"type": "json_object"})

    def test_none_mode(self):
        body = self.make("none")._build_body("s", "u", TRANSLATION_SCHEMA, "none")
        self.assertNotIn("response_format", body)

    def test_model_override(self):
        body = self.make("none")._build_body("s", "u", None, "none", "stage-model")
        self.assertEqual(body["model"], "stage-model")

    def test_looks_like_moderation(self):
        self.assertTrue(looks_like_moderation(400, '{"error":{"message":"content_policy_violation"}}'))
        self.assertTrue(looks_like_moderation(403, "flagged as unsafe"))
        self.assertTrue(looks_like_moderation(400, "内容敏感，已拒绝"))
        self.assertFalse(looks_like_moderation(400, "response_format is not supported"))
        self.assertFalse(looks_like_moderation(401, "invalid api key"))
        self.assertFalse(looks_like_moderation(500, "content policy"))

    def test_empty_choices_raise_content_filtered(self):
        _EmptyChoicesHandler.modes = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _EmptyChoicesHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        client = LLMClient(
            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            "k", "m", timeout=10, retries=3,
            structured_output="json_schema", proxy="none",
        )
        try:
            with self.assertRaises(ContentFilteredError) as ctx:
                asyncio.run(client.chat_json("s", "u", TRANSLATION_SCHEMA, label="test"))
        finally:
            asyncio.run(client.aclose())
        self.assertEqual(_EmptyChoicesHandler.modes, ["json_schema"])
        self.assertIn("空 choices", str(ctx.exception))

    def test_unsupported_format_requires_manual_config(self):
        _UnsupportedFormatHandler.modes = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _UnsupportedFormatHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        client = LLMClient(
            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            "k", "m", timeout=10, retries=3,
            structured_output="json_schema", proxy="none",
        )
        try:
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(client.chat_json("s", "u", TRANSLATION_SCHEMA, label="test"))
        finally:
            asyncio.run(client.aclose())
        self.assertEqual(_UnsupportedFormatHandler.modes, ["json_schema"])
        message = str(ctx.exception)
        self.assertIn("structured_output=json_schema", message)
        self.assertIn("json_object", message)
        self.assertIn("none", message)

    def test_analysis_schema_enumerates_labels(self):
        item = ANALYSIS_SCHEMA["properties"]["corrections"]["items"]["properties"]
        self.assertEqual(item["confidence"]["enum"], ["high", "medium", "low"])
        self.assertIn("term", item["type"]["enum"])

    def test_usage_summary(self):
        client = self.make("none")
        client._accumulate_usage({"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.002})
        client._accumulate_usage({"prompt_tokens": 3, "completion_tokens": 2, "cost": 0.001})
        summary = client.usage_summary()
        self.assertIn("输入 13 tokens", summary)
        self.assertIn("输出 7 tokens", summary)
        self.assertIn("$0.0030", summary)


if __name__ == "__main__":
    unittest.main()