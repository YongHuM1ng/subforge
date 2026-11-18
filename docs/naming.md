# 文件名标准

## 标准格式

```text
作品名.来源.语言.srt
```

- 分隔符只用 `.`
- 来源：`ocr`（图像/硬字幕）、`asr`（语音识别）、`text`（文本字幕）
- 语言：ISO 639-1 两字母小写，如 `zh` `ja` `en` `ko` `fr` `de` `es` `ru` `pt` `it` `th` `vi` `id`
- 顺序固定为**来源 → 语言**，两者都可省略
- 不兼容 `jp` `eng` `whisper` `stt` 等别名

## 示例

| 文件名 | 识别结果 |
|---|---|
| `movie.ocr.ja.srt` | 日语 / OCR |
| `movie.asr.ja.srt` | 日语 / ASR |
| `movie.en.srt` | 英语 / 未标注 |
| `movie.ocr.srt` | 未标注 / OCR |
| `movie.srt` | 未标注 / 未标注 |

不符合标准的文件名会打印提示，并按“未标注”处理，不会中断运行。

旧顺序 `movie.ja.asr.srt` 现在会被判定为“元数据位置不对”，建议改名为 `movie.asr.ja.srt`。

## 译文输出命名

规则：去掉输入文件名末尾的标准「来源.语言」标记，再拼上目标语言代码。

```text
movie.asr.ja.srt              -> movie.zh.srt
movie.ocr.ja.srt              -> movie.zh.srt
movie.ja.srt                  -> movie.zh.srt
26.09 兔田佩克拉.asr.ja.srt    -> 26.09 兔田佩克拉.zh.srt
movie.srt                     -> movie.zh.srt
```

目标语言无法识别时，输出后缀为 `.translated.srt`。

## 识别产物

`src/asr/engine.py` 按同一标准输出（命令行入口是 `src/asr2srt.py`）：

```text
视频.mp4  ->  视频.asr.ja.srt
```

语种来自接口返回的 `language` 字段；取不到时按文本特征猜（假名→`ja`、韩文→`ko`、汉字→`zh`、拉丁字母→`en`）。猜不到就输出 `视频.asr.srt`（来源有标记、语言未标注）。

同名文件已存在时不会覆盖，而是自动改名：`视频.asr.ja.srt` → `视频.asr.ja.2.srt`。
解析文件名时会忽略末尾的自动序号，翻译输出仍是 `视频.zh.srt`。

## 为什么顺序是「来源 → 语言」

翻译工具会根据来源切换纠错提示：`asr` 侧重同音字/错误分词，`ocr` 侧重形近字/漏字。语言标记又决定排版宽度和针对性提示。两者都放在文件名里，可以把「这条字幕是怎么来的」一路传给翻译阶段，不需要额外参数。