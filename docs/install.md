# 安装与配置

## 环境要求

- Windows 10/11
- Python 3.11 或更高
- `ffmpeg`（识别阶段用于抽音轨、探测音频流和检测静音；便携版分自带 ffmpeg 和手动放置两种）
- 一个 OpenAI-compatible Chat Completions 服务（翻译用）
- 一个识别服务 API Key（默认小米 MiMo）

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

第一次识别会提示输入识别服务的 Key；默认是小米 MiMo，换其他服务见下文
“OpenAI-compatible ASR”。
翻译前需要编辑 `config.toml` 的 `[api]` 段。

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
| `SubForge-<版本>-windows-x64-portable.zip` | 不含 ffmpeg，需要安装到 PATH 或放到上面的目录 |
| `SubForge-<版本>-windows-x64-portable-ffmpeg.zip` | 自带 LGPL 构建的 ffmpeg，解压即用 |

源码运行时不自动下载 ffmpeg。附带版中 ffmpeg 的来源、许可证和可替换说明见
`tools\ffmpeg\NOTICE.txt`。

## 常用配置

便携包里的 `config.toml` 默认使用 **小米 MiMo 识别 + DeepSeek 官方翻译**，只列出
最常用项：翻译接口、ASR 预设、目标语言、润色开关和思考等级；没有列出的参数使用
默认值，通常不需要修改。

- 换翻译服务：改 `config.toml` 的 `[api]`，Key 写到 `.env` 的 `LLM_API_KEY`。
- 需要完整参数：用 `config.full.toml` 覆盖 `config.toml`；默认值完全相同。

## 两个 Key

| 用途 | 存放位置 | 环境变量（可选） |
|---|---|---|
| ASR（默认小米 MiMo） | 项目根目录 `.env` 的 `ASR_API_KEY` | `ASR_API_KEY` |
| 翻译（默认 DeepSeek） | 项目根目录 `.env` 的 `LLM_API_KEY` | `LLM_API_KEY` |

- ASR 第一次运行时会在控制台提示粘贴 Key，输入时不显示，并自动写入 `.env`。
- DeepSeek Key 在 [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) 创建。
- 换用其他识别服务时，默认仍然从 `.env` 的 `ASR_API_KEY` 读 Key，只需要换 Key 的值；
  如需使用别的变量名，再改 `[asr] api_key_env`。
- 翻译工具启动时会自动读取项目根目录的 `.env`；已存在的环境变量优先。
- `.env` 和 `config.toml` 都已加入 `.gitignore`，不要对外发送或提交。
- 密钥建议只放在 `.env`，`config.toml` 的 `[api] api_key` 留空。

> 如果 Key 曾经泄露，请立刻到服务商后台撤销并重新生成。

## 识别配置（[asr]）

`asr2srt.py` 和 `workflow.py` 会读取 `config.toml` 的 `[asr]` 段；不写则使用默认值。

### 预设

最常用的写法是在 `[asr]` 只写一个 `preset`：

| preset | 说明 |
|---|---|
| `mimo` | 便携包默认，小米 MiMo 的 Chat Completions ASR |
| `openrouter` | OpenRouter 的 JSON 音频转写接口 |
| `openai` | 标准 OpenAI `/audio/transcriptions`（multipart，`whisper-1`） |

所有预设默认都从 `.env` 的 `ASR_API_KEY` 读取 Key；切换 preset 时只需要换 Key 的值。

例如把现有 `[asr]` 切到 OpenRouter：

```toml
[asr]
preset = "openrouter"
model = "microsoft/mai-transcribe-2"
```

`.env` 里仍然只需 `ASR_API_KEY`；接口地址、协议、鉴权头都由预设处理。

```toml
[asr]
preset = "mimo"
# 需要覆盖预设时直接写字段，例如：
# language = "ja"
# model = "..."
```

显式写出的字段会覆盖预设，其余参数继续使用预设/默认值。

下面是完整字段参考：

