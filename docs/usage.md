# 使用与工作流

## 四个启动器

| 启动器 | 输入 | 输出 |
|---|---|---|
| `1_视频转字幕.cmd` | 视频/音频，可多选 | `作品名.asr.语言.srt` |
| `2_视频转字幕并翻译.cmd` | 视频/音频，可多选 | 上面的 SRT + `作品名.目标语言.srt` |
| `3_只翻译SRT.bat` | 一个或多个 SRT | `作品名.目标语言.srt` |
| `4_只润色SRT.bat` | 一个已翻译的 SRT | `作品名.目标语言.polished.srt` |

拖拽即可，不需要打开终端。批量拖多个文件时按顺序处理，单个失败不会中断整批。

## 队列模式

四个启动器都支持：**不带文件双击打开**，窗口会提示拖入文件。

- 可以多次拖入，每批按回车换行；拖完后按一次空行回车开始。
- 文件之间严格串行，一个完整跑完再处理下一个；单个失败不影响后续，结束时统一汇总。
- 路径会去重；文件不存在或扩展名不支持时，会列出问题并要求重新拖入整批。
- 队列模式没有额外的命令行选项入口，使用 `config.toml` 的现有配置。
- 第 3 号启动器把翻译当批量任务：拖入一个或多个 SRT 都逐个跑，每个文件是独立任务。
- 第 4 号队列不询问润色意见；缺少 `.analysis.json`、无法找到原始 SRT 的文件会被跳过并记为失败。

## 工作流（视频 → 原文 → 译文）

```powershell
.\.venv\Scripts\python.exe src\workflow.py "视频.mp4"
```

常用参数：

```powershell
# 只识别，不翻译
.\.venv\Scripts\python.exe src\workflow.py "视频.mp4" --no-translate

# 提高识别/翻译并发
.\.venv\Scripts\python.exe src\workflow.py "视频.mp4" --asr-workers 8 --tr-workers 6

# 换目标语言、跳过润色、减少终端输出
.\.venv\Scripts\python.exe src\workflow.py "视频.mp4" --target 繁體中文 --no-polish --quiet

# 只做识别规划，不调用接口（不花钱）
.\.venv\Scripts\python.exe src\workflow.py "视频.mp4" --dry-run

# 已有 ASR 字幕时强制重新识别
.\.venv\Scripts\python.exe src\workflow.py "视频.mp4" --redo-asr

# 已有译文（作品名.目标语言.srt）时强制重新翻译；默认跳过
.\.venv\Scripts\python.exe src\workflow.py "视频.mp4" --redo-translate
```

流程：

```text
视频 → 抽音轨 → 静音切片 → ASR → 作品名.asr.语言.srt
                                      ↓
                              translate_srt.py
                                      ↓
                              作品名.目标语言.srt
```

两个程序仍然是独立文件；`workflow.py` 只是按顺序调用它们。

## 命令行翻译

```powershell
.\.venv\Scripts\python.exe src\translate_srt.py "movie.asr.ja.srt"
.\.venv\Scripts\python.exe src\translate_srt.py "movie.asr.ja.srt" "out.zh.srt" --config config.toml
```

不指定输出路径时会自动生成 `作品名.目标语言代码.srt`。

指定源语言/目标语言：

```powershell
.\.venv\Scripts\python.exe src\translate_srt.py "movie.asr.ja.srt" --source Japanese --target "简体中文"
```

## 先翻译，下次只润色

第一次只翻译、不做润色：

```powershell
.\.venv\Scripts\python.exe src\translate_srt.py "movie.asr.ja.srt" "movie.zh.srt" --no-polish
```

除了译文，还会在同目录写出 `movie.zh.analysis.json`，里面是全文分析、术语和纠错结果。

之后想单独重新润色（比如换了润色模型或提示词），直接复用已有译文：

```powershell
.\.venv\Scripts\python.exe src\translate_srt.py "movie.asr.ja.srt" "movie.zh.polished.srt" --translated "movie.zh.srt"
```

- 自动读取 `movie.zh.analysis.json`，跳过全文分析和翻译，只发润色请求。
- 分析文件不存在时会重新分析；加 `--no-analysis` 则直接跳过分析。
- 想用别的分析文件：`--analysis-file path\to\analysis.json`。
- 第一次也可以手动指定保存位置：`--save-analysis path\to\analysis.json`。
- `--translated` 的译文 SRT 必须和输入 SRT 使用相同的字幕编号。
- 输入 SRT 编号有重复（拼接过的字幕）时会按顺序重新编号并打印 `[提示]`，避免两条字幕拿到同一句译文。

也可以完全不用命令行：把已翻译的 `movie.zh.srt` 拖到 `4_只润色SRT.bat` 上。

