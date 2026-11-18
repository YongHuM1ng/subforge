"""网络公共工具：代理配置解析。"""
from __future__ import annotations

import urllib.parse
import urllib.request


def resolve_proxy(endpoint: str, value: str | None) -> str | None:
    """解析代理设置。

    - "system"（默认）：使用系统代理（环境变量 + Windows 注册表），没有则直连。
    - "none" / "off" / "direct" / 空：从不使用代理。
    - 其他值：按 URL 使用指定代理。
    """
    value = (value or "").strip()
    if value.lower() in ("", "none", "off", "direct"):
        return None
    if value.lower() != "system":
        return value if "://" in value else "http://" + value
    try:
        proxies = urllib.request.getproxies()
    except (OSError, ValueError):
        return None
    if not proxies:
        return None
    scheme = urllib.parse.urlsplit(endpoint).scheme.lower() or "http"
    proxy = proxies.get(scheme) or proxies.get("https") or proxies.get("http") or proxies.get("all")
    if not proxy:
        return None
    return proxy if "://" in proxy else "http://" + proxy