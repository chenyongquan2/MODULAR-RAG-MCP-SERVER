# Docker & Kubernetes 学习笔记

> 以 Modular RAG MCP Server 项目为实例，结合实际文件讲解。

---

## 第一部分：Docker 基础

### Docker 是什么？

Docker 把应用 + 依赖 + 运行环境打包成一个"集装箱"（镜像），在任何机器上都能一模一样地运行。

没有 Docker 时：
```
"我电脑上能跑啊" → 换台机器就报错（Python 版本不对、缺依赖、配置不同...）
```

有了 Docker：
```
一次打包 → 到处运行（开发机、测试服务器、生产环境全部一致）
```

### 核心概念（只有 3 个）

| 概念 | 类比 | 说明 |
|------|------|------|
| **镜像 (Image)** | 安装光盘 | 只读模板，包含代码+依赖+配置 |
| **容器 (Container)** | 运行中的程序 | 从镜像启动的实例，可以有多个 |
| **Dockerfile** | 安装说明书 | 描述如何一步步构建镜像 |

### 读懂 Dockerfile

参考项目文件：`Dockerfile`

```dockerfile
# ---- 阶段 1：构建 ----
FROM python:3.11-slim AS builder    # 基于 Python 3.11 镜像开始
WORKDIR /build                      # 设置工作目录（类似 cd /build）

RUN apt-get update && \
    apt-get install -y gcc g++      # 安装编译工具（某些 Python 包需要）

COPY pyproject.toml README.md ./    # 先只拷贝依赖文件（利用缓存）
RUN pip install .                   # 安装依赖

# ---- 阶段 2：运行 ----
FROM python:3.11-slim AS runtime    # 全新的干净镜像（不带 gcc 等构建工具）
COPY --from=builder /opt/venv ...   # 只从阶段1复制装好的依赖
COPY src/ ./src/                    # 复制应用代码

EXPOSE 8501                         # 声明暴露端口
CMD ["python", "-m", "streamlit", "run", ...]  # 默认启动命令
```

**为什么分两个阶段？** 阶段 1 有 gcc 等工具（~277MB），最终镜像不需要它们。多阶段构建让镜像更小。

### 常用 Docker 命令

```bash
docker build -t modular-rag:test .     # 根据 Dockerfile 构建镜像
docker images                          # 查看本地所有镜像
docker run -p 8501:8501 modular-rag    # 从镜像启动容器，映射端口
docker ps                              # 查看运行中的容器
docker logs <容器名>                    # 查看容器日志
docker exec -it <容器名> bash          # 进入容器内部（类似 SSH）
docker stop <容器名>                    # 停止容器
```

### Docker Compose —— 多容器编排

项目有 3 个服务，不可能手动一个个 `docker run`。`docker-compose.yml` 用来一键管理多个容器。

参考项目文件：`docker-compose.yml`

```yaml
services:
  chromadb:                    # 服务1：数据库
    image: chromadb/chroma     # 直接用官方镜像
    ports:
      - "8000:8000"           # 主机端口:容器端口
    volumes:
      - chroma-data:/data     # 数据持久化（容器删了数据还在）
    healthcheck: ...           # 健康检查（其他服务等它就绪才启动）

  dashboard:                   # 服务2：前端
    build: .                   # 从当前目录的 Dockerfile 构建
    depends_on:
      chromadb:
        condition: service_healthy  # 等 chromadb 健康后才启动

  mcp-server:                  # 服务3：后端
    build: .                   # 同一个镜像
    command: ["python", "-m", "src.mcp_server.server"]  # 覆盖默认启动命令
```

关键点：
- **`volumes`** — 容器是临时的，删掉就没了。Volume 让数据持久保存
- **`depends_on`** — 控制启动顺序
- **`ports: "8501:8501"`** — 左边是你电脑的端口，右边是容器内的端口

```bash
docker compose up -d      # 启动所有服务（-d 后台运行）
docker compose ps         # 查看状态
docker compose logs -f    # 跟踪日志
docker compose down       # 停止并删除容器
docker compose down -v    # 连 volume（数据）一起删
```

---

## 第二部分：Kubernetes (K8s) 基础

### 为什么需要 K8s？

Docker Compose 适合单机开发。但在生产环境：

| 问题 | Docker Compose | Kubernetes |
|------|---------------|------------|
| 容器挂了怎么办？ | 手动重启 | **自动重启** |
| 流量大了怎么办？ | 手动加机器 | **自动扩缩容** |
| 怎么滚动更新？ | 停机更新 | **零停机滚动更新** |
| 多台机器怎么管？ | 不支持 | **跨节点统一调度** |

### K8s 核心概念

```
集群 (Cluster)
├── 节点 (Node) ─── 一台机器
│   ├── Pod ─── 最小部署单元（通常 = 1个容器）
│   ├── Pod
│   └── Pod
└── 节点 (Node)
    ├── Pod
    └── Pod
```

### K8s 资源类型详解

#### 1. Namespace — 隔离空间

参考项目文件：`k8s/base/namespace.yaml`

```yaml
kind: Namespace
metadata:
  name: modular-rag    # 你的应用住在 "modular-rag" 这个隔离区
```

类比：一栋大楼里的一个楼层，不同团队用不同楼层，互不干扰。

#### 2. ConfigMap — 配置文件

参考项目文件：`k8s/base/configmap.yaml`

```yaml
kind: ConfigMap
data:
  settings.yaml: |     # 把 settings.yaml 的内容存在 K8s 里
    llm:
      provider: "azure"
      ...
```

类比：一份共享文档，多个 Pod 都能读取。修改配置不需要重新构建镜像。

#### 3. Secret — 敏感信息

参考项目文件：`k8s/base/secret.yaml`

```yaml
kind: Secret
stringData:
  AZURE_OPENAI_API_KEY: "REPLACE_ME"   # API 密钥
```

类比：保险箱。和 ConfigMap 类似，但内容加密存储。

#### 4. Deployment — 无状态应用部署

参考项目文件：`k8s/base/dashboard-deployment.yaml`

