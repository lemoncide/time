"""
Per-user SSE (Server-Sent Events) notification queue management.

Thread-safe: APScheduler callbacks run in a separate thread pool.
"""
import json
import queue
import threading
from collections import defaultdict
from typing import Generator

_clients: dict[int, list[queue.Queue]] = defaultdict(list)
_lock = threading.Lock()

HEARTBEAT_INTERVAL = 15  # seconds


def register_client(user_id: int) -> queue.Queue:
    """Create a new queue for an SSE client and register it."""
    q: queue.Queue = queue.Queue()
    with _lock:
        _clients[user_id].append(q)
    return q


def unregister_client(user_id: int, q: queue.Queue) -> None:
    """Remove a client's queue; clean up empty user entries."""
    with _lock:
        if user_id in _clients:
            try:
                _clients[user_id].remove(q)
            except ValueError:
                pass
            if not _clients[user_id]:
                del _clients[user_id]


def push_event(user_id: int, event: dict) -> None:
    """Push a timer-fired event to all active SSE clients for a user."""
    with _lock:
        queues = list(_clients.get(user_id, []))
    for q in queues:
        try:
            q.put_nowait(event)
        except queue.Full:
            pass


def event_stream(user_id: int) -> Generator[str, None, None]:
    """
    SSE generator for a single client connection.

    Yields SSE-formatted strings. Sends a keepalive comment every
    HEARTBEAT_INTERVAL seconds when no events arrive.
    """
    q = register_client(user_id)
    try:
        # Initial connected event
        yield _format_sse({"type": "connected", "user_id": user_id})
        while True:
            try:
                event = q.get(timeout=HEARTBEAT_INTERVAL)
                yield _format_sse(event)
            except queue.Empty:
                # Heartbeat — keeps connection alive through proxies/load-balancers
                yield ": keepalive\n\n"
    except GeneratorExit:
        pass
    finally:
        unregister_client(user_id, q)


def _format_sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
