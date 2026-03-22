# TimerService — 用户手册

## 快速开始

### 1. 安装依赖

```bash
cd timer_service
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python run.py
```

服务默认监听 `http://localhost:5000`

---

## Webhook 完整使用流程

Webhook 需要你有一个**能接收 HTTP 请求的服务器**。项目自带了一个示例接收服务器 `webhook_receiver.py`。

### 什么时候需要用 Webhook

以下场景适合使用 Webhook：

| 场景 | 举例 |
|------|------|
| 定时器触发后需要自动执行业务逻辑 | 到期自动发邮件、推钉钉/企业微信消息 |
| 系统之间的自动对接 | 定时触发另一个系统的接口，比如定时拉取数据、定时生成报表 |
| 用户不在线时也要处理 | 浏览器关掉后 SSE 断开，但 Webhook 仍然能送达你的服务器 |
| 需要保留触发记录做后续处理 | 接收服务器将每次触发写入数据库，供后续审计或统计 |

> 如果只是在浏览器里看通知，用 SSE 就够了，`webhook_url` 留空即可。

### 第一步：同时启动两个服务

```bash
# 终端 1：启动 TimerService（主服务）
python run.py

# 终端 2：启动 Webhook 接收服务器
python webhook_receiver.py
```

### 第二步：创建带 Webhook 的定时器

```bash
# 先登录拿 token
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "你的用户名", "password": "你的密码"}'

# 创建一个 10 秒后触发的定时器，触发时通知接收服务器
curl -X POST http://localhost:5000/api/timers \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "name": "Webhook 测试",
    "timer_type": "one_time",
    "delay_seconds": 10,
    "webhook_url": "http://localhost:5001/callback"
  }'
```

### 第三步：等待触发

10 秒后，终端 2 会打印：

```
==================================================
  收到定时器通知！
  名称：Webhook 测试
  类型：one_time
  触发时间：2026-03-22T10:30:00
  定时器 ID：1
==================================================
```

### 第四步：查看历史记录

所有收到的 Webhook 事件会保存在 `webhook_events.log`，也可以通过接口查看：

```bash
# 查看所有已收到的事件
curl http://localhost:5001/events

# 清空记录
curl -X POST http://localhost:5001/events/clear
```

### 接收服务器接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /callback | 接收 TimerService 的触发通知 |
| GET | /events | 查看所有已收到的事件 |
| POST | /events/clear | 清空事件日志 |

### 扩展：收到通知后做更多事

打开 `webhook_receiver.py`，在 `callback()` 函数里添加你的业务逻辑：

```python
@app.route("/callback", methods=["POST"])
def callback():
    data = request.get_json()

    # 发邮件、推钉钉、写数据库……在这里添加
    send_email(data['timer_name'])

    return jsonify({"msg": "已收到"}), 200
```

---

### 3. 打开 Web 界面

浏览器访问 `http://localhost:5000`，进行注册和登录。

---

## Web 界面使用说明

### 注册账户

1. 访问 `http://localhost:5000/register`
2. 填写用户名（3–80 字符）和密码（至少 8 字符）
3. 点击"注册"

### 登录

1. 访问 `http://localhost:5000/login`
2. 输入用户名和密码，点击"登录"
3. 登录成功后跳转到控制台

### 控制台功能

**创建定时器（左侧面板）：**

1. 填写名称
2. 选择类型：
   - **一次性定时器**：输入延迟秒数（1–86400）
   - **每日定时器**：选择每天触发的时间（UTC，格式 HH:MM）
3. 可选：填写 Webhook 回调 URL
4. 点击"创建定时器"

**查看定时器（右侧面板）：**

| 状态 | 含义 |
|------|------|
| 进行中（绿色） | 定时器激活，等待触发 |
| 已触发（灰色） | 一次性定时器已完成 |
| 已取消（红色） | 用户手动取消 |

**实时通知：** 定时器触发时，页面右下角会自动弹出通知 Toast，无需刷新页面。

**取消定时器：** 点击定时器行末的 ✕ 按钮取消进行中的定时器。

---

## API 使用说明

### 认证

所有 API 请求（注册和登录除外）需在 Header 中携带 JWT Token：

```
Authorization: Bearer <your_token>
```

### 注册

```bash
curl -X POST http://localhost:5000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "mypassword"}'
```

响应：
```json
{"msg": "User created", "user_id": 1}
```

### 登录

```bash
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "mypassword"}'
```

响应：
```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi..."
}
```

> `access_token` 用于日常请求，有效期 24 小时。`refresh_token` 用于续期，有效期 30 天，妥善保存。

### 刷新 Token

当 `access_token` 过期收到 401 时，用 `refresh_token` 换一个新的，无需重新登录：

```bash
curl -X POST http://localhost:5000/api/auth/refresh \
  -H "Authorization: Bearer <refresh_token>"
```

响应：
```json
{"access_token": "eyJhbGciOi...（新的）"}
```

> Web 控制台会在收到 401 时**自动完成刷新**，无需手动操作。

### 创建一次性定时器

```bash
curl -X POST http://localhost:5000/api/timers \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "name": "30秒后提醒",
    "timer_type": "one_time",
    "delay_seconds": 30
  }'
```