- 自动读取同目录的 `movie.zh.analysis.json`，找到原文并只跑润色。
- 拖入后会提示输入本次润色意见，直接回车跳过；命令行可用 `--polish-prompt`。
- 输出 `movie.zh.polished.srt`；已存在时自动改名，不覆盖。
- 也可以拖入 `movie.zh.polished.srt` 再润色一轮：仍读取 `movie.zh.analysis.json`，输出 `movie.zh.polished.2.srt`。
- 没有 `.analysis.json` 时会提示输入原文 SRT，并重新做一次全文分析。
- 第一次生成这个分析文件的方法：用 `--no-polish` 翻译，或在完整翻译时加 `--save-analysis`。

## 失败后重跑

没有批次缓存；请求失败时已完成的批次不会保留。例外是润色阶段失败：
此时翻译已全部完成，会先写出未润色的 `作品名.目标语言.srt` 和 `.analysis.json`（正式产物，不是缓存），
把它拖到 `4_只润色SRT.bat` 即可只重跑润色。

- `3_只翻译SRT.bat` 分析或翻译失败：重跑会重新请求整个分析/翻译/润色阶段；润色失败见上。
- `4_只润色SRT.bat` 润色失败：重跑会重新润色全部批次。
- `2_视频转字幕并翻译.cmd` 翻译/润色失败：重跑时如果已有 `作品名.asr.语言.srt`，会跳过 ASR；已有 `作品名.目标语言.srt` 时也会跳过翻译（`--redo-translate` 强制重做）。
- 想强制重新识别：给 `workflow.py` 加 `--redo-asr`。
- 翻译成功、只想重新润色：用 `--no-polish` 翻译，再用 `--translated` 读取已有译文，只跑润色。这个流程不依赖缓存。

## 内容审查回退

分析、翻译、润色遇到内容审查/拒答时，主模型最多请求 3 次（首次 + 2 次重试）。
仍失败且配置了 `[models] fallback` 时，当前批次和同阶段后续批次改用回退模型；
回退模型也失败才报错。每批内容/进度行会显示当前模型，回退时打印 `[回退]`。

配置方法见 [安装与配置](install.md) 的「内容审查回退」。

## 常用参数

| 参数 | 说明 |
|---|---|
| `--workers N` | 翻译并发数（默认取 `[processing] max_workers`） |
| `--batch-size N` | 每批字幕条数，默认 20；调大可减少请求数 |
| `--context N` | 前后文条数，默认 3 |
| `--target` / `--source` | 覆盖配置里的目标/源语言 |
| `--model` / `--endpoint` | 临时覆盖模型或接口 |
| `--analysis-model` / `--translation-model` / `--polish-model` | 按阶段覆盖模型（见安装文档） |
| `--fidelity` | `faithful` / `natural` / `creative` |
| `--no-analysis` | 关闭全文分析 |
| `--no-polish` | 只翻译、不润色（省一轮请求），并保存分析结果 |
| `--translated PATH` | 使用已有译文 SRT，只做润色 |
| `--polish-prompt TEXT` | 本次润色的附加意见（如“保留关西腔”“少用四字词”） |
| `--analysis-file PATH` | 读取已保存的分析 JSON（配合 `--translated`） |
| `--save-analysis PATH` | 保存本次全文分析 JSON |
| `--quiet` | 只输出批次进度，不逐条打印字幕 |
| `--force` | 输出已存在时直接覆盖（默认自动改名） |
| `--no-wrap` | 不按目标语言宽度自动折行 |
| `--no-fallback` | 本次运行关闭模型回退（审查时仍会重试 3 次） |
| `--debug-api` | 打印 HTTP 状态、耗时和 usage |

## 输出命名与覆盖

- 派生规则：去掉输入文件名末尾的「来源.语言」标记，再拼上目标语言代码。
- 已存在时**自动改名**：`movie.zh.srt` → `movie.zh.2.srt`、`movie.zh.3.srt`……
- 想直接覆盖用 `--force`。

## 性能建议

1. **并发**：连接池已复用，`--workers 4~6` 通常明显更快；遇到 429 就降回 2。
2. **批量**：`--batch-size 30~40` 能减少请求数，但格式错误的风险也会上升。
3. **润色**：`--no-polish` 少一整轮请求，赶时间时最有效。
4. **输出**：`--quiet` 避免逐条打印拖慢 Windows 控制台。
5. **失败重跑**：没有批次缓存，失败后会重新请求失败阶段。如果翻译已经成功、只想重新润色，用上面的 `--no-polish` + `--translated` 两步流程，避免重复翻译。
6. **批量文件**：`src\workflow.py --jobs 2` 或 `src\asr2srt.py -J 2` 可以同时处理多个视频。注意总请求数 ≈ `jobs × workers`，别把服务商打爆。
7. **分阶段模型**：分析用便宜模型、翻译用最强模型、润色按预算选择，能明显降低长视频的总成本（见安装文档）。

## 只翻译已有字幕的快捷方式

把 `.srt` 直接拖到 `3_只翻译SRT.bat`（可以一次拖多个，按顺序逐个处理）。