```yaml
kind: Deployment
spec:
  replicas: 1              # 运行几个副本
  template:
    spec:
      containers:
        - name: dashboard
          image: modular-rag:latest
          ports:
            - containerPort: 8501
          resources:
            requests:           # 最少需要多少资源
              memory: "256Mi"
              cpu: "250m"       # 0.25 核 CPU
            limits:             # 最多能用多少资源
              memory: "512Mi"
              cpu: "500m"
          readinessProbe:       # 就绪探针：确认能接受流量
            httpGet:
              path: /_stcore/health
          livenessProbe:        # 存活探针：挂了自动重启
            httpGet:
              path: /_stcore/health
```

关键机制：
- **replicas** — 想扩容？改成 `replicas: 3` 就行
- **readinessProbe** — K8s 定期检查，没就绪不分配流量
- **livenessProbe** — K8s 定期检查，挂了自动杀掉重建

#### 5. StatefulSet — 有状态应用（数据库）

参考项目文件：`k8s/base/chromadb-statefulset.yaml`

```yaml
kind: StatefulSet           # 不是 Deployment！
spec:
  volumeClaimTemplates:     # 自动创建持久存储
    - metadata:
        name: chroma-data
      spec:
        storage: 10Gi       # 申请 10GB 磁盘
```

**Deployment vs StatefulSet 详解**：

本质区别是**有没有"身份"和"记忆"**。

以本项目举例：

```
Dashboard 用 Deployment：
  Pod-A 挂了 → K8s 随便创建一个 Pod-B 替代
  Pod-B 和 Pod-A 完全等价，没有区别
  用户根本感觉不到换了一个

ChromaDB 用 StatefulSet：
  Pod-A 挂了 → K8s 必须创建一个叫 "chromadb-0" 的 Pod 来替代
  它还要挂载回原来那块 10Gi 的磁盘
  数据还在，身份还是它
```

核心区别：

| | Deployment | StatefulSet |
|--|------------|-------------|
| **Pod 有没有固定名字** | 随机（`dashboard-7d9f-xk2p`） | 固定（`chromadb-0`、`chromadb-1`） |
| **存储跟不跟 Pod 走** | 不跟，换个 Pod 就没了 | 跟，`chromadb-0` 永远挂载同一块盘 |
| **Pod 之间有没有顺序** | 没有，同时起同时死 | 有，`0` 先起，`1` 后起 |
1
直觉类比：

```
Deployment  →  餐厅服务员
               走一个换一个，顾客不在乎是哪个人端菜
               每个服务员都能做同样的事

StatefulSet →  主厨
               张三主厨有自己的专属厨房（磁盘）和专属食谱（状态）
               张三走了只能等张三回来，或者找个接手他厨房的人
               换成李四，厨房不一样，做出来的东西就不对了
```

如何选择：

```
有没有需要持久保存的数据？
  │
  ├── 没有（无状态）→ Deployment
  │    示例：Dashboard、MCP Server、Web 服务、API 服务
  │
  └── 有（有状态）→ StatefulSet
       示例：数据库（ChromaDB、MySQL、Redis）、消息队列（Kafka）
```

**补充问答：**

**Q：StatefulSet Pod 挂了，为什么必须起一个相同名字的 Pod，而不是随便起一个挂载同一块磁盘就行？**

从存储角度来说，你的直觉是对的——只要挂载同一块磁盘数据就还在。但固定名字是为了解决存储以外的问题：

1. **其他服务通过名字找它**
   ```
   Kafka 集群 3 个节点互相认识对方：
   kafka-0 知道要联系 kafka-1、kafka-2

   kafka-1 挂了，随机起一个 kafka-xyz → 其他节点找不到它
   必须起一个叫 kafka-1 的 → 其他节点照样能找到
   ```

2. **配置和证书绑定了名字**
   很多中间件的配置文件、TLS 证书里直接写了节点名字，名字变了就要重新配置。

3. **单节点场景其实无所谓**
   对于项目里只有 1 个副本的 ChromaDB，名字固不固定无关紧要，只要挂载回同一块磁盘数据就还在。固定名字是 StatefulSet 为支持**多副本有状态集群**设计的，单节点只是顺带享受了这个特性。

---

**Q：挂载（Mount）是什么意思？**

挂载就是**把一块存储设备接入到某个目录，让程序通过这个目录读写那块存储上的数据**。

生活类比：

```
你有一块移动硬盘
插到电脑上 → Windows 分配给它 D:\ 盘符
你往 D:\data\ 写文件 → 实际写到了移动硬盘里

这就是挂载：移动硬盘 挂载到 D:\
```

在容器里：

```
PVC（一块 10Gi 的网络磁盘）
  ↓ 挂载到
容器内的 /data 目录

ChromaDB 往 /data 写向量数据
  ↓ 实际写到
那块 10Gi 的网络磁盘上

Pod 挂了，磁盘还在
新 Pod 启动，把同一块磁盘再挂载到 /data
ChromaDB 启动，打开 /data，数据还在 ✓
```

K8s 里挂载的写法：

```yaml
volumeMounts:
  - name: chroma-data
    mountPath: /data    # 容器内的目录入口
                        # 读写这个目录 = 读写那块 10Gi 磁盘
```

**挂载 = 把磁盘接入到某个目录入口**，程序不需要知道背后是什么存储，正常读写目录就行。

#### 6. Service — 内部网络

```yaml
kind: Service
spec:
  type: ClusterIP           # 仅集群内部可访问
  ports:
    - port: 8501
  selector:
    app.kubernetes.io/name: dashboard   # 流量转发给带这个标签的 Pod
```

类比：内部电话分机号。Pod 可能被杀掉重建（IP 变了），但 Service 名字不变，其他服务通过 `dashboard:8501` 始终能找到它。

#### 7. Ingress — 外部入口

参考项目文件：`k8s/base/ingress.yaml`

```yaml
kind: Ingress
spec:
  rules:
    - host: rag-dashboard.example.com   # 外部域名
      http:
        paths:
          - path: /
            backend:
              service:
                name: dashboard         # 转发到 dashboard Service
                port: 8501
```

类比：大楼前台。外部访问统一走前台，前台根据你找的人（域名/路径）转接到对应楼层（Service）。

### 资源关系图

```
外部用户
  │
  ▼
Ingress (rag-dashboard.example.com)
  │
  ▼
Service (dashboard:8501)
  │
  ▼
Deployment (dashboard) ──挂载──▶ ConfigMap (settings.yaml)
  │                              Secret (API keys)
  │
  │ 内部访问 chromadb:8000
  ▼
Service (chromadb:8000)
  │
  ▼
StatefulSet (chromadb) ──持久存储──▶ PVC (10Gi)
```

