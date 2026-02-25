# Engrama 使用教程与操作指南 (How-to Guides)

> 本文档基于 Diátaxis 体系构建，旨在为您提供详细的“怎么做（How-to）”指导和端到端的示例。
> 如果您想了解项目的架构或进行快速部署，请参阅主 [README.md](./README.md)。

---

## 目录

1. [如何通过 REST API 接入](#1-如何通过-rest-api-接入)
2. [如何通过 MCP 接入 AI 助手](#2-如何通过-mcp-接入-ai-助手)
3. [理解并配置三层隔离模型](#3-理解并配置三层隔离模型)
4. [高级测试与数据隔离策略](#4-高级测试与数据隔离策略)

---

## 1. 如何通过 REST API 接入

Engrama 提供了基础的 REST API 供您的后端服务调用。调用任何记忆 API 之前，都必须先进行租户注册和 API Key 申请。

### 1.1 初始化渠道与获取 API Key

**准备工作**：确保服务启动，并获取了管理员 Token（定义于 `.env` 文件中的 `ENGRAMA_ADMIN_TOKEN`）。

```bash
# 步骤 1：注册你的企业/组织（Tenant）
curl -X POST http://localhost:8000/v1/channels/tenants \
  -H "X-Admin-Token: your_super_secret_token_here" \
  -H "Content-Type: application/json" \
  -d '{"name": "我的玄学科技公司"}'
# 返回示例: {"id": "tenant_12345", "name": "我的玄学科技公司", ...}

# 步骤 2：为你的产品创建一个项目（Project）
curl -X POST http://localhost:8000/v1/channels/projects \
  -H "X-Admin-Token: your_super_secret_token_here" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "tenant_12345", "name": "八字算命 AI 助手"}'
# 返回示例: {"id": "proj_67890", ...}

# 步骤 3：生成用于调用的 API Key
# 💡 提示：如果不传 user_id，这是一个“项目级密钥”（B端）；传了 user_id 就是特定的“用户级密钥”（C端）。
curl -X POST http://localhost:8000/v1/channels/api-keys \
  -H "X-Admin-Token: your_super_secret_token_here" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "tenant_12345", "project_id": "proj_67890"}'
# 会返回一长串 eng_xxxx 的 Key，请妥善保管！
```

### 1.2 储存与搜索记忆

拿到 `eng_xxxx` 密钥后，你就可以脱离 Admin 身份，开始纯粹的记忆存取了：

**储存一条喜好（Preference）**:
```bash
curl -X POST http://localhost:8000/v1/memories \
  -H "X-API-Key: eng_xxxxxxxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_apple_001", 
    "content": "我特别喜欢在早上喝黑咖啡", 
    "memory_type": "preference"
  }'
```

**利用大模型语义进行搜索**:
```bash
curl -X POST http://localhost:8000/v1/memories/search \
  -H "X-API-Key: eng_xxxxxxxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_apple_001", 
    "query": "用户早上的饮食习惯是什么？"
  }'
# Engrama 会通过 TEI embedding 进行向量相似度匹配，精准返回黑咖啡的记忆。
```

---

## 2. 如何通过 MCP 接入 AI 助手

这是 Engrama 最强大的原生协同方式：直接把记忆引擎挂载给各大 AI Agent（如 Claude Desktop 或 Cursor），让 AI 自己决定什么时候存记忆、什么时候搜记忆。

### 场景 A：客户端直连模式（C 端专属）

在这个模式下，每个人/设备分配一把自己的 API Key（带有固定的 `user_id`），直接启动 `stdio` 进行传输：

```bash
# 在终端或 App 的守护进程中直接拉起 MCP
ENGRAMA_API_KEY=eng_xxx_个人版 python -m mcp_server
```

**在 Cursor 中的配置** (`.cursor/mcp.json`)：
```json
{
  "mcpServers": {
    "engrama": {
      "command": "/绝对路径/engrama/.venv/bin/python",
      "args": ["-m", "mcp_server"],
      "env": {
        "ENGRAMA_API_KEY": "eng_xxxx_个人专属Key"
      }
    }
  }
}
```

### 场景 B：服务端代理模式（B 端集成）

如果是作为整个服务的统一基座，使用**项目级 API Key**，这需要通过环境变量指派当前的上下文用户：

```bash
# 启动时注入用户 ID，告诉 MCP Server “这轮对话是服务于谁的”
ENGRAMA_API_KEY=eng_超级项目Key ENGRAMA_USER_ID=user_2046 python -m mcp_server
```

---

## 3. 理解并配置三层隔离模型

Engrama 在底层强制实行数据隔离，数据不可跨级读取：

```text
Tenant（租户：企业 / 个人开发者）
  └── Project（项目：酒店 AI / 客服 AI）
       └── User（用户：张三 / 李四）
            └── Memory Fragment（记忆片段）
```

* **Tenant (租户)**：最顶层。适用于 SaaS 平台化，即便两个租户的项目名一致，数据和请求也完全隔绝。
* **Project (项目)**：第二层。同一个公司（租户）下，可能有“客服助手”和“代码助手”。这两者的记忆（Collection 点位）通过 Payload `project_id` 完全隔离。
* **User (用户)**：最底层。属于同一个项目的两个不同的真实人类对话者。

### 🚨 数据安全警告（API Key 分级）
1. **项目级 Key**：权限巨大，由于没有绑定终端用户，调用方必须在每次涉及 `/v1/memories` 接口时手动传入 `user_id`。如果写错，会导致用户 A 读到用户 B 的数据。
2. **用户级 Key**：极度安全。签发时便死死绑定了 `user_id`。持有这把钥匙的客户端在发请求时**可以不传、甚至瞎传** `user_id`，引擎底层拦截器会无视传参，强制将其指向绑定的真实身份，从根源上杜绝越权（IDOR）。

---

## 4. 高级测试与数据隔离策略

开发修改代码时，测试绝不能污染生产库数据。我们已经引入了顶级的隔离规范。

### 环境准备

请参考 `.env.example.test`，确保测试参数如下指向：
1. 你的 PostgreSQL URI 后缀是 `_test`（例如 `long_term_memory_test`）。
2. Qdrant 的 Collection 指定为 `test_memories`。
3. Redis 的数据库选择为 `/1`。

### 开启无痛测试

平时开发时，绝对不要直接用 `pytest` 裸跑！必须显式声明环境变量解锁：

```bash
# 这会触发隔离逻辑并在安全的库上跑，保护生产数据
ENGRAMA_ENV=test pytest
```

如果不带这个后缀，程序将探测到你在尝试执行破坏性数据清理操作并**强制抛异常熔断**，保护你的业务数据库。
