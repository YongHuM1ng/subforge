import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from asr.config import ASR_DEFAULTS, load_asr_config

ROOT = Path(__file__).resolve().parents[1]


class ConfigExampleTest(unittest.TestCase):
    def test_example_uses_known_asr_fields(self):
        data = tomllib.loads((ROOT / "config.toml.example").read_text(encoding="utf-8"))
        self.assertLessEqual(set(data["asr"]), set(ASR_DEFAULTS))
        self.assertIn("pause_before_polish", data["translation"])
        self.assertNotIn("options", data.get("models", {}))
        self.assertIn("fallback_enabled", data["models"])
        self.assertIn("fallback", data["models"])

    def test_example_loads(self):
        with patch.dict(os.environ, {"ASR_MODEL": "", "ASR_PROXY": ""}):
            values = load_asr_config(ROOT / "config.toml.example",
                                     ROOT / "tests" / "nonexistent.env")
        self.assertEqual(values["model"], ASR_DEFAULTS["model"])
        self.assertIn("proxy", values)

    def test_asr_proxy_falls_back_to_api_section(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.toml"
            config.write_text('[api]\nproxy = "http://127.0.0.1:7890"\n', encoding="utf-8")
            with patch.dict(os.environ, {"ASR_PROXY": ""}):
                values = load_asr_config(config, Path(folder) / "missing.env")
        self.assertEqual(values["proxy"], "http://127.0.0.1:7890")


if __name__ == "__main__":
    unittest.main()