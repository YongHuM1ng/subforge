# 便携包构建

生成 Windows 免安装包，内置 Python 3.11.9 embeddable 和 aiohttp 依赖。

```powershell
.\.venv\Scripts\python.exe packaging\build_portable.py --variant both
```

产物在 `dist\`：

- `SubForge-<版本>-portable.zip`：不带 ffmpeg，用户自行安装或放到 `tools\ffmpeg\bin`
- `SubForge-<版本>-portable-ffmpeg.zip`：附带 ffmpeg / ffprobe，解压即用

`--variant base` 或 `--variant ffmpeg` 可以只构建其中一个；`--refresh` 会重新下载
Python、aiohttp 轮子和 ffmpeg。

## 缓存

下载内容放在 `packaging/.cache/`（已忽略，不会提交）：

- `python-3.11.9-embed-amd64.zip`
- `wheels/`：用 pip 为 cp311 win_amd64 下载的 aiohttp 依赖
- ffmpeg 压缩包

Python 压缩包有内置 SHA-256 校验；aiohttp 轮子由 pip 负责下载。

## ffmpeg 来源

附带版固定使用 FFmpeg-Builds 的一个日期构建，而不是会变化的 `latest` 标签：

```text
autobuild-2026-11-17-12-40 / ffmpeg-n8.1.3-35-gf1acb0a266-win64-lgpl-8.1.zip
```

构建时从 `ghfast.top` 镜像或官方 GitHub 下载，并用该 release 的
`checksums.sha256` 校验。升级版本时修改 `packaging/build_portable.py` 顶部的
`FFMPEG_TAG` / `FFMPEG_ASSET`。

`tools/ffmpeg/` 里会写入：

- `bin/ffmpeg.exe`、`bin/ffprobe.exe`
- `LICENSE.txt`：该构建附带的 LGPL 许可证
- `NOTICE.txt`：来源地址、校验值、许可证和可替换说明

这是 LGPL 构建。重新分发时保留上述文件；项目源码仍为 MIT。

## 发布

```powershell
git tag v0.1.0
git push origin v0.1.0
gh release create v0.1.0 dist\SubForge-0.1.0-portable.zip dist\SubForge-0.1.0-portable-ffmpeg.zip `
  --title "SubForge 0.1.0" --notes "首个便携版"
```

`v0.1.0` 和产物文件名里的版本要与 `pyproject.toml` 一致。
