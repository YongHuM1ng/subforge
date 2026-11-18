import sys
from pathlib import Path

# 让测试在 src 布局下能导入 srt_translator。
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))