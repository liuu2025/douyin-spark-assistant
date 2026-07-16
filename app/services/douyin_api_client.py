"""
douyin-spark 后端 API Client。

这个文件只负责一件事：
用当前用户 token 调 douyin-spark 后端的普通用户接口，并把 JSON 结果返回给上层。

第一版只封装只读 GET 接口，不做任何修改用户数据的操作。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import settings


JsonDict = dict[str, Any]


class DouyinApiError(Exception):
    """调用 douyin-spark 后端失败时抛出的异常。"""

    def __init__(self, message: str, code: str = "request_failed", status: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


@dataclass
class DouyinSparkApiClient:
    """
    douyin-spark 后端 HTTP 客户端。

    dataclass 会自动生成 __init__，让我们可以写：
    DouyinSparkApiClient(token="xxx")
    """

    token: str
    base_url: str = settings.DOUYIN_SPARK_API_BASE_URL
    timeout: int = 30

    def __post_init__(self) -> None:
        # 去掉末尾 /，避免拼接口路径时出现双斜杠。
        self.base_url = self.base_url.rstrip("/")
        self.token = self.token.strip()

    def get_current_user(self) -> JsonDict:
        """查询当前登录控制台账号。"""
        data = self._get("/account/me")
        return data.get("user", data) if isinstance(data, dict) else {"raw": data}

    def list_douyin_accounts(self) -> list[JsonDict]:
        """查询当前用户管理的抖音号列表。"""
        data = self._get("/douyin-accounts")
        return self._pick_items(data)

    def get_douyin_account(self, douyin_id: str) -> JsonDict:
        """查询某个抖音号详情。"""
        data = self._get(f"/douyin-accounts/{douyin_id}")
        return data.get("account", data) if isinstance(data, dict) else {"raw": data}

    def get_login_status(self, douyin_id: str) -> JsonDict:
        """查询某个抖音号登录状态。"""
        data = self._get(f"/douyin-accounts/{douyin_id}/login-status")
        return data if isinstance(data, dict) else {"raw": data}

    def list_send_tasks(self, douyin_id: str) -> list[JsonDict]:
        """查询某个抖音号的发送任务。"""
        data = self._get(f"/douyin-accounts/{douyin_id}/send-tasks")
        return self._pick_items(data)

    def list_account_runs(self, douyin_id: str, limit: int = 10) -> JsonDict:
        """查询某个抖音号最近运行记录。"""
        data = self._get(f"/douyin-accounts/{douyin_id}/send-runs", {"limit": limit})
        if isinstance(data, dict):
            return data
        return {"items": data if isinstance(data, list) else [], "total": 0}

    def list_my_redeem_codes(self) -> list[JsonDict]:
        """查询当前用户自己的兑换码列表。"""
        data = self._get("/redeem-codes/my")
        return self._pick_items(data)

    def list_schedule_slots(self) -> list[JsonDict]:
        """查询普通用户可见的轮次列表。"""
        data = self._get("/send-schedule/slots")
        return self._pick_items(data)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """
        发送 GET 请求并解析 JSON。

        urllib.request 是 Python 标准库里的 HTTP 工具。
        Request 用来创建请求对象，urlopen 用来真正发送请求。
        """
        if not self.token:
            raise DouyinApiError("缺少用户登录 token，无法查询实时状态。", "missing_token", 401)

        url = self._build_url(path, params)

        # Authorization 头和前端保持一致：Bearer <token>。
        request = Request(
            url=url,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            raise self._build_http_error(exc) from exc
        except URLError as exc:
            raise DouyinApiError(
                f"douyin-spark 后端连接失败：{exc.reason}",
                "backend_unreachable",
            ) from exc
        except TimeoutError as exc:
            raise DouyinApiError("douyin-spark 后端请求超时。", "request_timeout") from exc
        except json.JSONDecodeError as exc:
            raise DouyinApiError("douyin-spark 后端返回内容不是有效 JSON。", "invalid_json") from exc

    def _build_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        """把 base_url、接口路径、查询参数拼成完整 URL。"""
        full_url = f"{self.base_url}/{path.lstrip('/')}"
        if not params:
            return full_url

        # urlencode 会把 {"limit": 10} 转成 limit=10。
        query = urlencode({key: value for key, value in params.items() if value is not None})
        return f"{full_url}?{query}" if query else full_url

    def _build_http_error(self, exc: HTTPError) -> DouyinApiError:
        """把后端错误响应转换成统一异常。"""
        raw = exc.read().decode("utf-8", errors="replace")
        code = "request_failed"
        message = raw or f"HTTP {exc.code}"

        try:
            payload = json.loads(raw) if raw else {}
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            code = error.get("code") or code
            message = error.get("message") or message
        except json.JSONDecodeError:
            pass

        return DouyinApiError(message=message, code=code, status=exc.code)

    def _pick_items(self, data: Any) -> list[JsonDict]:
        """
        兼容后端两种列表返回格式：
        1. 直接返回数组。
        2. 返回 {"items": [...]}。
        """
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return [item for item in data["items"] if isinstance(item, dict)]
        return []
