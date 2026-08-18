# Agent Docker 部署说明

本文说明 `douyin-spark-assistant` 如何构建 Python/FastAPI Agent 镜像，以及如何在本机 Docker Desktop 或 Ubuntu Docker 环境中运行。

当前版本：

```text
douyin-spark-assistant v0.9.0
```

配套版本：

```text
douyin-spark v0.9.0
douyin-spark-client v0.9.0
```

## 一、Agent 容器的职责

Agent 是独立的 Python/FastAPI 服务，负责：

```text
LangChain/LangGraph Agent
RAG 知识库检索
Embedding 调用
聊天模型调用
内部只读工具调用
LangGraph 会话 Checkpointer
SSE 流式回答
```

它不替代 Go 后端，也不直接负责前端登录、抖音号数据库或发送任务数据库。

完整链路是：

```text
浏览器
  -> douyin-spark-web
  -> douyin-spark Go 后端
  -> douyin-spark-assistant
  -> 大模型、Embedding 模型和 Go 后端内部接口
```

前端不要直接访问 Agent 的 8000 端口。Go 后端会校验用户登录态，并把用户 token 转发给 Agent。

## 二、镜像和容器信息

当前 Agent 镜像约定：

```text
镜像：douyin-spark-assistant:local
容器：douyin-spark-assistant
容器端口：8000
本机端口：8000
```

Docker 基础镜像：

```dockerfile
FROM python:3.12-slim
```

Dockerfile 会执行：

```text
1. 复制 requirements_deploy.txt。
2. 安装 Python 生产运行依赖。
3. 复制 app/。
4. 复制 scripts/。
5. 使用 uvicorn 监听 0.0.0.0:8000。
```

容器入口：

```text
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 三、依赖文件

Agent 有两份依赖清单：

```text
requirements_deploy.txt
  容器生产运行依赖，位于项目根目录。

docs/requirements_full.txt
  完整开发、实验和扩展依赖清单。
```

Dockerfile 使用的是：

```dockerfile
COPY requirements_deploy.txt .
RUN pip install --no-cache-dir -r requirements_deploy.txt
```

因此，正常构建 Docker 镜像时不需要单独在宿主机执行 `pip install`。依赖安装会在 `docker build` 阶段自动完成。

只有直接使用 Conda/Python 在宿主机启动 Agent 时，才需要手动把依赖安装到对应 Python 环境：

```powershell
D:\Apps\DevTools\Miniconda3\envs\langchain1.2\python.exe -m pip install -r requirements_deploy.txt
```

这条命令修改的是本地 Python 环境，不是 Docker 容器。

修改 `requirements_deploy.txt` 后必须重新构建镜像：

```powershell
docker build -t douyin-spark-assistant:local .
```

## 四、宿主机目录挂载

推荐挂载：

```text
knowledge/
  -> /app/knowledge:ro

storage/
  -> /app/storage
```

`knowledge/` 使用只读挂载，避免容器运行时修改知识库源文件。

`storage/` 使用可写挂载，用于保存：

```text
Chroma 向量库
LangGraph Checkpointer 会话数据库
运行日志
```

不要因为重建容器而删除 `storage/`。删除其中的：

```text
assistant_checkpoints.sqlite
```

会导致历史会话状态消失；删除 `vectorstore/` 后需要重新执行知识库入库。

## 五、环境变量

真实配置放在项目根目录的 `.env`，不要提交到 GitHub。

常用配置包括：

```env
DEEPSEEK_API_KEY=<your-chat-model-api-key>
DEEPSEEK_BASE_URL=<your-chat-model-base-url>
CHAT_MODEL=deepseek-v4-flash

SILICONFLOW_API_KEY=<your-siliconflow-api-key>
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B

DOUYIN_SPARK_API_BASE_URL=http://host.docker.internal:8787/api/v1

KNOWLEDGE_DIR=/app/knowledge/user
CHROMA_PERSIST_DIR=/app/storage/vectorstore
ASSISTANT_CHECKPOINT_DB_PATH=/app/storage/assistant_checkpoints.sqlite
```

本机 Docker Desktop 中，Agent 容器访问宿主机暴露的 Go 后端时通常使用：

```text
http://host.docker.internal:8787/api/v1
```

如果 Agent 和 Go 后端在同一个 Docker Compose 网络中，使用服务名：

```text
http://douyin-spark:8787/api/v1
```

服务器真实配置通常使用：

```text
DOUYIN_SPARK_API_BASE_URL=http://douyin-spark:8787/api/v1
```

聊天模型和 Embedding 模型是两套配置：

```text
CHAT_MODEL
  只影响聊天模型。

SILICONFLOW_API_KEY、SILICONFLOW_BASE_URL、EMBEDDING_MODEL
  用于 Embedding 和知识库向量检索。更换 Embedding 模型后，必须清空对应的 vectorstore 并重新入库。
```

## 六、本地容器部署

本机 Docker Desktop 的完整操作步骤见：

```text
本地Docker Agent模块容器启动教程.md
```

本地部署的目标是：

```text
douyin-spark-assistant:local
        -> douyin-spark-assistant
        -> http://127.0.0.1:8000
```

## 七、服务器部署

服务器部署采用“本地构建镜像、上传镜像、服务器导入”的方式：

```text
1. 本地执行 docker build。
2. 本地用 docker run 和 /health 测试。
3. docker save 导出镜像 tar。
4. 使用 Xshell 连接服务器，使用文件传输或 scp 上传 tar。
5. 服务器执行 docker load。
6. 服务器准备 .env、knowledge/ 和 storage/。
7. 服务器执行 docker compose 重建 Agent 容器。
8. 执行知识库入库。
9. 检查 8000 端口和容器日志。
```

本地导出示例：

```powershell
docker save -o .\.tmp-douyin-spark-assistant-local.tar douyin-spark-assistant:local
```

服务器导入示例：

```bash
sudo docker load -i /opt/douyin-spark-images/.tmp-douyin-spark-assistant-local.tar
```

服务器重建示例：

```bash
cd /opt/douyin-spark-deploy
sudo docker compose up -d --force-recreate douyin-spark-assistant
```

知识库入库示例：

```bash
sudo docker exec douyin-spark-assistant python scripts/ingest_knowledge.py
```

## 八、健康检查和日志

本机健康检查：

```powershell
curl.exe http://127.0.0.1:8000/health
```

服务器健康检查：

```bash
curl -fsS http://127.0.0.1:8000/health
```

正常返回：

```json
{"status":"ok","service":"douyin-spark-assistant"}
```

查看容器状态：

```powershell
docker ps --filter name=douyin-spark-assistant
```

查看日志：

```powershell
docker logs --tail 100 douyin-spark-assistant
```

持续跟踪日志：

```powershell
docker logs -f douyin-spark-assistant
```

按 `Ctrl+C` 只会退出日志查看，不会停止容器。

## 九、安全注意事项

不要提交或上传到 Public GitHub 仓库：

```text
.env
真实 API Key
storage/
assistant_checkpoints.sqlite
Chroma 向量库
运行日志
Docker 镜像 tar 包
```

服务器上的 `.env` 应限制权限：

```bash
chmod 600 /opt/douyin-spark-assistant/.env
```

不要把服务器部署记录、真实服务器地址和真实模型密钥复制到公开仓库。
