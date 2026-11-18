# 项目评审：架构、代码与工程化

评审范围：`src/`（约 4 000 行 Python）、`tests/`（71 个用例）、四个启动器、`docs/`、仓库根配置。
评审基准：分支 `chore/remove-webui`，含 19 个未提交改动。

结论先行：**核心设计是对的，翻译侧成熟度明显高于识别侧**。真正需要修的不是架构，而是若干具体缺陷 + 缺一整套工程脚手架。下面按「值得修 / 值得改 / 可以不管」三档给出。

---

## 一、架构评价

### 1.1 分层是清晰的

```text
启动器 (.cmd/.bat/.ps1)          拖拽入口，只做参数转发与路径校验
        ↓
workflow.py                     串联层：ASR → 翻译，子进程调用
        ↓
asr/ (识别)        srt_translator/ (翻译)
        ↓                  ↓
   config/cues/media   config/pipeline/client/cache
```

三个值得肯定的决定：

1. **`workflow.py` 只做串联，不复制逻辑**。它用 `subprocess` 调 `translate_srt.py` 而不是 import，代价是一次进程开销，换来的是两个程序完全解耦——翻译侧改了内部 API，工作流不受影响。这个取舍对当前规模是合适的。
2. **缓存键用 identity dict**（`cache.py:41`）。新增一个影响结果的输入维度，只需要在 `translate_srt.py` 的 identity 里加一个字段，不用碰哈希逻辑。这是整个项目里最经得起时间检验的设计。
3. **失败不静默降级**（`client.py:186-200`、`client.py:205-215`）。`response_format` 不支持、`choices` 为空都直接报错并给出下一步动作，而不是偷偷降级重发。对按量计费的工具来说，这比"尽力成功"重要得多。

### 1.2 主要结构问题

| 问题 | 位置 | 影响 |
|---|---|---|
| `src/` 不是可安装包，靠 `sys.path.insert` 打补丁 | `tests/__init__.py:5`、`workflow.py:29` | 只能从仓库根运行；`pytest -k` 之类的外部工具会导入失败 |
| 两套配置系统风格不一致 | `asr/config.py`（模块全局 + `apply_asr_config` 改写 global）vs `srt_translator/config.py`（纯 dict 传递） | 识别侧改配置靠副作用，难测试、难并行 |
| `asr2srt.py` 的 64 行 re-export 兼容层 | `src/asr2srt.py` | 每加一个常量要改三处：`config.py` 的 global、`asr2srt.py` 的 import、`_MUTABLE` 列表 |
| 字幕条没有公共模型 | `asr` 全用裸 `tuple[float, float, str]`；`srt_translator` 用 `Cue` | 字段含义靠位置约定，`(a, b, text)` 顺序写反编译器不报错 |

**建议**：`asr2srt.py` 是 WebUI 移除后的遗留兼容层。如果启动器已全部改指 `asr/cli.py`，可以只保留 `from asr.cli import main` 两行，删掉那 30 个 re-export 和 `_MUTABLE` 机制。这一处能砍掉约 60 行高维护成本代码。

`SubtitleTranslator.__init__` 有 20 个位置参数（`pipeline.py:13-19`），调用点（`translate_srt.py` 中 `SubtitleTranslator(...)`）全是裸位置实参。加第 21 个参数时，错位不会报错只会静默传错。建议改成 `@dataclass` 配置对象。

---

## 二、值得修的缺陷

### 2.1 `finalize_cues` 会整条丢掉字幕（已实测）

`src/asr/cues.py:166`

```python
else:
    fixed.pop()          # ← 把前一条字幕整个删掉
```

触发条件：前一条字幕短于 0.5 秒，且后一条起点紧贴（间隔小于 `MIN_GAP`）。实测：

```python
输入  [(1.0, 1.3, '上一句'), (1.31, 3.0, '当前句'), (4.0, 5.0, '第三句')]
输出  [(1.31, 3.0, '当前句'), (4.0, 5.0, '第三句')]      # 第一条消失
```

这不是时间轴调整，是**整句文本丢失**，而且静默发生、没有日志。日语/中文的短感叹句（「え？」「あっ」「はい」）正好落在这个长度区间。现有测试 `test_build_and_finalize` 没有覆盖这条分支。

修法：`pop()` 之后要么把被丢的文本并入下一条，要么保留但压到最短时长（`MIN_CUE`），至少不要静默丢内容。