---

## 第三部分：Helm — K8s 的包管理器

### 为什么需要 Helm？

`k8s/base/` 目录有 8 个 YAML 文件，里面很多值是写死的。如果要：
- 开发环境用 1 副本，生产用 3 副本
- 不同环境用不同镜像版本

就要维护多份几乎相同的 YAML。**Helm 让你用模板 + 变量来管理**。

### 怎么用？

`helm/modular-rag/values.yaml` 定义变量：

```yaml
dashboard:
  replicas: 1                 # 改这里就能调整副本数
  resources:
    requests:
      memory: "256Mi"
```

模板里引用变量：

```yaml
replicas: {{ .Values.dashboard.replicas }}
resources:
  {{- toYaml .Values.dashboard.resources | nindent 12 }}
```

部署时可以覆盖任何值：

```bash
# 默认部署
helm install modular-rag ./helm/modular-rag/

# 生产环境：3 副本 + 设置 API key + 开启 Ingress
helm install modular-rag ./helm/modular-rag/ \
  --set dashboard.replicas=3 \
  --set secrets.azureOpenaiApiKey="sk-xxx" \
  --set ingress.enabled=true \
  --set ingress.host="rag.mycompany.com"

# 升级（修改配置后）
helm upgrade modular-rag ./helm/modular-rag/

# 回滚
helm rollback modular-rag 1

# 卸载
helm uninstall modular-rag
```

### 速查对照表

| Docker 概念 | K8s 对应 | 项目中的文件 |
|------------|---------|--------------|
| `docker run` | Pod / Deployment | `dashboard-deployment.yaml` |
| `docker compose` | Helm / Kustomize | `helm/` 或 `k8s/base/` |
| 端口映射 `-p` | Service | 每个 deployment 对应的 service |
| volume | PersistentVolumeClaim | chromadb-statefulset 中的 PVC |
| 环境变量 | ConfigMap / Secret | `configmap.yaml` / `secret.yaml` |
| healthcheck | liveness/readinessProbe | deployment 中的 probe 配置 |

---

## 第四部分：k8s/base 与 Helm 的区别，以及 Helm 目录结构

### k8s/base vs Helm —— 本质区别

两套文件的**内容逻辑完全相同**，区别只是管理方式：

```
k8s/base/   → 值写死在 YAML 里，直接 apply
helm/       → 值抽成变量，通过模板渲染后再 apply
```

对比同一个东西的两种写法：

**k8s/base/dashboard-deployment.yaml（写死）**
```yaml
replicas: 1
image: modular-rag:latest
memory: "256Mi"
cpu: "250m"
```

**helm/templates/dashboard-deployment.yaml（模板）**
```yaml
replicas: {{ .Values.dashboard.replicas }}
image: {{ include "modular-rag.image" . }}
memory: {{ .Values.dashboard.resources.requests.memory }}
cpu: {{ .Values.dashboard.resources.requests.cpu }}
```

值在 `values.yaml` 里统一管理：
```yaml
dashboard:
  replicas: 1
  resources:
    requests:
      memory: "256Mi"
      cpu: "250m"
```

| | k8s/base | Helm |
|--|----------|------|
| 适合场景 | 配置固定、单环境 | 多环境、频繁改参数 |
| 修改方式 | 直接改 YAML 文件 | 改 values.yaml 或 `--set` |
| 部署命令 | `kubectl apply -k k8s/base/` | `helm install` / `helm upgrade` |
| 回滚 | 手动 git revert 再 apply | `helm rollback` 一条命令 |

> 实际项目里通常**二选一**，不需要同时维护两套。本项目两套都有是为了演示两种方案，上生产选 Helm 就够了。

---

### Helm 目录结构详解

```
helm/modular-rag/
├── Chart.yaml                    # Chart 的身份证
├── values.yaml                   # 默认变量值
└── templates/                    # 模板文件目录
    ├── _helpers.tpl              # 公共函数（不会渲染成 K8s 资源）
    ├── namespace.yaml
    ├── configmap.yaml
    ├── secret.yaml
    ├── chromadb-statefulset.yaml
    ├── chromadb-service.yaml
    ├── dashboard-deployment.yaml
    ├── dashboard-service.yaml
    ├── mcp-server-deployment.yaml
    └── ingress.yaml
```

#### `Chart.yaml` — Chart 的身份证

```yaml
apiVersion: v2
name: modular-rag          # Chart 名字
version: 0.1.0             # Chart 自己的版本（改了模板就升这个）
appVersion: "0.1.0"        # 应用的版本（对应你的代码版本）
description: ...
```

#### `values.yaml` — 所有变量的默认值

```yaml
dashboard:
  replicas: 1              # 部署时可以用 --set 覆盖任意值
  resources:
    requests:
      memory: "256Mi"
chromadb:
  persistence:
    size: 10Gi
```

#### `templates/_helpers.tpl` — 公共函数库

文件名以 `_` 开头，**不会被渲染成 K8s 资源**，只定义可复用的函数片段：

```yaml
{{- define "modular-rag.fullname" -}}    # 定义一个函数
{{- .Release.Name }}-{{ .Chart.Name }}
{{- end }}

# 其他模板里调用：
name: {{ include "modular-rag.fullname" . }}
```

#### `templates/*.yaml` — 实际的 K8s 资源模板

和 `k8s/base/` 里的文件一一对应，区别是值换成了变量引用 `{{ .Values.xxx }}`。

---

### 更复杂项目的 Helm 目录

```
helm/modular-rag/
├── Chart.yaml
├── values.yaml
├── values-dev.yaml          # 开发环境覆盖值
├── values-prod.yaml         # 生产环境覆盖值
├── charts/                  # 子 Chart（依赖的其他 Chart）
│   └── chromadb/            # 直接依赖官方 chromadb chart
├── templates/
│   └── ...
└── .helmignore              # 类似 .gitignore，打包时排除的文件
```

多环境用法：

```bash
# 开发环境
helm install modular-rag . -f values-dev.yaml

# 生产环境（3 副本 + 大磁盘）
helm install modular-rag . -f values-prod.yaml
```

---

## 补充：k8s/base 和 helm/ 目录是如何联动/映射的？

**答：它们之间没有任何联动或映射关系。**

