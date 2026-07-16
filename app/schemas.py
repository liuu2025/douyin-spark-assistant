"""
FastAPI 请求和响应模型。

Pydantic 的 BaseModel 用来声明 JSON 字段。
FastAPI 会根据这些模型自动校验请求体，并生成接口文档。
"""

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """POST /chat 的请求体。"""

    message: str = Field(..., description="用户输入的问题")
    conversation_id: str | None = Field(None, description="会话 ID，可选；不传时自动创建")
    current_page: str | None = Field(None, description="用户当前所在页面，可选")
    douyin_id: str | None = Field(None, description="当前抖音号 ID，可选")
    top_k: int = Field(4, description="知识库检索条数")


class ToolCallSummary(BaseModel):
    """一次内部工具调用摘要。"""

    name: str
    ok: bool
    summary: str
    error_code: str | None = None


class KnowledgeSource(BaseModel):
    """被引用的知识库来源。"""

    source: str = ""
    document_title: str = ""
    section_title: str = ""
    question_title: str = ""


class ConversationMemoryUsage(BaseModel):
    """当前会话上下文使用情况。"""

    current_tokens: int = 0
    max_tokens: int = 1
    current_fraction: float = 0
    trigger_fraction: float = 0.75
    keep_fraction: float = 0.4
    trigger_tokens: int = 0
    keep_tokens: int = 0


class AssistantActionSuggestion(BaseModel):
    """前端可展示的操作建议；只提示，不直接修改业务状态。"""

    type: str
    target_state: bool
    title: str
    message: str
    button_label: str
    reason: str = ""
    requires_account_selection: bool = True
    requires_confirmation: bool = True


class ChatResponse(BaseModel):
    """POST /chat 的响应体。"""

    answer: str
    conversation_id: str
    selected_douyin_id: str | None = None
    # default_factory=list 表示每个响应对象都有自己的新列表。
    tools: list[ToolCallSummary] = Field(default_factory=list)
    sources: list[KnowledgeSource] = Field(default_factory=list)
    memory: ConversationMemoryUsage | None = None
    action_suggestion: AssistantActionSuggestion | None = None


class ConversationSummary(BaseModel):
    """会话列表中的一条会话摘要。"""

    conversation_id: str
    title: str


class ConversationMessage(BaseModel):
    """前端展示用的会话消息。"""

    role: str
    content: str


class CreateConversationResponse(BaseModel):
    """POST /conversations 的响应体。"""

    conversation_id: str


class ConversationListResponse(BaseModel):
    """GET /conversations 的响应体。"""

    items: list[ConversationSummary] = Field(default_factory=list)


class ConversationDetailResponse(BaseModel):
    """GET /conversations/{conversation_id} 的响应体。"""

    conversation_id: str
    messages: list[ConversationMessage] = Field(default_factory=list)
    memory: ConversationMemoryUsage


class DeleteConversationResponse(BaseModel):
    """DELETE /conversations/{conversation_id} 的响应体。"""

    status: str


class HealthResponse(BaseModel):
    """GET /health 的响应体。"""

    status: str
    service: str


class ErrorResponse(BaseModel):
    """统一错误响应格式。"""

    error: dict[str, Any]
