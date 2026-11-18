# 安装与配置

## 环境要求

- Windows 10/11
- Python 3.11 或更高
- `ffmpeg`（识别阶段用于抽音轨、探测音频流和检测静音；便携版分自带 ffmpeg 和手动放置两种）
- 一个 OpenAI-compatible Chat Completions 服务（翻译用）
- 一个 OpenRouter API Key（识别用）

## 便携包（Windows 10/11 x64，不用安装 Python）

从 [GitHub Releases](https://github.com/YongHuM1ng/subforge/releases) 下载：

| 包 | 说明 |
|---|---|
| `SubForge-<版本>-windows-x64-portable.zip` | 不含 ffmpeg，需要安装到 PATH 或放到 `tools\ffmpeg\bin` |
| `SubForge-<版本>-windows-x64-portable-ffmpeg.zip` | 自带 LGPL 构建的 ffmpeg，解压即用 |
| `SubForge-<版本>-windows-x64-portable-ffmpeg.7z` | 同上，体积更小；Windows 10 需用 7-Zip 解压 |

不带 ffmpeg 的版本只提供 zip。

便携包只支持 64 位 Windows：内置的是 Windows amd64 embeddable Python 和 win64
静态 ffmpeg。32 位 Windows、ARM64、Linux、macOS 不能直接运行。

解压后直接双击启动器。便携包内置 `runtime\python`，启动器会优先使用它；
源码开发环境没有 `runtime` 时自动回退到 `.venv\Scripts\python.exe`。

第一次识别会提示输入 OpenRouter Key；翻译前需要编辑 `config.toml` 的 `[api]` 段。

## 安装

```powershell
cd D:\AI\translate
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`src/asr/` 与入口 `src/asr2srt.py` 只依赖标准库；`aiohttp` 只有翻译工具需要。
也可以直接用 `.venv\Scripts\python.exe`，不必激活环境。

开发和跑 lint / 测试时，再装上开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

检查 ffmpeg：

```powershell
ffmpeg -version
```

### ffmpeg

识别阶段需要 `ffmpeg`。查找顺序：

1. 环境变量 `FFMPEG_BIN`
2. 系统 PATH
3. 项目内的 `tools\ffmpeg\bin`

没有安装时，可以从 [ffmpeg.org 下载页](https://ffmpeg.org/download.html) 获取，解压后把
`ffmpeg.exe` 放到：

```text
tools\ffmpeg\bin\ffmpeg.exe
```

GitHub Releases 提供两种便携包：

| 包 | 说明 |
|---|---|
| `SubForge-<版本>-portable.zip` | 不含 ffmpeg，需要安装到 PATH 或放到上面的目录 |
| `SubForge-<版本>-portable-ffmpeg.zip` | 自带 LGPL 构建的 ffmpeg，解压即用 |

源码运行时不自动下载 ffmpeg。附带版中 ffmpeg 的来源、许可证和可替换说明见
`tools\ffmpeg\NOTICE.txt`。

## 两个 Key

| 用途 | 存放位置 | 环境变量（可选） |
|---|---|---|
| ASR（OpenRouter） | 项目根目录 `.env` 的 `OPENROUTER_API_KEY` | `OPENROUTER_API_KEY` |
| 翻译 | 项目根目录 `.env` 的 `LLM_API_KEY` | `LLM_API_KEY` |

- ASR 第一次运行时会在控制台提示粘贴 Key，输入时不显示，并自动写入 `.env`。
- 翻译工具启动时会自动读取项目根目录的 `.env`；已存在的环境变量优先。
- `.env` 和 `config.toml` 都已加入 `.gitignore`，不要对外发送或提交。
- 密钥建议只放在 `.env`，`config.toml` 的 `[api] api_key` 留空。

> 如果 Key 曾经泄露，请立刻到服务商后台撤销并重新生成。

## 识别配置（[asr]）

`asr2srt.py` 和 `workflow.py` 会读取 `config.toml` 的 `[asr]` 段；不写则使用默认值：

```toml
[asr]
api_url = "https://openrouter.ai/api/v1/audio/transcriptions"
model = "microsoft/mai-transcribe-2"
workers = 8
jobs = 1
min_chunk = 20.0
max_chunk = 60.0
target_chunk = 45.0
silence_noise = "-32dB"
silence_min = 0.35
fallback_chunk = 15.0
line_width = 42
max_lines = 2
min_cue = 1.0
max_cue = 7.0
min_gap = 0.06
price_per_hour = 0.10
# 时间戳粒度：word / segment / none；接口不接受时报错并提示改这里
timestamps = "word"
# 不填时沿用 [api] proxy；需要单独指定时再取消注释
# proxy = "http://127.0.0.1:7890"
```

环境变量 `ASR_API_URL` / `ASR_MODEL` / `ASR_WORKERS` / `ASR_PROXY` / `ASR_TIMESTAMPS` 优先级更高。

翻译侧的 `config.toml` 在启动时会校验：数值超出范围、布尔值写成带引号的字符串、
`structured_output` / `translation_fidelity` 取值不合法时直接报错并列出全部问题；
拼错的字段名（如把 `max_workers` 写成 `workers`）会打印 `[提示]`。

## 翻译配置

从模板复制：

```powershell
Copy-Item .\config.toml.example .\config.toml
notepad .\config.toml
```

`[api]` 常用项：

```toml
[api]
endpoint = "https://api.openai.com/v1/chat/completions"
model = "gpt-4o-mini"
api_key = ""
timeout = 120
retries = 2
# json_schema：严格 JSON Schema（推荐，但部分代理不支持）
# json_object：兼容性更好
# none：不发送 response_format
structured_output = "json_object"
# system = 使用系统代理（无则直连，默认）；none = 从不走代理；也可填 http://host:port
proxy = "system"
```

`[translation]`：

```toml
[translation]
source = "自动识别"
target = "简体中文"
polish = true
```

`[processing]`：

```toml
[processing]
batch_size = 20
context = 3
global_analysis = true
max_workers = 2
```

## 代理

默认 `proxy = "system"`：读取系统/IE 代理以及 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`，没有配置就直连。

```powershell
.\.venv\Scripts\python.exe src\translate_srt.py input.srt --proxy none
.\.venv\Scripts\python.exe src\translate_srt.py input.srt --proxy http://127.0.0.1:7890
```

识别侧也支持代理：优先读 `[asr] proxy`，没有时沿用 `[api] proxy`，
所以通常只配置一次 `[api] proxy` 即可让识别和翻译都走代理。
也可以用环境变量 `ASR_PROXY` 覆盖。

## 模型配置与切换

默认模型来自 `[api] model`。启动时直接指定（只对本次运行有效）：

```powershell
.\.venv\Scripts\python.exe src\translate_srt.py input.srt --model "gemini-3.7-flash-high"
```

> `[models] options` 是旧版 WebUI 的遗留配置，当前代码不会读取；切换模型请用 `--model`
> 或下面的分阶段模型。

> 不同服务商的模型不能共用同一个 endpoint/key。需要切换服务商时，修改 `config.toml` 的 `[api]`，或用 `--endpoint` 临时指定。

### 分阶段模型

分析、翻译、润色三个阶段对能力的要求不同，可以分别指定：

```toml
[models]
# 不填则使用 [api] model
analysis = "qwen-plus"          # 全文分析：上下文大、便宜优先
translation = "gpt-4o"          # 翻译：质量瓶颈，用最强的模型
polish = "gpt-4o-mini"          # 润色：可同翻译模型，或降一档省时间
```

也可以用命令行临时覆盖：

```powershell
.\.venv\Scripts\python.exe src\translate_srt.py "movie.asr.ja.srt" `
    --analysis-model qwen-plus `
    --translation-model gpt-4o `
    --polish-model gpt-4o-mini
```

建议：

- **分析**：用便宜、上下文窗口大的模型即可；它只负责主题/术语/可疑片段。
- **翻译**：这是决定成片质量的一步，尽量用最强模型。
- **润色**：想省钱可以降一档，但润色也会改动译文，质量敏感时保持与翻译同档。
- 三个模型必须能通过同一个 `endpoint`/`key` 调用。
- 不使用批次缓存；换模型后直接重跑即可，不会复用上一次的结果。

### 内容审查回退

有些字幕内容可能触发模型的内容审查/拒答。可以配置一个回退模型：

```toml
[models]
# 是否启用模型回退
fallback_enabled = true
# 默认回退模型；留空表示不启用
fallback = "gpt-4o-mini"

# 可选：按阶段覆盖；不填则使用上面的 fallback
# analysis_fallback = "qwen-plus"
# translation_fallback = "gpt-4o-mini"
# polish_fallback = "gpt-4o-mini"
```

行为：

- 只对内容审查/拒答触发：HTTP 200 空 `choices`、`finish_reason=content_filter`、
  `message.refusal`，或 HTTP 400/403 命中审查关键词。
- 主模型最多请求 3 次（首次 + 2 次重试）。仍失败时，当前批次和同阶段后续批次改用回退模型。
- 回退模型也最多请求 3 次；仍失败则报错。
- 分析、翻译、润色三个阶段互相独立；一个阶段回退不会改变另外两个阶段的主模型。
- `fallback_enabled = false` 会关闭回退；也可以用 `--no-fallback` 只对本次运行关闭。
  关闭后仍会重试 3 次，然后报错。
- 回退模型必须和主模型共用同一个 `endpoint` / `key`，并且支持当前的
  `structured_output`；不支持时会报 HTTP 400，需要改成 `json_object` 或 `none`。
- 分析请求会打印 `[模型]`；翻译/润色批次的表格标题（或 `--quiet` 进度行）会带当前模型，
  回退时额外打印 `[回退]` 提示。

## 推荐配置

第三方代理先保守一点：

```toml
[api]
timeout = 120
retries = 2
structured_output = "json_object"

[processing]
batch_size = 10
context = 3
global_analysis = false
max_workers = 1
```

稳定后再提高：

```toml
batch_size = 20
max_workers = 2
global_analysis = true
```