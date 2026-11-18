import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import workflow
from asr import cli as asr_cli
from asr.engine import ProcessResult
from workflow import find_existing_asr_srt


class WorkflowResumeTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def touch(self, name: str, mtime: int) -> Path:
        path = self.root / name
        path.write_text("1\n00:00:01,000 --> 00:00:02,000\nx\n", encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def test_finds_language_tagged_srt(self):
        srt = self.touch("movie.asr.ja.srt", 1000)
        self.assertEqual(find_existing_asr_srt(self.root / "movie.mp4"), srt)

    def test_finds_untagged_srt(self):
        srt = self.touch("movie.asr.srt", 1000)
        self.assertEqual(find_existing_asr_srt(self.root / "movie.mp4"), srt)

    def test_picks_newest_when_multiple(self):
        self.touch("movie.asr.ja.srt", 1000)
        newest = self.touch("movie.asr.en.srt", 2000)
        self.assertEqual(find_existing_asr_srt(self.root / "movie.mp4"), newest)

    def test_ignores_unrelated_files(self):
        self.touch("other.asr.ja.srt", 1000)
        self.assertIsNone(find_existing_asr_srt(self.root / "movie.mp4"))

    def test_handles_video_name_with_asr_tag(self):
        srt = self.touch("movie.asr.ja.srt", 1000)
        self.assertEqual(find_existing_asr_srt(self.root / "movie.asr.ja.mp4"), srt)


class WorkflowChainTest(unittest.TestCase):
    def test_runs_asr_then_translation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / "movie.mp4"
            video.write_bytes(b"x")
            config = root / "config.toml"
            config.write_text("", encoding="utf-8")
            srt = root / "movie.asr.ja.srt"
            with patch.object(workflow.asr_config, "apply_asr_config"), \
                    patch.object(workflow.asr_config, "load_asr_config", return_value={}), \
                    patch.object(workflow, "get_api_key", return_value="key"), \
                    patch.object(workflow, "process_file",
                                  return_value=ProcessResult(path=srt)) as asr_call, \
                    patch.object(workflow, "run_translation", return_value=0) as translate_call:
                code = workflow.main([str(video), "--config", str(config)])
            self.assertEqual(code, 0)
            asr_call.assert_called_once()
            translate_call.assert_called_once()
            self.assertEqual(translate_call.call_args.args[0], srt)


class WorkflowQueueTest(unittest.TestCase):
    def test_no_video_enters_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / "config.toml"
            config.write_text("", encoding="utf-8")
            videos = [root / "a.mp4", root / "b.mp4"]
            with patch.object(workflow, "collect_files", return_value=videos) as collect, \
                    patch.object(workflow, "run_serial", return_value=0) as serial, \
                    patch.object(workflow.asr_config, "apply_asr_config"), \
                    patch.object(workflow.asr_config, "load_asr_config", return_value={}), \
                    patch.object(workflow, "get_api_key", return_value="key"):
                code = workflow.main(["--config", str(config)])
            self.assertEqual(code, 0)
            collect.assert_called_once()
            self.assertEqual(serial.call_args.args[0], videos)

    def test_empty_queue_shows_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.toml"
            config.write_text("", encoding="utf-8")
            with patch.object(workflow, "collect_files", return_value=[]), \
                    patch.object(workflow, "run_serial") as serial, \
                    redirect_stdout(io.StringIO()):
                code = workflow.main(["--config", str(config)])
            self.assertEqual(code, 1)
            serial.assert_not_called()


class AsrQueueTest(unittest.TestCase):
    def test_no_file_enters_queue_with_serial_jobs(self):
        files = [Path("a.mp4"), Path("b.mp4")]
        with patch.object(asr_cli, "collect_files", return_value=files) as collect, \
                patch.object(asr_cli, "run_serial", return_value=0) as serial, \
                patch.object(asr_cli, "apply_asr_config"), \
                patch.object(asr_cli, "load_asr_config", return_value={}), \
                patch.object(asr_cli, "resolve_proxy", return_value=None), \
                patch.object(asr_cli, "get_api_key", return_value="key"), \
                patch.object(asr_cli, "process_file", return_value=True) as process, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(asr_cli.main([]), 0)
            collect.assert_called_once()
            self.assertEqual(serial.call_args.args[0], files)
            # 队列模式必须把文件级并发强制为 1。
            action = serial.call_args.args[1]
            action(Path("a.mp4"))
            self.assertEqual(process.call_args.args[2]["jobs"], 1)


if __name__ == "__main__":
    unittest.main()