两套文件是**完全独立**的，互相不知道对方的存在：

```
k8s/base/                    helm/modular-rag/templates/
├── namespace.yaml    ←无关→  ├── namespace.yaml
├── configmap.yaml    ←无关→  ├── configmap.yaml
├── dashboard-        ←无关→  ├── dashboard-
│   deployment.yaml           │   deployment.yaml
└── ...                       └── ...
```

它们只是**描述同一件事的两种写法**，就像同一份菜谱，一份用中文写死了"放 1 勺盐"，另一份用模板写"放 `{{ .Values.salt }}` 勺盐"。两份菜谱独立存在，做出来的菜一样。

### 部署时走完全不同的路径

```
k8s/base/ 路径：
  kubectl apply -k k8s/base/
    → kubectl 直接读 YAML 文件
    → 发给 K8s API
    → 创建资源

helm/ 路径：
  helm install modular-rag ./helm/modular-rag/
    → Helm 读 values.yaml + templates/
    → 渲染成普通 YAML
    → 发给 K8s API
    → 创建资源
```

最终到达 K8s 的内容是一样的，但走的是**完全不同的工具链**，中间没有任何交叉。

### 为什么看起来像在"映射"

因为它们描述的是**同一套应用**，所以文件名相同、内容逻辑相同，容易误以为有关联。实际上只是人为保持了命名一致，方便对照阅读，不是技术上的依赖关系。

**实际项目里选一套用就够了，另一套删掉也完全没问题。**

---

## 补充：Helm 和 K8s 是什么关系？

### 核心结论

**Helm 不是独立的部署方式，它是 K8s 的包管理工具。**

```
K8s   →  操作系统
Helm  →  应用商店（App Store）
```

Helm 最终还是把资源部署到 K8s 上，只是帮你管理了"怎么部署"这个过程：

```
你                         K8s 集群
 │                              │
 ├── kubectl apply ─────────────► 直接部署
 │                              │
 └── helm install ──► Helm 渲染模板 ──► 还是部署到 K8s
```

**两条路最终都到同一个地方：K8s 集群。**

---

### 三种说法的真实含义

| 说法 | 真实含义 |
|------|---------|
| "用 K8s 部署" | 泛指把应用跑在 K8s 集群上 |
| "用 kubectl apply 部署" | 直接把 YAML 文件提交给 K8s |
| "用 Helm 部署" | 通过 Helm 工具把模板渲染后提交给 K8s |

后两个都是"用 K8s 部署"，只是**操作方式**不同。

---

### 什么时候选哪种

```
需要部署到 K8s 吗？
  │
  └── 是
        │
        ├── 配置简单、不需要多环境、一次性部署
        │     └──► kubectl apply（直接用 k8s/base/）
        │
        └── 需要多环境、频繁升级回滚、配置经常变
              └──► Helm（用 helm install）
```

**kubectl 是手动挡，Helm 是自动挡，目的地都是 K8s。**

---

### 用本项目举例

```bash
# 方式一：kubectl 直接部署（k8s/base/）
kubectl apply -k k8s/base/
# Helm 完全不参与，kubectl 直接和 K8s 通信

# 方式二：Helm 部署（helm/）
helm install modular-rag ./helm/modular-rag/
# Helm 先把模板渲染成 YAML，再提交给 K8s
# 最终效果和方式一完全一样
```

两种方式部署出来的结果在 K8s 里**完全一样**，区别只是有没有 Helm 这个中间层帮你管理。

---

### kubectl apply 和 helm 的区别，以及何时选 Helm

#### kubectl apply 不需要一个个文件 apply

```bash
# apply 单个文件
kubectl apply -f namespace.yaml

# apply 整个目录（一次性全部）
kubectl apply -f k8s/base/

# apply Kustomize 目录（本项目用的）
kubectl apply -k k8s/base/
```

#### kubectl apply 的三个不便之处

**1. 不知道"这批资源是一组的"**

```bash
kubectl apply -f k8s/base/
# K8s 只知道"有人提交了这些资源"，不知道它们属于同一个应用

# 卸载时你得自己记得删哪些：
kubectl delete -f k8s/base/namespace.yaml
kubectl delete -f k8s/base/configmap.yaml
kubectl delete -f k8s/base/dashboard-deployment.yaml
# ... 一个个来，漏删就留下垃圾资源
```

**2. 没有版本历史，无法快速回滚**

```bash
# 改了配置，重新 apply
kubectl apply -f k8s/base/

# 发现新版本有问题，想回滚？
# → 只能手动 git revert 改回旧配置，再 apply 一次
# → 没有"上一个版本"的概念
```

**3. 多环境需要维护多份文件**

```
k8s/dev/      ← 开发环境（1 副本，小内存）
k8s/staging/  ← 测试环境（2 副本）
k8s/prod/     ← 生产环境（3 副本，大内存）
```

三份文件内容 90% 相同，改一个配置要同步改三个地方，容易遗漏。

#### Helm 的 Release 概念解决了这些问题

Helm 每次 `helm install` 都被记录为一个有版本的整体：

```
helm install modular-rag ./helm/modular-rag/
  → Release v1 被记录：
    - 包含哪些资源（namespace + configmap + 3个deployment...）
    - 用了什么 values
    - 时间戳

helm upgrade modular-rag ./helm/modular-rag/ --set dashboard.replicas=3
  → Release v2 被记录

helm rollback modular-rag 1
  → 一条命令回到 v1

helm uninstall modular-rag
  → 自动删除所有相关资源，不会漏
```

#### 完整对比

| | kubectl apply | helm |
|--|--------------|------|
| **一次 apply 所有文件** | ✓（`-f 目录` 或 `-k`） | ✓ |
| **知道这批资源是一组的** | ✗ | ✓（Release） |
| **版本历史** | ✗ | ✓ |
| **一条命令回滚** | ✗ | ✓ |
| **一条命令完整卸载** | 需手动记住所有资源 | ✓ |
| **多环境（不重复写配置）** | 需维护多份 YAML | ✓（values 文件） |
| **用别人写好的配置** | ✗ | ✓（Helm 仓库） |

#### 什么时候选 Helm

```
满足以下任意一条 → 用 Helm，否则 kubectl apply 足够：

1. 需要多环境（dev/staging/prod 配置不同）
2. 需要频繁升级，且要求能快速回滚
3. 想直接用社区维护的现成 Chart（如 bitnami/redis）
4. 团队多人协作，需要统一管理部署历史
```

