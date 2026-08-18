# 更新日志

本文档记录 `douyin-spark-assistant` 智能客服服务的版本变化。

## v0.9.2 - 2026-08-18

本版本迁移智能客服知识库 Embedding 配置，替换已经不可用的旧 Embedding 中转站。

### 改进

- 将 Embedding 配置从 `ZETATECHS_*` 切换为 `SILICONFLOW_*`。
- 新增 `EMBEDDING_MODEL` 环境变量，默认使用 `Qwen/Qwen3-Embedding-0.6B`。
- 知识库向量库重建为 `1024` 维。
- Chroma collection 新增 `hnsw:space=cosine` 配置，用于 Qwen3 Embedding 检索。
- 入库脚本和检索测试脚本修复 Windows 控制台 UTF-8 输出问题。
- 检索测试脚本重写为干净 UTF-8 文本，方便后续回归。

### 部署

- 服务器只重建 `douyin-spark-assistant` 容器。
- 服务器保留 `knowledge/` 和 `assistant_checkpoints.sqlite`，仅备份并重建 `storage/vectorstore`。
- 服务器重建后验证 collection 为 `douyin_user_knowledge`、`1024` 维、`109` 条向量、`hnsw:space=cosine`。

### 注意

- `Qwen/Qwen3-Embedding-0.6B` 已完成链路迁移，但短问题检索排序仍需线上观察；如召回不稳，优先评估 `Qwen/Qwen3-Embedding-4B` 后重新入库。

## v0.9.1 - 2026-07-17

本版本为智能客服服务文档补丁版本，配套 `douyin-spark v0.9.1` 和 `douyin-spark-client v0.9.1`。Agent 运行代码、依赖文件和接口行为无变化。

### 文档与部署

- 新增 Agent Docker 部署说明，记录 `douyin-spark-assistant:local` 镜像、`python:3.12-slim` 基础镜像、`requirements_deploy.txt`、`.env`、`knowledge/` 和 `storage/` 的部署边界。
- 新增本地 Docker Agent 模块容器启动教程，覆盖镜像构建、容器创建或重建、健康检查、知识库入库、三端联调和常见问题处理。
- 补充本机 Docker 与服务器 Docker 中访问 Go 后端地址的差异说明。
- 将环境变量示例中的模型密钥改为公开占位符，避免误把真实 `.env` 内容写入公开文档。

### 已验证

- 本次仅修改文档，未修改 Python 运行代码、依赖文件或知识库内容。

## v0.9.0 - 2026-07-17

本版本为 `douyin-spark-assistant` 首次正式发布版本，配套 `douyin-spark v0.9.0` 和 `douyin-spark-client v0.9.0`。该服务作为独立 Python/FastAPI Agent 模块，为 douyin-spark 普通用户提供知识库问答、实时状态解释、内部工具检查和智能客服会话能力。

### 新增

- 新增 FastAPI 服务入口，提供健康检查、普通聊天、SSE 流式聊天和会话管理接口。
- 新增 LangChain/LangGraph Agent 主流程，支持大模型结合知识库资料和内部工具结果生成回答。
- 新增普通用户 Markdown 知识库，覆盖账号登录、添加抖音号、远程浏览器登录、登录状态、发送任务、轮次、兑换码、运行记录和常见问题。
- 新增 Chroma 向量库入库和检索流程。
- 新增 LangGraph SQLite Checkpointer，用于保存当前用户的会话历史。
- 新增按上下文 token 百分比触发的历史消息总结能力。
- 新增内部只读工具，可查询当前用户、当前用户管理的抖音号、单个抖音号详情、登录状态、发送任务、运行记录、兑换码和轮次。
- 新增自动发送开启/关闭操作建议结构，由前端弹窗二次确认后再执行真实业务操作。
- 新增 `requirements_deploy.txt` 和 Dockerfile，支持生产 Docker 镜像部署。

### 改进

- 系统提示词限定智能客服职责范围，只回答 douyin-spark 普通用户使用问题，并拒绝验证码绕过、平台限制绕过等不安全请求。
- 工具描述补充清晰的功能、返回结果和失败原因说明，提升大模型选择工具的稳定性。
- 流式接口返回 `status`、`tool`、`delta`、`done` 和 `error` 事件，方便前端展示阶段状态和逐字输出。
- 回答结果包含 `tools`、`sources`、`memory` 和 `action_suggestion`，方便前端展示本次检查、参考资料、上下文使用率和操作建议。

### 文档与部署

- 新增 README，说明项目定位、运行链路、环境变量、本地启动、知识库入库、测试脚本和 Docker 部署。
- 新增 `docs/api.md`，记录 assistant 直连接口和推荐的 Go 后端代理链路。
- 新增 `.env.example`，只包含公开占位符，不包含真实 API Key。
- 新增 `.gitignore`，排除 `.env`、`storage/`、本地缓存、临时部署包、日志和生成的向量库。

### 已验证

- 已通过 Python 编译检查。
- 已通过本地 Docker 镜像构建和健康检查。
- 已配套 Go 后端 `/api/v1/assistant/...` 代理接口和前端智能客服页面。
