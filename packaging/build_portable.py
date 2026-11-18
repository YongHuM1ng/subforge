"""构建 SubForge 的 Windows 免安装便携包。

用法：
    .venv\\Scripts\\python.exe packaging\\build_portable.py --variant both --seven-zip

产物（dist/）：
    SubForge-<版本>-windows-x64-portable.zip         不带 ffmpeg，需手动放置或安装
    SubForge-<版本>-windows-x64-portable-ffmpeg.zip  自带 ffmpeg（LGPL 构建）
    加 --seven-zip 时，附带 ffmpeg 的版本会同时生成同名 .7z（需要安装 7-Zip；
    Windows 10 不自带 7z 解压）。不带 ffmpeg 的版本只发 zip。

仅支持 64 位 Windows 10/11：便携包内置的是 Windows amd64 embeddable Python 和
win64 静态 ffmpeg，不能在 32 位 Windows、ARM64、Linux 或 macOS 上直接运行。

便携包内置 Windows embeddable Python 和 aiohttp，解压后双击启动器即可运行。
ffmpeg 只在「附带版」构建时下载，并带 NOTICE 与许可证说明；应用运行时不再联网下载。
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tomllib
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "packaging" / ".cache"
WHEELS = CACHE / "wheels"
DEFAULT_OUT = ROOT / "dist"

PY_VERSION = "3.11.9"
PY_ZIP = f"python-{PY_VERSION}-embed-amd64.zip"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/{PY_ZIP}"
PY_SHA256 = "009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b"

# 固定到某个日期构建，避免 latest 标签和镜像缓存不同步导致校验失败。
FFMPEG_TAG = "autobuild-2026-11-17-12-40"
FFMPEG_ASSET = "ffmpeg-n8.1.3-35-gf1acb0a266-win64-lgpl-8.1.zip"
FFMPEG_BASE = f"https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/{FFMPEG_TAG}"
FFMPEG_URL = f"{FFMPEG_BASE}/{FFMPEG_ASSET}"
FFMPEG_SUMS = f"{FFMPEG_BASE}/checksums.sha256"
MIRROR_BASE = "https://ghfast.top/"
USER_AGENT = "SubForge-build/0.1"


def log(message: str = "") -> None:
    print(message, flush=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _openers(url: str, direct_first: bool):
    direct = ("直连", urllib.request.build_opener(urllib.request.ProxyHandler({})))
    proxies = urllib.request.getproxies()
    proxy = proxies.get("https") or proxies.get("http")
    if not proxy:
        return [direct]
    proxied = ("代理", urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    ))
    return [direct, proxied] if direct_first else [proxied, direct]


def fetch_text(url: str) -> str:
    errors = []
    for label, opener in _openers(url, direct_first=url.startswith(MIRROR_BASE)):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except Exception as exc:
            errors.append(f"{label}：{exc}")
    raise RuntimeError("；".join(errors))


def download(url: str, target: Path, direct_first: bool) -> None:
    errors = []
    for label, opener in _openers(url, direct_first):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=60) as response, target.open("wb") as file:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                percent = -10
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    file.write(chunk)
                    done += len(chunk)
                    if total:
                        current = min(100, done * 100 // total)
                        if current >= percent + 10:
                            log(f"  {current}%")
                            percent = current
            if target.stat().st_size <= 0:
                raise RuntimeError("下载结果为空")
            return
        except Exception as exc:
            errors.append(f"{label}：{exc}")
            log(f"  {label}下载失败：{exc}")
            target.unlink(missing_ok=True)
    raise RuntimeError("；".join(errors))


def ensure_python_zip(refresh: bool = False) -> Path:
    target = CACHE / PY_ZIP
    if target.exists() and not refresh and sha256(target) == PY_SHA256:
        return target
    log(f"[构建] 下载 Python {PY_VERSION} embeddable…")
    download(PY_URL, target, direct_first=False)
    actual = sha256(target)
    if actual != PY_SHA256:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"Python 压缩包 SHA-256 不匹配：{actual}")
    return target


def ensure_wheels(refresh: bool = False) -> None:
    if any(WHEELS.glob("*.whl")) and not refresh:
        return
    if refresh and WHEELS.exists():
        shutil.rmtree(WHEELS)
    WHEELS.mkdir(parents=True, exist_ok=True)
    log("[构建] 下载 aiohttp 依赖轮子…")
    command = [
        sys.executable, "-m", "pip", "download",
        "--only-binary=:all:", "--platform", "win_amd64",
        "--implementation", "cp", "--python-version", PY_VERSION.rsplit(".", 1)[0],
        "--abi", "cp311", "-d", str(WHEELS), "-r", str(ROOT / "requirements.txt"),
    ]
    subprocess.run(command, check=True, cwd=ROOT)


def ensure_ffmpeg_archive(refresh: bool = False) -> Path:
    target = CACHE / FFMPEG_ASSET
    log("[构建] 获取 ffmpeg 校验值…")
    checksum_text = None
    for url in (FFMPEG_SUMS, MIRROR_BASE + FFMPEG_SUMS):
        try:
            checksum_text = fetch_text(url)
            break
        except Exception as exc:
            log(f"  获取校验值失败：{exc}")
    if not checksum_text:
        raise RuntimeError("无法获取 ffmpeg 的 checksums.sha256")
    expected = ""
    for line in checksum_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == FFMPEG_ASSET:
            expected = parts[0].lower()
            break
    if len(expected) != 64:
        raise RuntimeError("校验文件里没有当前 ffmpeg 压缩包的 SHA-256")
    if target.exists() and not refresh and sha256(target) == expected:
        return target

    for label, url, direct_first in (
        ("ghfast.top 镜像", MIRROR_BASE + FFMPEG_URL, True),
        ("官方 GitHub", FFMPEG_URL, False),
    ):
        log(f"[构建] 下载 ffmpeg（{label}）…")
        try:
            download(url, target, direct_first)
            actual = sha256(target)
            if actual != expected:
                target.unlink(missing_ok=True)
                raise RuntimeError(f"SHA-256 不匹配：{actual}")
            return target
        except Exception as exc:
            log(f"  {label}失败：{exc}")
    raise RuntimeError("ffmpeg 下载失败，请检查网络或稍后重试")


def copy_project(staging: Path) -> None:
    for name in ("README.md", "LICENSE", "requirements.txt", "pyproject.toml"):
        shutil.copy2(ROOT / name, staging / name)
    for launcher in sorted(ROOT.glob("*.bat")):
        shutil.copy2(launcher, staging / launcher.name)
    shutil.copytree(ROOT / "src", staging / "src",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
    docs = staging / "docs"
    docs.mkdir()
    for item in (ROOT / "docs").iterdir():
        if item.is_file() and item.name != "review.md":
            shutil.copy2(item, docs / item.name)
    # 便携包放默认配置；完整参数参考放进 docs。
    shutil.copy2(ROOT / "config.common.toml", staging / "config.toml")
    shutil.copy2(ROOT / "config.toml.example", docs / "config-reference.toml")
    (staging / "首次使用.txt").write_text(
        "SubForge 便携版\n"
        "================\n\n"
        "默认：小米 MiMo 识别 + DeepSeek 官方翻译。\n\n"
        "1. 到 DeepSeek 开放平台创建 Key：https://platform.deepseek.com/api_keys\n"
        "   （小米 MiMo 的 Key 请按小米控制台创建）\n"
        "2. 在 .env 写两个 Key：\n"
        "   ASR_API_KEY=...          # 默认小米 MiMo 的 Key\n"
        "   LLM_API_KEY=...          # DeepSeek Key\n"
        "3. 双击启动器，把视频/字幕拖进去。\n\n"
        "换翻译服务：改 config.toml 的 [api] endpoint / model，\n"
        "            把该服务的 Key 写到 .env 的 LLM_API_KEY。\n"
        "完整参数参考：docs\\config-reference.toml 或 docs\\install.md。\n\n"
        "如果下载的是不带 ffmpeg 的包，请安装 ffmpeg 到 PATH，\n"
        "或把 ffmpeg.exe 放到 tools\\ffmpeg\\bin。\n",
        encoding="utf-8",
    )


def install_python(staging: Path, archive: Path) -> None:
    python_dir = staging / "runtime" / "python"
    python_dir.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(python_dir)
    pth = python_dir / "python311._pth"
    pth.write_text(
        "python311.zip\n.\nLib\\site-packages\n..\\..\\src\nimport site\n",
        encoding="utf-8",
        newline="\n",
    )
    if not (python_dir / "python.exe").exists():
        raise RuntimeError("Python embeddable 解压后缺少 python.exe")


def install_wheels(staging: Path) -> None:
    site = staging / "runtime" / "python" / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    wheels = sorted(WHEELS.glob("*.whl"))
    if not wheels:
        raise RuntimeError("没有可用的 wheel，请检查 pip download 的输出")
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as zf:
            zf.extractall(site)


def install_ffmpeg(staging: Path, archive: Path, expected: str) -> None:
    bin_dir = staging / "tools" / "ffmpeg" / "bin"
    bin_dir.mkdir(parents=True)
    license_written = False
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = Path(info.filename).name
            if name == "ffmpeg.exe":
                with zf.open(info) as source, (bin_dir / name).open("wb") as target:
                    shutil.copyfileobj(source, target)
            elif name.lower() in ("license.txt", "copying.lgplv2.1") and not license_written:
                with zf.open(info) as source, (bin_dir.parent / "LICENSE.txt").open("wb") as target:
                    shutil.copyfileobj(source, target)
                license_written = True
    if not (bin_dir / "ffmpeg.exe").exists():
        raise RuntimeError("ffmpeg 压缩包缺少 ffmpeg.exe")

    notice = (
        "FFmpeg binary bundled with SubForge\n"
        "===================================\n\n"
        f"Archive: {FFMPEG_URL}\n"
        f"SHA-256: {expected}\n"
        f"Downloaded: {date.today().isoformat()}\n"
        "Build: FFmpeg-Builds (LGPL static build, https://github.com/FFmpeg-Builds/FFmpeg-Builds)\n"
        "Source code: https://github.com/FFmpeg/FFmpeg\n"
        "License: GNU Lesser General Public License v2.1 or later\n"
        "License text: LICENSE.txt (in this directory, if provided by the build)\n\n"
        "You may replace ffmpeg.exe with another compatible build.\n"
    )
    (bin_dir.parent / "NOTICE.txt").write_text(notice, encoding="utf-8")
    if not license_written:
        (bin_dir.parent / "LICENSE.txt").write_text(
            "This build did not include LICENSE.txt. See:\n"
            "https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt\n",
            encoding="utf-8",
        )


def zip_package(staging: Path, target: Path) -> None:
    log(f"[构建] 打包 {target.name}…")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                zf.write(path, Path("SubForge") / path.relative_to(staging))
    log(f"[完成] {target}  ({target.stat().st_size / 1048576:.1f} MB)")


def find_7z() -> str | None:
    for name in ("7z", "7za"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (r"C:\Program Files\7-Zip\7z.exe",
                      r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if Path(candidate).exists():
            return candidate
    return None


def make_7z(staging: Path, target: Path) -> Path | None:
    exe = find_7z()
    if not exe:
        log("[跳过] 未找到 7-Zip，无法生成 .7z（安装 7-Zip 后加 --seven-zip 重试）")
        return None
    log(f"[构建] 打包 {target.name}…")
    subprocess.run(
        [exe, "a", "-t7z", "-mx=9", "-mmt=on", "-y",
         str(target.resolve()), "SubForge"],
        cwd=staging.parent, check=True, stdout=subprocess.DEVNULL,
    )
    log(f"[完成] {target}  ({target.stat().st_size / 1048576:.1f} MB)")
    return target


def build_variant(version: str, with_ffmpeg: bool, out_dir: Path,
                  seven_zip: bool = False) -> list[Path]:
    suffix = "portable-ffmpeg" if with_ffmpeg else "portable"
    base = f"SubForge-{version}-windows-x64-{suffix}"
    target = out_dir / f"{base}.zip"
    staging = out_dir / ".build" / "SubForge"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    log(f"\n[构建] {suffix}")
    copy_project(staging)
    install_python(staging, ensure_python_zip())
    install_wheels(staging)
    if with_ffmpeg:
        archive = ensure_ffmpeg_archive()
        expected = sha256(archive)
        install_ffmpeg(staging, archive, expected)
    zip_package(staging, target)
    built = [target]
    if seven_zip and with_ffmpeg:
        archive_7z = make_7z(staging, out_dir / f"{base}.7z")
        if archive_7z:
            built.append(archive_7z)
    shutil.rmtree(staging, ignore_errors=True)
    return built


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 SubForge Windows 便携包")
    parser.add_argument("--variant", choices=("base", "ffmpeg", "both"), default="both",
                        help="base=不带 ffmpeg；ffmpeg=附带 ffmpeg；both=两个都构建")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出目录")
    parser.add_argument("--refresh", action="store_true", help="重新下载缓存的 Python/依赖/ffmpeg")
    parser.add_argument("--seven-zip", action="store_true",
                        help="为附带 ffmpeg 的版本同时生成 .7z（Windows 10 需要 7-Zip 解压）")
    args = parser.parse_args()

    with (ROOT / "pyproject.toml").open("rb") as file:
        version = tomllib.load(file)["project"]["version"]
    args.out.mkdir(parents=True, exist_ok=True)

    ensure_python_zip(args.refresh)
    ensure_wheels(args.refresh)
    built = []
    if args.variant in ("base", "both"):
        built.extend(build_variant(version, False, args.out, args.seven_zip))
    if args.variant in ("ffmpeg", "both"):
        ensure_ffmpeg_archive(args.refresh)
        built.extend(build_variant(version, True, args.out, args.seven_zip))

    log("\n[完成] 产物：")
    for path in built:
        log(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
