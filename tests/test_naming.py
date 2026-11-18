import unittest
from pathlib import Path

from srt_translator.track import derive_output_path, output_stem, parse_track_name


class TrackNamingTest(unittest.TestCase):
    def test_new_order_source_then_language(self):
        meta = parse_track_name(Path("movie.asr.ja.srt"))
        self.assertEqual(meta.language, "ja")
        self.assertEqual(meta.source, "asr")
        self.assertFalse(meta.warning)

    def test_ocr_language(self):
        meta = parse_track_name(Path("movie.ocr.en.srt"))
        self.assertEqual(meta.language, "en")
        self.assertEqual(meta.source, "ocr")
        self.assertFalse(meta.warning)

    def test_language_only(self):
        meta = parse_track_name(Path("movie.ja.srt"))
        self.assertEqual(meta.language, "ja")
        self.assertEqual(meta.source, "")

    def test_source_only(self):
        meta = parse_track_name(Path("movie.asr.srt"))
        self.assertEqual(meta.language, "")
        self.assertEqual(meta.source, "asr")

    def test_old_order_is_flagged(self):
        meta = parse_track_name(Path("movie.ja.asr.srt"))
        self.assertTrue(meta.warning)

    def test_plain_name(self):
        meta = parse_track_name(Path("movie.srt"))
        self.assertEqual((meta.language, meta.source, meta.warning), ("", "", ""))

    def test_output_path_strips_both_markers(self):
        self.assertEqual(
            derive_output_path(Path("26.09 兔田佩克拉.asr.ja.srt"), "简体中文").name,
            "26.09 兔田佩克拉.zh.srt",
        )

    def test_output_path_language_only(self):
        self.assertEqual(derive_output_path(Path("kaguya.en.srt"), "简体中文").name, "kaguya.zh.srt")

    def test_output_stem(self):
        self.assertEqual(output_stem(Path("movie.asr.ja.srt")), "movie")

    def test_collision_counter_is_ignored(self):
        meta = parse_track_name(Path("movie.asr.ja.2.srt"))
        self.assertEqual((meta.language, meta.source), ("ja", "asr"))
        self.assertEqual(output_stem(Path("movie.asr.ja.2.srt")), "movie")
        self.assertEqual(
            derive_output_path(Path("movie.asr.ja.2.srt"), "简体中文").name, "movie.zh.srt")

    def test_numeric_title_is_not_treated_as_counter(self):
        self.assertEqual(output_stem(Path("movie.2024.zh.srt")), "movie.2024")

    def test_unknown_target_falls_back(self):
        self.assertTrue(derive_output_path(Path("movie.asr.ja.srt"), "Klingon").name.endswith(".translated.srt"))


if __name__ == "__main__":
    unittest.main()