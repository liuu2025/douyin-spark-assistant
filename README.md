# douyin-spark-assistant

`douyin-spark-assistant` 是 douyin-spark 的普通用户智能客服 Agent 服务。

它不是单纯的知识库问答。它会同时使用普通用户知识库、RAG 检索、LangChain/LangGraph Agent、内部只读工具和 douyin-spark 后端实时状态，帮助用户理解当前账号、抖音号、登录状态、发送任务、兑换码、轮次和运行记录等问题。

项目文档只给维护者和开发者看。普通用户知识库只放在 `knowledge/user/`，不要把接口、部署、数据库、开发说明写进普通用户知识库。

## 当前能力

- 使用 Markdown 普通用户知识库回答页面操作和状态含义。
- 使用 Chroma 保存知识库向量。
- 使用 Embedding 模型检索相关知识片段。
- 使用 LangChain/LangGraph Agent 调用内部只读工具。
- 内部工具会带用户 token 查询 douyin-spark Go 后端。
- 使用 LangGraph SQLite Checkpointer 保存当前会话历史。
- 使用 SummarizationMiddleware 按上下文 token 百分比自动总结旧消息。
- 提供普通聊天接口和 SSE 流式聊天接口。
- 给前端返回工具检查摘要、知识库来源、上下文使用率和操作建议。

## 运行链路

本地联调时通常是三段服务：

```text
浏览器
  -> douyin-spark-client 前端：http://localhost:8080
  -> douyin-spark Go 后端：http://localhost:8787
  -> douyin-spark-assistant：http://localhost:8000
```

前端不会直接调用 assistant。前端请求 Go 后端：

```text
/api/v1/assistant/...
```

Go 后端再把请求转发给 assistant：

```text
/chat
/chat/stream
/conversations
```

这样做的好处是前端仍然只面对 douyin-spark 后端，用户 token 也由 Go 后端统一校验和转发。

## Agent 回答流程

一次智能客服回答大致是：

1. 前端发送用户问题、当前页面、可选抖音号 ID 和会话 ID。
2. Go 后端读取当前登录用户，转发请求到 assistant。
3. assistant 检索 `knowledge/user/` 入库后的 Chroma 向量库。
4. assistant 创建 LangGraph Agent，并把内部工具说明交给大模型。
5. 大模型判断是否需要调用工具。
6. 工具带用户 token 查询 douyin-spark 后端实时状态。
7. 大模型结合知识库资料和工具结果生成普通用户能理解的回答。
8. 流式接口通过 SSE 返回阶段状态、工具结果、答案增量和最终结果。

## 目录结构

```text
app/
  main.py                    FastAPI 入口
  config.py                  环境变量配置
  schemas.py                 API 请求和响应模型
  prompts/
    assistant_system.txt     智能客服系统提示词
  services/
    agent_service.py         LangChain/LangGraph Agent 主流程
    assistant_service.py     聊天模型、Embedding 和提示词加载
    douyin_api_client.py     douyin-spark 后端 API Client
    rag_service.py           知识库向量检索
  tools/
    douyin_tools.py          Agent 内部只读工具

knowledge/
  user/                      普通用户知识库 Markdown

scripts/
  ingest_knowledge.py        知识库入库脚本
  test_retrieval.py          知识库检索测试
  test_agent_tools.py        内部工具测试
  test_agent_decision.py     工具定义和调用结果检查
  test_agent_answer.py       Agent 回答测试

storage/
  vectorstore/               Chroma 向量库
  assistant_checkpoints.sqlite LangGraph 会话状态
  assistant_uvicorn.*.log    本地服务日志
```

## 环境变量

本地配置通常写在项目根目录的 `.env`。

不要把真实密钥提交到代码仓库。

常用配置：

```env
DEEPSEEK_API_KEY=你的聊天模型密钥
DEEPSEEK_BASE_URL=聊天模型 OpenAI 兼容地址
CHAT_MODEL=deepseek-v4-flash

ZETATECHS_API_KEY=你的 Embedding 密钥
ZETATECHS_BASE_URL=Embedding OpenAI 兼容地址

DOUYIN_SPARK_API_BASE_URL=http://localhost:8787/api/v1

KNOWLEDGE_DIR=./knowledge/user
CHROMA_PERSIST_DIR=./storage/vectorstore
KNOWLEDGE_RELEVANCE_THRESHOLD=0.35

ASSISTANT_CHECKPOINT_DB_PATH=./storage/assistant_checkpoints.sqlite
ASSISTANT_CONTEXT_MAX_INPUT_TOKENS=16000
ASSISTANT_SUMMARY_TRIGGER_FRACTION=0.75
ASSISTANT_SUMMARY_KEEP_FRACTION=0.40
```

