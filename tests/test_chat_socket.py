import json
import threading
import time

import uvicorn
import websocket

from chat_server import ChatRoom, app, room_state


def test_chat_socket_connects_and_returns_buyer_agent_message():
    config = uvicorn.Config(app, host="127.0.0.1", port=8766, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(0.5)
    room_state["test-room"] = ChatRoom(
        buyer_context={"budget_inr": 70000, "hard_constraints": {"ram_gb_min": 16}},
        supplier_context={"supplier_id": "test-supplier", "minimum_price_inr": 60000},
        approved=True,
    )
    socket = websocket.create_connection("ws://127.0.0.1:8766/ws/test-room/seller-human", timeout=60)
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


def test_unapproved_room_rejects_socket():
    config = uvicorn.Config(app, host="127.0.0.1", port=8767, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(0.5)
    room_state["blocked-room"] = ChatRoom(buyer_context={}, supplier_context={}, approved=False)
    socket = websocket.create_connection("ws://127.0.0.1:8767/ws/blocked-room/seller-human", timeout=10)
    assert json.loads(socket.recv())["type"] == "error"
    socket.close()
    server.should_exit = True
    thread.join(timeout=2)


def test_supplier_agent_chat_is_available_before_direct_contact_approval():
    config = uvicorn.Config(app, host="127.0.0.1", port=8768, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(0.5)
    room_state["agent-room"] = ChatRoom(
        buyer_context={"budget_inr": 70000},
        supplier_context={"supplier_id": "supplier-a"},
        approved=False,
        agent_chat_enabled=True,
    )
    socket = websocket.create_connection("ws://127.0.0.1:8768/ws/agent-room/buyer-user", timeout=10)
    assert json.loads(socket.recv())["type"] == "connected"
    socket.close()
    server.should_exit = True
    thread.join(timeout=2)
