# API 文档

本文档说明 `douyin-spark-assistant` 对外提供的 HTTP 接口。

FastAPI 自动接口文档也可以直接查看：

```text
http://localhost:8000/docs
```

OpenAPI JSON：

```text
http://localhost:8000/openapi.json
```

## 基础地址

assistant 本地服务地址：

```text
http://localhost:8000
```

浏览器前端通常不直接访问 assistant，而是访问 Go 后端代理路径：

```text
http://localhost:8080/api/v1/assistant/...
```

Go 后端会把 `/api/v1/assistant/...` 转发到 assistant。

## 鉴权和用户身份

前端请求 Go 后端时带：

```http
Authorization: Bearer <token>
```

Go 后端会验证当前用户，并把 token 转发给 assistant。

assistant 使用该 token 调用 douyin-spark 后端接口，查询当前用户自己的抖音号、任务、兑换码、运行记录等实时状态。

assistant 也读取：

```http
X-Assistant-User-ID: <public_uid>
```

这个请求头由 Go 后端转发，用于区分 LangGraph Checkpointer 里的不同用户会话。

如果没有 token，Agent 仍然可以根据知识库回答通用说明，但不能声称已经检查了用户实时状态。

## GET /health

健康检查接口。

### 响应示例

```json
{
  "status": "ok",
  "service": "douyin-spark-assistant"
}
```

## POST /chat

非流式聊天接口。

该接口会等待 Agent 完整执行结束后，一次性返回回答。

前端当前主要使用 `/chat/stream`，`/chat` 更适合脚本调试或不需要流式显示的场景。

### 请求体

```json
{
  "message": "为什么任务显示正常但没有发送？",
  "conversation_id": "可选会话 ID",
  "current_page": "智能客服",
  "douyin_id": "可选抖音号 ID",
  "top_k": 4
}
```

字段说明：

- `message`：用户问题，必填。
- `conversation_id`：会话 ID，可选。不传时 assistant 会创建新会话。
- `current_page`：用户当前页面，可选。用于帮助 Agent 理解上下文。
- `douyin_id`：当前抖音号 ID，可选。用户已选中某个抖音号时传入。
- `top_k`：知识库检索条数，默认 `4`。

### 响应体

```json
{
  "answer": "客服回答正文",
  "conversation_id": "会话 ID",
  "selected_douyin_id": "本轮重点抖音号 ID，可为空",
  "tools": [
    {
      "name": "list_douyin_accounts",
      "ok": true,
      "summary": "查到 2 个抖音号...",
      "error_code": null
    }
  ],
  "sources": [
    {
      "source": "knowledge/user/login-status.md",
      "document_title": "登录状态",
      "section_title": "各种登录状态是什么意思",
      "question_title": ""
    }
  ],
  "memory": {
    "current_tokens": 1200,
    "max_tokens": 16000,
    "current_fraction": 0.075,
    "trigger_fraction": 0.75,
    "keep_fraction": 0.4,
    "trigger_tokens": 12000,
    "keep_tokens": 6400
  },
  "action_suggestion": null
}
```

字段说明：

- `answer`：最终回答。
- `conversation_id`：当前会话 ID。
- `selected_douyin_id`：Agent 本轮识别出的重点抖音号，可为空。
- `tools`：本轮内部工具调用摘要。
- `sources`：本轮使用的知识库来源。
- `memory`：当前会话上下文使用情况。
- `action_suggestion`：给前端展示的操作建议，只是建议，不代表已经执行操作。

## POST /chat/stream

流式聊天接口。

该接口使用 Server-Sent Events 返回阶段状态、工具结果、回答文本增量和最终结果。

响应头：

