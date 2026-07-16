"""
智能客服 Agent 服务。

这一版使用 LangChain 原生 Agent + Tool Calling：
1. create_agent 会创建一个 LangGraph Agent。
2. StructuredTool 会把内部工具名称、说明、参数 schema 交给大模型。
3. 大模型需要工具时，会返回 tool_calls。
4. LangGraph 会执行工具，并把 ToolMessage 放回对话。
5. 没有新的 tool_calls 时，最后一条 AIMessage.content 就是最终答案。

同时接入：
1. LangGraph SQLite Checkpointer：按 conversation_id 保存当前会话状态。
2. SummarizationMiddleware：上下文接近预算时自动总结旧消息。
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.checkpoint.sqlite import SqliteSaver

from app.config import settings
from app.services.assistant_service import get_chat_model, load_system_prompt
from app.services.rag_service import format_docs_for_prompt, retrieve_knowledge
from app.tools.douyin_tools import ToolResult, create_langchain_tools, tool_result_from_json


@dataclass
class AgentAnswer:
    """Agent 最终返回给 API 层的数据。"""

    answer: str
    conversation_id: str
    tool_results: list[ToolResult]
    source_docs: list[Document]
    selected_douyin_id: str | None = None
    memory: "ConversationMemoryUsage | None" = None
    action_suggestion: "ActionSuggestion | None" = None


@dataclass
class ActionSuggestion:
    """前端可展示的操作建议；它不代表已经执行操作。"""

    type: str
    target_state: bool
    title: str
    message: str
    button_label: str
    reason: str = ""
    requires_account_selection: bool = True
    requires_confirmation: bool = True


@dataclass
class ConversationMemoryUsage:
    """当前会话上下文使用情况。"""

    current_tokens: int
    max_tokens: int
    current_fraction: float
    trigger_fraction: float
    keep_fraction: float
    trigger_tokens: int
    keep_tokens: int


@dataclass
class ConversationItem:
    """会话列表里展示的一条记录。"""

    conversation_id: str
    title: str


@dataclass
class DisplayMessage:
    """前端展示用的简化消息。"""

    role: str
    content: str


@dataclass
class AgentStreamEvent:
    """流式接口返回给 FastAPI 的事件。"""

    type: str
    data: dict[str, Any]


_CHECKPOINTER: SqliteSaver | None = None
_CHECKPOINTER_CONN: sqlite3.Connection | None = None


def answer_with_agent(
    question: str,
    token: str | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
    current_page: str | None = None,
    douyin_id: str | None = None,
    top_k: int = 4,
    max_rounds: int = 8,
) -> AgentAnswer:
    """
    根据用户问题生成智能客服回答。

    conversation_id 对应 LangGraph 的 thread_id。
    为了避免不同用户串会话，真正保存时会加上 user_id 前缀。
    """
    conversation_id = normalize_conversation_id(conversation_id)
    question = question.strip()
    if not question:
        return AgentAnswer(
            answer="请先输入你的问题。",
            conversation_id=conversation_id,
            tool_results=[],
            source_docs=[],
        )

    # retrieve_knowledge 会在 Chroma 向量库中找和问题最相关的知识库片段。
    docs = retrieve_knowledge(question, k=top_k)
    knowledge_context = format_docs_for_prompt(docs)

    # create_langchain_tools 会创建带名称、说明、参数 schema 的标准 LangChain Tools。
    # token 来自当前请求，所以每次请求都重新创建工具，确保查的是当前用户自己的数据。
    tools = create_langchain_tools(token)

    # create_agent 创建的是 LangGraph Agent。
    # checkpointer 保存同一个 thread_id 下的历史消息，下一轮会自动接上。
    agent = create_agent(
        model=chat_model_with_profile(),
        tools=tools,
        system_prompt=build_system_prompt_for_tools(),
        middleware=[create_summary_middleware()],
        checkpointer=get_checkpointer(),
    )

    scoped_thread_id = build_scoped_thread_id(user_id, conversation_id)
    config = {
        # thread_id 是 LangGraph Checkpointer 用来区分会话的关键字段。
        "configurable": {"thread_id": scoped_thread_id},
        # recursion_limit 防止模型一直要求工具调用导致无限循环。
        "recursion_limit": max_rounds * 2 + 4,
    }

    # HumanMessage 表示本轮用户输入。
    # 这里放入当前页面、抖音号、RAG 资料和用户问题，方便模型结合当前场景回答。
    user_message = HumanMessage(
        content=build_user_prompt(
            question=question,
            knowledge_context=knowledge_context,
            current_page=current_page,
            douyin_id=douyin_id,
            has_token=bool(token),
        )
    )

    # invoke 会执行完整 Agent 流程：
    # 追加本轮用户消息 -> 调模型 -> 如需工具则执行工具 -> 再调模型 -> 得到最终回答。
    result = agent.invoke({"messages": [user_message]}, config=config)
    messages = result.get("messages", []) if isinstance(result, dict) else []
    turn_messages = messages_after_latest_user_question(messages, question)

    tool_results, selected_douyin_id = collect_tool_results(turn_messages, douyin_id)
    answer = find_final_answer(turn_messages)

    return AgentAnswer(
        answer=answer or "暂时没有生成回答，请稍后再试。",
        conversation_id=conversation_id,
        tool_results=tool_results,
        source_docs=docs,
        selected_douyin_id=selected_douyin_id,
        memory=get_conversation_memory_usage(user_id, conversation_id),
        action_suggestion=build_action_suggestion(question, tool_results),
    )


def stream_answer_with_agent(
    question: str,
    token: str | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
    current_page: str | None = None,
    douyin_id: str | None = None,
    top_k: int = 4,
    max_rounds: int = 8,
) -> Iterator[AgentStreamEvent]:
    """
    流式生成智能客服回答。

    这里用 SSE 事件表达过程：
    - start: 会话开始
    - status: 当前阶段
    - delta: 回答文本增量
    - tool: 工具检查结果
    - done: 最终结果和本轮元数据
    - error: 出错信息
    """
    conversation_id = normalize_conversation_id(conversation_id)
    question = question.strip()
    if not question:
        yield AgentStreamEvent("error", {"message": "请先输入你的问题。"})
        return

    yield AgentStreamEvent(
        "start",
        {
            "conversation_id": conversation_id,
            "memory": memory_usage_to_dict(get_conversation_memory_usage(user_id, conversation_id)),
        },
    )

    try:
        yield AgentStreamEvent("status", {"message": "正在检索知识库资料"})
        docs = retrieve_knowledge(question, k=top_k)
        knowledge_context = format_docs_for_prompt(docs)
        yield AgentStreamEvent("status", {"message": "知识库检索完成，正在让大模型分析"})

        tools = create_langchain_tools(token)
        log_agent_debug(
            "turn_start",
            conversation_id=conversation_id,
            user_id=user_id or "",
            has_token=bool(token),
            current_page=current_page or "",
            douyin_id=douyin_id or "",
            question=question,
            tool_names=[tool.name for tool in tools],
        )
        agent = create_agent(
            model=chat_model_with_profile(streaming=True),
            tools=tools,
            system_prompt=build_system_prompt_for_tools(),
            middleware=[create_summary_middleware(streaming=False)],
            checkpointer=get_checkpointer(),
        )

        scoped_thread_id = build_scoped_thread_id(user_id, conversation_id)
        config = {
            "configurable": {"thread_id": scoped_thread_id},
            "recursion_limit": max_rounds * 2 + 4,
        }

        user_message = HumanMessage(
            content=build_user_prompt(
                question=question,
                knowledge_context=knowledge_context,
                current_page=current_page,
                douyin_id=douyin_id,
                has_token=bool(token),
            )
        )

        yield AgentStreamEvent("status", {"message": "大模型正在分析问题"})
        streamed_text = ""

        # stream_mode="messages" 会返回模型消息、工具消息或模型增量消息。
        # 支持流式的模型会分多次返回 AIMessageChunk；不支持时可能一次返回完整 AIMessage。
        for message, metadata in agent.stream(
            {"messages": [user_message]},
            config=config,
            stream_mode="messages",
        ):
            node = metadata.get("langgraph_node") if isinstance(metadata, dict) else ""

            if isinstance(message, ToolMessage):
                result = tool_result_from_json(message_content_to_text(message.content))
                yield AgentStreamEvent(
                    "tool",
                    {
                        "name": result.name,
                        "ok": result.ok,
                        "summary": result.summary,
                        "error_code": result.error_code,
                    },
                )
                yield AgentStreamEvent("status", {"message": "工具检查完成，大模型正在整理结果"})
                continue

            if node != "model":
                continue

            tool_calls = getattr(message, "tool_calls", None) or []
            if tool_calls:
                log_agent_debug(
                    "model_tool_calls",
                    conversation_id=conversation_id,
                    tool_calls=simplify_tool_calls(tool_calls),
                )
                tool_names = [
                    str(tool_call.get("name") or "内部工具")
                    for tool_call in tool_calls
                    if isinstance(tool_call, dict)
                ]
                label = "、".join(tool_names) if tool_names else "内部工具"
                yield AgentStreamEvent("status", {"message": f"正在调用工具：{label}"})
                continue

            content = message_content_to_text(getattr(message, "content", ""))
            if not content:
                continue

            if streamed_text and content.startswith(streamed_text):
                content = content[len(streamed_text) :]
            if not content:
                continue

            # 不同模型/中转站返回粒度不同。
            # 这里统一拆成单字 delta，让前端始终呈现“逐字输出”的效果。
            for delta in split_text_for_stream(content):
                streamed_text += delta
                yield AgentStreamEvent("delta", {"text": delta})

        messages = latest_conversation_messages(user_id, conversation_id)
        turn_messages = messages_after_latest_user_question(messages, question)
        tool_results, selected_douyin_id = collect_tool_results(turn_messages, douyin_id)
        final_answer = find_final_answer(turn_messages)
        log_agent_debug(
            "turn_done",
            conversation_id=conversation_id,
            tool_count=len(tool_results),
            tool_results=[
                {
                    "name": item.name,
                    "ok": item.ok,
                    "summary": item.summary,
                    "error_code": item.error_code,
                }
                for item in tool_results
            ],
            final_answer_preview=(final_answer or streamed_text)[:160],
        )

        if final_answer and not streamed_text:
            yield AgentStreamEvent("status", {"message": "大模型已完成分析，正在输出结果"})
            for delta in split_text_for_stream(final_answer):
                streamed_text += delta
                yield AgentStreamEvent("delta", {"text": delta})

        yield AgentStreamEvent(
            "done",
            {
                "answer": final_answer or streamed_text,
                "conversation_id": conversation_id,
                "selected_douyin_id": selected_douyin_id,
                "tools": [tool_result_to_summary_dict(item) for item in tool_results],
                "sources": [source_doc_to_dict(doc) for doc in docs],
                "memory": memory_usage_to_dict(get_conversation_memory_usage(user_id, conversation_id)),
                "action_suggestion": action_suggestion_to_dict(
                    build_action_suggestion(question, tool_results)
                ),
            },
        )
    except Exception as exc:
        yield AgentStreamEvent("error", {"message": f"智能客服暂时没有回复成功：{exc}"})


def create_conversation_id() -> str:
    """生成一个新的会话 ID。"""
    return uuid.uuid4().hex


def list_conversations(user_id: str | None, limit: int = 50) -> list[ConversationItem]:
    """
    从 Checkpointer 中列出当前用户的会话。

    这里没有额外建聊天表。
    列表信息直接从 LangGraph checkpoint 里读取。
    """
    prefix = build_thread_prefix(user_id)
    seen: set[str] = set()
    items: list[ConversationItem] = []

    # checkpointer.list(None) 会按 checkpoint 从新到旧遍历。
    # 同一个 thread 会有多条 checkpoint，这里只取最新的一条。
    for checkpoint in get_checkpointer().list(None, limit=limit * 20):
        thread_id = str(checkpoint.config.get("configurable", {}).get("thread_id") or "")
        if not thread_id.startswith(prefix) or thread_id in seen:
            continue

        seen.add(thread_id)
        conversation_id = thread_id.removeprefix(prefix)
        messages = messages_from_checkpoint(checkpoint.checkpoint)
        items.append(
            ConversationItem(
                conversation_id=conversation_id,
                title=conversation_title(messages),
            )
        )
        if len(items) >= limit:
            break

    return items


def get_conversation_messages(user_id: str | None, conversation_id: str) -> list[DisplayMessage]:
    """
    读取某个会话当前保存的消息。

    如果旧消息已经被总结，最早的原文可能不会完整保留。
    这是按 token 自动压缩上下文的正常结果。
    """
    conversation_id = normalize_conversation_id(conversation_id)
    scoped_thread_id = build_scoped_thread_id(user_id, conversation_id)
    config = {"configurable": {"thread_id": scoped_thread_id}}
    checkpoint = get_checkpointer().get_tuple(config)
    if checkpoint is None:
        return []

    return display_messages_from_langchain(messages_from_checkpoint(checkpoint.checkpoint))


def get_conversation_memory_usage(user_id: str | None, conversation_id: str | None) -> ConversationMemoryUsage:
    """计算当前会话上下文使用率。"""
    conversation_id = normalize_conversation_id(conversation_id)
    messages = latest_conversation_messages(user_id, conversation_id)
    current_tokens = count_tokens_approximately(messages) if messages else 0
    max_tokens = max(settings.ASSISTANT_CONTEXT_MAX_INPUT_TOKENS, 1)
    trigger_fraction = settings.ASSISTANT_SUMMARY_TRIGGER_FRACTION
    keep_fraction = settings.ASSISTANT_SUMMARY_KEEP_FRACTION

    return ConversationMemoryUsage(
        current_tokens=current_tokens,
        max_tokens=max_tokens,
        current_fraction=current_tokens / max_tokens,
        trigger_fraction=trigger_fraction,
        keep_fraction=keep_fraction,
        trigger_tokens=int(max_tokens * trigger_fraction),
        keep_tokens=int(max_tokens * keep_fraction),
    )


def delete_conversation(user_id: str | None, conversation_id: str) -> None:
    """删除当前用户的一个会话 checkpoint。"""
    conversation_id = normalize_conversation_id(conversation_id)
    scoped_thread_id = build_scoped_thread_id(user_id, conversation_id)
    get_checkpointer().delete_thread(scoped_thread_id)


def get_checkpointer() -> SqliteSaver:
    """
    创建并复用 SQLite Checkpointer。

    SqliteSaver 是 LangGraph 的数据库型 Checkpointer。
    它把每个 thread_id 的 Agent 状态写进 SQLite 文件。
    """
    global _CHECKPOINTER, _CHECKPOINTER_CONN

    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    db_path = Path(settings.ASSISTANT_CHECKPOINT_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False 允许 FastAPI 多请求线程复用这个连接。
    # SqliteSaver 内部有锁，会串行保护写入。
    _CHECKPOINTER_CONN = sqlite3.connect(str(db_path), check_same_thread=False)
    _CHECKPOINTER = SqliteSaver(_CHECKPOINTER_CONN)

    # setup 会创建 checkpoints / writes 表。
    _CHECKPOINTER.setup()
    return _CHECKPOINTER


def chat_model_with_profile(streaming: bool = False):
    """
    创建聊天模型，并补充上下文窗口信息。

    SummarizationMiddleware 使用 fraction 时，需要知道 max_input_tokens。
    这里填的是本项目的“有效上下文预算”，不是硬说模型只能支持这么多。
    """
    model = get_chat_model(streaming=streaming)
    model.profile = {"max_input_tokens": settings.ASSISTANT_CONTEXT_MAX_INPUT_TOKENS}
    return model


def create_summary_middleware(streaming: bool = False) -> SummarizationMiddleware:
    """
    创建按 token 百分比自动总结的中间件。

    trigger=("fraction", 0.75)：上下文达到预算 75% 时触发总结。
    keep=("fraction", 0.40)：总结后保留最近约 40% 预算的原始消息。
    """
    return SummarizationMiddleware(
        model=chat_model_with_profile(streaming=streaming),
        trigger=("fraction", settings.ASSISTANT_SUMMARY_TRIGGER_FRACTION),
        keep=("fraction", settings.ASSISTANT_SUMMARY_KEEP_FRACTION),
        summary_prompt=SUMMARY_PROMPT,
    )


def build_system_prompt_for_tools() -> str:
    """
    组合系统提示词。

    load_system_prompt 是客服身份、范围和边界。
    这里追加 Tool Calling 的工作规则。
    """
    return (
        load_system_prompt()
        + "\n\n"
        + "你可以使用系统提供的内部只读工具查询当前用户状态。"
        + "如果用户问题涉及他的账号、抖音号、登录状态、发送任务、运行记录、兑换码或轮次，"
        + "请优先调用合适的工具查询实时状态。"
        + "如果信息不足，例如没有 douyin_id，可以先调用 list_douyin_accounts。"
        + "如果用户的问题是在承接上一轮，例如“可以呀”“继续”“帮我查”，要结合历史对话判断要查什么。"
        + "如果工具结果显示缺少 token 或登录失效，要明确告诉用户无法检查实时状态，并给通用排查建议。"
        + "当你不再需要工具时，直接用普通中文回答用户。"
    )


def build_user_prompt(
    question: str,
    knowledge_context: str,
    current_page: str | None,
    douyin_id: str | None,
    has_token: bool,
) -> str:
    """组装本轮用户消息。"""
    return f"""