### 2.2 ASR 请求完全不走代理

`src/asr/transcribe.py:51-63` 用 `urllib.request.urlopen`，没有任何 `ProxyHandler`。翻译侧有一整套代理解析（`client.py:60-84`），识别侧一点都没有。

后果：`config.toml` 的 `[api] proxy` 只对翻译生效；`docs/install.md` 的「代理」一节也只讲翻译。在需要代理才能访问 OpenRouter 的网络环境下，翻译能跑、ASR 直接超时，而用户会以为是 Key 或 ffmpeg 的问题。

修法：把 `resolve_proxy` 抽成公共模块，ASR 侧构造 `urllib.request.build_opener(ProxyHandler(...))`。

### 2.3 输出编码不一致（Windows 上会乱码）

| 写入方 | 编码 | 位置 |
|---|---|---|
| ASR 生成 SRT | `utf-8-sig`（带 BOM） | `asr/cues.py:194` |
| 翻译生成 SRT | `utf-8`（无 BOM） | `translate_srt.py:415` |

同一批产物两种编码。无 BOM 的中文 SRT 在部分 Windows 播放器和老编辑器中显示为乱码，而这正是这个项目的主要使用场景。建议统一为 `utf-8-sig`。

顺带：`3_只翻译SRT.bat` 没有 `chcp 65001`（`1_`、`2_`、`4_` 都有）。走 3 号启动器时终端中文输出会是乱码——实际运行测试套件时就能看到这个现象。

### 2.4 输出写入不是原子的

`translate_srt.py:415-416`

```python
output.write_text(dump_srt(result), encoding="utf-8")
cache.clear()          # 上一行成功后才清缓存
```

写文件过程中崩溃会留下半截 SRT，而缓存已按「成功」路径清理的逻辑没被执行——但用户看到文件存在，很可能直接拿去用。建议写临时文件 + `os.replace()`。

同类问题：ASR 侧 `engine.py:117` 直接 `write_srt(cues, out_srt)`，同名文件会被**静默覆盖**。翻译侧有 `unique_output_path` 自动改名，识别侧没有。两个模块的行为应该一致。

### 2.5 `.env` 键匹配用 `startswith`

`src/asr/keys.py:37`

```python
if line.strip().startswith("ASR_API_KEY"):
```

如果用户 `.env` 里有 `ASR_API_KEY_BACKUP=...`，这一行会被整行替换成 `ASR_API_KEY=<new>`，备份键被静默破坏。应改为按 `=` 切分后比对键名。

### 2.6 `[models] options` 是死配置

`config.toml.example` 和 `docs/install.md` 都教用户配置：

```toml
[models]
options = ["gpt-4o-mini"]
```

但 `src/` 下没有任何代码读取 `options`。同一段的 `analysis` / `translation` / `polish` 是有用的（`translate_srt.py` 中 `stage_model()` 读取），只有 `options` 是 WebUI 时代的残留。文档在教一个无效配置。

---

## 三、代码质量

### 3.1 重复实现

`is_cjk` / `char_width` / `display_width` 在三个文件里各有一份：

- `asr/text.py:28-53`
- `srt_translator/textwrap.py:16-40`
- `srt_translator/tui.py:15-29`

折行函数也有两份近亲实现：`asr/text.py:135 _fix_line_breaks`（宽度上限用 `config.LINE_WIDTH + 2`）和 `srt_translator/textwrap.py:79 _fix_breaks`（用传入的 `limit + 2`）。禁则规则一模一样，参数来源不同。建议抽一个 `src/common/width.py`，两套都要用的东西只写一次。

### 3.2 `words_to_segments` 的 O(n²)

`asr/cues.py:31-46`：每处理一个词，都把当前组 `join_tokens` 一遍再 `display_width` 一遍算宽度。而 `cur_w` 这个累加变量（`:35`、`:48`、`:50`）算了但从未使用。

一小时音频大约 1 万个词，这里是 O(n²) 的字符串拼接。虽然实测影响不显著，但 `cur_w` 的存在说明作者本来就想用累加避免重算，只是引用了 `group_w` 而没换上 `cur_w`。改一处即可。

### 3.3 未使用的 import

- `asr/cues.py:4` — `import re`
- `asr/media.py:13` — `from .util import log`

说明仓库没有跑过 linter。

