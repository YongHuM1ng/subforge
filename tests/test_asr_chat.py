import json
import tempfile
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from asr import config, transcribe


class ChatTextTest(unittest.TestCase):
    def test_string_content(self):
        self.assertEqual(
            transcribe._extract_chat_text(
                {"choices": [{"message": {"content": "你好"}}]}),
            "你好",
        )

    def test_list_content(self):
        self.assertEqual(
            transcribe._extract_chat_text({"choices": [{
                "message": {"content": [
                    {"type": "text", "text": "你"},
                    {"type": "text", "text": "好"},
                ]},
            }]}),
            "你好",
        )

    def test_json_string_content(self):
        self.assertEqual(
            transcribe._extract_chat_text(
                {"choices": [{"message": {"content": '{"text": "转录结果"}'}}]}),
            "转录结果",
        )

    def test_top_level_text(self):
        self.assertEqual(transcribe._extract_chat_text({"text": "raw"}), "raw")

    def test_empty(self):
        self.assertEqual(transcribe._extract_chat_text({}), "")


class ChatRequestTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.wav = Path(self.folder.name) / "a.wav"
        with wave.open(str(self.wav), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"\x00\x00" * 1600)

    def tearDown(self):
        self.folder.cleanup()

    def test_chat_payload_and_api_key_header(self):
        captured = {}

        def fake_post(url, payload, headers):
            captured.update(url=url, payload=payload, headers=headers)
            return {
                "choices": [{"message": {"content": "识别文本"}}],
                "usage": {"total_tokens": 12},
            }

        with patch.object(config, "PROTOCOL", "chat_completions"), \
                patch.object(config, "API_URL", "https://api.example/v1/chat/completions"), \
                patch.object(config, "MODEL", "mimo-v2.5-asr"), \
                patch.object(config, "API_KEY_HEADER", "api-key"), \
                patch.object(config, "API_KEY_PREFIX", ""), \
                patch.object(config, "AUDIO_FORMAT", "data_url"), \
                patch.object(config, "LANGUAGE", "zh"), \
                patch("asr.transcribe._post_json", side_effect=fake_post):
            result = transcribe.api_transcribe(self.wav, "secret", 0)

        self.assertEqual(captured["url"], "https://api.example/v1/chat/completions")
        self.assertEqual(captured["headers"]["api-key"], "secret")
        self.assertNotIn("Authorization", captured["headers"])
        self.assertEqual(captured["payload"]["model"], "mimo-v2.5-asr")
        self.assertEqual(captured["payload"]["asr_options"], {"language": "zh"})
        audio = captured["payload"]["messages"][0]["content"][0]["input_audio"]["data"]
        self.assertTrue(audio.startswith("data:audio/wav;base64,"))
        self.assertEqual(result["text"], "识别文本")
        self.assertEqual(result["language"], "zh")
        self.assertEqual(result["usage"]["total_tokens"], 12)

    def test_chat_uses_bearer_by_default(self):
        captured = {}

        def fake_post(url, payload, headers):
            captured.update(headers=headers)
            return {"choices": [{"message": {"content": "x"}}]}

        with patch.object(config, "PROTOCOL", "chat_completions"), \
                patch.object(config, "API_KEY_HEADER", "Authorization"), \
                patch.object(config, "API_KEY_PREFIX", "Bearer "), \
                patch.object(config, "AUDIO_FORMAT", "data_url"), \
                patch.object(config, "LANGUAGE", ""), \
                patch("asr.transcribe._post_json", side_effect=fake_post):
            transcribe.api_transcribe(self.wav, "secret", 0)

        self.assertEqual(captured["headers"]["Authorization"], "Bearer secret")

    def test_chat_base64_audio_format(self):
        captured = {}

        def fake_post(url, payload, headers):
            captured.update(payload=payload)
            return {"choices": [{"message": {"content": "x"}}]}

        with patch.object(config, "PROTOCOL", "chat_completions"), \
                patch.object(config, "AUDIO_FORMAT", "base64"), \
                patch.object(config, "LANGUAGE", ""), \
                patch("asr.transcribe._post_json", side_effect=fake_post):
            transcribe.api_transcribe(self.wav, "secret", 0)

        audio = captured["payload"]["messages"][0]["content"][0]["input_audio"]
        self.assertEqual(audio["format"], "wav")
        self.assertFalse(audio["data"].startswith("data:"))

    def test_transcriptions_protocol_still_used_by_default(self):
        captured = {}

        def fake_post(url, payload, headers):
            captured.update(payload=payload, headers=headers)
            return {"text": "ok"}

        with patch.object(config, "PROTOCOL", "transcriptions"), \
                patch.object(config, "MODEL", "whisper-1"), \
                patch("asr.transcribe._post_json", side_effect=fake_post):
            result = transcribe.api_transcribe(self.wav, "secret", 2)

        self.assertEqual(captured["payload"]["response_format"], "verbose_json")
        self.assertEqual(captured["payload"]["timestamp_granularities"], ["word"])
        self.assertIn("Authorization", captured["headers"])
        self.assertEqual(result["text"], "ok")

    def test_chat_request_over_http(self):
        captured = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                captured["header"] = self.headers.get("api-key")
                captured["payload"] = json.loads(self.rfile.read(length))
                body = json.dumps({
                    "choices": [{"message": {"content": "本地响应"}}],
                    "usage": {"total_tokens": 3},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(config, "PROTOCOL", "chat_completions"), \
                    patch.object(config, "API_URL",
                                 f"http://127.0.0.1:{server.server_port}/v1/chat/completions"), \
                    patch.object(config, "MODEL", "mimo-v2.5-asr"), \
                    patch.object(config, "PROXY", "none"), \
                    patch.object(config, "API_KEY_HEADER", "api-key"), \
                    patch.object(config, "API_KEY_PREFIX", ""), \
                    patch.object(config, "AUDIO_FORMAT", "data_url"), \
                    patch.object(config, "LANGUAGE", "zh"):
                result = transcribe.api_transcribe(self.wav, "secret", 0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(captured["header"], "secret")
        self.assertEqual(captured["payload"]["model"], "mimo-v2.5-asr")
        self.assertEqual(captured["payload"]["asr_options"], {"language": "zh"})
        self.assertEqual(result["text"], "本地响应")
        self.assertEqual(result["usage"]["total_tokens"], 3)

    def test_openai_multipart_request(self):
        captured = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                captured["content_type"] = self.headers.get("Content-Type") or ""
                captured["authorization"] = self.headers.get("Authorization") or ""
                captured["body"] = self.rfile.read(length)
                body = json.dumps({
                    "text": "hello",
                    "segments": [{"start": 0, "end": 1, "text": "hello"}],
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(config, "PROTOCOL", "openai_transcriptions"), \
                    patch.object(config, "API_URL",
                                 f"http://127.0.0.1:{server.server_port}/v1/audio/transcriptions"), \
                    patch.object(config, "MODEL", "whisper-1"), \
                    patch.object(config, "PROXY", "none"), \
                    patch.object(config, "API_KEY_HEADER", "Authorization"), \
                    patch.object(config, "API_KEY_PREFIX", "Bearer "), \
                    patch.object(config, "LANGUAGE", "ja"):
                result = transcribe.api_transcribe(self.wav, "secret", 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertTrue(captured["content_type"].startswith("multipart/form-data; boundary="))
        self.assertEqual(captured["authorization"], "Bearer secret")
        body = captured["body"].decode("utf-8", "replace")
        self.assertIn('name="model"', body)
        self.assertIn("whisper-1", body)
        self.assertIn('name="response_format"', body)
        self.assertIn("verbose_json", body)
        self.assertIn('name="timestamp_granularities[]"', body)
        self.assertIn('name="language"', body)
        self.assertIn("ja", body)
        self.assertIn('name="file"; filename="a.wav"', body)
        self.assertIn("audio/wav", body)
        self.assertEqual(result["text"], "hello")


if __name__ == "__main__":
    unittest.main()
