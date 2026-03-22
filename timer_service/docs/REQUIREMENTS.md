# TimerService — 需求文档

## 1. 项目概述

TimerService 是一个基于 Python/Flask 的 RESTful 定时通知服务。用户可通过 REST API 或 Web 界面注册定时任务，到时由服务主动通知客户端。

---

## 2. 功能需求

### 2.1 用户认证

| 编号 | 需求 | 优先级 |
|------|------|--------|
| F-AUTH-01 | 用户可通过用户名/密码注册账户 | 高 |
| F-AUTH-02 | 用户名长度 3–80 字符，密码至少 8 字符 | 高 |
| F-AUTH-03 | 用户名在系统内唯一 | 高 |
| F-AUTH-04 | 用户可使用账户密码登录，同时获取 access_token（24小时）和 refresh_token（30天） | 高 |
| F-AUTH-05 | access_token 过期后，客户端可用 refresh_token 换取新的 access_token，无需重新登录 | 中 |
| F-AUTH-06 | Web 控制台在收到 401 响应时自动刷新 token，用户无感知 | 中 |

### 2.2 一次性定时器（One-time Timer）

| 编号 | 需求 | 优先级 |
|------|------|--------|
| F-OT-01 | 用户可创建一次性定时器，设置延迟时间（单位：秒） | 高 |
| F-OT-02 | 延迟时间范围：1 秒 ~ 86400 秒（24 小时） | 高 |
| F-OT-03 | 定时器到时后触发一次通知，随后状态变为 `fired` | 高 |
| F-OT-04 | 定时器到时后不再触发 | 高 |

### 2.3 每日定时器（Daily Timer）

| 编号 | 需求 | 优先级 |
|------|------|--------|
| F-DL-01 | 用户可创建每日定时器，设置触发时间（HH:MM，UTC） | 高 |
| F-DL-02 | 定时器每天在指定时间触发一次通知 | 高 |
| F-DL-03 | 每日定时器触发后状态保持 `active`，等待下次触发 | 高 |
| F-DL-04 | 服务重启后，每日定时器自动恢复调度 | 中 |

### 2.4 通知机制

| 编号 | 需求 | 优先级 |
|------|------|--------|
| F-NOTIF-01 | 支持 SSE（Server-Sent Events）实时推送；客户端建立长连接，定时器触发时收到事件 | 高 |
| F-NOTIF-02 | 支持 Webhook 回调；用户可为定时器配置回调 URL，触发时 POST JSON 到该 URL | 中 |
| F-NOTIF-03 | Webhook 请求超时为 5 秒，失败不重试，结果记录在数据库 | 中 |
| F-NOTIF-04 | SSE 连接保持心跳（每 15 秒发送一次 keep-alive 注释） | 低 |

### 2.5 定时器管理

| 编号 | 需求 | 优先级 |
|------|------|--------|
| F-MGMT-01 | 用户可查看自己的所有定时器（支持按状态过滤） | 高 |
| F-MGMT-02 | 用户可查看单个定时器的详情，包括历史触发记录 | 中 |
| F-MGMT-03 | 用户可取消（删除）一个进行中的定时器 | 高 |
| F-MGMT-04 | 用户只能看到和操作自己创建的定时器 | 高（安全） |
| F-MGMT-05 | 用户可查询自己所有定时器的全部触发历史，支持按 timer_id 过滤 | 中 |

### 2.6 Web 界面

| 编号 | 需求 | 优先级 |
|------|------|--------|
| F-WEB-01 | 提供注册/登录页面 | 高 |
| F-WEB-02 | 提供控制台页面，显示用户的所有定时器及其状态 | 高 |
| F-WEB-03 | 控制台页面支持创建定时器（表单） | 高 |
| F-WEB-04 | 控制台页面通过 SSE 实时展示定时器触发通知（无需刷新页面） | 高 |
| F-WEB-05 | 控制台页面支持取消定时器 | 中 |

---

## 3. 非功能需求

| 编号 | 需求 | 说明 |
|------|------|------|
| NF-01 | 安全性 | 所有 API 接口需要 JWT 认证；用户数据严格隔离 |
| NF-02 | 可靠性 | 服务重启后自动恢复所有激活的定时器调度 |
| NF-03 | 可测试性 | 关键模块有单元/集成测试，覆盖率不低于 80% |
| NF-04 | 可扩展性 | 调度器与通知模块解耦，便于后续扩展（如邮件通知） |
| NF-05 | 时区 | 所有时间统一使用 UTC，前端展示时说明 |

---

## 4. 约束条件

- 语言：Python 3.11+
- 框架：Flask 3.x
- 数据库：SQLite（开发/测试），可配置为其他 SQLAlchemy 支持的数据库
- 调度器：APScheduler 3.x
- 认证：JWT（flask-jwt-extended）

---

## 5. 定时器状态机

```
创建 ──► active ──► fired      （一次性定时器到时）
              └──► cancelled   （用户手动取消）
              │
              └──► active      （每日定时器触发后仍保持 active）
```

---

## 6. API 接口一览

| 方法 | 路径 | 描述 | 认证 |
|------|------|------|------|
| POST | /api/auth/register | 用户注册 | 无 |
| POST | /api/auth/login | 用户登录，返回 access_token + refresh_token | 无 |
| POST | /api/auth/refresh | 刷新 access_token | refresh_token |
| POST | /api/timers | 创建定时器 | JWT |
| GET | /api/timers | 列出我的定时器 | JWT |
| GET | /api/timers/{id} | 查看定时器详情（含触发记录） | JWT |
| DELETE | /api/timers/{id} | 取消定时器 | JWT |
| GET | /api/timers/events | 查询所有触发历史（支持 ?timer_id= 过滤） | JWT |
| GET | /api/timers/stream | SSE 实时通知流 | JWT (query param) |

---

## 7. Webhook 请求格式

定时器触发时，向 `webhook_url` 发送如下 POST 请求：

```json
{
  "timer_id": 42,
  "timer_name": "My Daily Report",
  "fired_at": "2026-03-21T09:30:00",
  "timer_type": "daily"
}
```