---

### 如何理解"Helm 是 K8s 的包管理器"？

类比 Python 的 pip：

```
pip install requests      → 下载 requests 包，帮你装好所有依赖
helm install modular-rag  → 下载 Chart 包，帮你在 K8s 里创建所有资源
```

#### 没有包管理器时

假设你要在 K8s 里部署一套 Prometheus 监控：

```bash
# 要手动一个个 apply 几十个文件
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
kubectl apply -f rbac.yaml
kubectl apply -f deployment.yaml
# ... 还有几十个
```

升级版本时，不知道哪些文件变了，手动对比容易出错。卸载时，不知道当初创建了哪些资源，容易漏删。

#### 有了 Helm

```bash
# 安装
helm install prometheus prometheus-community/prometheus

# 升级
helm upgrade prometheus prometheus-community/prometheus --version 2.0.0

# 卸载（自动清理所有相关资源）
helm uninstall prometheus
```

Helm 帮你记住了：这次安装创建了哪些资源、用了什么配置、是第几个版本。

#### 包管理器的三个核心能力

| 能力 | pip 怎么做 | Helm 怎么做 |
|------|-----------|------------|
| **安装** | `pip install requests` | `helm install myapp ./chart` |
| **版本管理** | `pip install requests==2.0` | `helm upgrade` / `helm rollback` |
| **卸载** | `pip uninstall requests` | `helm uninstall`（清理所有 K8s 资源） |
| **依赖管理** | `requirements.txt` | `Chart.yaml` 里的 `dependencies` |
| **公共仓库** | PyPI | Artifact Hub（helm.sh/hub） |

#### Helm 公共仓库 —— 真正体现"包管理器"的地方

Helm 有公共仓库，别人打包好的 Chart 可以直接用：

```bash
# 添加官方仓库
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add bitnami https://charts.bitnami.com/bitnami

# 搜索包
helm search repo redis

# 直接安装别人做好的 Chart（不需要自己写一行 YAML）
helm install my-redis bitnami/redis
helm install my-kafka bitnami/kafka
```

**这才是包管理器最大的价值** —— 不需要自己写 ChromaDB 的 K8s 配置，直接 `helm install chromadb ...` 就能用社区维护好的最佳实践配置。

---

## 第五部分：古法部署 vs Docker vs K8s —— 三种方式如何选择

### 三种部署方式是什么

| 方式 | 本质 | 一句话描述 |
|------|------|-----------|
| **古法部署** | 直接在操作系统上运行 | `python main.py`、`systemctl`、手动装依赖 |
| **Docker** | 应用级别的隔离和打包 | 把代码+依赖+环境封装成镜像，一键运行 |
| **Kubernetes** | 集群级别的容器编排 | 在多台机器上自动管理、调度、恢复容器 |

### 古法部署（直接运行）

**优势：**
- 零学习成本，直接 `python xxx.py` 就能跑
- 没有任何中间层，性能最好、调试最方便
- 不需要安装 Docker 或任何额外工具

**适合的场景：**
- 个人开发、学习、快速验证想法
- 只有一个服务、一台机器
- 团队所有人环境一致（比如都用同一台开发服务器）
- 性能敏感场景（容器有微小的网络/IO 开销）
- 嵌入式设备、边缘计算等资源极度受限的环境

**该换方案的信号：**
- "在我机器上能跑" 开始频繁出现
- 新人入职搭环境要半天以上
- 部署靠一份 Word 文档记录步骤，经常漏步骤
- 同一台机器上的不同项目依赖版本冲突

### Docker / Docker Compose

**优势：**
- 环境一致性 — 开发、测试、部署用完全相同的环境
- 一键启动 — `docker compose up` 启动整套服务
- 隔离干净 — 项目间互不干扰，用完即弃
- 交付标准化 — 给别人一个镜像就能跑，不需要安装指南

**适合的场景：**
- 团队开发，需要统一环境
- 2-5 个服务的中小型应用
- 单机或少量服务器（1-3 台）部署
- 需要快速搭建 / 销毁测试环境
- CI/CD 中跑测试（干净隔离，用完即弃）

**该换方案的信号：**
- 服务挂了没人发现，需要手动重启
- 单机扛不住，需要跨多台机器部署
- 需要频繁扩缩容应对流量波动
- 更新版本时需要停机

### Kubernetes

**优势：**
- 自动恢复 — 容器挂了自动重启，节点挂了自动迁移
- 弹性伸缩 — 根据流量自动增减副本数
- 零停机更新 — 滚动更新，用户无感知
- 多机调度 — 自动选择最优节点部署
- 生态丰富 — 监控、日志、证书管理等开箱即用

**适合的场景：**
- 服务不能挂（需要高可用、自动恢复）
- 用户量会波动（需要弹性扩缩容）
- 微服务架构（>5 个服务，服务间调用复杂）
- 多环境管理（dev / staging / prod 用同一套配置模板）
- 团队有专职运维，或使用云厂商托管 K8s（AKS、EKS、GKE）

**不适合的场景：**
- 团队没人懂 K8s，运维成本反而比收益高
- 只有 1-2 个服务，用 K8s 是大炮打蚊子
- 预算有限（K8s 控制平面本身消耗 2-4GB 内存）

### 快速决策流程图

```
你的应用有几个服务？
  │
  ├── 1 个，自己用 ──────────────────────► 古法部署
  │
  ├── 1-5 个，小团队 ───► 需要高可用吗？
  │                         ├── 不需要 ──► Docker Compose
  │                         └── 需要 ────► Kubernetes
  │
  └── >5 个，多团队 ─────────────────────► Kubernetes
```

另一个角度 —— 按团队规模：

```
1 人开发           → 古法部署 或 Docker
2-5 人团队         → Docker Compose
5-20 人 + 运维     → Kubernetes
20+ 人 / 多团队    → Kubernetes + GitOps（ArgoCD）
```

### 选择决策表（完整版）