当前是否收到用户 token：{has_token}
当前页面：{current_page or "用户没有提供当前页面"}
当前抖音号 ID：{douyin_id or "用户没有提供当前抖音号 ID"}

知识库资料：
{knowledge_context}

用户问题：
{question}

回答要求：
1. 如果需要实时状态，请使用工具，不要猜。
2. 如果工具返回了状态，回答时先说明查到了什么，再解释这意味着什么。
3. 最后告诉用户下一步去哪个页面、点哪个按钮、看什么状态。
4. 不要讲接口、数据库、部署、代码、管理员后台。
5. 不要承诺发送一定成功。
6. 不要指导绕过验证码、安全验证、平台限制或风控。
""".strip()


def collect_tool_results(
    messages: list[BaseMessage],
    selected_douyin_id: str | None,
) -> tuple[list[ToolResult], str | None]:
    """
    从本轮 LangGraph 消息中提取工具调用结果。

    AIMessage.tool_calls 保存模型想调用什么工具。
    ToolMessage.content 保存工具实际返回的 JSON 文本。
    """
    tool_calls_by_id: dict[str, Any] = {}
    tool_results: list[ToolResult] = []

    for message in messages:
        if isinstance(message, AIMessage):
            for tool_call in getattr(message, "tool_calls", None) or []:
                tool_call_id = str(tool_call.get("id") or "")
                if tool_call_id:
                    tool_calls_by_id[tool_call_id] = tool_call
            continue

        if isinstance(message, ToolMessage):
            content = message_content_to_text(message.content)
            result = tool_result_from_json(content)
            tool_results.append(result)

            tool_call = tool_calls_by_id.get(str(message.tool_call_id))
            selected_douyin_id = update_selected_douyin_id(selected_douyin_id, tool_call, result)

    return tool_results, selected_douyin_id


def find_final_answer(messages: list[BaseMessage]) -> str:
    """找到本轮最后一条没有 tool_calls 的 AIMessage，作为最终回答。"""
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        if getattr(message, "tool_calls", None):
            continue
        content = message_content_to_text(message.content).strip()
        if content:
            return content
    return ""


def update_selected_douyin_id(
    selected_douyin_id: str | None,
    tool_call: Any,
    result: ToolResult,
) -> str | None:
    """根据工具参数和结果更新本轮重点抖音号。"""
    if isinstance(tool_call, dict):
        args = tool_call.get("args") or {}
        if isinstance(args, dict):
            douyin_id = str(args.get("douyin_id") or "").strip()
            if douyin_id:
                return douyin_id

    if selected_douyin_id:
        return selected_douyin_id

    if result.name == "list_douyin_accounts" and isinstance(result.data, list) and len(result.data) == 1:
        only_account = result.data[0]
        if isinstance(only_account, dict):
            douyin_id = str(only_account.get("douyin_id") or "").strip()
            return douyin_id or None

    return selected_douyin_id


def build_action_suggestion(question: str, tool_results: list[ToolResult]) -> ActionSuggestion | None:
    """
    根据本轮用户问题和只读工具结果生成前端操作建议。
    这里只建议前端展示按钮，不直接修改自动发送状态。
    """
    requested_state = requested_auto_send_state(question)
    related_question = is_auto_send_problem_question(question)
    accounts = accounts_from_tool_results(tool_results)

    if requested_state is True:
        return ActionSuggestion(
            type="set_auto_send",
            target_state=True,
            title="开启自动发送",
            message="请选择要开启自动发送的抖音号。选择后系统会重新检查最新状态，再让你确认是否开启。",
            button_label="开启自动发送",
            reason="user_requested_enable",
        )

    if requested_state is False:
        return ActionSuggestion(
            type="set_auto_send",
            target_state=False,
            title="关闭自动发送",
            message="请选择要关闭自动发送的抖音号。选择后系统会重新检查最新状态，再让你确认是否关闭。",
            button_label="关闭自动发送",
            reason="user_requested_disable",
        )

    if not related_question:
        return None

    if has_disabled_auto_send_account_ready_to_enable(accounts):
        return ActionSuggestion(
            type="set_auto_send",
            target_state=True,
            title="开启自动发送",
            message="检查到可能有抖音号的自动发送处于关闭状态。如需开启，请先选择具体抖音号。",
            button_label="开启自动发送",
            reason="auto_send_disabled_and_problem_related",
        )

    return None


def requested_auto_send_state(question: str) -> bool | None:
    """识别用户是否明确要求开启或关闭自动发送。"""
    text = normalize_question_text(question)
    enable_words = ("开启", "打开", "启用", "恢复", "开一下", "帮我开", "打开一下")
    disable_words = ("关闭", "关掉", "暂停", "停用", "关一下", "帮我关", "不要自动发送")

    if "自动发送" not in text:
        return None
    if any(word in text for word in disable_words):
        return False
    if any(word in text for word in enable_words):
        return True
    return None


def is_auto_send_problem_question(question: str) -> bool:
    """判断问题是否和自动发送不运行强相关。"""
    text = normalize_question_text(question)
    if "自动发送" in text and any(word in text for word in ("不", "没", "不能", "失败", "为什么", "怎么")):
        return True
    return "任务" in text and any(word in text for word in ("没发送", "没有发送", "不发送", "没运行", "不运行"))


def normalize_question_text(question: str) -> str:
    """去掉空白，方便做轻量意图判断。"""
    return re.sub(r"\s+", "", question or "")


def accounts_from_tool_results(tool_results: list[ToolResult]) -> list[dict[str, Any]]:
    """从本轮工具结果中收集抖音号数据。"""
    accounts: list[dict[str, Any]] = []
    for result in tool_results:
        if not result.ok:
            continue
        if result.name == "list_douyin_accounts" and isinstance(result.data, list):
            accounts.extend(item for item in result.data if isinstance(item, dict))
        elif result.name == "get_douyin_account" and isinstance(result.data, dict):
            accounts.append(result.data)
    return accounts


def has_disabled_auto_send_account_ready_to_enable(accounts: list[dict[str, Any]]) -> bool:
    """
    是否存在值得提示“开启自动发送”的账号。
    前端确认前还会重新读取最新状态，这里只做提示级判断。
    """
    for account in accounts:
        status = str(account.get("status") or "").strip()
        login_state = str(account.get("login_state") or "").strip()
        entitlement = str(account.get("polling_entitlement_status") or "").strip()
        if status == "paused" and login_state == "ok" and entitlement in {"active", "valid"}:
            return True
    return False


def messages_after_latest_user_question(messages: list[BaseMessage], question: str) -> list[BaseMessage]:
    """截取本轮用户问题之后的新消息，避免把历史工具结果重复返回给前端。"""
    marker = f"用户问题：\n{question}"
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, HumanMessage) and marker in message_content_to_text(message.content):
            return messages[index + 1 :]
    return messages


def messages_from_checkpoint(checkpoint: dict[str, Any]) -> list[BaseMessage]:
    """从 LangGraph checkpoint 原始数据里取出 messages。"""
    values = checkpoint.get("channel_values", {}) if isinstance(checkpoint, dict) else {}
    messages = values.get("messages", []) if isinstance(values, dict) else []
    return [message for message in messages if isinstance(message, BaseMessage)]


def latest_conversation_messages(user_id: str | None, conversation_id: str) -> list[BaseMessage]:
    """读取某个会话最新 checkpoint 中的 LangChain messages。"""
    scoped_thread_id = build_scoped_thread_id(user_id, conversation_id)
    config = {"configurable": {"thread_id": scoped_thread_id}}
    checkpoint = get_checkpointer().get_tuple(config)
    if checkpoint is None:
        return []
    return messages_from_checkpoint(checkpoint.checkpoint)


def display_messages_from_langchain(messages: list[BaseMessage]) -> list[DisplayMessage]:
    """把 LangChain 消息转成前端展示消息，过滤系统消息和工具消息。"""
    items: list[DisplayMessage] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            question = extract_user_question(message_content_to_text(message.content))
            if question:
                items.append(DisplayMessage(role="user", content=question))
            continue

        if isinstance(message, AIMessage):
            if getattr(message, "tool_calls", None):
                continue
            content = message_content_to_text(message.content).strip()
            if content:
                items.append(DisplayMessage(role="assistant", content=content))

    return items


def conversation_title(messages: list[BaseMessage]) -> str:
    """使用第一条用户问题作为会话标题。"""
    for message in messages:
        if not isinstance(message, HumanMessage):
            continue
        question = extract_user_question(message_content_to_text(message.content))
        if question:
            return shorten_title(question)
    return "新会话"


def extract_user_question(content: str) -> str:
    """从内部 Prompt 中提取真正的用户问题，避免前端显示 RAG 资料。"""
    match = re.search(r"用户问题：\s*(.*?)\s*回答要求：", content, re.S)
    if not match:
        return ""
    return match.group(1).strip()


def shorten_title(text: str, limit: int = 24) -> str:
    """把长问题压成会话列表标题。"""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def message_content_to_text(content: Any) -> str:
    """兼容 LangChain content 是字符串或分段列表的情况。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "".join(parts)
    return str(content)


