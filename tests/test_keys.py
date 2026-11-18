import tempfile
import unittest
from pathlib import Path

from asr.keys import save_key


class SaveKeyTest(unittest.TestCase):
    def test_replaces_only_exact_key(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            env.write_text(
                "OPENROUTER_API_KEY_BACKUP=old-backup\n"
                "OPENROUTER_API_KEY=old\n"
                "# comment\n",
                encoding="utf-8",
            )
            save_key(env, "new")
            text = env.read_text(encoding="utf-8")
            self.assertIn("OPENROUTER_API_KEY_BACKUP=old-backup", text)
            self.assertIn("OPENROUTER_API_KEY=new", text)
            self.assertNotIn("OPENROUTER_API_KEY=old\n", text)
            self.assertIn("# comment", text)

    def test_appends_when_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            env.write_text("LLM_API_KEY=x\n", encoding="utf-8")
            save_key(env, "new")
            self.assertIn("OPENROUTER_API_KEY=new", env.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()