| 场景 | 推荐方案 | 原因 |
|------|---------|------|
| 个人学习/实验 | **古法部署** | 零成本，专注业务逻辑 |
| 个人项目/Demo | **Docker Compose** | 环境一致，方便分享 |
| 本地开发/调试 | **Docker Compose** | 轻量快速，改完重启即可 |
| CI/CD 跑测试 | **Docker** | 干净隔离，用完销毁 |
| 1-3 台服务器部署 | **Docker Compose** | K8s 运维成本大于收益 |
| 需要高可用（不能挂） | **Kubernetes** | 自动恢复 + 多副本 |
| 用户量会增长 | **Kubernetes** | 弹性扩缩容 |
| 微服务架构（>5 个服务） | **Kubernetes** | 统一管理服务发现、负载均衡 |
| 多环境（dev/staging/prod） | **Kubernetes + Helm** | 同一套模板，不同 values 文件 |
| 多团队共享基础设施 | **Kubernetes + GitOps** | 统一管控、审计、自动化 |

### 核心原则：不要过度工程化

**一句话决策：**
```
能直接跑就直接跑 → 环境不一致了上 Docker → 需要高可用和弹性了上 K8s
```

复杂度应该匹配实际需求。过早引入 K8s 的团队，往往花更多时间在运维 K8s 本身，而不是业务开发。

### 渐进式演进路径（推荐）

大多数项目不需要一开始就上 K8s，推荐的演进路线：

```
阶段 1：古法部署
  python scripts/start_dashboard.py
  ↓ 团队协作，环境不一致

阶段 2：Docker Compose（← 本项目当前处于这个阶段）
  docker compose up -d
  ↓ 用户增长，需要高可用和弹性

阶段 3：Kubernetes
  helm install modular-rag ./helm/modular-rag/
  ↓ 多团队多项目共享集群

阶段 4：Kubernetes + GitOps
  git push → ArgoCD 自动同步部署
```

### 本项目的建议

对于 Modular RAG MCP Server：

- **现阶段**：用 Docker Compose 进行开发和小规模部署
- **未来上生产**：K8s 清单和 Helm Chart 已经准备好，可以直接切换
- **不需要二选一**：三种方式的配置可以共存，适配不同场景

---

## 补充：ArgoCD — GitOps 持续部署工具

### ArgoCD 是什么，解决什么问题？

传统 CI/CD（GitHub Actions / GitLab CI）确实能触发部署，但有一个根本缺陷：

> **"部署完之后，集群的状态还和 Git 一致吗？"**
> 流水线结束就走了，之后集群发生什么，CI 完全不知道。

**这就导致了"配置漂移"问题：**

```
Git 里写的（期望状态）       集群实际运行的状态
─────────────────────       ─────────────────────
replicas: 3                 replicas: 1   ← 有人手动 kubectl 改了
image: v1.0                 image: v2.0-hotfix ← 紧急修复直接改的
mcp-server: 开着             mcp-server: 关着  ← 临时关掉忘了开回来
```

没有告警，没有人知道。团队越大、集群越多，这类问题越频繁。

**ArgoCD 的解法：让 Git 成为集群状态的唯一真相，任何偏离都立刻被发现。**

```
没有 ArgoCD：
  周五运维直接 kubectl 改了集群
  周一早上没人知道集群和 Git 不一致，也许永远不会发现

有了 ArgoCD：
  周五运维直接 kubectl 改了集群
  30秒后 ArgoCD 发现：集群实际状态 ≠ Git 期望状态
  → 自动修复回 Git 的状态，或者发告警让人处理
  → 界面上清楚显示哪些资源"漂移"了
```

---

### 用类比理解：装修工人 vs 物业管理员

```
GitHub Actions 是"装修工人"：
  你发指令（push 代码）→ 工人来施工 → 施工完走人
  有人后来偷偷把墙漆改了？工人不知道，下次才会重新施工

ArgoCD 是"物业管理员"：
  合同里写好房间应该是什么样（Git 里的配置）
  管理员 24 小时住在楼里，不断巡逻对比合同和实际
  有人偷偷改了？立刻发现，自动改回来或发告警
```

```
GitHub Actions：  "代码变了，我去部署一次"    （事件驱动，部署完就走）
ArgoCD：         "集群必须和 Git 保持一致"    （持续保障，永远在岗）
```

---

### GitHub Actions vs ArgoCD 完整对比

| | GitHub Actions / GitLab CI | ArgoCD |
|--|---------------------------|--------|
| **定位** | CI + CD 工具（通用） | 专职 CD 工具（K8s 专属） |
| **运行位置** | GitHub 服务器（外部） | K8s 集群内部 |
| **触发方式** | push 事件触发 | 持续轮询 Git（每 3 分钟） |
| **部署方式** | 主动推送（Push-based） | 自动拉取（Pull-based） |
| **集群访问** | 需要把 K8s 凭证给 CI/CD | 不需要，ArgoCD 在集群里 |
| **状态感知** | 不知道集群当前状态 | 实时对比 Git 期望 vs 集群实际 |
| **漂移检测** | ✗ | ✓（有人手动改了集群会告警/自动修复） |
| **回滚** | 重新跑流水线 | git revert 即可 |

**一句话：GitHub Actions 管"怎么构建和部署"，ArgoCD 管"部署后状态是否一直正确"。**

---

### 什么时候需要 ArgoCD？

```
"我能保证所有人都只通过 Git 改集群，没有人会直接 kubectl 改生产吗？"
  是 → 传统 CI/CD 够用
  否 → 需要 ArgoCD 来兜底
```

| 场景 | 推荐 |
|------|------|
| 小团队（≤3人），大家都遵守规范 | 传统 CI/CD |
| 单集群，部署频率低 | 传统 CI/CD |
| 团队大，无法约束所有人通过 Git 改集群 | ArgoCD |
| 多集群（dev/staging/prod）统一管控 | ArgoCD |
| 合规/审计要求，必须追踪每次变更 | ArgoCD |
| 安全要求，不想把 K8s 凭证暴露给外部 CI | ArgoCD |
| 金融、医疗等对配置漂移零容忍的系统 | ArgoCD |

---

### ArgoCD 是 K8s 专属的吗？

**是的**，ArgoCD 本身运行在 K8s 里，监控的是 K8s 资源（Deployment、Service、ConfigMap 等），离开 K8s 就没有意义。

```
ArgoCD 依赖 K8s 的：
  - K8s API  → 读取集群实际状态
  - K8s CRD  → ArgoCD 自己的配置也存在 K8s 里
  - K8s RBAC → 权限控制
```

其他部署方式的对应 CD 工具：

