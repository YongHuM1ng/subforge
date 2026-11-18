"""3/4 号启动器的队列模式入口。

3 号启动器把翻译当作批量任务：拖入一个或多个 SRT 都走本脚本，逐个调用
translate_srt.py，文件之间严格串行。
4 号启动器拖单个文件时仍走 start_polish.ps1（可以输入本次润色意见）；
双击不带文件、或一次拖入多个时由启动器调用本脚本。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from common.console import emit, setup_streams
from common.queue import collect_files, resolve_files, run_serial
from srt_translator.track import analysis_sidecar, polished_output

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
PROGRAM = SRC / "translate_srt.py"
CONFIG = ROOT / "config.toml"


def _run_translate(srt: Path) -> bool:
    print(f"· 调用翻译：{srt.name}", flush=True)
    command = [sys.executable, str(PROGRAM), str(srt), "--config", str(CONFIG)]
    return subprocess.run(command, cwd=str(ROOT)).returncode == 0


def _resolve_original(translated: Path) -> tuple[Path | None, str, str]:
    """从 作品名.目标语言.analysis.json 读取原始 SRT 与目标语言（润色产物也能反查）。"""
    sidecar = analysis_sidecar(translated)
    if not sidecar.exists():
        return None, "", f"找不到分析文件：{sidecar.name}"
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return None, "", f"无法读取分析文件 {sidecar.name}：{exc}"
    if not isinstance(data, dict):
        return None, "", f"分析文件格式无效：{sidecar.name}"
    saved = str(data.get("input") or "").strip()
    if not saved:
        return None, "", f"分析文件没有记录原始 SRT：{sidecar.name}"
    original = Path(saved)
    if not original.is_absolute():
        original = sidecar.parent / original
    try:
        original = original.resolve()
    except OSError:
        pass
    if original.suffix.lower() != ".srt":
        return None, "", f"分析文件记录的原始文件不是 SRT：{original}"
    if not original.exists():
        return None, "", f"原始 SRT 不存在：{original}"
    target = str(data.get("target") or "").strip()
    return original, target, ""


def _run_polish(translated: Path) -> bool:
    original, target, problem = _resolve_original(translated)
    if original is None:
        emit(f"[跳过] {translated.name}：{problem}", file=sys.stderr)
        return False
    output = polished_output(translated)
    command = [
        sys.executable, str(PROGRAM), str(original), str(output),
        "--translated", str(translated), "--config", str(CONFIG),
        "--analysis-file", str(analysis_sidecar(translated)),
    ]
    if target:
        command += ["--target", target]
    print(f"· 调用润色：{translated.name}", flush=True)
    return subprocess.run(command, cwd=str(ROOT)).returncode == 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SRT 队列模式：逐个执行翻译或润色")
    parser.add_argument("mode", choices=("translate", "polish"), help="translate = 只翻译；polish = 只润色")
    parser.add_argument("files", nargs="*", help="直接拖入的 SRT；省略时从控制台收集")
    return parser


def collect_paths(files: list[str], title: str) -> list[Path]:
    """已有文件参数时直接校验；否则进入交互式收集。"""
    if files:
        paths, issues = resolve_files(files, base_dir=Path.cwd(), accept_exts={".srt"})
        if issues:
            for raw, problem in issues:
                emit(f"[错误] {raw}：{problem}", file=sys.stderr)
            return []
        return paths
    return collect_files({".srt"}, base_dir=Path.cwd(), title=title)


def main(argv: list[str]) -> int:
    setup_streams()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not CONFIG.exists():
        example = ROOT / "config.toml.example"
        if example.exists():
            shutil.copyfile(example, CONFIG)
            emit(f"[提示] 已从 {example.name} 创建 config.toml，请填写 API 配置后重新运行。",
                 file=sys.stderr)
            return 2
        emit(f"[错误] 找不到配置文件：{CONFIG}", file=sys.stderr)
        print("请复制 config.toml.example 为 config.toml 并填写。", file=sys.stderr)
        return 2

    if args.mode == "translate":
        title = "[队列] 只翻译 SRT"
        action = _run_translate
    else:
        title = "[队列] 只润色 SRT"
        print("队列模式不询问润色意见，使用 config.toml 的现有配置；", flush=True)
        print("缺少 .analysis.json、无法找到原始 SRT 的文件会被跳过并记为失败。", flush=True)
        action = _run_polish

    paths = collect_paths(args.files, title)
    if not paths:
        if not args.files:
            print("用法：双击启动器进入队列模式并拖入文件；或把 SRT 拖到启动器上直接处理。")
        return 1
    return run_serial(paths, action)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))