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

    def test_common_config_has_translation_defaults(self):
        data = tomllib.loads((ROOT / "config.common.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["api"]["endpoint"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(data["api"]["model"], "deepseek-flash")
        self.assertEqual(data["api"]["reasoning_effort"], "low")
        self.assertEqual(data["asr"]["preset"], "mimo")
        self.assertEqual(data["translation"]["target"], "简体中文")
        self.assertFalse(data["translation"]["polish"])
        self.assertNotIn("processing", data)

    def test_common_config_uses_mimo_preset(self):
        with patch.dict(os.environ, {"ASR_PRESET": "", "ASR_PROTOCOL": "",
                                     "ASR_API_KEY_ENV": "", "ASR_AUDIO_FORMAT": "",
                                     "ASR_LANGUAGE": ""}):
            values = load_asr_config(ROOT / "config.common.toml",
                                     ROOT / "tests" / "nonexistent.env")
        self.assertEqual(values["protocol"], "chat_completions")
        self.assertEqual(values["api_url"], "https://api.xiaomimimo.com/v1/chat/completions")
        self.assertEqual(values["model"], "mimo-v2.5-asr")
        self.assertEqual(values["api_key_env"], "ASR_API_KEY")
        self.assertEqual(values["api_key_header"], "api-key")
        self.assertEqual(values["api_key_prefix"], "")
        self.assertEqual(values["audio_format"], "data_url")
        self.assertEqual(values["language"], "zh")
        self.assertEqual(values["timestamps"], "none")

    def test_preset_fields_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.toml"
            config.write_text(
                '[asr]\npreset = "mimo"\nlanguage = "ja"\nmodel = "custom"\n',
                encoding="utf-8",
            )
            values = load_asr_config(config, Path(folder) / "missing.env")
        self.assertEqual(values["protocol"], "chat_completions")
        self.assertEqual(values["api_key_env"], "ASR_API_KEY")
        self.assertEqual(values["language"], "ja")
        self.assertEqual(values["model"], "custom")

    def test_env_preset_applies_defaults(self):
        with patch.dict(os.environ, {"ASR_PRESET": "mimo", "ASR_PROTOCOL": "",
                                     "ASR_API_KEY_ENV": "", "ASR_AUDIO_FORMAT": "",
                                     "ASR_LANGUAGE": ""}):
            values = load_asr_config(ROOT / "tests" / "nonexistent.toml",
                                     ROOT / "tests" / "nonexistent.env")
        self.assertEqual(values["protocol"], "chat_completions")
        self.assertEqual(values["model"], "mimo-v2.5-asr")
        self.assertEqual(values["api_key_env"], "ASR_API_KEY")
        self.assertEqual(values["timestamps"], "none")

    def test_openai_preset_resolves(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.toml"
            config.write_text('[asr]\npreset = "openai"\n', encoding="utf-8")
            with patch.dict(os.environ, {"ASR_PRESET": "", "ASR_PROTOCOL": "",
                                         "ASR_API_KEY_ENV": "", "ASR_AUDIO_FORMAT": "",
                                         "ASR_LANGUAGE": ""}):
                values = load_asr_config(config, Path(folder) / "missing.env")
        self.assertEqual(values["protocol"], "openai_transcriptions")
        self.assertEqual(values["api_url"], "https://api.openai.com/v1/audio/transcriptions")
        self.assertEqual(values["model"], "whisper-1")
        self.assertEqual(values["api_key_env"], "ASR_API_KEY")
        self.assertEqual(values["timestamps"], "word")


if __name__ == "__main__":
    unittest.main()