带 Webhook 回调：

```bash
curl -X POST http://localhost:5000/api/timers \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "name": "30秒定时",
    "timer_type": "one_time",
    "delay_seconds": 30,
    "webhook_url": "https://your-server.com/callback"
  }'
```

响应：
```json
{
  "id": 1,
  "name": "30秒后提醒",
  "timer_type": "one_time",
  "delay_seconds": 30,
  "status": "active",
  "next_fire_at": "2026-03-21T10:30:30",
  "trigger_count": 0
}
```

### 创建每日定时器

```bash
curl -X POST http://localhost:5000/api/timers \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "name": "每日早报",
    "timer_type": "daily",
    "trigger_time": "09:00"
  }'
```

> `trigger_time` 使用 **UTC 时间**。北京时间 17:00 对应 UTC 09:00。

### 查看所有定时器

```bash
curl http://localhost:5000/api/timers \
  -H "Authorization: Bearer <token>"
```

按状态过滤：

```bash
curl "http://localhost:5000/api/timers?status=active" \
  -H "Authorization: Bearer <token>"
```

状态可选值：`active` / `fired` / `cancelled`

### 查看单个定时器详情

```bash
curl http://localhost:5000/api/timers/1 \
  -H "Authorization: Bearer <token>"
```

响应包含 `events` 字段，记录每次触发历史：

```json
{
  "id": 1,
  "name": "30秒后提醒",
  "status": "fired",
  "events": [
    {
      "fired_at": "2026-03-21T10:30:30",
      "webhook_status": "success",
      "webhook_response_code": 200
    }
  ]
}
```

### 查询触发历史

```bash
# 查看所有定时器的全部触发记录
curl http://localhost:5000/api/timers/events \
  -H "Authorization: Bearer <token>"

# 只看某个定时器的触发记录
curl "http://localhost:5000/api/timers/events?timer_id=1" \
  -H "Authorization: Bearer <token>"
```

响应：
```json
{
  "count": 3,
  "events": [
    {
      "id": 3,
      "timer_id": 1,
      "fired_at": "2026-03-22T10:30:00",
      "webhook_status": "success",
      "webhook_response_code": 200
    }
  ]
}
```

### 取消定时器

```bash
curl -X DELETE http://localhost:5000/api/timers/1 \
  -H "Authorization: Bearer <token>"
```

### 订阅 SSE 实时通知

**浏览器 JavaScript（推荐）：**

```javascript
const token = "<your_jwt_token>";
const es = new EventSource(`/api/timers/stream?token=${token}`);

es.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === "timer_fired") {
    console.log(`定时器触发: ${data.timer_name} at ${data.fired_at}`);
  }
};
```

**curl 测试：**

```bash
curl -N "http://localhost:5000/api/timers/stream?token=<your_token>"
```

SSE 事件格式：
```
data: {"type": "connected", "user_id": 1}

data: {"type": "timer_fired", "timer_id": 1, "timer_name": "30秒后提醒", "fired_at": "2026-03-21T10:30:30", "timer_type": "one_time", "status": "fired"}

: keepalive
```

---

## 运行测试

```bash
cd timer_service

# 运行所有测试
pytest tests/ -v

# 查看代码覆盖率
pytest tests/ --cov=app --cov-report=term-missing

# 只运行认证测试
pytest tests/test_auth.py -v

# 只运行定时器测试
pytest tests/test_timers.py -v
```

---

## 常见问题

**Q: 创建每日定时器时应该填什么时间？**
A: 填写 UTC 时间，格式 `HH:MM`。例如北京时间每天上午 9 点 = UTC `01:00`。

**Q: 定时器触发后消失了？**
A: 一次性定时器触发后状态变为 `fired`，不再触发，这是正常行为。每日定时器会持续触发。

**Q: Token 过期了怎么办？**
A: Web 控制台会自动用 refresh_token 换新 token，无需操作。API 客户端收到 401 后，调 `/api/auth/refresh` 拿新的 access_token 即可。refresh_token 30 天后过期，届时需重新登录。

**Q: SSE 连接断开了怎么办？**
A: 在 Web 控制台点击"重连"按钮，或刷新页面（会自动重连）。

**Q: Webhook 没有收到回调？**
A: 检查定时器详情中 `webhook_status` 字段。失败可能原因：URL 不可达、服务器超时（>5秒）。TimerService 不重试失败的 Webhook。

**Q: 服务重启后定时器还在吗？**
A: 是的。服务启动时会自动从数据库恢复所有 `active` 状态的定时器。已过时间的一次性定时器将立即触发。

---

## 环境变量配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `SECRET_KEY` | dev-secret | Flask Session 密钥（**生产必须修改**） |
| `JWT_SECRET_KEY` | jwt-dev-secret | JWT 签名密钥（**生产必须修改**） |
| `DATABASE_URL` | sqlite:///timer_service.db | 数据库连接串 |

示例（Linux/macOS）：
```bash
export SECRET_KEY="$(openssl rand -hex 32)"
export JWT_SECRET_KEY="$(openssl rand -hex 32)"
python run.py
```
