"""
LangChain 原生 Tool 定义测试脚本。

这个脚本不调用大模型。
它只检查：
1. 内部工具是否被包装成 LangChain StructuredTool。
2. 工具是否带有 name、description、args_schema。
3. 工具执行后是否返回 Agent 可放进 ToolMessage 的 JSON 字符串。
"""

from __future__ import annotations

import json
import os
import sys


# 把项目根目录加入 Python 模块搜索路径。
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.tools.douyin_tools import create_langchain_tools


def main() -> None:
    tools = create_langchain_tools(token=None)
    print("工具数量：", len(tools))

    for tool in tools:
        print("-" * 80)
        print("工具名：", tool.name)
        print("说明：", tool.description)
        print("参数模型：", tool.args_schema.__name__ if tool.args_schema else None)

    tool_map = {tool.name: tool for tool in tools}
    result = tool_map["get_login_status"].invoke({"douyin_id": "123456"})
    payload = json.loads(result)

    print("=" * 80)
    print("工具执行结果")
    print("=" * 80)
    print("name:", payload["name"])
    print("ok:", payload["ok"])
    print("error_code:", payload["error_code"])
    print("summary:", payload["summary"])


if __name__ == "__main__":
    main()
