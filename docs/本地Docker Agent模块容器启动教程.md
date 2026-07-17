# 本地 Docker Agent 模块容器启动教程

本文用于在 Windows + Docker Desktop 中构建和启动 `douyin-spark-assistant` 容器。

当前项目路径：

```text
D:\Projects\test\douyin-spark-workspace\douyin-spark-assistant
```

当前容器信息：

```text
容器名：douyin-spark-assistant
镜像名：douyin-spark-assistant:local
本机端口：8000
容器端口：8000
```

## 一、启动前提

先打开 Docker Desktop，并等待 Docker Engine 显示运行。

执行：

```powershell
docker version
```

如果出现：

```text
Cannot connect to the Docker daemon
```

说明 Docker Desktop 尚未启动完成。

本教程还假设：

```text
.env 已存在并填写了本地测试需要的配置
knowledge/user/ 已存在
storage/ 已存在
Go 后端容器正在 8787 端口运行
```

检查配置和目录：

```powershell
cd D:\Projects\test\douyin-spark-workspace\douyin-spark-assistant
Test-Path .\.env
Test-Path .\knowledge\user
Test-Path .\storage
```

这三项都应该返回：

```text
True
```

不要把 `.env` 内容直接打印到终端或复制到公开文档，因为里面可能包含聊天模型、Embedding 模型和后端访问配置。

## 二、检查镜像和容器

检查 Agent 镜像：

```powershell
docker images douyin-spark-assistant
```

如果能看到：

```text
douyin-spark-assistant   local   ...
```

说明本机已有镜像。

检查 Agent 容器：

```powershell
docker ps -a --filter name=douyin-spark-assistant
```

可能有三种情况：

```text
STATUS 为 Up
  容器已经运行，不需要重复创建。

STATUS 为 Exited
  容器存在但已停止，可以执行 docker start。

没有任何输出
  容器不存在，需要执行 docker run 创建。
```

## 三、构建 Agent 镜像

如果是第一次启动，或者修改了以下内容，需要重新构建：

```text
app/
scripts/
app/prompts/assistant_system.txt
requirements_deploy.txt
Dockerfile
```

进入项目目录：

```powershell
cd D:\Projects\test\douyin-spark-workspace\douyin-spark-assistant
```

构建镜像：

```powershell
docker build -t douyin-spark-assistant:local .
```

Docker 构建过程中会：

```text
1. 拉取或使用 python:3.12-slim。
2. 复制 requirements_deploy.txt。
3. 使用 pip 安装容器依赖。
4. 复制 app/ 和 scripts/。
5. 生成 douyin-spark-assistant:local。
```

如果只是看到：

```text
WARNING: current commit information was not captured
```

通常不影响镜像构建。只要最后显示构建成功并生成镜像即可。

## 四、启动已有容器

如果容器存在但状态是 `Exited`，并且代码和镜像都没有变化，可以执行：

```powershell
docker start douyin-spark-assistant
```

查看状态：

```powershell
docker ps --filter name=douyin-spark-assistant
```

## 五、创建或重建 Agent 容器

如果刚刚重新构建了镜像，或者容器不存在，执行：

```powershell
docker rm -f douyin-spark-assistant 2>$null
docker run -d --name douyin-spark-assistant --restart unless-stopped --env-file .env -p 8000:8000 -e DOUYIN_SPARK_API_BASE_URL=http://host.docker.internal:8787/api/v1 -v D:\Projects\test\douyin-spark-workspace\douyin-spark-assistant\knowledge:/app/knowledge:ro -v D:\Projects\test\douyin-spark-workspace\douyin-spark-assistant\storage:/app/storage douyin-spark-assistant:local
```

这条命令的作用：

```text
--name douyin-spark-assistant
  设置容器名。

--restart unless-stopped
  Docker Desktop 重启后自动恢复容器，除非手动停止它。

--env-file .env
  把本地真实配置传入容器。

-p 8000:8000
  把本机 8000 映射到容器 8000。

DOUYIN_SPARK_API_BASE_URL=http://host.docker.internal:8787/api/v1
  让 Agent 访问本机 Docker 暴露的 Go 后端。

knowledge:/app/knowledge:ro
  把本地知识库以只读方式挂载到容器。

storage:/app/storage
  把本地向量库、会话数据库和日志挂载到容器。
```

如果 Go 后端和 Agent 在同一个 Docker Compose 网络中，可以把后端地址改为：

```text
http://douyin-spark:8787/api/v1
```

## 六、健康检查

容器启动后执行：

```powershell
curl.exe http://127.0.0.1:8000/health
```

正常结果：

