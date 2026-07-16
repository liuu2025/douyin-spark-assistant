"""
douyin-spark-assistant 服务入口。

运行方式示例：
uvicorn app.main:app --reload --port 8000
"""

import json
from typing import Any

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationMemoryUsage as ConversationMemoryUsageSchema,
    ConversationMessage,
    ConversationSummary,
    CreateConversationResponse,
    DeleteConversationResponse,
    HealthResponse,
    KnowledgeSource,
    AssistantActionSuggestion,
    ToolCallSummary,
)
from app.services.agent_service import (
    answer_with_agent,
    create_conversation_id,
    delete_conversation,
    get_conversation_memory_usage,
    get_conversation_messages,
    list_conversations,
    memory_usage_to_dict,
    source_doc_to_dict,
    stream_answer_with_agent,
)


# FastAPI 是 Python 常用 Web 框架。
# app 对象就是整个 HTTP 服务，路由都挂在它上面。
app = FastAPI(title="douyin-spark-assistant")

# CORS 中间件允许浏览器前端跨端口访问 assistant。
# 本地开发时前端和 assistant 端口通常不同，所以这里先放开。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """健康检查接口，用来确认 assistant 服务是否启动。"""
    return HealthResponse(status="ok", service="douyin-spark-assistant")


@app.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
    x_assistant_user_id: str | None = Header(default=None),
) -> ChatResponse:
    """
    智能客服聊天接口。

    Header 会读取 HTTP 请求头。
    前端应传 Authorization: Bearer <token>。
    """
    token = extract_bearer_token(authorization)

    # answer_with_agent 会完成：知识库检索、内部工具查询、大模型回答。
    result = answer_with_agent(
        question=request.message,
        token=token,
        user_id=x_assistant_user_id,
        conversation_id=request.conversation_id,
        current_page=request.current_page,
        douyin_id=request.douyin_id,
        top_k=request.top_k,
    )

    # 把内部 dataclass 转成 Pydantic 响应模型。
    tools = [
        ToolCallSummary(
            name=item.name,
            ok=item.ok,
            summary=item.summary,
            error_code=item.error_code,
        )
        for item in result.tool_results
    ]

    sources = [
        KnowledgeSource(**source_doc_to_dict(doc))
        for doc in result.source_docs
    ]

    return ChatResponse(
        answer=result.answer,
        conversation_id=result.conversation_id,
        selected_douyin_id=result.selected_douyin_id,
        tools=tools,
        sources=sources,
        memory=ConversationMemoryUsageSchema(**memory_usage_to_dict(result.memory)) if result.memory else None,
        action_suggestion=(
            AssistantActionSuggestion(**result.action_suggestion.__dict__)
            if result.action_suggestion
            else None
        ),
    )


@app.post("/chat/stream")
def chat_stream(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
    x_assistant_user_id: str | None = Header(default=None),
) -> StreamingResponse:
    """
    智能客服流式聊天接口。

    使用 Server-Sent Events 返回：
    event: start/status/delta/tool/done/error
    data: JSON
    """
    token = extract_bearer_token(authorization)

    def event_stream():
        for event in stream_answer_with_agent(
            question=request.message,
            token=token,
            user_id=x_assistant_user_id,
            conversation_id=request.conversation_id,
            current_page=request.current_page,
            douyin_id=request.douyin_id,
            top_k=request.top_k,
        ):
            yield format_sse(event.type, event.data)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/conversations", response_model=CreateConversationResponse)
def create_conversation() -> CreateConversationResponse:
    """
    创建一个新的会话 ID。

    真正的历史消息会在用户第一次发送问题时写入 Checkpointer。
    """
    return CreateConversationResponse(conversation_id=create_conversation_id())


@app.get("/conversations", response_model=ConversationListResponse)
def conversations(
    x_assistant_user_id: str | None = Header(default=None),
) -> ConversationListResponse:
    """读取当前用户的智能客服会话列表。"""
    items = [
        ConversationSummary(conversation_id=item.conversation_id, title=item.title)
        for item in list_conversations(x_assistant_user_id)
    ]
    return ConversationListResponse(items=items)


@app.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def conversation_detail(
    conversation_id: str,
    x_assistant_user_id: str | None = Header(default=None),
) -> ConversationDetailResponse:
    """读取某个会话当前保存的可展示消息。"""
    messages = [
        ConversationMessage(role=item.role, content=item.content)
        for item in get_conversation_messages(x_assistant_user_id, conversation_id)
    ]
    memory = get_conversation_memory_usage(x_assistant_user_id, conversation_id)
    return ConversationDetailResponse(
        conversation_id=conversation_id,
        messages=messages,
        memory=ConversationMemoryUsageSchema(**memory_usage_to_dict(memory)),
    )


@app.delete("/conversations/{conversation_id}", response_model=DeleteConversationResponse)
def remove_conversation(
    conversation_id: str,
    x_assistant_user_id: str | None = Header(default=None),
) -> DeleteConversationResponse:
    """删除某个会话的 Checkpoint。"""
    delete_conversation(x_assistant_user_id, conversation_id)
    return DeleteConversationResponse(status="ok")


def extract_bearer_token(authorization: str | None) -> str | None:
    """
    从 Authorization 请求头里提取 token。

    标准格式是：Bearer abc.def.xxx
    只返回后面的 token 字符串。
    """
    if not authorization:
        return None

    value = authorization.strip()
    prefix = "Bearer "
    if value.lower().startswith(prefix.lower()):
        return value[len(prefix):].strip() or None

    # 兼容用户直接传 token 的情况。
    return value or None


def format_sse(event: str, data: dict[str, Any]) -> str:
    """把事件名和 JSON 数据格式化成 SSE 文本。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
