"""
douyin-spark 内部只读工具。

这里定义的是 LangChain 标准 Tool。
大模型通过 bind_tools(...) 读取工具名称、说明和参数 schema，
然后在 AIMessage.tool_calls 中返回要调用的工具。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.services.douyin_api_client import DouyinApiError, DouyinSparkApiClient


JsonDict = dict[str, Any]


@dataclass
class ToolResult:
    """记录一次内部工具调用结果。"""

    name: str
    ok: bool
    summary: str
    data: Any = None
    error_code: str | None = None


class EmptyArgs(BaseModel):
    """无参数工具的参数模型。"""


class DouyinIdArgs(BaseModel):
    """需要抖音号 ID 的工具参数。"""

    douyin_id: str = Field(
        ...,
        description="要查询的抖音号 ID。通常来自用户选择的抖音号，或抖音号列表中的 douyin_id 字段。",
    )


class AccountRunsArgs(BaseModel):
    """查询运行记录的工具参数。"""

    douyin_id: str = Field(
        ...,
        description="要查询运行记录的抖音号 ID。通常来自用户选择的抖音号，或抖音号列表中的 douyin_id 字段。",
    )
    limit: int = Field(
        10,
        ge=1,
        le=50,
        description="返回最近多少条运行记录。默认 10，最少 1，最多 50。",
    )


class DouyinReadOnlyTools:
    """
    douyin-spark 只读工具集合。

    这个类只封装后端查询，不直接暴露给模型。
    create_langchain_tools 会把这些方法包装成 LangChain 标准 Tool。
    """

    def __init__(self, token: str | None):
        self.client = DouyinSparkApiClient(token=token or "")

    def get_current_user(self) -> ToolResult:
        """查询当前控制台账号。"""
        return self._safe_call(
            "get_current_user",
            self.client.get_current_user,
            _summary_user,
        )

    def list_douyin_accounts(self) -> ToolResult:
        """查询当前用户管理的抖音号列表。"""
        return self._safe_call(
            "list_douyin_accounts",
            self.client.list_douyin_accounts,
            _summary_accounts,
        )

    def get_douyin_account(self, douyin_id: str) -> ToolResult:
        """查询一个抖音号详情。"""
        return self._safe_call(
            "get_douyin_account",
            lambda: self.client.get_douyin_account(douyin_id),
            _summary_account_detail,
        )

    def get_login_status(self, douyin_id: str) -> ToolResult:
        """查询一个抖音号登录状态。"""
        return self._safe_call(
            "get_login_status",
            lambda: self.client.get_login_status(douyin_id),
            _summary_login_status,
        )

    def list_send_tasks(self, douyin_id: str) -> ToolResult:
        """查询一个抖音号的发送任务列表。"""
        return self._safe_call(
            "list_send_tasks",
            lambda: self.client.list_send_tasks(douyin_id),
            _summary_tasks,
        )

    def list_account_runs(self, douyin_id: str, limit: int = 10) -> ToolResult:
        """查询一个抖音号最近运行记录。"""
        return self._safe_call(
            "list_account_runs",
            lambda: self.client.list_account_runs(douyin_id, limit=limit),
            _summary_runs,
        )

    def list_my_redeem_codes(self) -> ToolResult:
        """查询当前用户兑换码列表。"""
        return self._safe_call(
            "list_my_redeem_codes",
            self.client.list_my_redeem_codes,
            _summary_redeem_codes,
        )

    def list_schedule_slots(self) -> ToolResult:
        """查询当前可用轮次。"""
        return self._safe_call(
            "list_schedule_slots",
            self.client.list_schedule_slots,
            _summary_slots,
        )

    def _safe_call(
        self,
        name: str,
        func: Callable[[], Any],
        summarizer: Callable[[Any], str],
    ) -> ToolResult:
        """
        统一执行工具调用。

        func 是真正查询数据的函数。
        summarizer 把原始数据转换成一句中文摘要。
        """
        try:
            data = func()
            return ToolResult(name=name, ok=True, summary=summarizer(data), data=data)
        except DouyinApiError as exc:
            return ToolResult(
                name=name,
                ok=False,
                summary=_summary_error(exc),
                data=None,
                error_code=exc.code,
            )


def create_langchain_tools(token: str | None) -> list[StructuredTool]:
    """
    创建 LangChain 标准 Tool 列表。

    token 来自当前请求。
    每次请求都创建一组闭包工具，这样工具内部可以安全使用当前用户 token。
    """
    readonly = DouyinReadOnlyTools(token)

    def get_current_user() -> str:
        """查询当前登录控制台账号信息，返回账户 ID、昵称、QQ 邮箱等基础资料。"""
        return tool_result_to_json(readonly.get_current_user())

    def list_douyin_accounts() -> str:
        """查询当前登录用户已关联的抖音号列表。"""
        return tool_result_to_json(readonly.list_douyin_accounts())

    def get_douyin_account(douyin_id: str) -> str:
        """查询指定抖音号详情，包括账号状态、登录状态、自动发送资格、任务数量和最近错误。"""
        return tool_result_to_json(readonly.get_douyin_account(douyin_id))

    def get_login_status(douyin_id: str) -> str:
        """查询指定抖音号当前登录状态，返回是否有效、无效、未验证、最近检查时间和错误原因。"""
        return tool_result_to_json(readonly.get_login_status(douyin_id))

    def list_send_tasks(douyin_id: str) -> str:
        """查询指定抖音号的发送任务列表，返回任务状态、轮次配置、启用情况等信息。"""
        return tool_result_to_json(readonly.list_send_tasks(douyin_id))

    def list_account_runs(douyin_id: str, limit: int = 10) -> str:
        """查询指定抖音号最近运行记录，返回成功、失败、跳过和错误原因等信息。"""
        return tool_result_to_json(readonly.list_account_runs(douyin_id, limit=limit))

    def list_my_redeem_codes() -> str:
        """查询当前用户兑换码列表，返回兑换码状态、绑定抖音号、兑换时间和有效天数。"""
        return tool_result_to_json(readonly.list_my_redeem_codes())

    def list_schedule_slots() -> str:
        """查询当前可用轮次列表，返回轮次名称、状态、时间配置等信息。"""
        return tool_result_to_json(readonly.list_schedule_slots())

    # StructuredTool.from_function 会把函数包装成 LangChain Tool。
    # name、description 和 args_schema 会提供给大模型做原生工具调用决策。
    return [
        StructuredTool.from_function(
            func=get_current_user,
            name="get_current_user",
            description=(
                "功能：查询当前登录控制台账号信息。"
                "参数：不需要参数。"
                "返回：当前用户的账户 ID、昵称、QQ 邮箱、账号状态等基础资料。"
                "失败：通常表示缺少登录 token、token 失效，或后端暂时不可用。"
            ),
            args_schema=EmptyArgs,
        ),
        StructuredTool.from_function(
            func=list_douyin_accounts,
            name="list_douyin_accounts",
            description=(
                "功能：查询当前登录用户已关联、绑定、添加、管理的抖音号列表。"
                "参数：不需要参数。"
                "返回：抖音号列表。每个抖音号通常包含 douyin_id、昵称、账号状态 status、"
                "登录状态 login_state、自动发送资格 polling_entitlement_status、资格有效期、"
                "发送任务数量和最近错误等信息。"
                "空结果：表示当前账号暂时没有关联抖音号。"
                "失败：通常表示缺少登录 token、token 失效，或后端暂时不可用。"
            ),
            args_schema=EmptyArgs,
        ),
        StructuredTool.from_function(
            func=get_douyin_account,
            name="get_douyin_account",
            description=(
                "功能：查询指定抖音号详情。"
                "参数：需要 douyin_id。"
                "返回：该抖音号的昵称、账号状态 status、登录状态 login_state、"
                "自动发送资格 polling_entitlement_status、资格有效期、发送任务数量、"
                "最近错误、是否自动加入新增轮次 auto_apply_new_slots 等信息。"
                "字段说明：status=active 通常表示自动发送开关已开启，status=paused 通常表示自动发送已暂停；"
                "polling_entitlement_status 表示轮询资格状态；"
                "auto_apply_new_slots 只表示是否自动加入以后新增轮次，不是自动发送总开关。"
                "失败：通常表示 douyin_id 不存在、当前用户无权查看、缺少登录 token、token 失效，或后端暂时不可用。"
            ),
            args_schema=DouyinIdArgs,
        ),
        StructuredTool.from_function(
            func=get_login_status,
            name="get_login_status",
            description=(
                "功能：查询指定抖音号登录状态。"
                "参数：需要 douyin_id。"
                "返回：登录状态、展示文案、最近检查时间、最近错误原因等信息。"
                "字段说明：ok 通常表示当前登录可用；invalid 通常表示需要重新登录；"
                "unchecked 或未验证表示系统还没有完成检查。"
                "失败：通常表示 douyin_id 不存在、当前用户无权查看、缺少登录 token、token 失效，或后端暂时不可用。"
            ),
            args_schema=DouyinIdArgs,
        ),
        StructuredTool.from_function(
            func=list_send_tasks,
            name="list_send_tasks",
            description=(
                "功能：查询指定抖音号的发送任务列表。"
                "参数：需要 douyin_id。"
                "返回：任务列表。每个任务通常包含任务状态、发送内容摘要、是否启用、"
                "参与轮次、创建时间、更新时间等信息。"
                "空结果：表示这个抖音号暂时没有发送任务。"
                "失败：通常表示 douyin_id 不存在、当前用户无权查看、缺少登录 token、token 失效，或后端暂时不可用。"
            ),
            args_schema=DouyinIdArgs,
        ),
        StructuredTool.from_function(
            func=list_account_runs,
            name="list_account_runs",
            description=(
                "功能：查询指定抖音号最近运行记录。"
                "参数：需要 douyin_id；limit 可控制返回最近多少条，默认 10，最多 50。"
                "返回：最近运行记录，包括成功、失败、跳过、运行时间、失败或跳过原因等信息。"
                "空结果：表示最近暂时没有运行记录。"
                "失败：通常表示 douyin_id 不存在、当前用户无权查看、缺少登录 token、token 失效，或后端暂时不可用。"
            ),
            args_schema=AccountRunsArgs,
        ),
        StructuredTool.from_function(
            func=list_my_redeem_codes,
            name="list_my_redeem_codes",
            description=(
                "功能：查询当前用户的兑换码列表。"
                "参数：不需要参数。"
                "返回：兑换码状态、有效天数、绑定的抖音号、兑换时间等信息。"
                "空结果：表示当前账号暂时没有兑换码记录。"
                "失败：通常表示缺少登录 token、token 失效，或后端暂时不可用。"
            ),
            args_schema=EmptyArgs,
        ),
        StructuredTool.from_function(
            func=list_schedule_slots,
            name="list_schedule_slots",
            description=(
                "功能：查询当前可用轮次列表。"
                "参数：不需要参数。"
                "返回：轮次列表。每个轮次通常包含轮次名称、状态、时间配置等信息。"
                "空结果：表示当前暂时没有可选择的轮次。"
                "失败：通常表示缺少登录 token、token 失效，或后端暂时不可用。"
            ),
            args_schema=EmptyArgs,
        ),
    ]


def tool_result_to_json(result: ToolResult) -> str:
    """
    把 ToolResult 转成 ToolMessage 的文本内容。

    LangChain Tool 返回值最终会进入 ToolMessage.content，
    所以这里用 JSON 字符串，方便模型读取结构化结果。
    """
    return json.dumps(
        {
            "name": result.name,
            "ok": result.ok,
            "summary": result.summary,
            "error_code": result.error_code,
            "data": compact_for_prompt(result.data),
        },
        ensure_ascii=False,
    )


def tool_result_from_json(content: str) -> ToolResult:
    """把工具返回的 JSON 字符串转回 ToolResult，方便 API 层展示工具摘要。"""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return ToolResult(name="unknown_tool", ok=False, summary=content, error_code="invalid_tool_json")

    return ToolResult(
        name=str(payload.get("name") or "unknown_tool"),
        ok=bool(payload.get("ok")),
        summary=str(payload.get("summary") or ""),
        data=payload.get("data"),
        error_code=payload.get("error_code"),
    )


def compact_for_prompt(value: Any, max_list_items: int = 5) -> Any:
    """
    压缩工具原始数据，避免工具结果塞进上下文时过长。

    列表只保留前几项，长字符串会截断。
    """
    if isinstance(value, dict):
        return {key: compact_for_prompt(item, max_list_items) for key, item in value.items()}
    if isinstance(value, list):
        return [compact_for_prompt(item, max_list_items) for item in value[:max_list_items]]
    if isinstance(value, str) and len(value) > 600:
        return value[:600] + "...（已截断）"
    return value


def _summary_user(user: JsonDict) -> str:
    public_uid = user.get("public_uid") or "-"
    nickname = user.get("nickname") or "未设置昵称"
    status = user.get("status") or "-"
    return f"当前控制台账号 ID 是 {public_uid}，昵称是 {nickname}，账号状态是 {status}。"


def _summary_accounts(accounts: list[JsonDict]) -> str:
    if not accounts:
        return "当前账号下没有查到抖音号。用户需要先添加抖音号。"

    parts = []
    for account in accounts[:5]:
        douyin_id = account.get("douyin_id") or "-"
        name = account.get("display_name") or account.get("profile_nickname") or "未命名"
        login_state = account.get("login_state") or "未验证"
        entitlement = account.get("polling_entitlement_status") or "-"
        parts.append(f"{name}（{douyin_id}，登录状态 {login_state}，资格 {entitlement}）")

    more = f"；另外还有 {len(accounts) - 5} 个" if len(accounts) > 5 else ""
    return f"查到 {len(accounts)} 个抖音号：" + "；".join(parts) + more + "。"


def _summary_account_detail(account: JsonDict) -> str:
    name = account.get("display_name") or account.get("profile_nickname") or "未命名"
    douyin_id = account.get("douyin_id") or "-"
    login_state = account.get("login_state") or "未验证"
    task_count = account.get("send_task_count")
    active_count = account.get("active_send_task_count")
    entitlement = account.get("polling_entitlement_status") or "-"
    eligible_until = account.get("polling_eligible_until") or "-"
    last_error = account.get("last_error_message") or account.get("latest_task_error_message") or "-"
    return (
        f"抖音号 {name}（{douyin_id}）登录状态是 {login_state}，"
        f"发送任务数 {task_count}，启用任务数 {active_count}，"
        f"自动发送资格状态 {entitlement}，有效期到 {eligible_until}，最近错误：{last_error}。"
    )


def _summary_login_status(status: JsonDict) -> str:
    login_state = status.get("login_state") or "-"
    text = status.get("display_text") or "-"
    need_relogin = status.get("need_relogin")
    can_verify = status.get("can_verify")
    checked = status.get("last_checked_text") or status.get("last_checked_at") or "-"
    return (
        f"登录状态是 {login_state}，页面显示为 {text}，"
        f"是否建议重新登录：{need_relogin}，是否可以验证：{can_verify}，最近检查时间：{checked}。"
    )


def _summary_tasks(tasks: list[JsonDict]) -> str:
    if not tasks:
        return "这个抖音号下没有查到发送任务。"

    parts = []
    for task in tasks[:5]:
        task_id = task.get("id") or task.get("task_id") or "-"
        enabled = task.get("enabled")
        status = task.get("status") or "-"
        slot_ids = task.get("slot_ids") or []
        last_error = task.get("last_error_message") or "-"
        parts.append(f"{task_id}（启用 {enabled}，状态 {status}，轮次数 {len(slot_ids)}，最近错误 {last_error}）")

    more = f"；另外还有 {len(tasks) - 5} 个" if len(tasks) > 5 else ""
    return f"查到 {len(tasks)} 个发送任务：" + "；".join(parts) + more + "。"


def _summary_runs(runs_payload: JsonDict) -> str:
    runs = runs_payload.get("items") if isinstance(runs_payload, dict) else []
    if not runs:
        return "最近没有查到运行记录。可能是任务还没有触发，或没有满足运行条件。"

    parts = []
    for run in runs[:5]:
        status = run.get("status") or "-"
        slot_id = run.get("slot_id") or "-"
        finished_at = run.get("finished_at") or run.get("started_at") or "-"
        error = run.get("last_error_message") or run.get("last_error_code") or "-"
        parts.append(f"{finished_at}：状态 {status}，轮次 {slot_id}，错误 {error}")

    return f"最近 {len(runs)} 条运行记录：" + "；".join(parts) + "。"


def _summary_redeem_codes(codes: list[JsonDict]) -> str:
    if not codes:
        return "当前账号下没有查到兑换码记录。"

    parts = []
    for code in codes[:5]:
        status = code.get("status") or "-"
        days = code.get("days") or "-"
        douyin_id = code.get("redeemed_douyin_id") or code.get("douyin_id") or "-"
        redeemed_at = code.get("redeemed_at") or "-"
        parts.append(f"状态 {status}，天数 {days}，绑定抖音号 {douyin_id}，兑换时间 {redeemed_at}")

    more = f"；另外还有 {len(codes) - 5} 条" if len(codes) > 5 else ""
    return f"查到 {len(codes)} 条兑换码记录：" + "；".join(parts) + more + "。"


def _summary_slots(slots: list[JsonDict]) -> str:
    if not slots:
        return "当前没有查到可用轮次。"

    parts = []
    for slot in slots[:8]:
        name = slot.get("name") or "-"
        status = slot.get("status") or "-"
        mode = slot.get("mode") or "-"
        time_text = slot.get("time_of_day") or slot.get("interval_seconds") or "-"
        parts.append(f"{name}（{mode}，{time_text}，{status}）")

    more = f"；另外还有 {len(slots) - 8} 个" if len(slots) > 8 else ""
    return f"查到 {len(slots)} 个轮次：" + "；".join(parts) + more + "。"


def _summary_error(exc: DouyinApiError) -> str:
    if exc.code == "unauthorized":
        return "用户登录已失效，无法查询实时状态。需要重新登录控制台。"
    if exc.code == "missing_token":
        return "缺少用户登录 token，无法查询实时状态。"
    if exc.code == "not_found":
        return "没有查到对应数据，可能是不属于当前账号，或者已经不存在。"
    return f"查询失败，错误码 {exc.code}，错误信息：{exc.message}"
