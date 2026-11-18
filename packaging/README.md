# 便携包构建

生成 **Windows 10/11 x64** 免安装包，内置 Python 3.11.9 embeddable 和 aiohttp 依赖。
产物不能直接用于 32 位 Windows、ARM64、Linux 或 macOS。

```powershell
.\.venv\Scripts\python.exe packaging\build_portable.py --variant both --seven-zip
```

产物在 `dist\`：

- `SubForge-<版本>-windows-x64-portable.zip`：不带 ffmpeg，用户自行安装或放到 `tools\ffmpeg\bin`
- `SubForge-<版本>-windows-x64-portable-ffmpeg.zip`：附带 ffmpeg，解压即用
- `SubForge-<版本>-windows-x64-portable-ffmpeg.7z`：同上，体积更小；需要 `--seven-zip` 且本机装有 7-Zip

不带 ffmpeg 的版本只发 zip。7z 只用于压缩 `ffmpeg.exe`，Windows 10 需要 7-Zip 才能解压。

## 包内配置

- `config.toml`：由 `config.common.toml` 生成，默认小米 MiMo + DeepSeek，通常不用改
- `config.full.toml`：完整参数；复制覆盖 `config.toml` 后行为不变
- `.env`：空白模板，预置 `ASR_API_KEY=` 和 `LLM_API_KEY=`
- `docs/install.md`：配置和启动器说明

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

- `bin/ffmpeg.exe`（识别、探测音频流、抽音轨、静音检测都只用它）
- `LICENSE.txt`：该构建附带的 LGPL 许可证
- `NOTICE.txt`：来源地址、校验值、许可证和可替换说明

这是 LGPL 构建。重新分发时保留上述文件；项目源码仍为 MIT。

## 发布

```powershell
git tag v0.2.1
git push origin v0.2.1
gh release create v0.2.1 dist\SubForge-0.2.1-windows-x64-portable.zip `
  dist\SubForge-0.2.1-windows-x64-portable-ffmpeg.zip `
  dist\SubForge-0.2.1-windows-x64-portable-ffmpeg.7z `
  --title "SubForge 0.2.1" --notes "ASR 预设、DeepSeek 默认配置、思考等级"
```

`v0.2.1` 和产物文件名里的版本要与 `pyproject.toml` 一致。