def split_text_for_stream(text: str) -> Iterator[str]:
    """
    把模型返回文本拆成小段输出。

    中文按单字输出，英文连续空白也会保留。
    短暂停顿让浏览器有机会逐步渲染，而不是瞬间刷完。
    """
    for char in text:
        if not char:
            continue
        yield char
        time.sleep(0.008)


def normalize_conversation_id(conversation_id: str | None) -> str:
    """清理会话 ID；为空时生成新会话。"""
    value = str(conversation_id or "").strip()
    if not value:
        return create_conversation_id()
    return re.sub(r"[^a-zA-Z0-9_-]", "", value)[:80] or create_conversation_id()


def build_scoped_thread_id(user_id: str | None, conversation_id: str) -> str:
    """把用户 ID 和会话 ID 合成 LangGraph thread_id。"""
    return build_thread_prefix(user_id) + normalize_conversation_id(conversation_id)


def build_thread_prefix(user_id: str | None) -> str:
    """生成当前用户的 thread_id 前缀。"""
    scope = re.sub(r"[^a-zA-Z0-9_-]", "", str(user_id or "anonymous"))[:80] or "anonymous"
    return f"{scope}:"


def source_doc_to_dict(doc: Document) -> dict[str, Any]:
    """把知识库 Document 转成 API 可以返回的普通 dict。"""
    return {
        "source": doc.metadata.get("source", ""),
        "document_title": doc.metadata.get("document_title", ""),
        "section_title": doc.metadata.get("section_title", ""),
        "question_title": doc.metadata.get("question_title", ""),
    }


