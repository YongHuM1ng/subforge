import unittest

from srt_translator.languages import language_profile
from srt_translator.textwrap import display_width, wrap_text


class TextWrapTest(unittest.TestCase):
    def test_profiles(self):
        self.assertEqual(language_profile("简体中文").code, "zh")
        self.assertEqual(language_profile("ja").code, "ja")
        self.assertEqual(language_profile("英文").code, "en")
        self.assertEqual(language_profile("未知语言").code, "")

    def test_english_respects_max_lines(self):
        text = "This is a fairly long English subtitle line that should be wrapped without losing any words."
        lines = wrap_text(text, "英文")
        self.assertLessEqual(len(lines), 2)
        self.assertEqual(" ".join(lines), text)

    def test_japanese_wrap_counts_fullwidth(self):
        text = "これは字幕のタイミングを確認するための、少し長めのテスト文章です。もう一文つけ加えて長さを稼ぎます。"
        lines = wrap_text(text, "日语")
        self.assertLessEqual(len(lines), 2)
        self.assertEqual("".join(lines), text)

    def test_chinese_wrap(self):
        text = "这是一句很长的中文字幕，用来测试自动折行功能是否正常工作，并且不会丢失任何内容。"
        lines = wrap_text(text, "简体中文")
        self.assertLessEqual(len(lines), 2)
        self.assertEqual("".join(lines), text)
        self.assertTrue(all(display_width(line) <= 40 for line in lines))

    def test_punctuation_not_at_line_start(self):
        lines = wrap_text("这是一句测试字幕。新的句子从这里开始。", "简体中文")
        self.assertFalse(any(line.startswith("。") for line in lines))

    def test_empty(self):
        self.assertEqual(wrap_text("   ", "简体中文"), [])


if __name__ == "__main__":
    unittest.main()