说明：

- `CHAT_MODEL` 只影响聊天模型，不影响 Embedding。
- `ZETATECHS_*` 用于知识库入库和检索。
- `DOUYIN_SPARK_API_BASE_URL` 是 assistant 调 douyin-spark 后端的地址。
- `ASSISTANT_CONTEXT_MAX_INPUT_TOKENS` 是本项目控制会话压缩的有效上下文预算。
- `ASSISTANT_SUMMARY_TRIGGER_FRACTION` 默认 `0.75`，表示上下文达到预算 75% 时触发总结。
- `ASSISTANT_SUMMARY_KEEP_FRACTION` 默认 `0.40`，表示总结后保留最近约 40% 预算的原始消息。

## 本地启动

先进入 assistant 项目：

```powershell
cd D:\Projects\test\douyin-spark-workspace\douyin-spark-assistant
```

使用 Miniconda 环境里的 Python 启动：

```powershell
D:\Apps\DevTools\Miniconda3\envs\langchain1.2\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

健康检查：

```powershell
(Invoke-WebRequest 'http://localhost:8000/health' -UseBasicParsing).Content
```

正常返回：

```json
{"status":"ok","service":"douyin-spark-assistant"}
```

FastAPI 自动接口文档：

```text
http://localhost:8000/docs
```

OpenAPI JSON：

```text
http://localhost:8000/openapi.json
```

## 知识库入库

普通用户知识库 Markdown 放在：

```text
knowledge/user/
```

修改知识库后，需要重新入库：

```powershell
cd D:\Projects\test\douyin-spark-workspace\douyin-spark-assistant
D:\Apps\DevTools\Miniconda3\envs\langchain1.2\python.exe scripts/ingest_knowledge.py
```

入库会读取 Markdown 文件，按标题切分，再对过长内容做兜底切分，最后写入 Chroma。

向量库位置由 `CHROMA_PERSIST_DIR` 控制，默认：

```text
storage/vectorstore/
```

## 常用测试脚本

测试知识库检索：

```powershell
D:\Apps\DevTools\Miniconda3\envs\langchain1.2\python.exe scripts/test_retrieval.py
```

测试内部工具：

```powershell
D:\Apps\DevTools\Miniconda3\envs\langchain1.2\python.exe scripts/test_agent_tools.py
```

检查工具定义和调用结果：

```powershell
D:\Apps\DevTools\Miniconda3\envs\langchain1.2\python.exe scripts/test_agent_decision.py
```

测试 Agent 回答：

```powershell
D:\Apps\DevTools\Miniconda3\envs\langchain1.2\python.exe scripts/test_agent_answer.py
```

如果要让工具查询当前用户的真实状态，需要传用户 token，或设置环境变量 `DOUYIN_SPARK_TOKEN`。

## 与前端联调

前端页面访问：

```text
http://localhost:8080/assistant
```

前端请求路径：

```text
/api/v1/assistant/chat/stream
```

Go 后端会转发到 assistant：

```text
http://localhost:8000/chat/stream
```

如果修改了 assistant Python 代码，重启 assistant 服务即可。

如果修改了 `douyin-spark-client` 前端代码，需要重新构建前端并重启前端容器。

## 注意事项

- `knowledge/user/` 只写普通用户知识库。
- 不要把接口文档、部署文档、数据库说明、开发调试说明放进 `knowledge/user/`。
- 工具描述是给大模型理解工具用的，不要当作普通注释随便删。
- `storage/vectorstore/` 是 Chroma 向量库，删除后需要重新入库。
- `storage/assistant_checkpoints.sqlite` 是会话状态，删除后历史会话会消失。
- `.env` 里可能有密钥，不要提交真实密钥。
- assistant 的内部工具只调用项目内部后端，不接入全网搜索工具。
