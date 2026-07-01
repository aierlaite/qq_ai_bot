"""测试通用路径设置：把项目根目录加到 sys.path，让 src 和 main 可被导入。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 标记符号，供 `from tests._path_setup import _` 使用（触发本模块加载）
_ = None

