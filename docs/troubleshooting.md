# 常见问题

## 翻译卡在「正在分析项目...」

这是全文分析的 API 请求。可以：

1. 等待 `timeout` 设置的时间
2. 把 `structured_output` 改成 `json_object`
3. 关闭全文分析：`--no-analysis`，或在配置里设 `global_analysis = false`
4. 降低并发：`--workers 1`
5. 加 `--debug-api` 查看请求状态

## 润色阶段很慢

润色是第二轮完整请求。可以：

- 配置 `max_workers = 1` 或 `--workers 1`
- 直接跳过：`--no-polish`
- 用 `--quiet` 减少终端输出

## 译文出现了长行 / 排版不统一

默认会按目标语言自动折行。如果仍不理想：

- 确认目标语言能被识别（`--target 简体中文`、`日语`、`英语`）
- 检查是否加了 `--no-wrap`
- 新增语言时在 `src/srt_translator/languages.py` 补一条 profile

## HTTP 400

通常是代理不支持某个请求参数。脚本不会自动改请求，错误信息会直接说明应改哪一项。

如果提示 `接口不接受 structured_output=json_schema`，在 `config.toml` 里依次尝试：

```toml
[api]
structured_output = "json_object"  # 再不行改成 "none"
```

改完直接重跑即可。仍报 400 时，检查模型名称、endpoint 和参数拼写。

## HTTP 200，但 `choices` 为空

返回体类似：

```json
{"choices": [], "usage": {"prompt_tokens": 2302, "completion_tokens": 0}}
```

这不是网络超时。`completion_tokens=0` 表示上游没有生成任何内容，常见原因：

1. 内容审查 / 模型拒答
2. 代理转发失败，或模型名在该代理上不可用
3. 提示词触发了安全过滤

脚本会把它当作**内容审查/拒答**处理：同一批次最多请求 3 次（首次 + 2 次重试）。

- 配置了 `[models] fallback`（或 `translation_fallback` / `polish_fallback` / `analysis_fallback`）
  时，3 次仍失败会切换到回退模型；回退模型也失败才报错。
- 没有配置回退模型时，3 次后直接报错。
- 回退功能可以用 `[models] fallback_enabled = false` 关闭；关闭后仍会重试 3 次，但不换模型。

排查顺序：

- 看终端里的 `[审查]` / `[回退]` 日志，以及每批表格标题里的模型名，确认是主模型还是回退模型被拒。
- 用同一套配置翻译一小段无关的普通字幕。如果普通内容也空，换模型或 endpoint；如果普通内容正常，基本可以确定是内容过滤。
- 确认回退模型的条款允许你要翻译的内容；回退模型必须和主模型共用同一个 endpoint / key。
- 加 `--debug-api` 看请求状态和输出长度。
- 如果只是代理不支持 `json_schema`，通常报 HTTP 400，不会返回空 choices。

提示词里集中列举敏感类别的措辞可能让部分模型过度过滤。若图片/视频内容本身在服务商条款允许范围内，可以换用措辞更中性的提示词，只保留「忠实保留原文语气和表达强度」，不要反复强调审查相关关键词。

## HTTP 401 / 403 / 404

- 401：Key 无效或没读到。检查 `LLM_API_KEY` 或 `config.toml`。
- 403：账号、模型或接口没有权限；如果错误信息里含审查/内容策略关键词，会按内容审查处理并尝试回退。
- 404：endpoint 或模型地址不正确。

## HTTP 429

请求频率过高。把并发降到 1 或 2，稍后重试。脚本会按指数退避自动重试。

## 翻译或润色中途失败

只有所有批次都成功且通过格式校验后才会写最终 SRT。没有批次缓存，中途失败时：

