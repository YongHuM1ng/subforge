# SubForge

[![CI](https://github.com/YongHuM1ng/subforge/actions/workflows/ci.yml/badge.svg)](https://github.com/YongHuM1ng/subforge/actions/workflows/ci.yml)

把视频变成字幕，再把字幕变成目标语言。提供 Windows 10/11 x64 免安装便携版，解压后双击启动器即可。

## 快速开始

便携包仅支持 **Windows 10/11 x64**。推荐下载自带 ffmpeg 的版本，不需要安装 Python 或 ffmpeg。

1. **下载便携包**：到 [Releases](https://github.com/YongHuM1ng/subforge/releases) 下载
   `SubForge-<版本>-windows-x64-portable-ffmpeg.zip`（自带 ffmpeg，推荐）或
   `...-ffmpeg.7z`（更小，Windows 10 需要 7-Zip 解压），解压到任意目录。
2. **配置两个 Key**

   便携包里的 `config.toml` 已经是默认配置：**小米 MiMo 识别 + DeepSeek 官方翻译**，
   **这个文件不用改**。包里已经带一个空白的 `.env`，用记事本打开填入：

   | 写入 `.env` 的变量 | 用途 | 填什么 |
   |---|---|---|
   | `ASR_API_KEY` | 语音识别 | 当前识别服务的 Key（默认小米 MiMo） |
   | `LLM_API_KEY` | 翻译 | DeepSeek 的 Key |

   - 小米 MiMo Key：到 [platform.xiaomimimo.com/console/api-keys](https://platform.xiaomimimo.com/console/api-keys) 创建。
   - DeepSeek Key：到 [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) 创建。
   - `.env` 内容：

     ```ini
     ASR_API_KEY=你的小米Key
     LLM_API_KEY=你的DeepSeekKey
     ```

   保存后程序会自动读取。

   - 只做识别：只填 `ASR_API_KEY`，拖到 `1_视频转字幕.bat`。第一次识别时如果
     `.env` 里没有 Key，程序也会提示输入并自动保存。
   - 思考等级：`config.toml` 的 `[api] reasoning_effort`，默认 `low`；
     可选 `none` / `low` / `medium` / `high` / `max`。
   - 识别换 OpenRouter：`[asr]` 改成 `preset = "openrouter"`、
     `model = "microsoft/mai-transcribe-2"`，Key 仍写 `ASR_API_KEY`。
   - 识别换标准 OpenAI：`[asr]` 改成 `preset = "openai"`。
   - 翻译换任意 OpenAI-compatible LLM API（OpenAI、OpenRouter、Qwen 等）：
     改 `[api]` 的 endpoint / model，把 Key 写到 `LLM_API_KEY`。
   - 想要完整参数：用 `config.full.toml` 覆盖 `config.toml`；默认值完全相同，行为不变。

   `.env` 和 `config.toml` 里可能有密钥，不要发给别人，也不要提交到 GitHub。
3. **拖入文件**：把视频拖到 `2_视频转字幕并翻译.bat`（识别 + 翻译），或
   `1_视频转字幕.bat`（只识别）。

| 启动器 | 作用 | 产物 |
|---|---|---|
| `1_视频转字幕.bat` | 只识别 | `作品名.asr.语言.srt` |
| `2_视频转字幕并翻译.bat` | 识别 + 翻译 | 上面那条，以及 `作品名.目标语言.srt` |
| `3_只翻译SRT.bat` | 翻译已有 SRT（可多选；润色默认关闭） | `作品名.目标语言.srt` |
| `4_只润色SRT.bat` | 重新润色已有译文 | `作品名.目标语言.polished.srt` |

双击启动器（不带文件）会进入队列模式：把文件拖进窗口，可多次拖入，每批回车换行，
最后按一次空行回车开始。文件之间严格串行，单个失败不影响后续，结束时统一汇总。

## 便携包说明

| 包 | 说明 |
|---|---|
| `SubForge-<版本>-windows-x64-portable.zip` | 不含 ffmpeg，需要安装到 PATH 或放到 `tools\ffmpeg\bin` |
| `SubForge-<版本>-windows-x64-portable-ffmpeg.zip` | 自带 LGPL 构建的 ffmpeg，解压即用 |
| `SubForge-<版本>-windows-x64-portable-ffmpeg.7z` | 同上，约 45 MB；Windows 10 需用 7-Zip 解压 |

不带 ffmpeg 的版本只提供 zip。便携包内置 `runtime\python`，不需要本机安装 Python；
32 位 Windows、ARM64、Linux、macOS 不能直接运行便携包。

## 模块

| 模块 | 职责 |
|---|---|
| `src/asr/` | 识别能力：配置、文本断句、音轨切片、转写、cue、主流程 |
| `src/srt_translator/` | 翻译底层：客户端、提示词、流水线、SRT、折行 |
| `src/asr2srt.py` / `translate_srt.py` / `workflow.py` / `queue_srt.py` | 命令行与启动器入口 |

## 功能

**识别（ASR）**

- 静音自适应切片（20–60 秒），长视频时间轴不漂移
- 支持 OpenAI-compatible ASR：内置 `openrouter` / `openai` / `mimo` 预设，也可逐项覆盖
- `verbose_json` + 词级时间戳；接口不接受时报错并提示改 `[asr] timestamps`（word / segment / none）
- 并发请求、失败重试，按音频秒数计费
- 不做跨运行缓存；识别失败重跑会重新请求所有分片；某一片最终失败时立即取消其余未发出的请求
- 输出命名自动带 `asr` 与语言标记，直接对接翻译工具
- 接口、模型、并发、切片、排版、计费参数均可在 `config.toml` 的 `[asr]` 段配置

**翻译**

- 自动识别源语言、分批翻译、前后文上下文
- 全文主题/风格/术语/ASR 纠错分析
- 翻译后润色（默认关闭，可在 `config.toml` 开启）
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
SubForge/
├── 1_视频转字幕.bat
├── 2_视频转字幕并翻译.bat
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
│   │   ├── ffmpeg.py            # ffmpeg 查找
│   │   ├── keys.py              # 识别 API Key
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
├── config.toml                  # 本地配置（不提交）
├── config.common.toml           # 默认配置（MiMo + DeepSeek）
├── config.full.toml             # 完整参数（默认值与 config.toml 相同）
└── .env                         # 密钥，不要提交
```

## 从源码运行

不用便携包时，需要本机 Python 3.11+ 和 ffmpeg。在项目根目录执行：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

启动器会优先使用 `runtime\python`，没有时回退到 `.venv\Scripts\python.exe`。
API 配置与便携版相同：翻译密钥写到 `.env` 的 `LLM_API_KEY`，识别 Key 在首次运行时输入。
源码运行时先把 `config.common.toml` 复制为 `config.toml`（需要完整参数时用
`config.full.toml`）。

详细步骤见 [安装与配置](docs/install.md)。

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