### 3.4 超长行

`pipeline.py` 有 13 行超过 140 字符，最长 391 字符（`:249`）。`prompts.py:6-7` 是 256/273 字符的提示词字符串。提示词保持单行可以理解（避免意外换行），但 `pipeline.py` 的 f-string 应该用括号分组。

### 3.5 错误处理分层

`asr/engine.py` 的 `process_file` 返回三态（`Path` / `True` / `None`），调用方靠 `isinstance` 判断（`workflow.py:151`）。建议改成显式结果对象或抛异常，让「dry-run 成功」「识别成功」「失败」三种情况在类型上就分得开。

---

## 四、测试

**做得好的**：网络层用真实的 `ThreadingHTTPServer`（`test_client.py`、`test_translate_cli.py`）而不是 mock `chat_json`，这样请求体构造、`response_format` 字段、空 choices 处理都被真实覆盖了。`test_translate_cli.py:768` 的断点续传测试验证了「只重发失败批次」，这是最难用手动测试保证的行为。71 个用例 2.4 秒跑完，纯逻辑测试没有拖慢反馈循环。

**缺口**：

| 缺口 | 说明 |
|---|---|
| `finalize_cues` 的丢字幕分支 | 2.1 的 bug 就在这条未覆盖的分支上 |
| `asr` 的重试与降级 | `transcribe_chunk` 的 400 → mode 降级、402 → `Gate.shrink()` 全无单测 |
| `workflow.py` 端到端 | 只测了 `find_existing_asr_srt`，没测「ASR → 子进程翻译」串联 |
| golden file | 没有「固定输入 SRT → 固定输出 SRT」的快照测试，折行/断句改动只能靠肉眼 |
| `plan_chunks` 边界 | 只测了一个常规用例，静音点缺失、尾片 < 3s、短片段合并都没覆盖 |

`docs/troubleshooting.md` 末尾列的测试覆盖清单已经过期——没提 `test_workflow.py`、`test_tui.py`、`test_translate_cli.py`。

---

## 五、工程化脚手架（harness）

这一节是当前最大的短板：项目有 4 000 行代码和 71 个测试，但**没有任何自动化**。所有检查都靠人记得去跑。

### 5.1 缺失清单

| 文件 | 作用 | 现状 |
|---|---|---|
| `pyproject.toml` | 包元数据、依赖、ruff/mypy 配置 | 不存在 |
| `requirements.txt` 或 lock | 可复现环境 | 不存在 |
| `.github/workflows/ci.yml` | 自动跑测试 | 不存在 |
| `.pre-commit-config.yaml` | 提交前 lint/format | 不存在 |
| `.editorconfig` | 统一换行符/编码 | 不存在 |
| `.gitattributes` | 中文文件名 + CRLF 策略 | 不存在 |
| `CLAUDE.md`（或类似） | 项目约定写给 AI 和新人 | 不存在 |
| `.claude/settings.json` | 项目级权限与 hooks | 不存在 |

### 5.2 具体建议

**`pyproject.toml`** — 让 `src/` 成为可导入的包，去掉 `sys.path` hack：

```toml
[project]
name = "subforge"
requires-python = ">=3.11"
dependencies = ["aiohttp>=3.9"]

[tool.ruff]
line-length = 120
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]   # F401 会立刻抓出 3.3 的两个无用 import
```

**依赖** — 当前 `.venv` 里还残留 `fastapi` / `uvicorn` / `pydantic` / `starlette`（WebUI 时代的依赖，`963ec48` 已移除代码）。重建环境时确认只需要 `aiohttp`。`docs/install.md` 里写的是 `pip install aiohttp`，这是对的，但没有任何文件固化它。

**换行符** — `git status` 已经报了一堆 `LF will be replaced by CRLF`。加一个 `.gitattributes`：

```gitattributes
* text=auto eol=lf
*.cmd text eol=crlf
*.bat text eol=crlf
*.ps1 text eol=crlf
```

`*.ps1` 保留 CRLF 是因为 `start_polish.ps1` 的注释明确要求 PowerShell 5.1 兼容。

**CI** — 因为识别侧依赖 ffmpeg，测试里已经有 `HAS_FFMPEG` 的 skip 机制，GitHub Actions 的 `ubuntu-latest` 自带 ffmpeg，可以直接跑全量：

