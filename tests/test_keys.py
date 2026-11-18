import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asr import config
from asr.keys import read_env_key, save_key


class SaveKeyTest(unittest.TestCase):
    def test_replaces_only_exact_key(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            env.write_text(
                "ASR_API_KEY_BACKUP=old-backup\n"
                "ASR_API_KEY=old\n"
                "# comment\n",
                encoding="utf-8",
            )
            save_key(env, "new")
            text = env.read_text(encoding="utf-8")
            self.assertIn("ASR_API_KEY_BACKUP=old-backup", text)
            self.assertIn("ASR_API_KEY=new", text)
            self.assertNotIn("ASR_API_KEY=old\n", text)
            self.assertIn("# comment", text)

    def test_appends_when_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            env.write_text("LLM_API_KEY=x\n", encoding="utf-8")
            save_key(env, "new")
            self.assertIn("ASR_API_KEY=new", env.read_text(encoding="utf-8"))

    def test_custom_key_name(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            save_key(env, "custom-secret", "CUSTOM_ASR_KEY")
            self.assertIn("CUSTOM_ASR_KEY=custom-secret",
                          env.read_text(encoding="utf-8"))

    def test_read_env_key_uses_configured_name(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".env").write_text("CUSTOM_ASR_KEY=secret\n", encoding="utf-8")
            with patch.object(config, "ROOT", root), \
                    patch.object(config, "API_KEY_ENV", "CUSTOM_ASR_KEY"):
                key, path = read_env_key()
            self.assertEqual(key, "secret")
            self.assertEqual(path, root / ".env")


if __name__ == "__main__":
    unittest.main()