import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import queue_srt
from common.queue import collect_files, run_serial, split_drag_line


def _quoted(*paths: Path) -> str:
    return " ".join(f'"{path}"' for path in paths)


class SplitDragLineTest(unittest.TestCase):
    def test_multiple_quoted_paths(self):
        line = '"D:\\movies\\a b.mp4" "D:\\movies\\c.mkv"'
        self.assertEqual(split_drag_line(line),
                         ["D:\\movies\\a b.mp4", "D:\\movies\\c.mkv"])

    def test_unquoted_paths(self):
        self.assertEqual(split_drag_line("a.mp4 b.mkv"), ["a.mp4", "b.mkv"])

    def test_single_quotes(self):
        self.assertEqual(split_drag_line("'a b.srt'"), ["a b.srt"])

    def test_blank_line(self):
        self.assertEqual(split_drag_line("   "), [])


class CollectFilesTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def touch(self, name: str) -> Path:
        path = self.root / name
        path.write_text("x", encoding="utf-8")
        return path

    def collect(self, stdin_text: str, accept_exts=None):
        out = io.StringIO()
        paths = collect_files(
            accept_exts or {".mp4"},
            base_dir=self.root,
            title="[队列] 测试",
            stream=out,
            stdin=io.StringIO(stdin_text),
        )
        return paths, out.getvalue()

    def test_multiple_lines_until_blank(self):
        first = self.touch("a.mp4")
        second = self.touch("b.mp4")
        paths, _ = self.collect(f"{first}\n{second}\n\n")
        self.assertEqual(paths, [first.resolve(), second.resolve()])

    def test_multiple_files_on_one_line(self):
        first = self.touch("a.mp4")
        second = self.touch("b.mp4")
        paths, _ = self.collect(_quoted(first, second) + "\n\n")
        self.assertEqual(paths, [first.resolve(), second.resolve()])

    def test_chinese_and_spaces_in_path(self):
        video = self.touch("中文 视频.mp4")
        paths, _ = self.collect(f'"{video}"\n\n')
        self.assertEqual(paths, [video.resolve()])

    def test_duplicates_removed_keeping_order(self):
        first = self.touch("a.mp4")
        second = self.touch("b.mp4")
        paths, _ = self.collect(f"{first}\n{second}\n{first}\n\n")
        self.assertEqual(paths, [first.resolve(), second.resolve()])

    def test_invalid_input_clears_batch_and_retries(self):
        good = self.touch("a.mp4")
        missing = self.root / "missing.mp4"
        paths, output = self.collect(f'{missing}\n"{good}"\n\n{good}\n\n')
        self.assertEqual(paths, [good.resolve()])
        self.assertIn("文件不存在", output)
        self.assertIn("本次输入已清空", output)

    def test_rejects_unsupported_extension(self):
        good = self.touch("a.mp4")
        bad = self.touch("a.srt")
        paths, output = self.collect(f"{bad}\n\n{good}\n\n")
        self.assertEqual(paths, [good.resolve()])
        self.assertIn("扩展名不受支持", output)

    def test_empty_input_returns_empty(self):
        paths, _ = self.collect("\n")
        self.assertEqual(paths, [])

    def test_eof_returns_empty(self):
        paths, _ = self.collect("")
        self.assertEqual(paths, [])


class RunSerialTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def paths(self, *names: str) -> list[Path]:
        return [self.root / name for name in names]

    def test_runs_in_order_and_continues_after_failure(self):
        calls = []

        def action(path: Path) -> bool:
            calls.append(path.name)
            if path.name == "b.mp4":
                return False
            if path.name == "c.mp4":
                raise RuntimeError("坏了")
            return True

        out = io.StringIO()
        code = run_serial(self.paths("a.mp4", "b.mp4", "c.mp4", "d.mp4"), action, stream=out)
        self.assertEqual(calls, ["a.mp4", "b.mp4", "c.mp4", "d.mp4"])
        self.assertEqual(code, 1)
        text = out.getvalue()
        self.assertIn("[队列 1/4] a.mp4", text)
        self.assertIn("[错误] c.mp4: RuntimeError: 坏了", text)
        self.assertIn("失败 2 个（b.mp4, c.mp4）", text)

    def test_all_success_returns_zero(self):
        out = io.StringIO()
        code = run_serial(self.paths("a.mp4", "b.mp4"), lambda path: True, stream=out)
        self.assertEqual(code, 0)
        self.assertIn("队列结束：成功 2 个", out.getvalue())

    def test_keyboard_interrupt_returns_130(self):
        def action(path: Path) -> bool:
            raise KeyboardInterrupt

        out = io.StringIO()
        code = run_serial(self.paths("a.mp4", "b.mp4"), action, stream=out)
        self.assertEqual(code, 130)
        self.assertIn("队列已中断", out.getvalue())


class PolishResolveTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def sidecar(self, name: str, payload: dict) -> Path:
        path = self.root / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_resolves_absolute_input(self):
        original = self.root / "movie.asr.ja.srt"
        original.write_text("x", encoding="utf-8")
        self.sidecar("movie.zh.analysis.json",
                     {"input": str(original), "target": "简体中文"})
        translated = self.root / "movie.zh.srt"
        resolved, target, problem = queue_srt._resolve_original(translated)
        self.assertEqual(resolved, original.resolve())
        self.assertEqual(target, "简体中文")
        self.assertEqual(problem, "")

    def test_resolves_relative_input_against_sidecar_dir(self):
        original = self.root / "sub" / "movie.asr.ja.srt"
        original.parent.mkdir()
        original.write_text("x", encoding="utf-8")
        self.sidecar("movie.zh.analysis.json",
                     {"input": "sub/movie.asr.ja.srt", "target": "日语"})
        resolved, target, problem = queue_srt._resolve_original(self.root / "movie.zh.srt")
        self.assertEqual(resolved, original.resolve())
        self.assertEqual(target, "日语")
        self.assertEqual(problem, "")

    def test_missing_sidecar_reports_problem(self):
        resolved, target, problem = queue_srt._resolve_original(self.root / "movie.zh.srt")
        self.assertIsNone(resolved)
        self.assertIn("找不到分析文件", problem)

    def test_invalid_sidecar_reports_problem(self):
        (self.root / "movie.zh.analysis.json").write_text("{", encoding="utf-8")
        resolved, _, problem = queue_srt._resolve_original(self.root / "movie.zh.srt")
        self.assertIsNone(resolved)
        self.assertIn("无法读取分析文件", problem)

    def test_translate_command(self):
        srt = self.root / "movie.asr.ja.srt"
        srt.write_text("x", encoding="utf-8")
        completed = mock.Mock(returncode=0)
        with mock.patch.object(queue_srt.subprocess, "run", return_value=completed) as run, \
                redirect_stdout(io.StringIO()):
            self.assertTrue(queue_srt._run_translate(srt))
        command = run.call_args.args[0]
        self.assertIn(str(srt), command)
        self.assertIn("--config", command)

    def test_polish_command_has_no_prompt(self):
        original = self.root / "movie.asr.ja.srt"
        original.write_text("x", encoding="utf-8")
        translated = self.root / "movie.zh.srt"
        translated.write_text("x", encoding="utf-8")
        self.sidecar("movie.zh.analysis.json",
                     {"input": str(original), "target": "简体中文"})
        completed = mock.Mock(returncode=0)
        with mock.patch.object(queue_srt.subprocess, "run", return_value=completed) as run, \
                redirect_stdout(io.StringIO()):
            self.assertTrue(queue_srt._run_polish(translated))
        command = run.call_args.args[0]
        self.assertIn("--translated", command)
        self.assertIn("--analysis-file", command)
        self.assertIn("--target", command)
        self.assertNotIn("--polish-prompt", command)
        self.assertIn(str(self.root / "movie.zh.polished.srt"), command)


class CollectPathsTest(unittest.TestCase):
    """3 号启动器把拖入的 SRT 作为参数传入，不再交互收集。"""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def test_accepts_given_files_in_order(self):
        first = self.root / "a.srt"
        second = self.root / "b.srt"
        first.write_text("x", encoding="utf-8")
        second.write_text("x", encoding="utf-8")
        paths = queue_srt.collect_paths([str(first), str(second), str(first)], "[队列] 测试")
        self.assertEqual(paths, [first.resolve(), second.resolve()])

    def test_rejects_missing_file(self):
        with mock.patch.object(queue_srt, "emit"):
            paths = queue_srt.collect_paths([str(self.root / "missing.srt")], "[队列] 测试")
        self.assertEqual(paths, [])

    def test_falls_back_to_interactive_collection(self):
        srt = self.root / "a.srt"
        srt.write_text("x", encoding="utf-8")
        with mock.patch.object(queue_srt, "collect_files", return_value=[srt]) as collect, \
                mock.patch("sys.stdin", io.StringIO()):
            paths = queue_srt.collect_paths([], "[队列] 测试")
        self.assertEqual(paths, [srt])
        collect.assert_called_once()


if __name__ == "__main__":
    unittest.main()