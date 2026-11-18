import unittest

from srt_translator.tui import _wrap, display_width, fit_widths, render_table


class TuiTest(unittest.TestCase):
    def assert_aligned(self, lines, second_column):
        """第二列在每一行的起始显示位置一致，且行尾不留空格。"""
        offsets = set()
        for line in lines:
            self.assertEqual(line, line.rstrip(), "行尾不应补空格")
            for text in second_column:
                if text in line:
                    offsets.add(display_width(line[:line.index(text)]))
        self.assertEqual(len(offsets), 1, "表格列必须对齐")

    def test_display_width(self):
        self.assertEqual(display_width("abc"), 3)
        self.assertEqual(display_width("駅前"), 4)
        self.assertEqual(display_width("aあ"), 3)

    def test_table_alignment(self):
        lines = render_table(
            ["原文", "译文"],
            [["駅前", "车站前"], ["こんにちは", "你好"]],
            max_width=60,
        )
        self.assert_aligned(lines, ["译文", "车站前", "你好"])
        text = "\n".join(lines)
        self.assertIn("駅前", text)
        self.assertIn("车站前", text)

    def test_fit_widths_equal_text_columns(self):
        widths = fit_widths(3, 118, fixed={0: 5}, weights=[0, 1, 1])
        self.assertEqual(widths[0], 5)
        self.assertEqual(widths[1], widths[2])
        self.assertLessEqual(sum(widths) + 4, 118)

    def test_table_wraps_long_cells(self):
        lines = render_table(
            ["编号", "润色前", "润色后"],
            [["1", "这是一段很长的润色前文本" * 3, "这是一段很长的润色后文本" * 3]],
            max_width=42,
        )
        self.assertTrue(all(display_width(line) <= 42 for line in lines))

    def test_ansi_width_is_ignored(self):
        self.assertEqual(display_width("\033[33m中文\033[0m"), 4)

    def test_table_alignment_with_ansi(self):
        lines = render_table(
            ["原文", "译文"],
            [["\033[33m駅前\033[0m", "\033[33m车站前\033[0m"]],
            max_width=60,
        )
        self.assert_aligned(lines, ["译文", "车站前"])

    def test_wrap_keeps_ansi_sequences_intact(self):
        raw = "\033[33mabcdef\033[0m"
        lines = _wrap(raw, 3)
        self.assertEqual("".join(lines), raw)
        self.assertEqual([display_width(line) for line in lines], [3, 3])


if __name__ == "__main__":
    unittest.main()