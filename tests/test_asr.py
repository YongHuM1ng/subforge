import shutil
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from asr.cues import build_cues, finalize_cues
from asr.engine import process_file
from asr.media import fixed_chunks, plan_chunks
from asr.text import display_width, split_sentences, wrap_lines
from asr.transcribe import ApiError, Gate, UnsupportedParamError, detect_language, run_chunks, transcribe_chunk
from asr.tui import format_bar, progress_line

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class AsrTextTest(unittest.TestCase):
    def test_width_and_split(self):
        self.assertEqual(display_width("abあ漢"), 6)
        self.assertEqual(split_sentences("Hello world. これはテストです。次！"),
                         ["Hello world.", "これはテストです。", "次！"])
        lines = wrap_lines("これはとても長い文章です。" * 8, 20, 2)
        self.assertLessEqual(len(lines), 2)
        self.assertLessEqual(display_width(lines[0]), 22)


class AsrChunkTest(unittest.TestCase):
    def test_plan_and_fixed(self):
        chunks = plan_chunks(120, [(30, 32), (60, 61), (90, 91)])
        self.assertEqual(chunks[0][0], 0.0)
        self.assertEqual(chunks[-1][1], 120)
        self.assertTrue(all(b - a <= 60 for a, b in chunks))
        self.assertEqual(fixed_chunks(50, 15), [(0, 15), (15, 30), (30, 45), (45, 50)])

    def test_plan_without_silence_covers_duration(self):
        chunks = plan_chunks(130, [])
        self.assertEqual(chunks[0][0], 0.0)
        self.assertEqual(chunks[-1][1], 130)
        self.assertTrue(all(b - a <= 60 for a, b in chunks))

    def test_plan_merges_tiny_tail(self):
        # 45–60 秒处有静音点，切完后只剩 2 秒尾巴，应并回前一片。
        self.assertEqual(plan_chunks(62, [(59.8, 60.2)]), [(0.0, 62)])


class AsrCueTest(unittest.TestCase):
    def test_build_and_finalize(self):
        results = [
            (0.0, 3.0, {"segments": [
                {"start": 0.0, "end": 1.0, "text": "こんにちは。"},
                {"start": 1.2, "end": 2.8, "text": "今日はいい天気ですね。"},
            ]}),
            (3.0, 6.0, {"text": "はい、散歩でもしませんか。"}),
        ]
        cues = build_cues(results)
        self.assertGreaterEqual(len(cues), 2)
        final = finalize_cues(cues, 6.0)
        self.assertTrue(all(0 <= a <= b <= 6.2 for a, b, _ in final))
        self.assertTrue(all(text.strip() for _, _, text in final))

    def test_finalize_merges_short_cue_instead_of_dropping(self):
        # 前一条只有 0.3 秒且紧贴下一条：文本并入下一条，不能被整句丢弃。
        cues = [(1.0, 1.3, "上一句"), (1.31, 3.0, "当前句"), (4.0, 5.0, "第三句")]
        final = finalize_cues(cues, 6.0)
        self.assertEqual([text for _, _, text in final], ["上一句当前句", "第三句"])
        self.assertTrue(all(a <= b for a, b, _ in final))

    def test_run_chunks_uses_thread_pool(self):
        with tempfile.TemporaryDirectory() as folder:
            workdir = Path(folder)
            wavs = [workdir / "a.wav", workdir / "b.wav"]
            response = {"text": "hello", "words": [{"word": "hello", "start": 0, "end": 1}]}
            with patch("asr.transcribe.transcribe_chunk", return_value=response):
                results = run_chunks(
                    wavs, [(0.0, 1.0), (1.0, 2.0)], "key", 2,
                    probe_timing=True, show_progress=False,
                )
            self.assertEqual(len(results), 2)

    def test_progress_bar(self):
        self.assertIn("  0%", format_bar(0, 10))
        self.assertIn(" 50%", format_bar(5, 10))
        self.assertIn("100%", format_bar(10, 10))
        line = progress_line("demo.mp4", 5, 10, 65)
        self.assertIn("demo.mp4", line)
        self.assertIn("50%", line)
        self.assertIn("01:05", line)
        self.assertIn("剩余约 01:05", line)

    def test_detect_language(self):
        self.assertEqual(detect_language([
            (0, 1, {"language": "Japanese", "text": "こんにちは"}),
            (1, 2, {"language": "ja", "text": "テスト"}),
        ]), "ja")
        self.assertEqual(detect_language([(0, 1, {"text": "你好世界"})]), "zh")


class TranscribeRetryTest(unittest.TestCase):
    def test_unsupported_timestamps_raise_with_config_hint(self):
        # 不自动降级：接口不接受词级时间戳时报错，并提示改 [asr] timestamps。
        calls = []

        def fake(path, key, mode):
            calls.append(mode)
            raise ApiError(400, '{"error":{"message":"timestamp_granularities is not supported"}}')

        state = {"mode": 2, "gate": None}
        with patch("asr.transcribe.api_transcribe", side_effect=fake), \
                patch("asr.transcribe.time.sleep"):
            with self.assertRaises(UnsupportedParamError) as ctx:
                transcribe_chunk(Path("x.wav"), "key", state)
        self.assertEqual(calls, [2])
        self.assertIn('timestamps 改为 "segment"', str(ctx.exception))

    def test_generic_400_is_not_treated_as_param_problem(self):
        calls = []

        def fake(path, key, mode):
            calls.append(mode)
            raise ApiError(400, '{"error":{"message":"invalid audio file"}}')

        with patch("asr.transcribe.api_transcribe", side_effect=fake), \
                patch("asr.transcribe.time.sleep"):
            with self.assertRaises(ApiError):
                transcribe_chunk(Path("x.wav"), "key", {"mode": 2, "gate": None})
        self.assertEqual(calls, [2])

    def test_run_chunks_cancels_pending_requests_on_failure(self):
        calls = []
        lock = threading.Lock()

        def fake(path, key, mode):
            with lock:
                calls.append(path.name)
            if path.name == "c001.wav":
                raise ApiError(401, "bad key")
            time.sleep(0.02)
            return {"text": "x", "segments": [{"start": 0, "end": 1, "text": "x"}]}

        wavs = [Path(f"c{i:03d}.wav") for i in range(40)]
        with patch("asr.transcribe.api_transcribe", side_effect=fake):
            with self.assertRaises(ApiError):
                run_chunks(wavs, [(i, i + 1) for i in range(40)], "k", 2, show_progress=False)
        # 失败后不再发出排队中的请求：最多是已在途的几个，而不是全部 40 个。
        self.assertLess(len(calls), 10)

    def test_402_shrinks_gate(self):
        errors = [ApiError(402, '{"error":{"message":"too many in-flight requests"}}')]

        def fake(*args, **kwargs):
            if errors:
                raise errors.pop()
            return {"text": "ok"}

        gate = Gate(4)
        state = {"mode": 2, "gate": gate}
        with patch("asr.transcribe.api_transcribe", side_effect=fake), \
                patch("asr.transcribe.time.sleep"):
            response = transcribe_chunk(Path("x.wav"), "key", state)
        self.assertEqual(response["text"], "ok")
        self.assertEqual(gate.limit, 2)


@unittest.skipUnless(HAS_FFMPEG, "需要 ffmpeg/ffprobe")
class AsrDryRunTest(unittest.TestCase):
    def test_dry_run(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "silence.wav"
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                handle.writeframes(b"\x00\x00" * 16000)
            result = process_file(path, "", {
                "txt": False, "keep_audio": False, "workers": 1, "jobs": 1,
                "dry_run": True,
            })
            self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()