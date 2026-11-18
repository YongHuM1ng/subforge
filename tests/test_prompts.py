import unittest

from srt_translator.prompts import (
    analysis_guidance,
    correction_limit,
    polish_guidance,
    source_guidance,
    source_label,
    system_prompt,
    translation_guidance,
    typography_guidance,
)


class PromptsTest(unittest.TestCase):
    def test_language_specific_asr_hint(self):
        ja = source_guidance("asr", "ja")
        en = source_guidance("asr", "en")
        self.assertIn("日语", ja)
        self.assertIn("英语 ASR", en)
        self.assertNotEqual(ja, en)

    def test_unknown_language_falls_back_to_base(self):
        self.assertEqual(source_guidance("asr", ""), source_guidance("asr"))

    def test_typography_per_target(self):
        self.assertIn("16 个汉字", typography_guidance("简体中文"))
        self.assertIn("20 个全角字符", typography_guidance("日语"))
        self.assertIn("42 个字符", typography_guidance("英语"))

    def test_source_label(self):
        self.assertIn("自动判断", source_label("自动识别"))
        self.assertEqual(source_label("日语"), "日语")
        self.assertTrue(source_label("自动识别", "ja").startswith("日语"))

    def test_guidance_contains_typography(self):
        self.assertIn("排版", translation_guidance("asr", "natural", "ja", "日语"))
        self.assertIn("口癖", polish_guidance("asr", "natural", "日语"))

    def test_analysis_guidance_mentions_types(self):
        text = analysis_guidance("简体中文", 100)
        self.assertIn("ruby", text)
        self.assertIn("span", text)
        self.assertIn("id 只写一个字幕编号", text)

    def test_terms_use_target_language(self):
        self.assertIn("首选的英语译名", analysis_guidance("英语", 100))
        self.assertNotIn("中文译名", analysis_guidance("英语", 100))

    def test_analysis_guidance_states_top_level_keys(self):
        text = analysis_guidance("简体中文", 100)
        self.assertIn('"summary"', text)
        self.assertIn('"style"', text)
        self.assertIn('"corrections"', text)
        self.assertIn('"terms"', text)
        self.assertIn("不要改名", text)

    def test_rules_are_not_repeated(self):
        for text in (translation_guidance("asr", "natural", "ja", "简体中文"),
                     polish_guidance("asr", "natural", "简体中文")):
            self.assertLessEqual(text.count("原文没有的信息"), 1)
            self.assertEqual(text.count("翻译策略"), 1)

    def test_non_chinese_target_forbids_chinese(self):
        self.assertIn("不要混入中文", translation_guidance("asr", "natural", "ja", "英语"))
        self.assertIn("不要混入中文", polish_guidance("asr", "natural", "日语"))
        self.assertNotIn("不要混入中文", translation_guidance("asr", "natural", "ja", "简体中文"))

    def test_length_rule_mentions_duration_and_example(self):
        text = translation_guidance("asr", "natural", "ja", "简体中文")
        self.assertIn("dur", text)
        self.assertIn("每秒约 6–8 个汉字", text)
        self.assertIn("书写与标点示例", text)

    def test_system_prompts_follow_stage(self):
        self.assertIn("校对编辑", system_prompt("polish", "简体中文"))
        self.assertNotIn("优先忠实原文", system_prompt("translation", "简体中文"))
        self.assertIn("分析员", system_prompt("analysis", "简体中文"))

    def test_polish_segmentation_does_not_talk_about_literal_translation(self):
        self.assertNotIn("直译", polish_guidance("asr", "natural", "简体中文").split("润色原则")[0])

    def test_correction_limit(self):
        self.assertEqual(correction_limit(10), 20)
        self.assertEqual(correction_limit(400), 100)
        self.assertEqual(correction_limit(5000), 150)


if __name__ == "__main__":
    unittest.main()