```json
{"status":"ok","service":"douyin-spark-assistant"}
```

如果没有返回结果，先查看状态：

```powershell
docker ps -a --filter name=douyin-spark-assistant
```

再查看日志：

```powershell
docker logs --tail 100 douyin-spark-assistant
```

## 七、知识库入库

如果首次运行、知识库文件有修改，或者 `storage/vectorstore/` 为空，需要在容器中执行：

```powershell
docker exec douyin-spark-assistant python scripts/ingest_knowledge.py
```

入库脚本会：

```text
1. 读取 /app/knowledge/user/ 下的 Markdown。
2. 按标题切分内容。
3. 调用 Embedding 模型生成向量。
4. 写入 /app/storage/vectorstore/。
```

如果入库时报模型网络错误、API Key 错误或连接超时，优先检查 `.env` 中的 Embedding 配置，不要先删除 `storage/`。

## 八、三端联调

本地 Docker 联调的目标链路：

```text
浏览器
  -> douyin-spark-web:8080
  -> douyin-spark:8787
  -> douyin-spark-assistant:8000
```

分别检查：

```powershell
curl.exe http://127.0.0.1:8080/health
curl.exe http://127.0.0.1:8787/health
curl.exe http://127.0.0.1:8000/health
```

浏览器打开：

```text
http://127.0.0.1:8080/
```

登录后进入：

```text
/assistant
```

前端不要直接请求：

```text
http://127.0.0.1:8000
```

前端应该请求 Go 后端的：

```text
/api/v1/assistant/...
```

## 九、修改代码后的规则

修改 `app/`、`scripts/`、系统提示词或 Dockerfile 后：

```powershell
docker build -t douyin-spark-assistant:local .
docker rm -f douyin-spark-assistant 2>$null
docker run -d --name douyin-spark-assistant --restart unless-stopped --env-file .env -p 8000:8000 -e DOUYIN_SPARK_API_BASE_URL=http://host.docker.internal:8787/api/v1 -v D:\Projects\test\douyin-spark-workspace\douyin-spark-assistant\knowledge:/app/knowledge:ro -v D:\Projects\test\douyin-spark-workspace\douyin-spark-assistant\storage:/app/storage douyin-spark-assistant:local
curl.exe http://127.0.0.1:8000/health
```

只执行：

```powershell
docker restart douyin-spark-assistant
```

不会自动把修改后的 Python 源码复制进旧镜像。因为当前 Dockerfile 使用 `COPY app ./app`，代码是在构建镜像时复制进去的。

修改 `requirements_deploy.txt` 后一定要重新构建镜像，否则新依赖不会进入容器。

修改 `knowledge/user/` 后，如果知识库目录是挂载状态，通常不需要重建镜像，但需要重新入库：

```powershell
docker exec douyin-spark-assistant python scripts/ingest_knowledge.py
```

修改 `.env` 后，建议重建容器，让新环境变量在启动阶段生效。

## 十、常见问题

### 1. 8000 端口被占用

检查：

```powershell
netstat -ano | findstr :8000
```

如果是旧 Python 进程占用，先关闭旧进程；如果是其他容器占用，检查：

```powershell
docker ps -a
```

### 2. 容器启动后马上退出

查看日志：

```powershell
docker logs --tail 100 douyin-spark-assistant
```

常见原因包括：

```text
.env 缺少必要配置
requirements_deploy.txt 依赖安装失败
storage 目录权限或挂载路径错误
Python 应用启动异常
```

### 3. Agent 健康检查正常，但工具查询失败

检查容器环境变量：

```powershell
docker inspect douyin-spark-assistant --format '{{range .Config.Env}}{{println .}}{{end}}'
```

确认：

```text
DOUYIN_SPARK_API_BASE_URL=http://host.docker.internal:8787/api/v1
```

同时检查 Go 后端：

```powershell
curl.exe http://127.0.0.1:8787/health
```

### 4. 知识库没有结果

先执行：

```powershell
docker exec douyin-spark-assistant python scripts/ingest_knowledge.py
```

不要把 `knowledge/user/` 和 `storage/vectorstore/` 混为一回事：

```text
knowledge/user/       Markdown 源文件
storage/vectorstore/  Embedding 生成的向量库
```

## 十一、停止和删除

停止容器：

```powershell
docker stop douyin-spark-assistant
```

重新启动：

```powershell
docker start douyin-spark-assistant
```

删除容器：

```powershell
docker rm -f douyin-spark-assistant
```

删除容器不会自动删除宿主机挂载的 `knowledge/` 和 `storage/`，但不要手动删除 `storage/`，除非你明确要清空会话、日志或向量库。

