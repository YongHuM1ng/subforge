import unittest

from srt_translator.srt import dump_srt, parse_srt, parse_timing

SAMPLE = """1
00:00:01,000 --> 00:00:02,500
こんにちは

2
00:00:03,000 --> 00:00:04,000
テストです
"""


class SrtTest(unittest.TestCase):
    def test_parse_and_dump_roundtrip(self):
        cues = parse_srt(SAMPLE)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].number, "1")
        self.assertEqual(cues[1].text, "テストです")
        self.assertEqual(parse_srt(dump_srt(cues)), cues)

    def test_parse_bom(self):
        cues = parse_srt("﻿" + SAMPLE)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].number, "1")

    def test_parse_invalid(self):
        with self.assertRaises(ValueError):
            parse_srt("not a subtitle")

    def test_timing(self):
        self.assertEqual(parse_timing("00:01:02,500 --> 00:01:03,000"), (62.5, 63.0))


if __name__ == "__main__":
    unittest.main()