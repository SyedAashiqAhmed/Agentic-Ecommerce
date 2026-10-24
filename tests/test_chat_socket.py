import json
import threading
import time

import uvicorn
import websocket

from chat_server import app


def test_chat_socket_connects_and_returns_buyer_agent_message():
    config = uvicorn.Config(app, host="127.0.0.1", port=8766, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(0.5)
    socket = websocket.create_connection("ws://127.0.0.1:8766/ws/test-room/seller-human", timeout=5)
    assert json.loads(socket.recv())["type"] == "connected"
    socket.send(json.dumps({
        "type": "message",
        "message": "Can you improve delivery?",
        "round_number": 2,
        "context": {"unit_price_inr": 65000, "delivery_days": 3, "budget_inr": 70000},
    }))
    messages = [json.loads(socket.recv()), json.loads(socket.recv())]
    assert messages[0]["sender_role"] == "seller-human"
    assert messages[1]["sender_role"] == "buyer-agent"
    socket.close()
    server.should_exit = True
    thread.join(timeout=2)