def memory_usage_to_dict(memory: ConversationMemoryUsage) -> dict[str, Any]:
    """把会话上下文使用率转成 API 可以返回的 dict。"""
    return {
        "current_tokens": memory.current_tokens,
        "max_tokens": memory.max_tokens,
        "current_fraction": memory.current_fraction,
        "trigger_fraction": memory.trigger_fraction,
        "keep_fraction": memory.keep_fraction,
        "trigger_tokens": memory.trigger_tokens,
        "keep_tokens": memory.keep_tokens,
    }


def tool_result_to_summary_dict(result: ToolResult) -> dict[str, Any]:
    """把 ToolResult 转成前端展示摘要。"""
    return {
        "name": result.name,
        "ok": result.ok,
        "summary": result.summary,
        "error_code": result.error_code,
    }


def action_suggestion_to_dict(suggestion: ActionSuggestion | None) -> dict[str, Any] | None:
    """把操作建议转成 API 可返回的 dict。"""
    if suggestion is None:
        return None
    return {
        "type": suggestion.type,
        "target_state": suggestion.target_state,
        "title": suggestion.title,
        "message": suggestion.message,
        "button_label": suggestion.button_label,
        "reason": suggestion.reason,
        "requires_account_selection": suggestion.requires_account_selection,
        "requires_confirmation": suggestion.requires_confirmation,
    }


