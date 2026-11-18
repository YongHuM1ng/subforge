# 字幕项目文件（设计稿）

> **状态：设计稿，尚未实现。** 本文只记录已对齐的需求，不代表当前代码行为。
>
> 当前实现：翻译与 ASR 缓存均已移除；`<译文>.analysis.json`、`--translated`
> 仍保留。项目文件功能尚未落地。

## 目标

- 在输出字幕旁自动记录每一步（分析、翻译、润色）的完整结果和进度。
- 翻译/润色失败时可以按项目文件续跑；润色不满意时可以只重新润色，不重新翻译。
- 项目文件是翻译流程唯一可信的状态来源，不再依赖 `temp/` 下的隐藏缓存。

## 非目标

- `1_视频转字幕.cmd` 的纯识别流程不创建项目文件。
- ASR 分片缓存已移除；项目文件只覆盖翻译/润色，不为 ASR 提供续跑。
- 不改变识别产物和翻译产物的现有命名规则。
- 不处理模型变化导致的结果差异；模型只记录，不使项目失效。

## 1. 缓存现状

**已移除**

- `src/srt_translator/cache.py`
- `BatchCache` 及其在 `pipeline.py`、`translate_srt.py` 中的调用
- 翻译侧 `--no-cache`
- 项目 `temp/srt_translator_cache/` 目录
- ASR 的 `temp/asr2srt/<hash>/` 分片缓存
- `asr2srt.py` / `workflow.py` 的 `--no-cache`

**保留**

- 无跨运行缓存。`--keep-audio` 只用于保留本次识别的临时音频，便于排查。

## 2. 项目文件位置与命名

项目文件放在**输出字幕同目录**，文件名由输出字幕名派生：

```text
movie.zh.srt            -> movie.zh.project.json
movie.zh.2.srt          -> movie.zh.2.project.json
movie.zh.polished.srt   -> movie.zh.project.json   （重新润色时反查主项目）
```

- 正常翻译：项目文件跟随本次计划的输出路径创建；即使输出 SRT 最终没有写出，项目文件也保留。
- 输出已存在时仍按现有规则自动改名为 `movie.zh.2.srt`，项目文件跟着变成 `movie.zh.2.project.json`。
- 重新润色时如果拖入的是 `movie.zh.polished.srt`，先去掉 `.polished`，再找 `movie.zh.project.json`。

## 3. 生命周期

1. 确定输入、输出和设置后，立即创建项目文件，状态记为 `running`。
2. 全文分析完成后写入 `analysis` 阶段。
3. 每批翻译完成后立即写入对应批次；全部完成后写入完整译文快照。
4. 每批润色完成后立即写入对应批次；全部完成后写入完整润色快照。
5. 成功写出最终 SRT 后，整体状态改为 `done`，**项目文件不删除**。
6. 任一阶段失败时，整体状态改为 `failed`，保留已完成内容，供下次续跑或单独重润色。
7. 项目文件使用原子写入：先写同目录临时文件，再 `os.replace`。

## 4. 文件结构

JSON，UTF-8，缩进 2，`ensure_ascii=False`。

```json
{
  "version": 1,
  "kind": "srt-project",
  "created_at": "2026-11-05T12:00:00+08:00",
  "updated_at": "2026-11-05T12:03:20+08:00",
  "status": "failed",
  "source": {
    "input": "movie.asr.ja.srt",
    "size": 12345,
    "mtime": 1762345678,
    "base": {
      "name": "movie.asr.ja.srt",
      "source": "asr",
      "language": "ja",
      "cues": [
        {"number": "1", "timing": "00:00:01,000 --> 00:00:02,000", "text": "こんにちは"}
      ]
    }
  },
  "settings": {
    "source_language": "自动识别",
    "target_language": "简体中文",
    "endpoint": "https://api.example.com/v1/chat/completions",
    "model": "gpt-4o-mini",
    "analysis_model": "",
    "translation_model": "",
    "polish_model": "",
    "batch_size": 20,
    "context": 3,
    "global_analysis": true,
    "polish": true,
    "translation_fidelity": "natural",
    "natural_segmentation": true,
    "subtitle_source": "asr",
    "additional_prompt": ""
  },
  "stages": {
    "analysis": {
      "status": "done",
      "model": "",
      "started_at": "2026-11-05T12:00:05+08:00",
      "finished_at": "2026-11-05T12:00:40+08:00",
      "error": null,
      "data": {
        "summary": "……",
        "style": "……",
        "corrections": [],
        "terms": []
      }
    },
    "translation": {
      "status": "failed",
      "model": "gpt-4o",
      "started_at": "2026-11-05T12:00:40+08:00",
      "finished_at": null,
      "error": "批次 40 失败：模型返回的字幕数量、编号或内容无效",
      "batches": {
        "0": {
          "status": "done",
          "model": "gpt-4o",
          "finished_at": "2026-11-05T12:01:10+08:00",
          "texts": ["你好", "今天天气真好"]
        },
        "40": {
          "status": "failed",
          "model": "gpt-4o",
          "finished_at": "2026-11-05T12:03:20+08:00",
          "error": "模型返回的字幕数量、编号或内容无效"
        }
      },
      "cues": []
    },
    "polish": {
      "status": "skipped",
      "model": "",
      "started_at": null,
      "finished_at": null,
      "error": null,
      "batches": {},
      "cues": [],
      "previous": null
    }
  }
}
```

### 各阶段说明

