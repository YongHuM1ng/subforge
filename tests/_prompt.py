"""测试用：从批次请求的用户消息里取出待处理字幕（<输入> 块）。"""
import json


def batch_items(user: str) -> list[dict]:
    start = user.rindex("<输入>") + len("<输入>")
    end = user.index("</输入>", start)
    return json.loads(user[start:end])
