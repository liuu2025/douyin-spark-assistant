"""
内部工具测试脚本。

这个脚本只测试 douyin-spark 后端只读工具。
它不会调用大模型，也不会修改用户数据。

运行示例：
python scripts/test_agent_tools.py
python scripts/test_agent_tools.py --token 你的token --douyin-id 抖音号ID
"""

from __future__ import annotations

import argparse
import os
import sys


# 把项目根目录加入 Python 模块搜索路径。
# 这样脚本可以 import app.tools.douyin_tools。
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.tools.douyin_tools import collect_status_snapshot


def main() -> None:
    # argparse 是 Python 标准库，用来读取命令行参数。
    parser = argparse.ArgumentParser(description="测试 douyin-spark 内部只读工具")
    parser.add_argument("--token", default=os.getenv("DOUYIN_SPARK_TOKEN"), help="用户登录 token")
    parser.add_argument("--douyin-id", default=None, help="要重点查询的抖音号 ID")
    parser.add_argument(
        "--question",
        default="为什么任务显示正常但没有发送？",
        help="模拟用户问题",
    )
    args = parser.parse_args()

    snapshot = collect_status_snapshot(
        token=args.token,
        question=args.question,
        current_page="测试脚本",
        douyin_id=args.douyin_id,
    )

    print("=" * 80)
    print("内部工具调用摘要")
    print("=" * 80)
    print(snapshot.prompt_text())

    print("\n重点抖音号：", snapshot.selected_douyin_id or "未确定")
    print("工具数量：", len(snapshot.results))


if __name__ == "__main__":
    main()
