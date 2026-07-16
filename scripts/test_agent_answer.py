"""
Agent 回答测试脚本。

这个脚本会走完整 Agent 流程：
1. 检索本地知识库。
2. 调用内部只读工具查询实时状态。
3. 调用大模型生成回答。

运行示例：
python scripts/test_agent_answer.py
python scripts/test_agent_answer.py --token 你的token --douyin-id 抖音号ID
"""

from __future__ import annotations

import argparse
import os
import sys


# 把项目根目录加入 Python 模块搜索路径。
# 这样脚本可以 import app.services.agent_service。
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.agent_service import answer_with_agent, source_doc_to_dict


def main() -> None:
    # argparse 是 Python 标准库，用来读取命令行参数。
    parser = argparse.ArgumentParser(description="测试 Agent 客服回答")
    parser.add_argument("--token", default=os.getenv("DOUYIN_SPARK_TOKEN"), help="用户登录 token")
    parser.add_argument("--douyin-id", default=None, help="要重点查询的抖音号 ID")
    parser.add_argument("--page", default="测试脚本", help="模拟当前页面")
    parser.add_argument(
        "--question",
        default="为什么任务显示正常但没有发送？",
        help="模拟用户问题",
    )
    args = parser.parse_args()

    result = answer_with_agent(
        question=args.question,
        token=args.token,
        current_page=args.page,
        douyin_id=args.douyin_id,
    )

    print("=" * 80)
    print("用户问题")
    print("=" * 80)
    print(args.question)

    print("\n" + "=" * 80)
    print("Agent 回答")
    print("=" * 80)
    print(result.answer)

    print("\n" + "=" * 80)
    print("内部工具")
    print("=" * 80)
    for item in result.tool_results:
        status = "成功" if item.ok else "失败"
        print(f"- {item.name}：{status}；{item.summary}")

    print("\n" + "=" * 80)
    print("知识库来源")
    print("=" * 80)
    for doc in result.source_docs:
        print(source_doc_to_dict(doc))


if __name__ == "__main__":
    main()