- 重跑会重新请求分析/翻译/润色，已完成的请求不会保留。
- ASR 识别中途失败也一样：重跑会重新请求所有分片。
- `2_视频转字幕并翻译.cmd` 会复用已有的 `作品名.asr.语言.srt` 并跳过 ASR；想强制重新识别加 `--redo-asr`。
- 润色阶段失败：会先保存未润色的译文和分析文件，拖到 `4_只润色SRT.bat` 只重跑润色。
- 翻译已经成功、只想重新润色：用 `--no-polish` 翻译，再用 `--translated` 读取已有译文。
- 加 `--debug-api` 看具体是哪一批失败。
- 如果模型经常返回数量不对，降低 `--batch-size`。

## 输出文件已存在

默认自动改名：`movie.zh.srt` → `movie.zh.2.srt`。想覆盖用 `--force`。

## ASR 报「余额不足 / in-flight requests」

这是 OpenRouter 对**进行中请求的额度预扣**，不是真的没余额。脚本会自动把并发减半重试；也可以手动降低 `--asr-workers`，或给账户充值。

## ASR 报「识别接口不接受 timestamp_granularities」

当前识别接口不支持 `[asr] timestamps` 指定的时间戳粒度。脚本不会自动换参数重发，
按提示把 `config.toml` 的 `[asr] timestamps` 改为 `segment`；仍报 `response_format`
时改为 `none`（按 `fallback_chunk` 秒定长切片，时间轴精度会下降）。

## 配置报「config.toml 配置有误」

翻译侧启动时会校验配置，并一次列出全部问题。常见原因：

- 布尔值加了引号：`polish = "false"` 应写成 `polish = false`
- 数值超出范围：`batch_size` 1–500、`context` 0–100、`max_workers` 1–32
- `structured_output` 只能是 `json_schema` / `json_object` / `none`

字段名拼错不会报错，但会打印 `[提示] … 有未识别的配置项`。

## 中文显示乱码 / 出现 `←[33m` 之类的字符

四个启动器都会自动执行 `chcp 65001`。如果是手动在终端运行，请先执行
`chcp 65001` 切到 UTF-8，或直接在 Windows Terminal 中运行。

终端颜色只在真实控制台里输出，脚本会自动打开 Windows 控制台的颜色支持；
输出重定向到文件时不带颜色。如果仍看到 `←[33m` 这类字符，设置环境变量
`NO_COLOR=1` 关闭颜色。

## ASR 请求超时 / 连不上

识别和翻译共用代理配置：优先读 `[asr] proxy`，没有时沿用 `[api] proxy`。
如果需要代理才能访问 OpenRouter：

```toml
[api]
proxy = "http://127.0.0.1:7890"
```

或者设置环境变量 `ASR_PROXY`。确认代理只覆盖识别侧时，再单独写 `[asr] proxy`。

## ASR 找不到 ffmpeg

确认 `ffmpeg` 和 `ffprobe` 在 PATH 中：

```powershell
ffmpeg -version
ffprobe -version
```

## ASR 提示「没有音轨」

视频容器里确实没有音频流，或音频是特殊编码。可以先用 ffmpeg 检查：

```powershell
ffprobe -v error -select_streams a:0 -show_streams "video.mp4"
```

## 语法检查与测试

```powershell
.\.venv\Scripts\python.exe -m compileall src
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

测试覆盖：

- `test_asr.py`：显示宽度、断句、切片规划、字幕归并、重试、时间戳参数报错、失败取消
- `test_workflow.py`：复用已有 ASR 字幕、ASR → 翻译串联
- `test_translate_cli.py`：命令行、失败重跑、`--translated` 润色
- `test_client.py`：请求体、结构化输出、审查错误识别
- `test_pipeline.py` / `test_prompts.py`：分阶段模型、纠错项过滤、提示词规则、审查回退
- `test_naming.py` / `test_srt.py` / `test_textwrap.py` / `test_tui.py`：命名、SRT、折行、终端表格
- `test_robustness.py`：配置校验、批次取消、润色失败保留译文、编号去重、繁体目标语言、终端颜色
- `test_queue.py` / `test_config_example.py` / `test_keys.py`：队列模式、配置示例、密钥写入
- `test_common.py` / `test_keys.py` / `test_config_example.py`：代理、原子写入、配置示例