```yaml
- run: python -m pip install aiohttp ruff
- run: ruff check src tests
- run: python -m unittest discover -s tests -t .
```

**`CLAUDE.md`** — 这个项目的约定分散在五篇文档里，且有几条是隐性的。值得写下来的：

- 只依赖标准库 + `aiohttp`，不要引入新依赖（这是刻意选择，不是疏忽）
- 错误信息、日志、提示词一律中文；`start_polish.ps1` 等 PowerShell 文件保持 ASCII-only
- 文件名标准是 `作品名.来源.语言.srt`，顺序固定，改这个规则要同步改 `track.py`、`naming.md`、`asr/engine.py`
- 新增目标语言只需改 `languages.py` 的 `PROFILES`
- 测试命令：`.venv\Scripts\python.exe -m unittest discover -s tests -t .`
- 不做自动降级：接口不支持某个参数时报错让人改配置，不要偷偷换请求

**项目级 hooks**（可选）— 如果希望每次改完代码自动验证，可以在 `.claude/settings.json` 里加一个 Stop hook 跑 `compileall` + unittest。但这会拖慢每次交互，对 2.4 秒的测试套件可以接受，值得试。

---

## 六、文档

整体质量在同类个人项目里属于偏上：`naming.md` 解释了「为什么顺序是来源→语言」，`internals.md` 写了缓存键包含哪些维度，`troubleshooting.md` 有可执行的排查步骤。问题集中在**同步**：

| 文档 | 问题 |
|---|---|
| `install.md` | 教用户配 `[models] options`（无效配置） |
| `troubleshooting.md` | 测试覆盖清单缺 3 个新文件；第 4 点「新增语言时」那段混用了英文逗号 |
| `naming.md` | 说识别产物由 `asr2srt.py` 生成，实际在 `asr/engine.py` |
| `README.md` | 把 `asr2srt.py` 同时描述为「兼容入口（重新导出 asr 包）」和「命令行入口」，读者会困惑该用哪个 |
| `config.toml` vs `config.toml.example` | 本地配置缺 `[asr]` 整段；多了 `pause_before_polish`；`translation_fidelity` 一个 `creative` 一个 `natural` |

建议：`config.toml.example` 的段落用测试断言校验（读 example，断言 `load_asr_config` / `load_config` 能解析出预期字段），防止继续漂移。

---

## 七、优先级建议

**P0 — 会造成用户可见错误，建议尽快修**

1. `finalize_cues` 丢字幕（2.1）— 加归并逻辑 + 回归测试
2. 输出编码统一为 `utf-8-sig`（2.3）— 一行改动
3. `3_只翻译SRT.bat` 补 `chcp 65001`（2.3）— 一行改动
4. ASR 侧接入代理（2.2）— 抽公共 `resolve_proxy`

**P1 — 影响可靠性，值得安排**

5. 输出原子写入 + ASR 侧同名文件不静默覆盖（2.4）
6. `.env` 键名精确匹配（2.5）
7. `pyproject.toml` + `ruff`（顺手清掉无用 import）
8. CI 跑 ruff + unittest
9. 删除 `[models] options` 或实现它（2.6）

**P2 — 结构改善，有空再做**

10. 抽 `common/width.py`，消掉 3 处重复
11. `asr2srt.py` 瘦身到只 re-export `main`
12. `SubtitleTranslator` 参数改 dataclass
13. `words_to_segments` 用上 `cur_w`
14. 补 golden file 测试与 `asr` 重试路径单测
15. 写 `CLAUDE.md` + `.gitattributes` + `.editorconfig`
16. 文档同步（第六节）

---

## 八、附：当前工作区状态

- 分支 `chore/remove-webui`，19 个未提交改动（`translate_srt.py` 增加 267 行最多）
- 测试全绿：71 passed / 2.445s
- `temp/` 目录 1.4 MB，已在 `.gitignore` 中，不会被提交
- `.env` 与 `config.toml` 均未被 git 跟踪（`git ls-files` 确认）；`config.toml.example` 里是干净的公网地址，没有泄漏私有 endpoint

---

## 九、处理状态（2026-11-05）

**已完成**

- P0：`finalize_cues` 改为把过短的前一条并入当前条（附回归测试）；输出统一 `utf-8-sig`；
  `3_只翻译SRT.bat` 补 `chcp 65001`；ASR 接入代理（`common/net.py`，优先 `[asr] proxy`，
  缺省沿用 `[api] proxy`，支持 `ASR_PROXY`）。
