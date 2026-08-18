"""
Knowledge retrieval smoke test.

Loads the persisted Chroma collection created by scripts/ingest_knowledge.py
and checks whether typical user questions recall reasonable knowledge chunks.
"""

import sys
from pathlib import Path


def configure_console_encoding():
    """Keep Chinese/emoji output from crashing Windows GBK consoles."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


configure_console_encoding()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from langchain_chroma import Chroma
except ImportError:
    from langchain_community.vectorstores import Chroma

from app.config import settings
from app.services.assistant_service import get_embeddings


COLLECTION_NAME = "douyin_user_knowledge"
COLLECTION_METADATA = {"hnsw:space": "cosine"}


def load_vectorstore():
    embeddings = get_embeddings()

    return Chroma(
        persist_directory=settings.CHROMA_PERSIST_DIR,
        embedding_function=embeddings,
        collection_name=COLLECTION_NAME,
        collection_metadata=COLLECTION_METADATA,
    )


def print_results(question, results):
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
