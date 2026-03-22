"""
Webhook 接收服务器（示例）

独立运行在 5001 端口，接收 TimerService 的定时器触发通知。
收到通知后打印日志，并记录到本地文件。

运行方式：
    python webhook_receiver.py

然后创建定时器时填写：
    "webhook_url": "http://localhost:5001/callback"
"""
import json
import os
from datetime import datetime

from flask import Flask, jsonify, request

app = Flask(__name__)
LOG_FILE = "webhook_events.log"


@app.route("/callback", methods=["POST"])
def callback():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "无效的请求体"}), 400

    # 打印到终端
    print("\n" + "=" * 50)
    print(f"  收到定时器通知！")
    print(f"  名称：{data.get('timer_name')}")
    print(f"  类型：{data.get('timer_type')}")
    print(f"  触发时间：{data.get('fired_at')}")
    print(f"  定时器 ID：{data.get('timer_id')}")
    print("=" * 50 + "\n")

    # 追加写入日志文件
    _write_log(data)

    # 在这里可以扩展任何业务逻辑：
    # - 发送邮件
    # - 推送微信/钉钉消息
    # - 调用另一个 API
    # - 触发数据库操作

    return jsonify({"msg": "已收到", "timer_id": data.get("timer_id")}), 200


@app.route("/events", methods=["GET"])
def list_events():
    """查看所有已收到的 Webhook 事件。"""
    events = _read_log()
    return jsonify({"count": len(events), "events": events}), 200


@app.route("/events/clear", methods=["POST"])
def clear_events():
    """清空事件日志。"""
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
    return jsonify({"msg": "已清空"}), 200


def _write_log(data: dict) -> None:
    entry = {
        "received_at": datetime.utcnow().isoformat(),
        **data,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _read_log() -> list:
    if not os.path.exists(LOG_FILE):
        return []
    events = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return events


if __name__ == "__main__":
    print("Webhook 接收服务器启动中...")
    print(f"监听地址：http://localhost:5001")
    print(f"回调端点：http://localhost:5001/callback")
    print(f"查看记录：http://localhost:5001/events")
    print("-" * 40)
    app.run(port=5001, debug=True)