- P1：输出原子写入（`common/io.py`）、ASR 同名产物自动改名；`.env` 键名精确匹配；
  新增 `pyproject.toml`、`requirements.txt`、ruff 配置、GitHub Actions；删除 `[models] options`
  并同步文档。
- P2：抽出 `common/textwidth.py`（宽度、折行、禁则）；`asr2srt.py` 瘦身为薄入口；
  `SubtitleTranslator` 改用 `TranslatorOptions` dataclass；`words_to_segments` 用上 `cur_w`；
  补 `finalize_cues`、ASR 重试/降级、`plan_chunks` 边界、workflow 串联等测试；
  新增 `CLAUDE.md`、`.editorconfig`、`.gitattributes`；文档同步。
- 3.5：`process_file` 改为 `ProcessResult` 结果对象。

**后续变更**

- 按后续需求，翻译批次缓存和 ASR 分片缓存均已移除；失败重跑会重新请求。
- 持久化项目文件方案见 [项目文件设计稿](project-file.md)（尚未实现）。

**仍缺**

- 固定输入/输出的 golden file 快照测试（折行、断句改动仍需结合具体用例检查）。
- 超长提示词行通过 ruff `per-file-ignores` 放行，尚未逐行改写。

---

## 十、第二轮评审处理（2026-11-05）

**已完成**

- 计费：ASR 某一分片最终失败时取消其余排队请求（实测原先 40 片会全部发出）；翻译某批失败时取消其余批次。
- `client.py`：只在 400 明确提到 `response_format` / `json_schema` 时提示改 `structured_output`，
  不再把 `invalid_request_error`、模型名错误等误报成结构化输出问题。
- ASR 不再在运行中自动去掉时间戳参数；新增 `[asr] timestamps`（word / segment / none），接口不接受时报错提示。
- 翻译侧配置校验（`validate_config`）：负数 `batch_size` 原先会静默输出空字幕；未知字段打印提示。
- `繁體中文` / `zh-TW` 等目标语言映射到 `zh`（原先输出 `.translated.srt`、按 42 列折行）。
- 输入字幕编号重复时按顺序重新编号，避免两条字幕拿到同一句译文。
- 润色阶段失败时先保存未润色译文与分析文件，可直接用 4 号启动器续跑。
- `workflow.py`：已有译文时跳过翻译（`--redo-translate` 强制）；全部复用时不再询问 ASR Key。
- `.env` 解析合并到 `common/env.py`；`polished` 产物可再次润色（反查原分析文件）。
- ASR 失败或中断时也会清理临时音频目录。
- 命令行 UI：新增 `common/console.py`（Windows 控制台颜色、非终端自动去色、统一标签颜色、
  ASCII 分隔标题）；翻译任务概览、批次耗时、润色表只列改动行、表格行尾不补空格；
  ASR 进度条显示剩余时间，日志不再与进度条挤在同一行；队列模式逐项显示结果与用时。

**仍缺**

- 语言信息仍分散在 `PROFILES`、`TARGET_CODES`、`LANGUAGE_NAMES`、`LANG_ALIASES` 四张表，未合并。
- 审查关键词（`blocked` / `sensitive` 等）在 403 上仍可能误判。

---

## 十一、提示词改版（2026-11-05）

- 纠错项 id 写成范围（`139-140`）时会展开；此前实测 85 条中有 10 条因此一个批次都收不到。
- 分析阶段对无效/截断 JSON 重试；纠错条数设上限；`confidence` / `type` 在 schema 中加枚举。
- system 按阶段区分（分析员 / 译者 / 校对编辑），去掉与 `creative` 冲突的"忠实优先"。
- 置信度使用规则（high 采用、medium 斟酌、low 仅参考）；术语只给一个目标语言首选译名。
- 去掉重复规则（来源说明、"不要添加信息"等）；分析不再带翻译策略；润色不再带"直译"相关分段说明。
- 批次数据用 `<标签>` 与指令分开；每条输入带 `dur`，按语言阅读速度控制长度。
- 源语言自动识别时使用文件名标注的语言；非中文目标禁止混入中文用词/标点，并给出示例句。
- 英文写的 ASR/OCR 细分提示统一改成中文。
- 尚未用真实模型做新旧对比（需要调用付费 API）。
