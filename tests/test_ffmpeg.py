import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asr import config, ffmpeg


class FindToolTest(unittest.TestCase):
    def test_env_override_wins(self):
        with patch.dict(os.environ, {"FFMPEG_BIN": r"C:\custom\ffmpeg.exe"}):
            self.assertEqual(config._find_tool("ffmpeg"), r"C:\custom\ffmpeg.exe")

    def test_path_wins_over_project_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(config, "TOOLS_BIN", Path(folder)), \
                    patch("asr.config.shutil.which", return_value=r"C:\path\ffmpeg.exe"):
                self.assertEqual(config._find_tool("ffmpeg"), r"C:\path\ffmpeg.exe")

    def test_project_tools_directory_is_last_resort(self):
        with tempfile.TemporaryDirectory() as folder:
            bin_dir = Path(folder)
            exe = bin_dir / "ffmpeg.exe"
            exe.write_bytes(b"x")
            with patch.object(config, "TOOLS_BIN", bin_dir), \
                    patch("asr.config.shutil.which", return_value=None), \
                    patch.dict(os.environ, {"FFMPEG_BIN": ""}):
                self.assertEqual(config._find_tool("ffmpeg"), str(exe))


class EnsureFfmpegTest(unittest.TestCase):
    def setUp(self):
        ffmpeg._checked = False
        ffmpeg._ok = False

    def tearDown(self):
        ffmpeg._checked = False
        ffmpeg._ok = False

    def test_success_when_both_tools_exist(self):
        with patch("asr.ffmpeg.shutil.which", return_value="tool"):
            self.assertTrue(ffmpeg.ensure_ffmpeg())

    def test_missing_tool_prints_manual_path(self):
        with patch("asr.ffmpeg.shutil.which", return_value=None), \
                patch.object(config, "FFMPEG", "ffmpeg"), \
                patch.object(config, "FFPROBE", "ffprobe"), \
                patch("asr.ffmpeg.log") as log:
            self.assertFalse(ffmpeg.ensure_ffmpeg())
        text = "\n".join(str(call.args[0]) for call in log.call_args_list)
        self.assertIn("ffmpeg.exe", text)
        self.assertIn(str(config.TOOLS_BIN), text)


if __name__ == "__main__":
    unittest.main()
