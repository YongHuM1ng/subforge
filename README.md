# SubForge

[![CI](https://github.com/YongHuM1ng/subforge/actions/workflows/ci.yml/badge.svg)](https://github.com/YongHuM1ng/subforge/actions/workflows/ci.yml)

把视频变成字幕，再把字幕变成目标语言。两个核心程序保持独立，`src/workflow.py` 只负责串联。

| 模块 | 职责 |
|---|---|
| `src/asr/` | 识别能力：配置、文本断句、音轨切片、转写、cue、主流程 |
| `src/srt_translator/` | 翻译底层：客户端、提示词、流水线、SRT、折行 |
| `src/asr2srt.py` / `translate_srt.py` / `workflow.py` / `queue_srt.py` | 命令行与启动器入口 |

## 快速开始

1. 首次使用请看 [安装与配置](docs/install.md)：建好 `.venv`、`config.toml`，并设置两个 Key。
2. 把视频拖到启动器上：

| 启动器 | 作用 | 产物 |
|---|---|---|
| `1_视频转字幕.cmd` | 只识别 | `作品名.asr.语言.srt` |
| `2_视频转字幕并翻译.cmd` | 识别 + 翻译 | 上面那条，以及 `作品名.目标语言.srt` |
| `3_只翻译SRT.bat` | 翻译已有 SRT（可多选，含润色） | `作品名.目标语言.srt` |
| `4_只润色SRT.bat` | 重新润色已有译文 | `作品名.目标语言.polished.srt` |

双击启动器（不带文件）会进入队列模式：把文件拖进窗口，可多次拖入，每批回车换行，
最后按一次空行回车开始。文件之间严格串行，单个失败不影响后续，结束时统一汇总。

## 免安装便携包

不想安装 Python：从 [Releases](https://github.com/YongHuM1ng/subforge/releases) 下载：

| 包 | 说明 |
|---|---|
| `SubForge-<版本>-portable.zip` | 不含 ffmpeg，需要安装到 PATH 或放到 `tools\ffmpeg\bin` |
| `SubForge-<版本>-portable-ffmpeg.zip` | 自带 LGPL 构建的 ffmpeg / ffprobe，解压即用 |

解压后双击启动器即可。首次识别会提示输入 OpenRouter Key；翻译前编辑 `config.toml`
的 `[api]` 段。便携包使用 `runtime\python`，不需要本机安装 Python。

## 功能

**识别（ASR）**

- 静音自适应切片（20–60 秒），长视频时间轴不漂移
- `verbose_json` + 词级时间戳；接口不接受时报错并提示改 `[asr] timestamps`（word / segment / none）
- 并发请求、失败重试，按音频秒数计费
- 不做跨运行缓存；识别失败重跑会重新请求所有分片；某一片最终失败时立即取消其余未发出的请求
- 输出命名自动带 `asr` 与语言标记，直接对接翻译工具
- 接口、模型、并发、切片、排版、计费参数均可在 `config.toml` 的 `[asr]` 段配置

**翻译**

- 自动识别源语言、分批翻译、前后文上下文
- 全文主题/风格/术语/ASR 纠错分析
- 翻译后润色；支持 JSON Schema / JSON Object
- 可保存分析结果，之后跳过分析和翻译，直接重新润色已有译文
- 异步并发、失败重试；不使用批次缓存，某批最终失败时取消其余批次
- 润色阶段失败时先保存未润色的译文和分析文件，可直接拖到 `4_只润色SRT.bat` 续跑
- 内容审查/拒答时自动重试，仍失败则回退到配置的模型（可按阶段覆盖）
- 分析/翻译/润色的每批输出都会显示当前使用的模型
- 视频流程已有 ASR 字幕时跳过识别、已有译文时跳过翻译（`--redo-asr` / `--redo-translate` 可强制重做）
- 终端输出：阶段分隔标题、任务概览、批次耗时；润色表只列有改动的字幕；
  颜色只在真实终端里显示（Windows 控制台自动开启），`NO_COLOR=1` 可关闭
- 按目标语言自动折行（中文 16 字/行、日文 20 字/行、英文 42 字符/行）
- 保留 NSFW、暴力、粗俗等原始表达

## 项目结构

```text
translate/
├── 1_视频转字幕.cmd
├── 2_视频转字幕并翻译.cmd
├── 3_只翻译SRT.bat
├── 4_只润色SRT.bat
├── src/
│   ├── asr/
│   │   ├── config.py            # 常量、配置、环境变量
│   │   ├── text.py              # 断句、显示宽度、折行
│   │   ├── media.py             # 音轨探测、静音切片
│   │   ├── transcribe.py        # 请求、重试、并发、语言识别
│   │   ├── cues.py              # 时间轴、cue、SRT/TXT
│   │   ├── engine.py            # 识别主流程
│   │   ├── ffmpeg.py            # ffmpeg/ffprobe 查找
│   │   ├── keys.py              # OpenRouter 密钥
│   │   └── cli.py               # 命令行
│   ├── asr2srt.py               # 识别命令行入口（实现在 asr.cli）
│   ├── workflow.py              # ASR → 翻译的串联入口
│   ├── translate_srt.py         # 翻译命令行入口
│   ├── common/                  # 代理、原子写入、路径、显示宽度
│   │   ├── io.py
│   │   ├── net.py
│   │   ├── paths.py
│   │   └── textwidth.py
│   ├── start_polish.ps1         # 4 号启动器的实现
│   └── srt_translator/          # 翻译底层实现
│       ├── client.py            # HTTP / 重试 / 结构化输出
│       ├── config.py
│       ├── languages.py         # 语言宽度与排版规则
│       ├── models.py
│       ├── pipeline.py          # 分析 / 翻译 / 润色可独立调用
│       ├── prompts.py
│       ├── srt.py
│       ├── textwrap.py          # 译文折行
│       └── track.py             # 文件名解析 / 输出命名
├── docs/
├── packaging/
│   └── build_portable.py        # 构建 Windows 免安装便携包
├── tests/
├── temp/                        # 运行临时文件，可随时删除
├── tools/                       # 手动放置或打包时加入的 ffmpeg（不提交）
├── config.toml                  # 本地配置（密钥已移到 .env）
├── config.toml.example
└── .env                         # 密钥，不要提交
```

## 开发

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

`pyproject.toml` 同时提供包元数据、`ruff` 配置和可编辑安装；GitHub Actions 会在
每次 push / PR 时跑 lint 和全部测试。

## 文档

- [安装与配置](docs/install.md)：Python、ffmpeg、`.venv`、`config.toml`、API Key、代理、模型选择
- [使用与工作流](docs/usage.md)：启动器、命令行、参数、性能建议
- [文件名标准](docs/naming.md)：`作品名.来源.语言.srt` 与输出命名
- [内部机制](docs/internals.md)：处理流程、上下文、全文分析、失败重跑、敏感内容
- [常见问题](docs/troubleshooting.md)：HTTP 错误、卡住、输出未生成
- [项目文件设计稿](docs/project-file.md)：规划中的持久化项目文件、断点续跑与重新润色（尚未实现）

## 许可证

本项目采用 [MIT License](LICENSE)。

本项目仅提供字幕文件处理和远端模型调用功能。使用者需要自行遵守所在地法律法规、模型服务商条款以及输入内容的版权和使用权限要求。