| 字段 | 说明 |
|---|---|
| `source.base.cues` | 原文 SRT 全文，重新润色时作为原文 |
| `settings` | 本次运行的实际设置；模型字段只作记录 |
| `stages.analysis.data` | 完整分析结果（主题、风格、纠错、术语） |
| `stages.translation.batches` | 按批 offset 记录的译文、状态、实际模型、时间和错误 |
| `stages.translation.cues` | 翻译成功后的完整译文快照；失败时可为空 |
| `stages.polish.batches` | 按批 offset 记录的润色结果 |
| `stages.polish.cues` | 最近一次成功润色的完整快照 |
| `stages.polish.previous` | 上一版润色结果的备份路径和元信息 |

## 5. 续跑与失效规则

### 可以复用

以下内容一致时，认为项目仍属于同一次任务：

- 输入 SRT 的路径、大小、mtime
- 源语言、目标语言
- `batch_size`、`context`
- `global_analysis`、`translation_fidelity`、`natural_segmentation`、`subtitle_source`、附加提示词

### 不参与失效判断

- endpoint 和模型字段（`model` / `analysis_model` / `translation_model` / `polish_model`）
- 模型变化不会清空项目；已完成批次继续复用，新批次使用新模型
- 每个批次单独记录实际使用的模型，便于之后审计

### 不一致时

输入或上述设置发生变化时：

1. 把旧项目归档为 `movie.zh.project.1.json`、`movie.zh.project.2.json`……（取第一个不存在的序号）
2. 按新设置创建新项目
3. 在终端提示归档路径

### 分批续跑

- `analysis` 已完成：直接读取 `stages.analysis.data`，不重新请求。
- `translation`：按 offset 检查批次；`status == "done"` 且译文条数与编号匹配时复用，其余重新请求。
- `polish`：同样按 offset 复用。
- 翻译完成但润色失败：保留译文快照，`--re-polish` 只补润色。
- 润色被跳过（`--no-polish`）：`polish.status = "skipped"`，之后仍可 `--re-polish`。

## 6. 重新润色

### 命令

```powershell
# 从译文 SRT 启动，自动找同目录的 movie.zh.project.json
.\.venv\Scripts\python.exe src\translate_srt.py --re-polish "movie.zh.srt"

# 也可以直接指定项目文件
.\.venv\Scripts\python.exe src\translate_srt.py --re-polish "movie.zh.project.json"
```

- 读取项目里的 `source.base.cues`、`stages.analysis.data`、`stages.translation.cues`。
- 不重新分析、不重新翻译。
- 允许用命令行覆盖润色模型：`--polish-model`。
- 如果项目缺少分析结果，按 `--no-analysis` 的方式直接润色，或提示用户先运行完整翻译。

### 输出与备份

```text
movie.zh.polished.srt
```

- 如果输出已存在：先改名为 `movie.zh.polished.1.srt`；若 `.1` 也存在，用 `.2`、`.3`……
- 备份成功后再写新文件；写入使用原子替换。
- 更新 `stages.polish`，把上一版记录到 `previous`：

```json
{
  "previous": {
    "file": "movie.zh.polished.1.srt",
    "model": "gpt-4o-mini",
    "finished_at": "2026-11-05T12:10:00+08:00"
  }
}
```

### 启动器

`4_只润色SRT.bat` 改为调用 `--re-polish`：

```text
拖入 movie.zh.srt          -> 找 movie.zh.project.json
拖入 movie.zh.polished.srt -> 去掉 .polished，找 movie.zh.project.json
```

找不到项目文件时给出明确错误，不再依赖 `.analysis.json`。

## 7. 旧机制移除

- 不再生成 `<译文>.analysis.json`。
- 移除 `--translated`、`--save-analysis`、`--analysis-file`。
- `--no-cache` 已全部移除（翻译和 ASR 都没有跨运行缓存）。
- 旧 `.analysis.json` 不做自动迁移。需要旧项目时，重新跑一次完整翻译生成新项目文件。

## 8. 失败语义

| 失败位置 | 项目文件保留内容 | 重跑行为 |
|---|---|---|
| 分析失败 | 输入快照、设置、已完成的旧阶段 | 从分析开始 |
| 翻译某批失败 | 分析结果、已完成批次 | 只补失败和未完成批次 |
| 全部翻译完成、润色失败 | 完整译文快照 | 普通重跑或 `--re-polish` |
| 写最终 SRT 失败 | 完整译文/润色快照 | 从快照重新写出，不重新请求 |

## 9. 实现清单（未来落地时）

- 新增 `src/srt_translator/project.py`：项目文件的加载、创建、归档、原子保存。
- `pipeline.py`：用项目对象记录分析和每批请求进度（`BatchCache` 已移除）。
- `translate_srt.py`：创建项目、增加 `--re-polish`、移除旧分析参数。
- `src/start_polish.ps1` / `4_只润色SRT.bat`：改为项目文件驱动。
- `workflow.py`：保持 `--redo-asr` 的 ASR 产物复用，不受项目文件影响。
- 测试：
  - 项目文件创建与结构
  - 分析/翻译/润色的项目文件续跑
  - 输入或设置变化后的归档
  - 模型变化不清空项目
  - `--re-polish` 不发起翻译请求
  - 润色备份轮转
- 文档：更新 `usage.md`、`internals.md`、`troubleshooting.md`。

## 10. 注意事项

- 项目文件内嵌字幕全文，等同于 SRT 文件，可能包含敏感内容；不要随意外传或提交到公开仓库。
- 项目文件会随批次数增加而重写，但单次写入量取决于字幕长度；一小时视频通常在数百 KB 量级。
- 项目文件是唯一的翻译状态来源；不要手工编辑正在使用的项目文件，否则可能破坏续跑校验。