| 部署方式 | CD 工具 |
|---------|--------|
| K8s | **ArgoCD**、FluxCD |
| 普通服务器（古法部署） | Ansible、Capistrano |
| Docker Compose | Watchtower（自动更新镜像） |
| 云平台（AWS/Azure） | 各云厂商自带部署服务 |

---

### ArgoCD 监控的是哪个仓库？

**ArgoCD 监控"K8s 配置目录"，不监控应用代码。**

通过 `Application` 资源声明监控哪个仓库的哪个目录：

```yaml
# argocd-application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: modular-rag
spec:
  source:
    repoURL: https://github.com/yourname/modular-rag-mcp-server
    targetRevision: main
    path: k8s/base          # ← ArgoCD 只监控这个目录
    # Helm 项目则写：path: helm/modular-rag
  destination:
    server: https://kubernetes.default.svc
    namespace: modular-rag
  syncPolicy:
    automated:
      prune: true       # Git 删了，集群也删
      selfHeal: true    # 集群漂移了，自动修复
```

**两种常见仓库组织方式：**

```
方式 A（同一个仓库，适合小团队）：
  modular-rag-mcp-server/
  ├── src/            ← 应用代码（GitHub Actions 关心，ArgoCD 不关心）
  ├── k8s/base/       ← ArgoCD 监控这里
  └── helm/           ← 或者这里

方式 B（分两个仓库，适合大团队）：
  modular-rag-mcp-server/   ← 代码仓库（GitHub Actions 监控）
  modular-rag-gitops/       ← 配置仓库（ArgoCD 监控，单独管权限）
    └── k8s/base/
```

---

### 代码改了，ArgoCD 不监控代码，部署会被遗漏吗？

**不会——CI 作为"桥梁"，把代码变化翻译成配置变化，再由 ArgoCD 响应。**

完整链路：

```
开发者 push 代码
       ↓
GitHub Actions（CI）触发：
  1. 运行测试
  2. docker build → 构建新镜像
  3. docker push  → 推送到镜像仓库（GHCR/DockerHub）
  4. 自动修改配置文件里的镜像 tag：
       image: ghcr.io/yourname/modular-rag:v1.2.3  ← 从旧 tag 改为新 tag
  5. git commit + git push → 把这个配置变更提交回 Git
       ↓
ArgoCD 检测到 k8s/base/ 的配置文件发生了变化：
  → 发现 image tag 从 v1.2.2 变成了 v1.2.3
  → 自动滚动更新：新 Pod 用新镜像启动，旧 Pod 逐步下线
```

**CI 更新 image tag 的具体写法（本项目 GitHub Actions）：**

```yaml
- name: Update image tag in k8s config
  run: |
    sed -i "s|image: ghcr.io/yourname/modular-rag:.*|image: ghcr.io/yourname/modular-rag:${{ github.sha }}|g" \
      k8s/base/mcp-server-deployment.yaml
    git add k8s/base/mcp-server-deployment.yaml
    git commit -m "ci: update image tag to ${{ github.sha }}"
    git push
    # 也可以用 kustomize edit set image 或 helm-updater 工具
```

**职责分工总结：**

| | GitHub Actions（CI） | ArgoCD（CD） |
|--|---------------------|-------------|
| 监控什么 | 代码仓库的 push 事件 | Git 配置目录的变化 |
| 做什么 | 测试 → 构建镜像 → **更新配置文件 image tag** | 检测配置变化 → 同步到 K8s |
| 运行位置 | GitHub 服务器 | K8s 集群内部 |

> **一句话：代码变化 → CI 构建镜像并更新配置 → ArgoCD 检测配置变化 → 部署到 K8s。
> CI 是桥梁，把"代码变了"翻译成"配置变了"，ArgoCD 只响应配置层面的变化。**

---

## 第六部分：本项目部署操作手册

### 前置条件

| 工具 | 用途 | 安装方式 |
|------|------|---------|
| Docker Desktop | 构建镜像、运行容器 | https://www.docker.com/products/docker-desktop/ |
| kubectl | 操作 K8s 集群（K8s 部署时需要） | `choco install kubernetes-cli` 或 Docker Desktop 自带 |
| Helm | K8s 包管理（Helm 部署时需要） | `choco install kubernetes-helm` |

### 方式一：Docker Compose 部署（推荐开发/小规模使用）

#### 步骤 1：构建镜像

```bash
# 在项目根目录执行
docker build -t modular-rag:latest .
```

首次构建需要下载基础镜像和安装依赖，约 5-15 分钟（取决于网速）。
后续构建有缓存，通常 30 秒内完成。

#### 步骤 2：配置环境变量

```bash
# 创建 .env 文件（不会被 git 提交）
cp .env.example .env   # 如果有模板的话

# 或者手动创建，写入你的 API key：
echo "AZURE_OPENAI_API_KEY=your-key-here" > .env
echo "OPENAI_API_KEY=your-key-here" >> .env
```

#### 步骤 3：启动全部服务

```bash
docker compose up -d
```

预期输出：
```
Container modular-rag-chromadb   Started
Container modular-rag-chromadb   Healthy
Container modular-rag-dashboard  Started
Container modular-rag-mcp-server Started
```

#### 步骤 4：验证服务状态

```bash
# 查看所有容器状态
docker compose ps

# 预期：3 个容器全部 running，chromadb 和 dashboard 显示 healthy
# NAME                     STATUS                  PORTS
# modular-rag-chromadb     Up (healthy)            0.0.0.0:8000->8000/tcp
# modular-rag-dashboard    Up (healthy)            0.0.0.0:8501->8501/tcp
# modular-rag-mcp-server   Up                      8501/tcp
```

#### 步骤 5：访问服务

- **Dashboard**：浏览器打开 http://localhost:8501
- **ChromaDB API**：http://localhost:8000/api/v2/heartbeat （返回心跳时间戳表示正常）

#### 日常操作

```bash
# 查看实时日志
docker compose logs -f              # 全部服务
docker compose logs -f dashboard    # 只看 Dashboard

# 重启单个服务（修改配置后）
docker compose restart dashboard

# 停止全部服务（保留数据）
docker compose down

# 停止并清除数据（重新开始）
docker compose down -v

# 重新构建（修改代码后）
docker compose up -d --build
```

#### 排错指南