```http
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

### 请求体

请求体和 `/chat` 相同：

```json
{
  "message": "我绑定了哪些抖音号",
  "conversation_id": "可选会话 ID",
  "current_page": "智能客服",
  "douyin_id": "可选抖音号 ID",
  "top_k": 4
}
```

### SSE 格式

每个事件格式：

```text
event: 事件名
data: JSON 字符串
```

事件之间用空行分隔。

前端需要按事件类型分别处理。

## SSE 事件

### start

表示本轮会话开始。

示例：

```text
event: start
data: {"conversation_id":"abc123","memory":{"current_tokens":0,"max_tokens":16000}}
```

前端通常用它更新当前会话 ID 和上下文使用率。

### status

表示当前处理阶段。

示例：

```text
event: status
data: {"message":"正在检索知识库资料"}
```

常见状态：

- `正在检索知识库资料`
- `知识库检索完成，正在让大模型分析`
- `大模型正在分析问题`
- `正在调用工具：list_douyin_accounts`
- `工具检查完成，大模型正在整理结果`
- `大模型已完成分析，正在输出结果`

前端建议把 `status.message` 单独显示为运行状态，不要和最终回答正文混在同一个字段里。

### tool

表示一个内部工具执行完成。

示例：

```text
event: tool
data: {"name":"list_douyin_accounts","ok":true,"summary":"查到 2 个抖音号...","error_code":null}
```

字段说明：

- `name`：工具名称。
- `ok`：工具是否成功。
- `summary`：适合展示给用户的工具结果摘要。
- `error_code`：失败时的错误码，可为空。

前端可以把它展示在“本次检查”区域。

### delta

表示回答正文增量。

示例：

```text
event: delta
data: {"text":"你"}
```

前端应该把 `text` 追加到当前 assistant 消息正文。

如果要做稳定的逐字体验，建议前端使用打字机队列：

```text
收到 delta -> 放入队列 -> 按固定节奏显示
```

这样即使浏览器一次收到多个小块，也能稳定展示流式效果。

### done

表示本轮回答完成。

示例：

```text
event: done
data: {
  "answer": "完整回答正文",
  "conversation_id": "abc123",
  "selected_douyin_id": null,
  "tools": [],
  "sources": [],
  "memory": {
    "current_tokens": 1200,
    "max_tokens": 16000,
    "current_fraction": 0.075,
    "trigger_fraction": 0.75,
    "keep_fraction": 0.4,
    "trigger_tokens": 12000,
    "keep_tokens": 6400
  },
  "action_suggestion": null
}
```

前端通常在 `done` 时：

- 确认最终 `answer`。
- 更新工具摘要。
- 更新知识库来源。
- 更新上下文使用率。
- 展示操作建议按钮。
- 结束 loading。

如果前面已经通过 `delta` 显示了正文，不要再把 `answer` 直接覆盖到页面上，否则可能破坏打字机效果。

### error

表示本轮回答失败。

示例：

```text
event: error
data: {"message":"智能客服暂时没有回复成功：..."}
```

前端应停止 loading，并展示错误提示。

## 会话接口

assistant 使用 LangGraph SQLite Checkpointer 保存会话状态。

会话不是长期记忆。它只用于当前智能客服历史上下文。

### POST /conversations

创建新会话 ID。

响应：

```json
{
  "conversation_id": "abc123"
}
```

真正的消息会在用户第一次发送问题后写入 Checkpointer。

### GET /conversations

读取当前用户的会话列表。

响应：

```json
{
  "items": [
    {
      "conversation_id": "abc123",
      "title": "为什么任务显示正常但没有发送？"
    }
  ]
}
```

### GET /conversations/{conversation_id}

读取某个会话当前可展示消息。

响应：

```json
{
  "conversation_id": "abc123",
  "messages": [
    {
      "role": "user",
      "content": "我绑定了哪些抖音号"
    },
    {
      "role": "assistant",
      "content": "我查到..."
    }
  ],
  "memory": {
    "current_tokens": 1200,
    "max_tokens": 16000,
    "current_fraction": 0.075,
    "trigger_fraction": 0.75,
    "keep_fraction": 0.4,
    "trigger_tokens": 12000,
    "keep_tokens": 6400
  }
}
```

如果旧消息已经被自动总结，最早的原始消息可能不会完整保留。这是上下文压缩的正常结果。

### DELETE /conversations/{conversation_id}

删除当前用户的某个会话 checkpoint。

响应：

```json
{
  "status": "ok"
}
```

## action_suggestion

`action_suggestion` 是 assistant 给前端的操作建议。

它不代表 assistant 已经修改业务状态。

当前主要用于自动发送开关确认流程。

示例：

```json
{
  "type": "set_auto_send",
  "target_state": true,
  "title": "开启自动发送",
  "message": "请选择要开启自动发送的抖音号。选择后系统会重新检查最新状态，再让你确认是否开启。",
  "button_label": "开启自动发送",
  "reason": "user_requested_enable",
  "requires_account_selection": true,
  "requires_confirmation": true
}
```

前端收到后应：

1. 展示操作按钮。
2. 让用户选择抖音号。
3. 重新读取该抖音号最新状态。
4. 弹窗让用户确认。
5. 用户确认后，再调用 douyin-spark Go 后端已有业务接口。

assistant 自己不直接执行修改操作。

## 前端接入建议

流式聊天推荐处理方式：

1. `start`：保存会话 ID 和 memory。
2. `status`：更新运行状态。
3. `tool`：追加到本次检查列表。
4. `delta`：追加到回答正文，或放入打字机队列。
5. `done`：更新最终元数据，等待打字机队列清空后结束 loading。
6. `error`：停止 loading，展示错误。

状态文本和回答正文建议分开存储：

```text
message.statusText  当前阶段
message.content     回答正文
```

这样可以避免状态和正文互相覆盖。

## 调试

浏览器前端可以临时打开智能客服流式事件日志：

```js
localStorage.setItem('douyin_spark_assistant_debug', '1')
location.reload()
```

关闭日志：

```js
localStorage.removeItem('douyin_spark_assistant_debug')
location.reload()
```

打开后，浏览器控制台会打印：

```text
[assistant-stream] status
[assistant-stream] tool
[assistant-stream] delta
[assistant-stream] done
```

这可以判断前端到底有没有收到 SSE 事件。
