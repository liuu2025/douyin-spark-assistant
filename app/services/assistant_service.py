"""智能客服模型和提示词配置。"""

from pathlib import Path

from langchain.chat_models import init_chat_model
from langchain_openai import OpenAIEmbeddings

from app.config import settings


PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "assistant_system.txt"


def get_chat_model(streaming: bool = False):
    """
    创建聊天大模型。

    init_chat_model 会根据 model 字符串创建对应的聊天模型客户端。
    DeepSeek 提供 OpenAI 兼容接口，所以这里仍然使用 openai provider。
    """
    return init_chat_model(
        model=f"openai:{settings.CHAT_MODEL}",
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        streaming=streaming,
        configurable_fields=("model", "model_provider", "temperature", "max_tokens", "streaming"),
    )


def get_embeddings():
    """
    创建 Embedding 模型。

    Embedding 用来把文本转成向量。
    入库和检索必须使用同一类 Embedding，检索结果才稳定。
    """
    if not settings.SILICONFLOW_API_KEY:
        raise RuntimeError("SILICONFLOW_API_KEY is not configured")
    if not settings.SILICONFLOW_BASE_URL:
        raise RuntimeError("SILICONFLOW_BASE_URL is not configured")

    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.SILICONFLOW_API_KEY,
        base_url=settings.SILICONFLOW_BASE_URL,
    )


def load_system_prompt() -> str:
    """
    读取系统提示词。

    系统提示词用于规定客服身份、回答边界和写作风格。
    """
    if not PROMPT_PATH.exists():
        return default_system_prompt()

    content = PROMPT_PATH.read_text(encoding="utf-8").strip()
    return content or default_system_prompt()


def default_system_prompt() -> str:
    """
    默认系统提示词。

    当 app/prompts/assistant_system.txt 还没写内容时使用。
    """
    return """你是 douyin-spark 的普通用户智能客服。

你的任务是帮助普通用户理解和使用 douyin-spark 前端页面。

你只负责以下 douyin-spark 用户功能：
1. 账号注册、登录、QQ 邮箱、账户 ID、昵称和密码。
2. 添加抖音号和远程浏览器登录。
3. 抖音登录状态，包括有效、无效、未验证和重新登录。
4. 发送任务的创建、修改、暂停、恢复和运行条件。
5. 轮次选择和任务参与轮次。
6. 兑换码、自动发送资格、绑定和过期。
7. 运行记录，以及发送成功、失败、跳过的原因。
8. douyin-spark 前端页面的操作路径和状态解释。

范围边界：
1. 只回答普通用户能看到、能操作、需要理解的内容。
2. 不负责天气、写作、编程、学习答疑、娱乐聊天、其他网站或其他系统的问题。
3. 不回答管理员后台、接口、数据库、部署、代码和开发者调试相关内容。
4. 如果问题与 douyin-spark 无关，简短说明服务范围，并引导用户提问上述功能。
5. 不要因为用户的问题与 douyin-spark 无关，就调用内部工具或编造项目相关答案。
6. 不能帮助用户绕过验证码、安全验证、平台限制或风控。遇到这类问题时，建议用户按页面提示完成正常验证，或联系人工客服。

回答规则：
1. 优先依据知识库资料和已经查询到的实际状态回答。
2. 不编造知识库或内部查询结果中没有的信息。
3. 如果资料或查询结果不足，请说明不确定，并告诉用户下一步怎么做，必要时建议联系人工客服。
4. 使用简单中文，短句优先。
5. 遇到失败场景，要说明可能原因、用户能做什么，以及仍然失败时该联系谁或查看哪里。
6. 遇到页面、状态或按钮，要说明它在哪里、什么时候点、点了之后会发生什么。
7. 不承诺发送一定成功。
""".strip()
