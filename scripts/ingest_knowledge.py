"""
知识库入库脚本

功能：
读取 knowledge/user/ 下的 Markdown 文件
-> 按 Markdown 标题切分
-> 对过长小节再做递归文本分割
-> 向量化
-> 存入 Chroma

设计原则：
1. 用户知识库是 Markdown 文档，标题本身就是天然的知识边界。
2. 先按 # / ## / ### 切分，可以避免把多个不同问题混进同一个 chunk。
3. 再用 RecursiveCharacterTextSplitter 兜底处理过长小节，避免单块过大。
"""

import os
import sys
import shutil
from pathlib import Path


def configure_console_encoding():
    """Keep emoji/status output from crashing Windows GBK consoles."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


configure_console_encoding()

# 将项目根目录加入 sys.path，确保可以 import app
# __file__ 是当前脚本路径，例如 scripts/ingest_knowledge.py
# parent.parent 表示回到项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# DirectoryLoader: 批量加载目录下匹配条件的文档
# TextLoader: 按纯文本方式读取单个文件
from langchain_community.document_loaders import DirectoryLoader, TextLoader

# MarkdownHeaderTextSplitter: 按 Markdown 标题层级切分文档
# RecursiveCharacterTextSplitter: 对过长文本块做递归切分
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

# Chroma: LangChain 封装的 Chroma 向量库客户端
try:
    from langchain_chroma import Chroma
except ImportError:
    from langchain_community.vectorstores import Chroma

# settings: 项目配置对象，包含知识库目录、Chroma 持久化目录等
from app.config import settings

# get_embeddings: 获取项目中配置好的 Embedding 模型实例
from app.services.assistant_service import get_embeddings


# 是否在入库前清空旧向量库
# 建议知识库重建时设为 True，避免重复入库导致同一段内容被召回多次
RESET_VECTORSTORE = True

# Chroma collection 名称
COLLECTION_NAME = "douyin_user_knowledge"
COLLECTION_METADATA = {"hnsw:space": "cosine"}


def load_markdown_documents():
    """
    加载 knowledge/user/ 下的所有 Markdown 文件。

    返回：
        List[Document]
        每个 Document 包含：
        - page_content: Markdown 文件全文
        - metadata: 文件路径等信息
    """
    print("📄 正在加载 Markdown 文档...")

    loader = DirectoryLoader(
        path=settings.KNOWLEDGE_DIR,          # 默认 ./knowledge/user
        glob="**/*.md",                       # 递归匹配所有 Markdown 文件
        loader_cls=TextLoader,                # 使用 TextLoader 读取文本
        loader_kwargs={"encoding": "utf-8"},  # Markdown 文件使用 UTF-8
        show_progress=True,                   # 显示加载进度
    )

    documents = loader.load()

    print(f"✅ 成功加载 {len(documents)} 份 Markdown 文档")
    return documents


def split_by_markdown_headers(documents):
    """
    第一层切分：按 Markdown 标题切分。

    为什么先按标题切？
    - 当前知识库文档本身已经按功能模块、主要知识点、常见问题组织。
    - # 表示文档主题。
    - ## 表示主要知识点。
    - ### 表示具体问题或具体场景。
    - 这些标题比纯字符数更适合作为 RAG 的切分边界。

    strip_headers=False 表示保留标题文本。
    这样 chunk 里会包含类似：
        # 登录状态
        ## 各种登录状态是什么意思
    对向量检索很有帮助。
    """
    print("🧩 正在按 Markdown 标题切分...")

    headers_to_split_on = [
        ("#", "document_title"),      # 一级标题：文档主题
        ("##", "section_title"),      # 二级标题：主要知识点
        ("###", "question_title"),    # 三级标题：具体问题
    ]

    markdown_splitter = MarkdownHeaderTextSplitter(
        # 指定按哪些 Markdown 标题层级切分，并把标题写入 metadata。
        headers_to_split_on=headers_to_split_on,
        # 保留标题行，让 chunk 自带“属于哪个功能/问题”的上下文，利于 RAG 检索。
        strip_headers=False,
    )

    # 保存按 Markdown 标题切出的第一层文本块，后面再处理过长的小节。
    header_chunks = []

    for doc in documents:
        # MarkdownHeaderTextSplitter.split_text 接收字符串，返回 Document 列表
        split_docs = markdown_splitter.split_text(doc.page_content)

        # split_text 生成的新 Document 会带有标题 metadata
        # 这里把原始文件 metadata 合并回去，避免丢失 source 文件路径
        for split_doc in split_docs:
            split_doc.metadata = {
                **doc.metadata,
                **split_doc.metadata,
            }
            header_chunks.append(split_doc)

    print(f"✅ Markdown 标题切分完成，共 {len(header_chunks)} 个标题块")
    return header_chunks


def split_long_chunks(header_chunks):
    """
    第二层切分：对过长标题块做递归切分。

    当前用户知识库的小节普遍较短：
    - 平均小节约 139 字
    - 大多数小节小于 300 字
    - 最长小节约 418 字

    因此这里设置 chunk_size=800，并不是为了把文档切大，
    而是为了让绝大多数完整小节不再被切碎。

    只有未来某个小节写得过长时，才会被继续切分。
    """
    print("✂️ 正在处理过长标题块...")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,       # 标题切分后再兜底，800 可以尽量保留完整小节
        chunk_overlap=80,     # 只在长小节内部重叠，保留少量上下文
        separators=[
            "\n\n",           # 优先按段落切
            "\n",             # 再按换行切
            "。",             # 中文句号
            "！",             # 中文感叹号
            "？",             # 中文问号
            "；",             # 中文分号
            " ",              # 空格
            "",               # 最后按字符切
        ],
    )

    chunks = text_splitter.split_documents(header_chunks)

    print(f"✅ 文本切分完成，共 {len(chunks)} 个最终文本块")
    return chunks


def print_chunk_summary(chunks):
    """
    打印 chunk 简要统计，方便检查切分是否合理。

    如果平均长度特别小，说明切得太碎。
    如果最大长度特别大，说明可能有长段落没有被切开。
    """
    if not chunks:
        print("⚠️ 没有生成任何文本块")
        return

    lengths = [len(chunk.page_content) for chunk in chunks]
    avg_len = sum(lengths) / len(lengths)
    max_len = max(lengths)
    min_len = min(lengths)

    print("📊 文本块统计：")
    print(f"   - 数量：{len(chunks)}")
    print(f"   - 最短：{min_len} 字")
    print(f"   - 平均：{avg_len:.1f} 字")
    print(f"   - 最长：{max_len} 字")


def reset_vectorstore_if_needed():
    """
    按需清空旧 Chroma 向量库目录。

    为什么建议重建？
    - 知识库文档经常会修改。
    - 如果不清空旧数据，重复运行脚本可能导致重复内容被入库。
    - 重复内容会让 RAG 召回结果变脏，智能客服可能反复引用同一段。
    """
    persist_dir = Path(settings.CHROMA_PERSIST_DIR)

    if not RESET_VECTORSTORE:
        print("ℹ️ 已跳过清空旧向量库")
        return

    if not persist_dir.exists():
        print("ℹ️ 旧向量库目录不存在，无需清空")
        return

    print(f"🧹 正在清空旧向量库目录：{persist_dir}")
    shutil.rmtree(persist_dir)
    print("✅ 旧向量库已清空")


def build_vectorstore(chunks):
    """
    生成向量并写入 Chroma。

    Chroma.from_documents 会自动完成：
    1. 调用 Embedding 模型把文本转成向量。
    2. 保存向量。
    3. 保存原始文本。
    4. 保存 metadata。
    """
    print("🧠 正在初始化 Embedding 模型...")
    embeddings = get_embeddings()

    print("💾 正在生成向量并写入 Chroma...")

    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=settings.CHROMA_PERSIST_DIR,
        collection_name=COLLECTION_NAME,
        collection_metadata=COLLECTION_METADATA,
    )

    print("🎉 向量库创建成功")
    print(f"   - 存储目录：{settings.CHROMA_PERSIST_DIR}")
    print(f"   - collection：{COLLECTION_NAME}")
    print(f"   - 相似度空间：{COLLECTION_METADATA['hnsw:space']}")

    return vectorstore


def main():
    """
    主流程：
    1. 加载 Markdown 文档
    2. 按 Markdown 标题切分
    3. 对过长小节做递归切分
    4. 清空旧向量库
    5. 生成向量并写入 Chroma
    """
    documents = load_markdown_documents()

    if not documents:
        print("⚠️ 未加载到任何 Markdown 文档，请检查 settings.KNOWLEDGE_DIR")
        return

    header_chunks = split_by_markdown_headers(documents)
    chunks = split_long_chunks(header_chunks)

    if not chunks:
        print("⚠️ 未生成任何文本块，入库已停止")
        return

    print_chunk_summary(chunks)

    reset_vectorstore_if_needed()
    build_vectorstore(chunks)


if __name__ == "__main__":
    main()
