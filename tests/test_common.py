import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.io import write_text_atomic
from common.net import resolve_proxy
from common.paths import unique_output_path


class ProxyTest(unittest.TestCase):
    def test_disabled_values(self):
        for value in ("", "none", "off", "direct", None):
            self.assertIsNone(resolve_proxy("https://example.com", value))

    def test_explicit_url(self):
        self.assertEqual(resolve_proxy("https://example.com", "127.0.0.1:7890"),
                         "http://127.0.0.1:7890")
        self.assertEqual(resolve_proxy("https://example.com", "socks5://127.0.0.1:1080"),
                         "socks5://127.0.0.1:1080")

    def test_system_proxy(self):
        with patch("common.net.urllib.request.getproxies",
                   return_value={"https": "127.0.0.1:7890"}):
            self.assertEqual(resolve_proxy("https://example.com", "system"),
                             "http://127.0.0.1:7890")

    def test_system_without_proxy(self):
        with patch("common.net.urllib.request.getproxies", return_value={}):
            self.assertIsNone(resolve_proxy("https://example.com", "system"))


class AtomicWriteTest(unittest.TestCase):
    def test_replaces_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "a.txt"
            write_text_atomic(path, "one", encoding="utf-8")
            write_text_atomic(path, "two", encoding="utf-8")
            self.assertEqual(path.read_text(encoding="utf-8"), "two")
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "nested" / "a.txt"
            write_text_atomic(path, "x", encoding="utf-8")
            self.assertTrue(path.exists())

    def test_utf8_sig_writes_bom(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "a.srt"
            write_text_atomic(path, "中文", encoding="utf-8-sig")
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))


class UniquePathTest(unittest.TestCase):
    def test_increments_counter(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "movie.zh.srt"
            self.assertEqual(unique_output_path(path), path)
            path.write_text("x", encoding="utf-8")
            second = unique_output_path(path)
            self.assertEqual(second.name, "movie.zh.2.srt")
            second.write_text("x", encoding="utf-8")
            self.assertEqual(unique_output_path(path).name, "movie.zh.3.srt")


if __name__ == "__main__":
    unittest.main()