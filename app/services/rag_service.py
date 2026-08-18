"""
RAG 检索服务。

这个文件只负责“查资料”：
1. 加载已经入库的 Chroma 向量库。
2. 根据用户问题做相似度检索。
3. 把检索到的文档整理成适合放进 Prompt 的文本。
"""

from functools import lru_cache
from typing import List

# Document 是 LangChain 的文档对象。
# page_content 存正文，metadata 存来源文件、标题等附加信息。
from langchain_core.documents import Document

# Chroma 是向量库客户端。
# 这里用它读取 scripts/ingest_knowledge.py 已经生成的本地向量库。
try:
    from langchain_chroma import Chroma
except ImportError:
    # 兼容旧写法：如果还没安装 langchain-chroma，就继续用 langchain_community 版本。
    from langchain_community.vectorstores import Chroma

from app.config import settings


# 和入库脚本里的 collection_name 保持一致。
COLLECTION_NAME = "douyin_user_knowledge"
COLLECTION_METADATA = {"hnsw:space": "cosine"}


@lru_cache(maxsize=1)
def get_vectorstore() -> Chroma:
    """
    加载本地 Chroma 向量库。

    @lru_cache(maxsize=1) 会缓存函数结果。
    这样服务运行期间不用每次用户提问都重新创建 Chroma 对象。
    """
    # 延迟导入 get_embeddings，避免 rag_service 和 assistant_service 互相导入时出错。
    from app.services.assistant_service import get_embeddings

    # get_embeddings() 返回 Embedding 模型。
    # Chroma 用它把用户问题转成向量，再去库里找相似文本。
    embeddings = get_embeddings()

    # persist_directory 是向量库保存目录，例如 ./storage/vectorstore。
    # collection_name 是集合名称，要和入库脚本一致。
    return Chroma(
        persist_directory=settings.CHROMA_PERSIST_DIR,
        embedding_function=embeddings,
        collection_name=COLLECTION_NAME,
        collection_metadata=COLLECTION_METADATA,
    )


def retrieve_knowledge(query: str, k: int = 4) -> List[Document]:
    """
    根据用户问题检索相关知识库片段。

    参数：
    - query: 用户问题。
    - k: 返回最相似的前 k 条资料。

    返回：
    - Document 列表，每条包含 page_content 和 metadata。
    """
    # 防止空问题进入检索。
    query = query.strip()
    if not query:
        return []

    vectorstore = get_vectorstore()

    # similarity_search_with_relevance_scores 会返回：
    # 1. Document 文档片段。
    # 2. relevance score 相关度分数，通常越接近 1 越相关。
    #
    # 不能只用 similarity_search 固定拿前 k 条。
    # 否则用户问“1+1”等无关问题时，也会硬凑出 4 条参考资料。
    try:
        scored_docs = vectorstore.similarity_search_with_relevance_scores(query=query, k=k)
    except Exception:
        # 兜底：如果当前 Chroma 版本不支持相关度分数，就退回原来的检索方式。
        return vectorstore.similarity_search(query=query, k=k)

    threshold = settings.KNOWLEDGE_RELEVANCE_THRESHOLD
    return [
        doc
        for doc, score in scored_docs
        if score >= threshold
    ]


def format_docs_for_prompt(docs: List[Document]) -> str:
    """
    把检索结果整理成一段 Prompt 上下文。

    大模型不直接理解 Document 对象。
    所以要把 source、标题、正文拼成普通文本。
    """
    if not docs:
        return "未检索到相关知识库资料。"

    parts = []

    for index, doc in enumerate(docs, start=1):
        # source 来自 TextLoader，通常是 Markdown 文件路径。
        source = doc.metadata.get("source", "-")

        # 这些标题来自 MarkdownHeaderTextSplitter。
        document_title = doc.metadata.get("document_title", "")
        section_title = doc.metadata.get("section_title", "")
        question_title = doc.metadata.get("question_title", "")

        # 拼出标题路径，例如：登录状态 / 常见问题 / 登录状态无效怎么办。
        title = " / ".join(
            item for item in [document_title, section_title, question_title] if item
        )

        parts.append(
            f"【资料 {index}】\n"
            f"来源：{source}\n"
            f"标题：{title or '-'}\n"
            f"内容：\n{doc.page_content}"
        )

    return "\n\n".join(parts)
