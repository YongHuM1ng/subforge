import json
import re
from typing import Any


def extract_json(text: str) -> Any:
    if not isinstance(text, str):
        raise ValueError("模型响应不是有效的 JSON 文本")
    if len(text) > 1_000_000:
        raise ValueError("模型响应过大，无法解析为 JSON")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(text[start:end + 1])