```toml
[asr]
# 预设：openrouter / openai / mimo；下面的显式字段会覆盖预设
preset = "openrouter"
api_url = "https://openrouter.ai/api/v1/audio/transcriptions"
model = "microsoft/mai-transcribe-2"
# transcriptions = OpenRouter JSON；openai_transcriptions = OpenAI multipart；
# chat_completions = 音频放进 messages
protocol = "transcriptions"
# 从 .env 读取 Key 的变量名；换服务时一起改
api_key_env = "ASR_API_KEY"
# 鉴权头和前缀：OpenRouter 用 Authorization + "Bearer "
api_key_header = "Authorization"
api_key_prefix = "Bearer "
# 仅 chat_completions：data_url = "data:audio/wav;base64,..."（MiMo）；
# base64 = 纯 base64 + format = "wav"（OpenAI 标准）
audio_format = "data_url"
# 仅 chat_completions：写入 asr_options.language；留空不发送
language = ""
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

环境变量 `ASR_PRESET` / `ASR_API_URL` / `ASR_MODEL` / `ASR_PROTOCOL` /
`ASR_API_KEY_ENV` / `ASR_API_KEY_HEADER` / `ASR_API_KEY_PREFIX` / `ASR_AUDIO_FORMAT` /
`ASR_LANGUAGE` / `ASR_WORKERS` / `ASR_PROXY` / `ASR_TIMESTAMPS` 优先级更高。

### OpenAI-compatible ASR（Chat Completions）

便携包默认就是小米 MiMo；单独写预设时只需要：

```toml
[asr]
preset = "mimo"
```

然后在 `.env` 写入：

```ini
ASR_API_KEY=你的Key
```

需要覆盖预设时，在同一段里写字段即可：

```toml
[asr]
preset = "mimo"
language = "ja"      # 覆盖预设的 zh
# model = "..."      # 换模型
```

自定义其他服务时，用 `preset = "openrouter"`（或不写 `preset`）作为基底，
覆盖需要的字段：

| 字段 | 说明 |
|---|---|
| `protocol` | `transcriptions`（OpenRouter JSON）、`openai_transcriptions`（OpenAI multipart）或 `chat_completions`（音频放进 `messages`） |
| `api_url` / `model` | 服务商的完整地址和模型名 |
| `api_key_env` | 从 `.env` / 环境变量读取哪个变量作为 Key |
| `api_key_header` / `api_key_prefix` | 鉴权头和前缀；MiMo 用 `api-key` + 空字符串 |
| `audio_format` | `data_url`（`data:audio/wav;base64,...`）或 `base64`（纯 base64 + `format: wav`） |
| `language` | 仅 `chat_completions`，写入 `asr_options.language`；不用就留空 |

- `timestamps`：`chat_completions` 只返回文本，会强制按 `none` 处理，使用
  `fallback_chunk` 定长切片。把 `fallback_chunk` 调小可以减少单个请求的体积。
- 标准 OpenAI 转写：`[asr] preset = "openai"`，把 OpenAI Key 写进 `.env` 的 `ASR_API_KEY`。

翻译侧的 `config.toml` 在启动时会校验：数值超出范围、布尔值写成带引号的字符串、
`structured_output` / `translation_fidelity` 取值不合法时直接报错并列出全部问题；
拼错的字段名（如把 `max_workers` 写成 `workers`）会打印 `[提示]`。

## 翻译配置

从常用模板开始：

```powershell
Copy-Item .\config.common.toml .\config.toml
```

需要完整参数参考时，从 `config.full.toml` 复制：

```powershell
Copy-Item .\config.full.toml .\config.toml
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
# json_schema：更严格，但部分服务不支持
# json_object：兼容性更好（默认）
# none：不发送 response_format
structured_output = "json_object"
# 思考等级（DeepSeek 等支持）：none / low / medium / high / max；留空不发送
reasoning_effort = ""
# system = 使用系统代理（无则直连，默认）；none = 从不走代理；也可填 http://host:port
proxy = "system"
```

`[translation]`：

```toml
[translation]
source = "自动识别"
target = "简体中文"
polish = false   # 默认关闭；需要二次润色时改 true
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