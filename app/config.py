import os
from pathlib import Path


# load_dotenv 会读取项目根目录的 .env 文件。
# override=True 表示 .env 里的值可以覆盖系统环境变量，方便本地调试。
try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    # 没安装 python-dotenv 时，用一个很小的兜底函数读取 .env。
    # 这里只支持 KEY=VALUE 这种常见写法，够本项目本地配置使用。
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        for line in _env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


class Settings:
    # 大模型聊天接口配置。
    APISHOP_API_KEY = os.getenv("APISHOP_API_KEY")
    APISHOP_BASE_URL = os.getenv("APISHOP_BASE_URL")
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL")
    CHAT_MODEL: str = os.getenv("CHAT_MODEL", "deepseek-v4-flash")

    # Embedding 接口配置。入库和检索要使用同一套 Embedding 配置。
    SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY")
    SILICONFLOW_BASE_URL = os.getenv("SILICONFLOW_BASE_URL")
    EMBEDDING_MODEL: str = os.getenv(
        "EMBEDDING_MODEL",
        "Qwen/Qwen3-Embedding-0.6B",
    )

    # douyin-spark 后端 API 地址。
    # assistant 会带用户 token 调这里，查询用户自己的账号状态。
    DOUYIN_SPARK_API_BASE_URL: str = os.getenv(
        "DOUYIN_SPARK_API_BASE_URL",
        "http://localhost:8787/api/v1",
    )

    # 普通用户知识库 Markdown 文档目录。
    KNOWLEDGE_DIR: str = os.getenv("KNOWLEDGE_DIR", "./knowledge/user")

    # Chroma 向量库持久化目录。
    CHROMA_PERSIST_DIR: str = os.getenv(
        "CHROMA_PERSIST_DIR",
        "./storage/vectorstore",
    )

    # RAG 检索相关度门槛。
    # 低于这个分数的资料不返回给大模型，也不在前端“参考资料”里展示。
    KNOWLEDGE_RELEVANCE_THRESHOLD: float = float(
        os.getenv("KNOWLEDGE_RELEVANCE_THRESHOLD", "0.35")
    )

    # LangGraph Checkpointer 保存聊天状态的 SQLite 文件。
    # 它只保存当前会话上下文，不保存长期用户记忆。
    ASSISTANT_CHECKPOINT_DB_PATH: str = os.getenv(
        "ASSISTANT_CHECKPOINT_DB_PATH",
        "./storage/assistant_checkpoints.sqlite",
    )

    # 给“按百分比压缩上下文”使用的有效上下文预算。
    # 这里不是模型一定支持的最大窗口，而是本项目希望客服会话最多使用的输入 token 预算。
    ASSISTANT_CONTEXT_MAX_INPUT_TOKENS: int = int(
        os.getenv("ASSISTANT_CONTEXT_MAX_INPUT_TOKENS", "16000")
    )

    # 当历史上下文达到 75% 预算时，自动总结旧消息。
    ASSISTANT_SUMMARY_TRIGGER_FRACTION: float = float(
        os.getenv("ASSISTANT_SUMMARY_TRIGGER_FRACTION", "0.75")
    )

    # 总结后保留最近约 40% 预算的原始消息，其余旧消息变成摘要。
    ASSISTANT_SUMMARY_KEEP_FRACTION: float = float(
        os.getenv("ASSISTANT_SUMMARY_KEEP_FRACTION", "0.40")
    )


# 实例化后，其他文件可以直接 from app.config import settings。
settings = Settings()
