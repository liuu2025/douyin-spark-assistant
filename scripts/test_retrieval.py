"""
知识库检索测试脚本

功能：
加载已经入库的 Chroma 向量库，
用几个典型用户问题测试能否召回正确知识库片段。
"""

import sys
from pathlib import Path

# 将项目根目录加入 sys.path，确保可以 import app
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from langchain_community.vectorstores import Chroma

from app.config import settings
from app.services.assistant_service import get_embeddings


COLLECTION_NAME = "douyin_user_knowledge"


def load_vectorstore():
    """
    加载本地已持久化的 Chroma 向量库。
    注意：这里不是重新入库，而是读取 scripts/ingest_knowledge.py 已经生成的数据。
    """
    embeddings = get_embeddings()

    vectorstore = Chroma(
        persist_directory=settings.CHROMA_PERSIST_DIR,
        embedding_function=embeddings,
        collection_name=COLLECTION_NAME,
    )

    return vectorstore


def print_results(question, results):
    """
    打印检索结果，方便人工判断是否召回正确。
    """
    print("\n" + "=" * 80)
    print(f"用户问题：{question}")
    print("=" * 80)

    if not results:
        print("未检索到结果")
        return

    for index, doc in enumerate(results, start=1):
        source = doc.metadata.get("source", "-")
        document_title = doc.metadata.get("document_title", "-")
        section_title = doc.metadata.get("section_title", "-")
        question_title = doc.metadata.get("question_title", "-")

        print(f"\n--- 结果 {index} ---")
        print(f"来源文件：{source}")
        print(f"文档主题：{document_title}")
        print(f"主要知识点：{section_title}")
        print(f"具体问题：{question_title}")
        print("内容片段：")
        print(doc.page_content[:500])


def main():
    """
    主流程：
    1. 加载 Chroma 向量库
    2. 准备典型用户问题
    3. 执行相似度检索
    4. 打印召回结果
    """
    vectorstore = load_vectorstore()

    test_questions = [
        "为什么添加抖音号后显示未验证？",
        "为什么任务显示正常但没有发送？",
        "兑换码兑换后为什么还是不能自动发送？",
        "登录状态无效怎么办？",
        "远程浏览器打不开怎么办？",
    ]

    for question in test_questions:
        results = vectorstore.similarity_search(
            query=question,
            k=3,
        )
        print_results(question, results)


if __name__ == "__main__":
    main()