import os
import sys
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = {
    "api": {
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
        "api_key": "",
        "timeout": 120,
        "retries": 3,
        "structured_output": "json_schema",
        "proxy": "system",
    },
    "translation": {
        "source": "自动识别",
        "target": "简体中文",
        "polish": True,
        "pause_before_polish": False,
        "natural_segmentation": True,
        "translation_fidelity": "natural",
    },
    "prompts": {
        "additional": "",
    },
    "processing": {
        "batch_size": 20,
        "context": 3,
        "global_analysis": True,
        "max_workers": 2,
    },
    "models": {
        "fallback_enabled": True,
        "fallback": "",
    },
}

# 数值字段的合法范围（含两端）。
RANGES = {
    ("api", "timeout"): (1, 3600),
    ("api", "retries"): (0, 20),
    ("processing", "batch_size"): (1, 500),
    ("processing", "context"): (0, 100),
    ("processing", "max_workers"): (1, 32),
}

CHOICES = {
    ("api", "structured_output"): ("json_schema", "json_object", "none"),
    ("translation", "translation_fidelity"): ("faithful", "natural", "creative"),
}

BOOLEANS = {
    ("translation", "polish"),
    ("translation", "pause_before_polish"),
    ("translation", "natural_segmentation"),
    ("processing", "global_analysis"),
    ("models", "fallback_enabled"),
}

STRINGS = {
    ("api", "endpoint"), ("api", "model"), ("api", "api_key"), ("api", "proxy"),
    ("translation", "source"), ("translation", "target"), ("prompts", "additional"),
}

MODEL_KEYS = (
    "analysis", "translation", "polish",
    "analysis_fallback", "translation_fallback", "polish_fallback",
)

# [asr] 由识别侧 asr/config.py 读取，这里只认段名，不检查字段。
KNOWN_SECTIONS = {"api", "translation", "prompts", "processing", "models", "asr"}


def load_config(path: Path) -> dict[str, Any]:
    config = _copy(DEFAULT_CONFIG)
    if path.exists():
        with path.open("rb") as file:
            data = tomllib.load(file)
        warn_unknown_keys(data, path.name)
        _merge(config, data)
    return config


def warn_unknown_keys(data: dict[str, Any], name: str = "config.toml") -> list[str]:
    """拼错的字段会被静默忽略；这里打印提示，但不中断。返回未知项列表便于测试。"""
    unknown: list[str] = []
    for section, values in data.items():
        if section not in KNOWN_SECTIONS:
            unknown.append(f"[{section}]")
            continue
        if section == "asr" or not isinstance(values, dict):
            continue
        known = set(DEFAULT_CONFIG.get(section, {}))
        if section == "models":
            known |= set(MODEL_KEYS)
        unknown.extend(f"{section}.{key}" for key in values if key not in known)
    if unknown:
        print(f"[提示] {name} 中有未识别的配置项，将被忽略：{', '.join(unknown)}", file=sys.stderr)
    return unknown


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """检查类型与范围；有问题时抛 ValueError，列出全部错误项，不静默改成默认值。"""
    errors: list[str] = []

    def get(section: str, key: str) -> Any:
        values = config.get(section)
        return values.get(key) if isinstance(values, dict) else None

    for (section, key), (low, high) in RANGES.items():
        value = get(section, key)
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"{section}.{key} 必须是整数（当前 {value!r}）")
        elif not low <= value <= high:
            errors.append(f"{section}.{key} 必须在 {low}–{high} 之间（当前 {value}）")
    for (section, key), options in CHOICES.items():
        value = get(section, key)
        if value not in options:
            errors.append(f"{section}.{key} 只能是 {' / '.join(options)}（当前 {value!r}）")
    for section, key in BOOLEANS:
        value = get(section, key)
        if not isinstance(value, bool):
            errors.append(f"{section}.{key} 必须是 true 或 false（当前 {value!r}，注意不要加引号）")
    for section, key in STRINGS:
        value = get(section, key)
        if not isinstance(value, str):
            errors.append(f"{section}.{key} 必须是字符串（当前 {value!r}）")
    models = config.get("models")
    if isinstance(models, dict):
        for key in ("fallback", *MODEL_KEYS):
            value = models.get(key)
            if value is not None and not isinstance(value, str):
                errors.append(f"models.{key} 必须是字符串（当前 {value!r}）")
    if errors:
        raise ValueError("config.toml 配置有误：\n  - " + "\n  - ".join(errors))
    return config


def apply_environment(config: dict[str, Any]) -> dict[str, Any]:
    # Environment variables are useful for secrets and override TOML values.
    mapping = {
        "LLM_API_KEY": ("api", "api_key"),
        "LLM_API_URL": ("api", "endpoint"),
        "LLM_MODEL": ("api", "model"),
        "LLM_PROXY": ("api", "proxy"),
    }
    for env_name, (section, key) in mapping.items():
        if os.getenv(env_name):
            config[section][key] = os.environ[env_name]
    return config


def resolve_models(config: dict[str, Any], overrides: dict[str, str | None],
                   no_fallback: bool = False) -> tuple[dict[str, str], dict[str, str], bool]:
    """按阶段解析主模型与回退模型。

    overrides 是命令行的 {阶段: 模型}，优先于 [models]。
    返回 (stage_models, fallback_models, fallback_enabled)；未配置的阶段不出现在 dict 里。
    """
    models = config.get("models") if isinstance(config.get("models"), dict) else {}

    def clean(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    stages = ("analysis", "translation", "polish")
    stage_models = {
        stage: value for stage in stages
        if (value := clean(overrides.get(stage)) or clean(models.get(stage)))
    }
    default_fallback = clean(models.get("fallback"))
    fallback_models = {
        stage: value for stage in stages
        if (value := clean(models.get(f"{stage}_fallback")) or default_fallback)
    }
    enabled = models.get("fallback_enabled", True) is not False and not no_fallback
    return stage_models, fallback_models, enabled


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    return value


def _merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value