```bash
# 容器启动失败？查看日志
docker compose logs <服务名>

# 容器里执行命令（进入容器排查）
docker exec -it modular-rag-dashboard bash

# ChromaDB 一直 unhealthy？
docker logs modular-rag-chromadb    # 看是否启动报错
docker exec modular-rag-chromadb bash -c 'echo > /dev/tcp/localhost/8000'  # 手动测试端口

# 镜像构建失败？清理缓存重新构建
docker build --no-cache -t modular-rag:latest .

# 端口被占用？
# Windows: netstat -ano | findstr :8501
# 然后修改 docker-compose.yml 中的端口映射，如 "8502:8501"
```

---

### 方式二：Kubernetes 部署（Kustomize）

> 需要先有一个 K8s 集群。本地可用 Docker Desktop 自带的 K8s（Settings → Kubernetes → Enable）。

#### 步骤 1：修改配置

```bash
# 1. 编辑 Secret，填入真实的 API key
vim k8s/base/secret.yaml
# 将 REPLACE_ME 替换为你的实际 key

# 2. 编辑 ConfigMap（可选，调整 RAG 配置）
vim k8s/base/configmap.yaml

# 3. 编辑 Ingress（可选，修改域名）
vim k8s/base/ingress.yaml
# 将 rag-dashboard.example.com 改为你的域名
```

#### 步骤 2：确保镜像可用

```bash
# 本地开发：先构建镜像
docker build -t modular-rag:latest .

# 生产环境：推送到镜像仓库后，修改 deployment 中的 image 字段
```

#### 步骤 3：部署

```bash
# 预检（不实际创建，只检查语法）
kubectl apply -k k8s/base/ --dry-run=client

# 正式部署
kubectl apply -k k8s/base/
```

#### 步骤 4：验证

```bash
# 查看所有资源
kubectl get all -n modular-rag

# 查看 Pod 状态（等待全部 Running）
kubectl get pods -n modular-rag -w

# 查看 Pod 日志
kubectl logs -n modular-rag -l app.kubernetes.io/name=dashboard
kubectl logs -n modular-rag -l app.kubernetes.io/name=chromadb

# 端口转发到本地访问（不需要 Ingress）
kubectl port-forward -n modular-rag svc/dashboard 8501:8501
# 然后浏览器打开 http://localhost:8501
```

#### 日常操作

```bash
# 扩缩容
kubectl scale deployment dashboard -n modular-rag --replicas=3

# 更新镜像版本
kubectl set image deployment/dashboard dashboard=modular-rag:v2 -n modular-rag

# 查看滚动更新状态
kubectl rollout status deployment/dashboard -n modular-rag

# 回滚到上一个版本
kubectl rollout undo deployment/dashboard -n modular-rag

# 删除全部资源
kubectl delete -k k8s/base/
```

---

### 方式三：Kubernetes 部署（Helm）

#### 步骤 1：预览渲染结果

```bash
# 查看 Helm 会生成什么 YAML（不实际部署）
helm template modular-rag ./helm/modular-rag/
```

#### 步骤 2：部署

```bash
# 基础部署
helm install modular-rag ./helm/modular-rag/

# 带参数部署（推荐）
helm install modular-rag ./helm/modular-rag/ \
  --set secrets.azureOpenaiApiKey="your-key" \
  --set secrets.openaiApiKey="your-key" \
  --set ingress.enabled=true \
  --set ingress.host="rag.yourcompany.com"

# 生产环境（多副本 + 自定义资源）
helm install modular-rag ./helm/modular-rag/ \
  --set dashboard.replicas=3 \
  --set chromadb.persistence.size=50Gi \
  --set secrets.azureOpenaiApiKey="your-key"
```

#### 步骤 3：验证

```bash
# 查看部署状态
helm status modular-rag

# 查看 Pod
kubectl get pods -n modular-rag

# 端口转发测试
kubectl port-forward -n modular-rag svc/modular-rag-dashboard 8501:8501
```

#### 日常操作

```bash
# 修改配置后升级
helm upgrade modular-rag ./helm/modular-rag/ \
  --set dashboard.replicas=2

# 查看历史版本
helm history modular-rag

# 回滚到指定版本
helm rollback modular-rag 1

# 卸载（删除所有资源）
helm uninstall modular-rag

# 卸载但保留 PVC（保留 ChromaDB 数据）
helm uninstall modular-rag --keep-history
```

---

### 三种部署方式命令速查

| 操作 | Docker Compose | K8s (Kustomize) | K8s (Helm) |
|------|---------------|-----------------|------------|
| 部署 | `docker compose up -d` | `kubectl apply -k k8s/base/` | `helm install modular-rag ./helm/modular-rag/` |
| 查看状态 | `docker compose ps` | `kubectl get pods -n modular-rag` | `helm status modular-rag` |
| 查看日志 | `docker compose logs -f` | `kubectl logs -n modular-rag <pod>` | 同 Kustomize |
| 停止/删除 | `docker compose down` | `kubectl delete -k k8s/base/` | `helm uninstall modular-rag` |
| 更新 | `docker compose up -d --build` | `kubectl apply -k k8s/base/` | `helm upgrade modular-rag ./helm/modular-rag/` |
| 回滚 | 手动切镜像版本 | `kubectl rollout undo` | `helm rollback modular-rag 1` |
| 扩容 | 不支持 | `kubectl scale --replicas=3` | `--set dashboard.replicas=3` |
| 访问 Dashboard | http://localhost:8501 | `kubectl port-forward svc/dashboard 8501:8501` | 同 Kustomize |

---

## 附录：构建验证中遇到的实际问题

在本项目容器化过程中遇到并修复的问题，作为经验记录：

| 问题 | 原因 | 修复 |
|------|------|------|
| Dockerfile 构建失败 | `pip install .` 需要 README.md（pyproject.toml 声明了 readme） | COPY 时加上 `README.md` |
| ChromaDB 健康检查失败 (curl) | ChromaDB 官方镜像不包含 `curl` | 改用其他检查方式 |
| ChromaDB 健康检查失败 (python) | ChromaDB 官方镜像的 Python 不在 PATH 中 | 改用 `bash -c 'echo > /dev/tcp/localhost/8000'` |
| ChromaDB 数据目录不对 | 官方镜像默认持久化目录是 `/data` 而非 `/chroma/chroma` | 查看容器日志确认实际路径后修正 |
