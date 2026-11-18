# 项目约定

视频/音频 → ASR 字幕 → 翻译 SRT 的个人工具。`src/workflow.py` 只负责串联，
`src/asr/`（识别）与 `src/srt_translator/`（翻译）保持独立。

## 依赖与运行

- 只依赖 Python 标准库 + `aiohttp`；这是刻意选择，不要为了小功能引入新依赖。
- Python 3.11+。开发环境：`.venv\Scripts\python.exe`。便携包使用
  `runtime\python\python.exe`，由 `packaging/build_portable.py` 生成。
- 测试：`.venv\Scripts\python.exe -m unittest discover -s tests -t .`
- 语法检查：`.venv\Scripts\python.exe -m compileall src`
- Lint：`ruff check src tests`（配置在 `pyproject.toml`）。
- 便携包：`.venv\Scripts\python.exe packaging\build_portable.py --variant both`；
  详见 `packaging/README.md`。

## 代码约定

- 错误信息、日志、提示词一律中文。
- 不做隐藏缓存：翻译和 ASR 都不写跨运行缓存；失败重跑从头开始。
- `src/*.ps1` 保持 ASCII-only，兼容 Windows PowerShell 5.1。
- 字幕文件名标准是 `作品名.来源.语言.srt`，顺序固定为来源 → 语言。
  改规则时同步改 `src/srt_translator/track.py`、`docs/naming.md`、`src/asr/engine.py`。
- 新增目标语言只需改 `src/srt_translator/languages.py` 的 `PROFILES`。
- 提示词在 `srt_translator/prompts.py`：每条规则每次请求只出现一次；静态指令在前、批次数据用
  `<标签>` 放在后面（`<输入>` 永远最后），保持各批前缀一致以利于前缀缓存。
  JSON 字段名与枚举值用英文，其余中文。改提示词后用 `temp/` 里的小样本对比新旧输出。
- 不做自动降级：接口不接受某个参数时报错并提示用户改配置，不要静默换请求
  （翻译侧 `[api] structured_output`，识别侧 `[asr] timestamps`）。
  例外是内容审查/拒答：按 `[models] fallback` 重试并回退模型，这是明确配置的行为。
- 某个 ASR 分片或翻译批次最终失败时立即取消其余请求，不为注定作废的结果计费。
- 每批输出都要显示当前使用的模型：分析打印 `[模型]`，翻译/润色显示在批次标题或进度行；
  回退时打印 `[回退]`。
- 配置读取：识别侧 `asr/config.py` 把值写入模块全局；翻译侧 `srt_translator/config.py`
  以 dict 传递。新增 `[asr]` 字段时同时更新 `ASR_DEFAULTS`、`ASR_ENV`
  （数值字段还要加 `ASR_RANGES`）和 `config.toml.example`。
- 输出 SRT 统一 `utf-8-sig`；写文件使用 `common.io.write_text_atomic`。
- 公共能力放在 `src/common/`：代理 `net.py`、原子写入 `io.py`、路径 `paths.py`、
  显示宽度与禁则 `textwidth.py`、队列输入与串行调度 `queue.py`、`.env` 解析 `env.py`、
  终端样式 `console.py`。不要在子包里再复制一份。
- 终端输出：入口先调用 `console.setup_streams()`；阶段标题用 `console.rule()`，
  带 `[标签]` 的行用 `console.emit()`（ASR 侧 `asr.util.log()` 已内置）自动着色。
  画线、进度条只用 ASCII（中文控制台会把制表符按双宽显示）；颜色只在真实终端输出。
- 翻译侧配置由 `srt_translator/config.py` 的 `validate_config` 校验，出错直接报错；
  新增字段时同步 `DEFAULT_CONFIG` 与对应的 `RANGES` / `CHOICES` / `BOOLEANS` / `STRINGS`。
- `.env` 与 `config.toml` 不提交；`config.toml.example` 只放公开示例地址。

## 启动器

- `1_视频转字幕.cmd` → `src/asr2srt.py`（薄入口，实现在 `asr.cli`）
- `2_视频转字幕并翻译.cmd` → `src/workflow.py`
- `3_只翻译SRT.bat` → `src/queue_srt.py translate`（翻译即批量：拖入一个或多个 SRT 都逐个执行）
- `4_只润色SRT.bat` → 单文件走 `src/start_polish.ps1`；双击无参数走
  `src/queue_srt.py polish` 队列模式，两者最终都调用 `translate_srt.py`
- 四个启动器双击且不带文件时都进入队列模式，公共逻辑在 `common/queue.py`
- 启动器按 `runtime\python\python.exe` → `.venv\Scripts\python.exe` → PATH 中的
  `python` 顺序查找解释器；`src/start_polish.ps1` 遵循同样的顺序
- 拖到图标上的文件以参数传入 `queue_srt.py`，由 `common/queue.py` 的 `resolve_files` 校验