def simplify_tool_calls(tool_calls: list[Any]) -> list[dict[str, Any]]:
    """把模型返回的 tool_calls 压缩成日志友好的结构。"""
    simplified: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        if isinstance(tool_call, dict):
            simplified.append(
                {
                    "name": tool_call.get("name"),
                    "args": tool_call.get("args"),
                    "id": tool_call.get("id"),
                }
            )
        else:
            simplified.append({"raw": str(tool_call)})
    return simplified


def log_agent_debug(event: str, **payload: Any) -> None:
    """输出 Agent 调试日志，方便判断模型是否真的返回 tool_calls。"""
    try:
        line = json.dumps(
            {"event": event, **payload},
            ensure_ascii=False,
            default=str,
        )
    except Exception as exc:
        line = json.dumps(
            {"event": event, "log_error": str(exc)},
            ensure_ascii=False,
        )
    print(f"[assistant-agent] {line}", file=sys.stderr, flush=True)


SUMMARY_PROMPT = """
你是 douyin-spark 智能客服的会话摘要助手。

请把旧对话压缩成一段简短中文摘要，用来让后续客服继续理解上下文。

只保留这些信息：
1. 用户正在咨询的 douyin-spark 功能或问题。
2. 用户已经确认过的抖音号、页面、任务、兑换码或状态。
3. 已经查到的结论和下一步建议。
4. 用户明确表达的继续意图。

不要保存：
1. 天气、编程、闲聊等和 douyin-spark 无关的内容。
2. 过期的实时状态作为永久事实。状态类信息要写成“当时查到”。
3. 任何长期用户偏好或长期记忆。

需要总结的历史消息：
{messages}
""".strip()
